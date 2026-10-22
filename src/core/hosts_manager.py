"""
HostsManager: Safe parsing, surgical updating, backup and restoration of Windows hosts file.
Designed to preserve all third-party rules, prevent mojibake with proper encoding handling,
and guarantee atomic, reversible operations.
"""

import os
import re
import sys
import shutil
import tempfile
from datetime import datetime
from pathlib import Path
from typing import List, Dict, Set, Optional, Tuple


from core.elevation import ElevationHelper
from core.validation import public_ip, domain_name
from threading import RLock
from functools import wraps


_HOSTS_LOCK = RLock()

def locked(function):
    @wraps(function)
    def wrapper(*args, **kwargs):
        with _HOSTS_LOCK:
            return function(*args, **kwargs)
    return wrapper


class HostsEntry:
    def __init__(self, ip: str, domain: str, comment: str = "", raw_line: str = ""):
        self.ip = ip.strip()
        self.domain = domain.strip().lower()
        self.comment = comment.strip()
        self.raw_line = raw_line

    def __repr__(self):
        return f"<HostsEntry {self.ip} -> {self.domain}>"


class HostsManager:
    MANAGED_START_PREFIX = "# === DNS Switcher Managed: "
    MANAGED_END_PREFIX = "# === End DNS Switcher: "

    def __init__(self, hosts_path: Optional[str] = None, backup_dir: Optional[str] = None):
        if hosts_path:
            self.hosts_path = Path(hosts_path)
        else:
            system_root = os.environ.get("SystemRoot", r"C:\Windows")
            self.hosts_path = Path(system_root) / "System32" / "drivers" / "etc" / "hosts"

        if backup_dir:
            self.backup_dir = Path(backup_dir)
        else:
            # Safe user-writable location (never inside C:\Windows\System32\)
            appdata = os.environ.get("APPDATA", str(Path.home()))
            self.backup_dir = Path(appdata) / "DNS-Switcher" / "backups"
        
        try:
            self.backup_dir.mkdir(parents=True, exist_ok=True)
        except OSError:
            # Fallback to temp directory if APPDATA is inaccessible
            self.backup_dir = Path(tempfile.gettempdir()) / "DNS-Switcher-backups"
            self.backup_dir.mkdir(parents=True, exist_ok=True)

    @staticmethod
    def read_file_safely(path: Path) -> Tuple[str, str]:
        """Reads a file detecting UTF-8 (with or without BOM) or CP1251/Latin1."""
        if not path.exists():
            return "", "utf-8-sig"

        raw_bytes = path.read_bytes()

        # Check BOM
        if raw_bytes.startswith(b"\xef\xbb\xbf"):
            try:
                return raw_bytes.decode("utf-8-sig"), "utf-8-sig"
            except UnicodeDecodeError:
                pass

        # Try plain utf-8
        try:
            return raw_bytes.decode("utf-8"), "utf-8"
        except UnicodeDecodeError:
            pass

        # Try cp1251 (standard Windows Russian)
        try:
            return raw_bytes.decode("cp1251"), "cp1251"
        except UnicodeDecodeError:
            pass

        # Fallback to latin-1
        return raw_bytes.decode("latin-1", errors="replace"), "latin-1"

    @staticmethod
    def write_file_safely(path: Path, content: str, encoding: str = "utf-8-sig") -> None:
        """
        Writes content atomically to path using temporary file.
        If writing to system path raises PermissionError, requests UAC elevation.
        """
        tmp_dir = tempfile.gettempdir()
        tmp_fd, tmp_path_str = tempfile.mkstemp(dir=tmp_dir, prefix="hosts_sw_", suffix=".tmp")
        try:
            with os.fdopen(tmp_fd, "w", encoding=encoding, newline="") as f:
                f.write(content)

            # Try direct copy first
            try:
                fd, adjacent = tempfile.mkstemp(dir=path.parent, prefix=".hosts-sw-")
                os.close(fd)
                try:
                    shutil.copyfile(tmp_path_str, adjacent)
                    os.replace(adjacent, path)
                finally:
                    if os.path.exists(adjacent):
                        os.unlink(adjacent)
                system_hosts = Path(os.environ.get("SystemRoot", r"C:\Windows")) / "System32/drivers/etc/hosts"
                if path.resolve() == system_hosts.resolve():
                    import subprocess
                    subprocess.run([str(Path(os.environ.get("SystemRoot", r"C:\Windows")) / "System32/ipconfig.exe"), "/flushdns"], capture_output=True, check=True, timeout=3, creationflags=getattr(subprocess, "CREATE_NO_WINDOW", 0))
            except PermissionError:
                # Elevate with UAC
                success = ElevationHelper.copy_file_elevated(tmp_path_str, str(path), flush_dns=True)
                if not success:
                    raise PermissionError(f"Требуются права администратора для записи в файл {path}")
        finally:
            if os.path.exists(tmp_path_str):
                try:
                    os.remove(tmp_path_str)
                except OSError:
                    pass

    def get_lines(self) -> List[str]:
        content, _ = self.read_file_safely(self.hosts_path)
        return content.splitlines()

    def parse_all_entries(self) -> Dict[str, List[str]]:
        """
        Returns a mapping of domain.lower() -> list of IPs found in hosts.
        Preserves multiple IPs per domain if present.
        """
        domain_to_ips: Dict[str, List[str]] = {}
        for line in self.get_lines():
            clean = line.strip()
            if not clean or clean.startswith("#"):
                continue

            # Strip inline comment
            if "#" in clean:
                clean = clean.split("#", 1)[0].strip()

            parts = clean.split()
            if len(parts) >= 2:
                ip = parts[0]
                domains = parts[1:]
                for d in domains:
                    d_lower = d.lower()
                    if d_lower not in domain_to_ips:
                        domain_to_ips[d_lower] = []
                    if ip not in domain_to_ips[d_lower]:
                        domain_to_ips[d_lower].append(ip)

        return domain_to_ips

    def get_service_current_ips(self, domains: List[str]) -> Dict[str, List[str]]:
        """Returns existing IPs in hosts for the specified domains."""
        all_entries = self.parse_all_entries()
        result = {}
        for d in domains:
            d_lower = d.lower()
            if d_lower in all_entries:
                result[d_lower] = all_entries[d_lower]
        return result

    def get_active_ip_for_service(self, domains: List[str]) -> Optional[str]:
        """Returns the most common or first assigned IP for the service's domains."""
        ips = self.get_service_current_ips(domains)
        if not ips:
            return None
        # Count frequency of IPs
        counts: Dict[str, int] = {}
        for domain, ip_list in ips.items():
            for ip in ip_list:
                counts[ip] = counts.get(ip, 0) + 1
        sorted_ips = sorted(counts.items(), key=lambda x: x[1], reverse=True)
        return sorted_ips[0][0] if sorted_ips else None

    def create_backup(self, tag: Optional[str] = None) -> Path:
        """Creates a timestamped backup of the current hosts file."""
        if not self.hosts_path.exists():
            raise FileNotFoundError(f"Hosts file not found at {self.hosts_path}")

        ts = datetime.now().strftime("%Y%m%d_%H%M%S_%f")
        suffix = "_" + re.sub(r"[^a-zA-Z0-9_-]", "_", tag)[:60] if tag else ""
        import uuid
        backup_filename = f"hosts.bak_{ts}{suffix}_{uuid.uuid4().hex[:8]}"
        backup_file = self.backup_dir / backup_filename

        shutil.copy2(str(self.hosts_path), str(backup_file))
        return backup_file

    def list_backups(self) -> List[Dict[str, any]]:
        """Lists all existing backups sorted newest first."""
        backups = []
        if not self.backup_dir.exists():
            return []

        for p in self.backup_dir.glob("hosts.bak_*"):
            if p.is_file():
                stat = p.stat()
                backups.append({
                    "path": str(p),
                    "filename": p.name,
                    "size": stat.st_size,
                    "created": datetime.fromtimestamp(stat.st_mtime).strftime("%Y-%m-%d %H:%M:%S"),
                    "mtime": stat.st_mtime,
                })

        # Also look in the hosts parent folder (e.g. hosts.bak_*)
        if self.hosts_path.parent.exists():
            for p in self.hosts_path.parent.glob("hosts.bak_*"):
                if p.is_file():
                    stat = p.stat()
                    backups.append({
                        "path": str(p),
                        "filename": p.name,
                        "size": stat.st_size,
                        "created": datetime.fromtimestamp(stat.st_mtime).strftime("%Y-%m-%d %H:%M:%S"),
                        "mtime": stat.st_mtime,
                    })

        # Deduplicate by path
        seen = set()
        deduped = []
        for b in sorted(backups, key=lambda x: x["mtime"], reverse=True):
            if b["path"] not in seen:
                seen.add(b["path"])
                deduped.append(b)

        return deduped

    @locked
    def restore_backup(self, backup_path: str) -> bool:
        """Restores hosts from a specified backup path."""
        src = Path(backup_path)
        if not src.exists():
            raise FileNotFoundError(f"Backup file not found: {backup_path}")

        # Create a safety backup of current state before restoring
        if self.hosts_path.exists():
            self.create_backup(tag="before_restore")

        try:
            shutil.copy2(str(src), str(self.hosts_path))
        except PermissionError:
            success = ElevationHelper.copy_file_elevated(str(src), str(self.hosts_path), flush_dns=True)
            if not success:
                raise PermissionError(f"Требуются права администратора для восстановления {self.hosts_path}")
        return True

    ROUTES_START = "# === DNS Switcher Routes ==="
    ROUTES_END = "# === End DNS Switcher Routes ==="

    def _split_managed(self, content):
        """Отделяет только наши блоки; остальной текст сохраняется без изменений."""
        sections = {}
        pattern = re.compile(
            r"^# === DNS Switcher Managed: ([^\r\n]+) ===\r?\n"
            r"(.*?)^# === End DNS Switcher: \1 ===(?:\r?\n|$)",
            re.MULTILINE | re.DOTALL)

        def collect(match):
            name, body = match.group(1), match.group(2)
            mappings = {}
            for line in body.splitlines():
                fields = line.partition('#')[0].split()
                if len(fields) >= 2:
                    for domain in fields[1:]:
                        mappings[domain_name(domain)] = public_ip(fields[0])
            sections[name] = mappings
            return ''

        remaining = pattern.sub(collect, content)
        if self.MANAGED_START_PREFIX in remaining or self.MANAGED_END_PREFIX in remaining:
            raise ValueError("Повреждены границы блока DNS Switcher. Hosts не изменён.")
        # Новая общая обёртка содержит только принадлежащие приложению записи.
        wrapper = re.compile(r"^# === DNS Switcher Routes ===\r?\n"
            r"(?:[ \t]*\r?\n)*# === End DNS Switcher Routes ===(?:\r?\n|$)", re.MULTILINE)
        remaining = wrapper.sub('', remaining)
        if self.ROUTES_START in remaining or self.ROUTES_END in remaining:
            raise ValueError("Повреждён общий блок DNS Switcher. Hosts не изменён.")
        return sections, remaining

    def _write_managed(self, sections, original, encoding):
        lines = [self.ROUTES_START, '']
        for name, mappings in sections.items():
            if not mappings:
                continue
            lines.append(f"{self.MANAGED_START_PREFIX}{name} ===")
            lines.extend(f"{ip:<16} {domain}" for domain, ip in sorted(mappings.items()))
            lines.append(f"{self.MANAGED_END_PREFIX}{name} ===")
            lines.append('')
        lines.append(self.ROUTES_END)
        prefix = "\r\n".join(lines) + "\r\n" if any(sections.values()) else ''
        self.write_file_safely(self.hosts_path, prefix + original, encoding)

    def get_conflicts(self, mappings):
        content, _ = self.read_file_safely(self.hosts_path)
        _, original = self._split_managed(content)
        conflicts = {}
        for line in original.splitlines():
            fields = line.partition('#')[0].split()
            if len(fields) >= 2:
                for domain in fields[1:]:
                    domain = domain.lower()
                    if domain in mappings and fields[0] != mappings[domain]:
                        conflicts.setdefault(domain, []).append(fields[0])
        return conflicts

    @locked
    def update_multiple_services(self, updates):
        if not updates:
            return True
        prepared = []
        for update in updates:
            name = update['service_name']
            if not name or any(c in name for c in "\r\n") or '===' in name:
                raise ValueError("Некорректное имя сервиса")
            target = public_ip(update['target_ip'])
            domains = [domain_name(domain) for domain in update['domains']]
            if not domains:
                raise ValueError("Не указаны домены")
            specified = update.get('domain_ips', {})
            mappings = {domain: public_ip(specified.get(domain, target)) for domain in domains}
            prepared.append((name, mappings))
        content, encoding = self.read_file_safely(self.hosts_path)
        sections, original = self._split_managed(content)
        for name, mappings in prepared:
            # У одного домена может быть только один адрес внутри блока программы.
            for owner in sections:
                if owner != name:
                    for domain in mappings:
                        sections[owner].pop(domain, None)
            sections.setdefault(name, {}).update(mappings)
        if self.hosts_path.exists():
            self.create_backup(tag='update')
        else:
            self.hosts_path.parent.mkdir(parents=True, exist_ok=True)
        self._write_managed(sections, original, encoding)
        return True

    def update_service_ip(self, service_name, target_ip, domains, provider_name=None):
        return self.update_multiple_services([dict(service_name=service_name,
            target_ip=target_ip, domains=domains, provider_name=provider_name)])

    @locked
    def remove_service_entries(self, service_name, domains):
        """Убирает только записи программы, не удаляет пользовательские строки."""
        if not self.hosts_path.exists():
            return False
        content, encoding = self.read_file_safely(self.hosts_path)
        sections, original = self._split_managed(content)
        if service_name not in sections:
            return False
        sections.pop(service_name)
        self.create_backup(tag='remove')
        self._write_managed(sections, original, encoding)
        return True

    def parse_geohide_services(self, file_path: Optional[str] = None) -> Dict[str, Dict[str, any]]:
        """
        Parses GeoHide structured hosts files (like hosts(2)).
        Extracts services with their domains and IPs based on section comments.
        Returns: { 'ServiceName': {'domains': [...], 'ips': [...], 'category': '...'} }
        """
        target = Path(file_path) if file_path else self.hosts_path
        if not target.exists():
            return {}

        content, _ = self.read_file_safely(target)
        lines = content.splitlines()

        services: Dict[str, Dict[str, any]] = {}
        current_service = "General"
        current_domains: Set[str] = set()
        current_ips: Set[str] = set()

        for line in lines:
            trimmed = line.strip()
            if not trimmed:
                continue

            # Detect comment headers representing service groups
            if trimmed.startswith("#"):
                comment_text = trimmed.lstrip("#").strip()
                # Ignore metadata lines
                if (
                    not comment_text
                    or "geohide.ru" in comment_text
                    or "Последнее обновление" in comment_text
                    or "Регион серверов" in comment_text
                    or "GeoHide DNS" in comment_text
                    or "сторонним сервисам" in comment_text
                    or re.match(r"^\d+\.\d+\.\d+\.\d+$", comment_text)
                ):
                    continue

                # Service header candidate
                # Save previous if had domains
                if current_domains and current_service != "General":
                    if current_service not in services:
                        services[current_service] = {"domains": set(), "ips": set()}
                    services[current_service]["domains"].update(current_domains)
                    services[current_service]["ips"].update(current_ips)

                current_service = comment_text.split(";")[0].strip()
                current_domains = set()
                current_ips = set()
                continue

            # Line with IP and domains
            parts = trimmed.split()
            if len(parts) >= 2:
                ip = parts[0]
                domains = [d.lower() for d in parts[1:] if not d.startswith("#")]
                current_ips.add(ip)
                current_domains.update(domains)

        # Append last group
        if current_domains and current_service:
            if current_service not in services:
                services[current_service] = {"domains": set(), "ips": set()}
            services[current_service]["domains"].update(current_domains)
            services[current_service]["ips"].update(current_ips)

        # Convert sets to sorted lists
        result = {}
        for s_name, data in services.items():
            result[s_name] = {
                "domains": sorted(list(data["domains"])),
                "ips": sorted(list(data["ips"])),
            }
        return result
