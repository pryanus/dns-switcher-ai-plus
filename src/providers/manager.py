"""
ProviderManager: Coordinates multiple DNS/SNI providers, prioritizes results, handles caching.
"""

from typing import Dict, List, Optional
from pathlib import Path
from threading import RLock
import time
from core.network import parallel
from core.validation import public_ip

from providers.base import BaseProvider, CandidateIP
from providers.geohide import GeoHideProvider
from providers.zapret import ZapretDnsProvider
from providers.malw import MalwDnsProvider
from providers.dns_ai import DnsAiProvider
from providers.custom import CustomProvider


class ProviderManager:
    def __init__(self, cache_dir: Optional[str] = None):
        self.operation_lock = RLock()
        self.cache_dir = cache_dir
        self._recent = {}
        self.providers: Dict[str, BaseProvider] = {}
        self._init_default_providers()

    def _init_default_providers(self) -> None:
        defaults = [
            GeoHideProvider(region="RU", enabled=True, priority=20, cache_dir=self.cache_dir),
            GeoHideProvider(region="EU", enabled=True, priority=18, cache_dir=self.cache_dir),
            GeoHideProvider(region="US", enabled=True, priority=16, cache_dir=self.cache_dir),
            MalwDnsProvider(enabled=True, priority=15, cache_dir=self.cache_dir),
            ZapretDnsProvider(enabled=True, priority=14, cache_dir=self.cache_dir),
            DnsAiProvider(enabled=True, priority=13, cache_dir=self.cache_dir),
            CustomProvider('google-public-dns', 'Google Public DNS (обычный DNS)',
                           CustomProvider.TYPE_DOH, 'https://dns.google/dns-query',
                           enabled=True, priority=1, cache_dir=self.cache_dir),
        ]
        for p in defaults:
            self.providers[p.id] = p

    def get_provider(self, provider_id: str) -> Optional[BaseProvider]:
        return self.providers.get(provider_id)

    def list_providers(self) -> List[BaseProvider]:
        return sorted(self.providers.values(), key=lambda p: p.priority, reverse=True)

    def add_custom_provider(self, provider: CustomProvider) -> None:
        self.providers[provider.id] = provider

    def remove_custom_provider(self, provider_id: str) -> bool:
        if provider_id in self.providers and isinstance(self.providers[provider_id], CustomProvider):
            del self.providers[provider_id]
            return True
        return False

    def set_provider_enabled(self, provider_id: str, enabled: bool) -> bool:
        p = self.get_provider(provider_id)
        if p:
            p.enabled = enabled
            return True
        return False

    def get_candidates(self, domain: str, cancellation=None) -> List[CandidateIP]:
        """
        Retrieves candidate IPs for a domain across all enabled providers,
        sorted by provider priority, with duplicates eliminated.
        """
        candidates: List[CandidateIP] = []
        seen_ips = set()

        sorted_providers = sorted(
            [p for p in self.providers.values() if p.enabled],
            key=lambda p: p.priority,
            reverse=True
        )

        def fetch(provider):
            key = (provider.id, domain)
            cached = self._recent.get(key)
            if cached and time.monotonic() - cached[0] < 60:
                return cached[1]
            value = provider.fetch_candidates(domain)
            self._recent[key] = (time.monotonic(), value)
            return value

        batches = parallel(sorted_providers, fetch, cancellation, timeout=4.0)
        for p, p_cands in zip(sorted_providers, batches):
            try:
                p_cands = p_cands or []
                for c in p_cands:
                    try:
                        c.ip = public_ip(c.ip)
                    except ValueError:
                        continue
                    if c.ip not in seen_ips:
                        seen_ips.add(c.ip)
                        candidates.append(c)
            except Exception as e:
                p.last_error = str(e)

        return candidates

    def update_all_databases(self, cancellation=None) -> Dict[str, bool]:
        """Runs update for all enabled providers."""
        providers = [p for p in self.providers.values() if p.enabled]
        def update(provider):
            try:
                return provider.update_database()
            except Exception as error:
                provider.last_error = str(error)
                return False
        results = parallel(providers, update, cancellation, timeout=6, limit=6)
        self._recent.clear()
        return {p.id: bool(result) for p, result in zip(providers, results)}
