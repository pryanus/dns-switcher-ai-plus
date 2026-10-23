"""
ZapretDnsProvider: Adapter for Zapret DNS using RFC 8484 DNS-over-HTTPS (DoH).
DoH Endpoint: https://dns.zapret.moe/dns-query
"""

import json
from datetime import datetime
from pathlib import Path
from typing import Dict, List, Optional
import httpx
import dns.message
import dns.rdatatype

from providers.base import BaseProvider, CandidateIP


class ZapretDnsProvider(BaseProvider):
    DOH_URL = "https://dns.zapret.moe/dns-query"

    def __init__(
        self,
        enabled: bool = True,
        priority: int = 12,
        cache_dir: Optional[str] = None
    ):
        super().__init__(
            id="zapret-dns",
            name="Zapret DNS",
            enabled=enabled,
            priority=priority,
            cache_dir=cache_dir
        )
        self._ip_cache: Dict[str, List[str]] = {}
        self._load_cache()

    @property
    def _cache_file(self) -> Optional[Path]:
        if self.cache_dir:
            p = Path(self.cache_dir)
            p.mkdir(parents=True, exist_ok=True)
            return p / "zapret_dns.json"
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
                "resolved_ips": self._ip_cache,
            }
            cache_p.write_text(json.dumps(data, indent=2, ensure_ascii=False), encoding="utf-8")

    def resolve_domain_doh(self, domain: str, timeout: float = 3.5) -> List[str]:
        """Sends an RFC 8484 DoH query to Zapret DNS."""
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
            else:
                self.last_error = f"HTTP {resp.status_code}"
                return []
        except Exception as e:
            self.last_error = str(e)
            return []

    def fetch_candidates(self, domain: str) -> List[CandidateIP]:
        if not self.enabled:
            return []

        clean_d = domain.strip().lower()
        # Check cache first
        cached_ips = self._ip_cache.get(clean_d, [])

        # If not in cache or user is querying, attempt DoH query
        resolved_ips = self.resolve_domain_doh(clean_d) or cached_ips

        results = []
        for ip in resolved_ips:
            results.append(CandidateIP(
                ip=ip,
                provider_id=self.id,
                provider_name=self.name,
                region="EU/Global"
            ))
        return results

    def update_database(self) -> bool:
        """Verifies endpoint health and updates cache timestamp."""
        test_ips = self.resolve_domain_doh("chatgpt.com")
        if test_ips:
            self.last_updated = datetime.now().strftime("%Y-%m-%d %H:%M:%S")
            self._save_cache()
            return True
        return False
