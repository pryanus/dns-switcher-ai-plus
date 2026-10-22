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

    def test_provider_manager_dedup_and_priority(self):
        manager = ProviderManager()
        with patch.object(GeoHideProvider, 'fetch_candidates', return_value=[CandidateIP('1.1.1.1', 'geohide-ru', 'GeoHide')]), \
             patch('providers.malw.MalwDnsProvider.fetch_candidates', return_value=[]), \
             patch('providers.zapret.ZapretDnsProvider.fetch_candidates', return_value=[]), \
             patch('providers.dns_ai.DnsAiProvider.fetch_candidates', return_value=[]):
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
