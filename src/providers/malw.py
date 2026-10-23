"""
MalwDnsProvider: Adapter for MALW DNS supporting DoH queries and SNI proxy hosts.
DoH Endpoint: https://dns.malw.link/dns-query
GitHub: https://github.com/ImMALWARE/dns.malw.link
"""

import json
from datetime import datetime
from pathlib import Path
from typing import Dict, List, Optional
import httpx
import dns.message
import dns.rdatatype

from providers.base import BaseProvider, CandidateIP
from core.validation import parse_hosts


class MalwDnsProvider(BaseProvider):
    DOH_URL = "https://dns.malw.link/dns-query"
    HOSTS_URL = "https://raw.githubusercontent.com/ImMALWARE/dns.malw.link/master/hosts"

    def __init__(
        self,
        enabled: bool = True,
        priority: int = 14,
        cache_dir: Optional[str] = None
    ):
        super().__init__(
            id="malw-dns",
            name="MALW DNS",
            enabled=enabled,
            priority=priority,
            cache_dir=cache_dir
        )
        self._ip_cache: Dict[str, List[str]] = {}
        self._hosts_ips = {}
        self._load_cache()
        bundled = Path(__file__).resolve().parents[1] / 'assets/malw_hosts.txt'
        if not self._hosts_ips and bundled.exists():
            self._hosts_ips = parse_hosts(bundled.read_text(encoding='utf-8'))
        self.supported_domains = set(self._hosts_ips)

    @property
    def _cache_file(self) -> Optional[Path]:
        if self.cache_dir:
            p = Path(self.cache_dir)
            p.mkdir(parents=True, exist_ok=True)
            return p / "malw_dns.json"
        return None

    def _load_cache(self) -> None:
        cache_p = self._cache_file
        if cache_p and cache_p.exists():
            try:
                data = json.loads(cache_p.read_text(encoding="utf-8"))
                self.last_updated = data.get("last_updated")
                self._ip_cache = data.get("resolved_ips", {})
                self._hosts_ips = data.get('hosts_ips', {})
            except Exception as e:
                self.last_error = f"Cache error: {e}"

    def _save_cache(self) -> None:
        cache_p = self._cache_file
        if cache_p:
            data = {
                "last_updated": self.last_updated,
                "resolved_ips": self._ip_cache,
                "hosts_ips": self._hosts_ips,
            }
            cache_p.write_text(json.dumps(data, indent=2, ensure_ascii=False), encoding="utf-8")

    def resolve_domain_doh(self, domain: str, timeout: float = 3.5) -> List[str]:
        clean_d = domain.strip().lower()
        query = dns.message.make_query(clean_d, dns.rdatatype.A)
        wire_data = query.to_wire()

        headers = {
            "Content-Type": "application/dns-message",
            "Accept": "application/dns-message",
            "User-Agent": "DNS-Switcher/1.0"
        }

        try:
            try:
                with httpx.Client(timeout=timeout, verify=True, http2=True) as client:
                    resp = client.post(self.DOH_URL, content=wire_data, headers=headers)
            except ImportError:
                with httpx.Client(timeout=timeout, verify=True, http2=False) as client:
                    resp = client.post(self.DOH_URL, content=wire_data, headers=headers)
            if resp.status_code == 200:
                answer_msg = dns.message.from_wire(resp.content)
                ips = []
                for rrset in answer_msg.answer:
                    if rrset.rdtype == dns.rdatatype.A:
                        for item in rrset:
                            ips.append(item.address)
                if ips:
                    self._ip_cache[clean_d] = ips
                    self._save_cache()
                return ips
        except Exception as e:
            self.last_error = str(e)
        return []

    def fetch_candidates(self, domain: str) -> List[CandidateIP]:
        if not self.enabled:
            return []

        clean_d = domain.strip().lower()
        cached = self._ip_cache.get(clean_d, [])
        ips = list(dict.fromkeys(self._hosts_ips.get(clean_d, []) + (self.resolve_domain_doh(clean_d) or cached)))

        results = []
        for ip in ips:
            # Skip localhost or 0.0.0.0 (adblock/sinkhole rules)
            if ip in ("0.0.0.0", "127.0.0.1", "::1"):
                continue
            results.append(CandidateIP(
                ip=ip,
                provider_id=self.id,
                provider_name=self.name,
                region="Global"
            ))
        return results

    def update_database(self) -> bool:
        """Downloads official MALW hosts and extracts access-restoration entries, ignoring sinkholes."""
        try:
            with httpx.Client(timeout=10.0, follow_redirects=True) as client:
                resp = client.get(self.HOSTS_URL)
                if resp.status_code == 200:
                    mappings = parse_hosts(resp.text)
                    if not mappings:
                        raise ValueError("Источник не содержит публичных адресов")
                    self._hosts_ips = mappings
                    self.supported_domains = set(mappings)
                    self._ip_cache = mappings
                    self.last_error = None

                    self.last_updated = datetime.now().strftime("%Y-%m-%d %H:%M:%S")
                    self._save_cache()
                    return True
                else:
                    # Fallback to test query
                    res = self.resolve_domain_doh("chatgpt.com")
                    if res:
                        self.last_updated = datetime.now().strftime("%Y-%m-%d %H:%M:%S")
                        self._save_cache()
                        return True
                    return False
        except Exception as e:
            self.last_error = str(e)
            return False
