"""
GeoHideProvider: Adapter for GeoHide Smart DNS / SNI proxy with RU, EU, US profiles.
"""

import json
import re
from datetime import datetime
from pathlib import Path
from typing import Dict, List, Optional, Set
import httpx

from providers.base import BaseProvider, CandidateIP
from core.validation import parse_hosts


# Regional default IPs known to belong to GeoHide
GEOHIDE_KNOWN_SERVERS = {
    "RU": [
        "193.233.112.68",
        "193.233.112.67",
        "159.194.200.33",
        "37.230.192.51",
        "46.8.158.6",
    ],
    "EU": [
        "5.175.161.40",    # Germany
        "5.175.161.3",     # Germany
        "143.20.64.192",   # Poland
        "45.13.237.213",
        "31.25.239.132",
    ],
    "US": [
        "192.255.159.240",
        "192.255.159.241",
        "192.3.233.253",
        "107.175.76.134",
    ],
}


class GeoHideProvider(BaseProvider):
    # GitHub repository URL for GeoHide DNS
    GITHUB_HOSTS_URL = "https://raw.githubusercontent.com/Internet-Helper/GeoHideDNS/main/hosts/hosts"

    def __init__(
        self,
        region: str = "RU",
        enabled: bool = True,
        priority: int = 15,
        cache_dir: Optional[str] = None
    ):
        reg = region.upper()
        name = f"GeoHide ({reg})"
        super().__init__(
            id=f"geohide-{reg.lower()}",
            name=name,
            enabled=enabled,
            priority=priority,
            cache_dir=cache_dir
        )
        self.region = reg
        self.known_ips = GEOHIDE_KNOWN_SERVERS.get(reg, GEOHIDE_KNOWN_SERVERS["RU"])
        self.supported_domains: Set[str] = set()
        self._domain_ips = {}
        self._load_cache()
        bundled = Path(__file__).resolve().parents[1] / "assets" / f"geohide_{reg.lower()}.txt"
        if not self._domain_ips and bundled.exists():
            self._domain_ips = parse_hosts(bundled.read_text(encoding="utf-8"))
        if self._domain_ips:
            self.supported_domains = set(self._domain_ips)
            self.known_ips = sorted({ip for ips in self._domain_ips.values() for ip in ips})

    @property
    def _cache_file(self) -> Optional[Path]:
        if self.cache_dir:
            p = Path(self.cache_dir)
            p.mkdir(parents=True, exist_ok=True)
            return p / f"geohide_{self.region.lower()}.json"
        return None

    def _load_cache(self) -> None:
        cache_p = self._cache_file
        if cache_p and cache_p.exists():
            try:
                data = json.loads(cache_p.read_text(encoding="utf-8"))
                self.last_updated = data.get("last_updated")
                self._domain_ips = data.get("domain_ips", {})
                self.known_ips = data.get("ips", self.known_ips)
                self.supported_domains = set(data.get("domains", []))
            except Exception as e:
                self.last_error = f"Cache load error: {e}"

    def _save_cache(self) -> None:
        cache_p = self._cache_file
        if cache_p:
            data = {
                "last_updated": self.last_updated,
                "region": self.region,
                "domain_ips": self._domain_ips,
                "ips": self.known_ips,
                "domains": sorted(list(self.supported_domains)),
            }
            cache_p.write_text(json.dumps(data, indent=2, ensure_ascii=False), encoding="utf-8")

    def fetch_candidates(self, domain: str) -> List[CandidateIP]:
        """
        Returns GeoHide IPs for the requested domain.
        If domain list is empty or domain matches, returns the region's candidate IPs.
        """
        if not self.enabled:
            return []

        return [CandidateIP(ip, self.id, self.name, self.region)
                for ip in self._domain_ips.get(domain.lower().strip(), [])]

    def update_database(self) -> bool:
        """Downloads latest hosts from GeoHide GitHub and extracts supported domains/IPs."""
        try:
            suffix = "hosts/hosts" if self.region == "RU" else f"hosts/{self.region.lower()}/hosts"
            url = "https://raw.githubusercontent.com/Internet-Helper/GeoHideDNS/main/" + suffix
            with httpx.Client(timeout=10.0, follow_redirects=True) as client:
                response = client.get(url)
                response.raise_for_status()
            if len(response.content) > 2_000_000:
                raise ValueError("Слишком большой ответ провайдера")
            mappings = parse_hosts(response.text)
            if not mappings:
                raise ValueError("Источник не содержит публичных адресов")
            self._domain_ips = mappings
            self.supported_domains = set(mappings)
            self.known_ips = sorted({ip for ips in mappings.values() for ip in ips})
            self.last_updated = datetime.now().strftime("%Y-%m-%d %H:%M:%S")
            self.last_error = None
            self._save_cache()
            return True
        except Exception as error:
            self.last_error = str(error)
            return False
