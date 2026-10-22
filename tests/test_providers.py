import unittest
from unittest.mock import patch
from pathlib import Path
import sys

sys.path.insert(0, str(Path(__file__).parent.parent / "src"))

from providers.base import CandidateIP
from providers.geohide import GeoHideProvider
from providers.custom import CustomProvider
from providers.manager import ProviderManager


class TestProviders(unittest.TestCase):
    def test_duplicate_ips_keep_all_source_names(self):
        manager = ProviderManager()
        for p in manager.list_providers(): p.enabled = False
        for pid in ('first', 'second'):
            manager.add_custom_provider(CustomProvider(pid, pid, 'manual', '', {'example.com': '1.1.1.1'}))
        pool = manager.get_candidates('example.com')
        self.assertEqual(len(pool), 1)
        self.assertEqual({s['id'] for s in pool[0].sources}, {'first', 'second'})

    def test_update_requeries_persistent_doh_cache_and_invalidates_manager_cache(self):
        manager = ProviderManager()
        for p in manager.list_providers(): p.enabled = False
        provider = CustomProvider('test', 'test', 'doh', 'https://example.com/dns-query')
        provider._ip_cache = {'example.com': ['1.1.1.1']}
        provider.last_updated = '2000-01-01 00:00:00'
        manager.add_custom_provider(provider)
        manager._recent[('test', 'example.com')] = (0, [])
        with patch.object(provider, '_resolve_doh', return_value=['8.8.4.4']) as resolve:
            self.assertTrue(manager.update_all_databases()['test'])
            resolve.assert_called_once_with('example.com')
        self.assertEqual(manager._recent, {})
        self.assertEqual([c.ip for c in manager.get_candidates('example.com')], ['8.8.4.4'])

    def test_builtin_catalog_is_backed_by_published_provider_lists(self):
        import json
        from core.catalog import Catalog
        from core.validation import parse_hosts
        assets = Path(__file__).resolve().parents[1] / 'src/assets'
        known = set(parse_hosts((assets / 'malw_hosts.txt').read_text(encoding='utf-8')))
        for region in ('ru', 'eu', 'us'):
            known.update(parse_hosts((assets / f'geohide_{region}.txt').read_text(encoding='utf-8')))
        declared = {row['name'].casefold() for row in json.loads((assets / 'zapret_services.json').read_text(encoding='utf-8'))}
        aliases = {'sora': 'chatgpt & sora (openai)'}
        for service in Catalog().list_all():
            self.assertTrue(service.primary_domain in known or aliases.get(service.id) in declared, service.id)

    def test_full_geohide_pool_and_google_fallback_are_available(self):
        manager = ProviderManager()
        ips = {c.ip for p in manager.list_providers() if p.id.startswith('geohide-')
               for c in p.fetch_candidates('chatgpt.com')}
        self.assertGreaterEqual(len(ips), 15)
        google = manager.get_provider('google-public-dns')
        self.assertEqual(google.endpoint_or_ip, 'https://dns.google/dns-query')
        self.assertLess(google.priority, manager.get_provider('dns-ai').priority)

    def test_required_auxiliary_checks_exist_in_published_provider_hosts(self):
        from core.catalog import Catalog
        from core.service_checks import checks_for
        from core.validation import parse_hosts
        assets = Path(__file__).resolve().parents[1] / 'src/assets'
        known = set()
        for filename in ('malw_hosts.txt', 'geohide_ru.txt', 'geohide_eu.txt', 'geohide_us.txt'):
            known.update(parse_hosts((assets / filename).read_text(encoding='utf-8')))
        for service in Catalog().list_all():
            for domain, *_ in checks_for(service):
                if domain != service.primary_domain:
                    self.assertIn(domain, known, f'{service.id}: invented required endpoint {domain}')

    def test_geohide_regional_candidates(self):
        p_ru = GeoHideProvider(region="RU")
        p_eu = GeoHideProvider(region="EU")
        p_us = GeoHideProvider(region="US")

        ru_cands = p_ru.fetch_candidates("chatgpt.com")
        eu_cands = p_eu.fetch_candidates("chatgpt.com")
        us_cands = p_us.fetch_candidates("chatgpt.com")

        self.assertTrue(len(ru_cands) > 0)
        self.assertTrue(len(eu_cands) > 0)
        self.assertTrue(len(us_cands) > 0)

        # RU contains 193.233.112.68
        ru_ips = [c.ip for c in ru_cands]
        self.assertIn("193.233.112.68", ru_ips)

        # EU contains 5.175.161.40
        eu_ips = [c.ip for c in eu_cands]
        self.assertIn("5.175.161.40", eu_ips)

    def test_public_dns_and_matching_origin_addresses_are_not_bypass_routes(self):
        manager = ProviderManager()
        google = manager.get_provider('google-public-dns')
        smart = manager.get_provider('dns-ai')
        for provider in manager.list_providers():
            provider.enabled = provider in (google, smart)
        with patch.object(google, 'fetch_candidates', return_value=[CandidateIP('8.8.8.8', google.id, google.name)]), \
             patch.object(smart, 'fetch_candidates', return_value=[CandidateIP('8.8.8.8', smart.id, smart.name), CandidateIP('1.1.1.1', smart.id, smart.name)]):
            self.assertEqual([c.ip for c in manager.get_candidates('example.com')], ['1.1.1.1'])

    def test_provider_scoped_candidates_do_not_lose_shared_ip_to_another_provider(self):
        manager = ProviderManager()
        first = CustomProvider('first', 'First', 'manual', '', {'example.com': '1.1.1.1'})
        second = CustomProvider('second', 'Second', 'manual', '', {'example.com': '1.1.1.1'})
        for p in manager.list_providers(): p.enabled = False
        manager.add_custom_provider(first)
        manager.add_custom_provider(second)
        self.assertEqual(manager.get_candidates('example.com', provider_id='second')[0].provider_id, 'second')
        self.assertEqual(manager.get_candidates('unknown.example', provider_id='second'), [])

    def test_provider_manager_dedup_and_priority(self):
        manager = ProviderManager()
        with patch.object(GeoHideProvider, 'fetch_candidates', return_value=[CandidateIP('1.1.1.1', 'geohide-ru', 'GeoHide')]), \
             patch('providers.malw.MalwDnsProvider.fetch_candidates', return_value=[]), \
             patch('providers.zapret.ZapretDnsProvider.fetch_candidates', return_value=[]), \
             patch('providers.dns_ai.DnsAiProvider.fetch_candidates', return_value=[]), \
             patch.object(CustomProvider, '_resolve_doh', return_value=[]):
            cands = manager.get_candidates("example.com")
        self.assertTrue(len(cands) > 0)

        # Verify no duplicate IPs
        ips = [c.ip for c in cands]
        self.assertEqual(len(ips), len(set(ips)))

    def test_custom_provider_manual(self):
        cp = CustomProvider(
            id="test-custom",
            name="My Custom",
            provider_type=CustomProvider.TYPE_MANUAL,
            endpoint_or_ip="",
            static_mappings={"myservice.org": "198.51.100.1"}
        )
        cands = cp.fetch_candidates("myservice.org")
        self.assertEqual(len(cands), 1)
        self.assertEqual(cands[0].ip, "198.51.100.1")
        self.assertEqual(cands[0].provider_name, "My Custom")


if __name__ == "__main__":
    unittest.main()
