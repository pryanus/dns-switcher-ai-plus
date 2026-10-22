"""
CustomProvider: Supports user-defined DoH, plain UDP/TCP DNS, remote/local hosts lists, or manual domain->IP pairs.
"""

import json
from datetime import datetime
from pathlib import Path
from typing import Dict, List, Optional
import httpx
import dns.query
import dns.message
import dns.query
import dns.rdatatype

from providers.base import BaseProvider, CandidateIP
from core.validation import parse_hosts


class CustomProvider(BaseProvider):
    TYPE_DOH = "doh"
    TYPE_PLAIN_DNS = "plain_dns"
    TYPE_HOSTS_URL = "hosts_url"
    TYPE_MANUAL = "manual"

    def __init__(
        self,
        id: str,
        name: str,
        provider_type: str,
        endpoint_or_ip: str,
        static_mappings: Optional[Dict[str, str]] = None,
        enabled: bool = True,
        priority: int = 10,
        cache_dir: Optional[str] = None
    ):
        super().__init__(
            id=id,
            name=name,
            enabled=enabled,
            priority=priority,
            cache_dir=cache_dir
        )
        import re
        if not re.fullmatch(r'[a-zA-Z0-9_-]{1,80}', id):
            raise ValueError("Некорректный идентификатор провайдера")
        self.provider_type = provider_type  # doh, plain_dns, hosts_url, manual
        self.endpoint_or_ip = endpoint_or_ip.strip()
        self.static_mappings = static_mappings or {}  # domain -> ip
        self._ip_cache: Dict[str, List[str]] = {}
        self._load_cache()

    @property
    def _cache_file(self) -> Optional[Path]:
        if self.cache_dir:
            p = Path(self.cache_dir)
            p.mkdir(parents=True, exist_ok=True)
            return p / f"custom_{self.id}.json"
        return None

    def _load_cache(self) -> None:
        cache_p = self._cache_file
        if cache_p and cache_p.exists():
            try:
                data = json.loads(cache_p.read_text(encoding="utf-8"))
                self.last_updated = data.get("last_updated")
                self._ip_cache = data.get("resolved_ips", {})
            except Exception as e:
                self.last_error = f"Cache error: {e}"

    def _save_cache(self) -> None:
        cache_p = self._cache_file
        if cache_p:
            data = {
                "last_updated": self.last_updated,
                "provider_type": self.provider_type,
                "endpoint_or_ip": self.endpoint_or_ip,
                "resolved_ips": self._ip_cache,
            }
            cache_p.write_text(json.dumps(data, indent=2, ensure_ascii=False), encoding="utf-8")

    def to_dict(self) -> Dict:
        base = super().to_dict()
        base.update({
            "provider_type": self.provider_type,
            "endpoint_or_ip": self.endpoint_or_ip,
            "static_mappings": self.static_mappings,
        })
        return base

    @classmethod
    def from_dict(cls, data: Dict, cache_dir: Optional[str] = None) -> "CustomProvider":
        return cls(
            id=data["id"],
            name=data["name"],
            provider_type=data.get("provider_type", cls.TYPE_DOH),
            endpoint_or_ip=data.get("endpoint_or_ip", ""),
            static_mappings=data.get("static_mappings", {}),
            enabled=data.get("enabled", True),
            priority=data.get("priority", 10),
            cache_dir=cache_dir
        )

    def fetch_candidates(self, domain: str) -> List[CandidateIP]:
        if not self.enabled:
            return []

        clean_d = domain.strip().lower()

        # 1. Manual static mapping
        if self.provider_type == self.TYPE_MANUAL:
            if clean_d in self.static_mappings:
                return [CandidateIP(self.static_mappings[clean_d], self.id, self.name, "Custom")]
            return []

        # 2. Cached check
        try:
            cache_fresh = (datetime.now() - datetime.fromisoformat(self.last_updated)).total_seconds() < 86400
        except (TypeError, ValueError):
            cache_fresh = False
        if clean_d in self._ip_cache and (self.provider_type == self.TYPE_HOSTS_URL or cache_fresh):
            return [CandidateIP(ip, self.id, self.name, "Custom") for ip in self._ip_cache[clean_d]]

        # 3. Resolve based on type
        resolved = []
        if self.provider_type == self.TYPE_DOH:
            resolved = self._resolve_doh(clean_d)
        elif self.provider_type == self.TYPE_PLAIN_DNS:
            resolved = self._resolve_plain_dns(clean_d)
        elif self.provider_type == self.TYPE_HOSTS_URL:
            # Check cached hosts
            resolved = self._ip_cache.get(clean_d, [])

        if resolved:
            self._ip_cache[clean_d] = resolved
            self.last_updated = datetime.now().strftime('%Y-%m-%d %H:%M:%S')
            self.last_error = None
            self._save_cache()

        return [CandidateIP(ip, self.id, self.name, "Custom") for ip in resolved]

    def _resolve_doh(self, domain: str) -> List[str]:
        query = dns.message.make_query(domain, dns.rdatatype.A)
        headers = {
            "Content-Type": "application/dns-message",
            "Accept": "application/dns-message",
        }
        try:
            with httpx.Client(timeout=3.5, verify=True, http2=True) as client:
                resp = client.post(self.endpoint_or_ip, content=query.to_wire(), headers=headers)
                if resp.status_code == 200:
                    answer_msg = dns.message.from_wire(resp.content)
                    ips = []
                    for rrset in answer_msg.answer:
                        if rrset.rdtype == dns.rdatatype.A:
                            for item in rrset:
                                ips.append(item.address)
                    return ips
        except Exception as e:
            self.last_error = str(e)
        return []

    def _resolve_plain_dns(self, domain: str) -> List[str]:
        """Sends standard DNS query to the specified resolver without altering system DNS."""
        try:
            query = dns.message.make_query(domain, dns.rdatatype.A)
            # Default to port 53 if not specified
            parts = self.endpoint_or_ip.split(":")
            ip = parts[0]
            port = int(parts[1]) if len(parts) > 1 else 53
            resp = dns.query.udp(query, ip, port=port, timeout=3.0)
            ips = []
            for rrset in resp.answer:
                if rrset.rdtype == dns.rdatatype.A:
                    for item in rrset:
                        ips.append(item.address)
            return ips
        except Exception as e:
            self.last_error = str(e)
            return []

    def update_database(self) -> bool:
        if self.provider_type == self.TYPE_HOSTS_URL:
            try:
                # Could be a web URL or local file path
                content = ""
                if self.endpoint_or_ip.startswith("http://") or self.endpoint_or_ip.startswith("https://"):
                    with httpx.Client(timeout=10.0) as client:
                        resp = client.get(self.endpoint_or_ip)
                        if resp.status_code == 200:
                            content = resp.text
                else:
                    p = Path(self.endpoint_or_ip)
                    if p.exists():
                        content = p.read_text(encoding="utf-8", errors="ignore")

                if content:
                    mappings = parse_hosts(content)
                    if not mappings:
                        raise ValueError("Источник не содержит публичных адресов")
                    self._ip_cache = mappings
                    self.last_error = None

                    self.last_updated = datetime.now().strftime("%Y-%m-%d %H:%M:%S")
                    self._save_cache()
                    return True
                self.last_error = "Не удалось получить hosts"
                return False
            except Exception as e:
                self.last_error = str(e)
                return False

        if self.provider_type in (self.TYPE_DOH, self.TYPE_PLAIN_DNS):
            resolver = self._resolve_doh if self.provider_type == self.TYPE_DOH else self._resolve_plain_dns
            domains = list(self._ip_cache) or ['canva.com']
            from core.network import parallel
            refreshed = dict(zip(domains, parallel(domains, resolver, timeout=None, limit=6)))
            if not any(refreshed.values()):
                self.last_error = 'Нет свежих DNS-ответов; прежний кэш сохранён'
                return False
            self._ip_cache = {domain: ips for domain, ips in refreshed.items() if ips}
        self.last_updated = datetime.now().strftime("%Y-%m-%d %H:%M:%S")
        self._save_cache()
        return True
