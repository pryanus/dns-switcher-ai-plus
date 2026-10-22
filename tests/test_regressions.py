"""Регрессии подбора и безопасной записи; только временные файлы и mock-сеть."""
import os
os.environ['QT_QPA_PLATFORM'] = 'offscreen'
import sys
import tempfile
import unittest
from pathlib import Path
from unittest.mock import MagicMock, patch
sys.path.insert(0, str(Path(__file__).resolve().parents[1] / 'src'))
from PySide6.QtWidgets import QApplication
from core.catalog import Catalog, ServiceDef
from core.hosts_manager import HostsManager
from core.storage import StorageManager, AppConfig
from core.verifier import ServiceVerifier, ServiceStatus, VerificationResult
from core.monitor import VerificationWorker
from core.single_instance import SingleInstance
from providers.manager import ProviderManager
from providers.base import CandidateIP
from providers.geohide import GeoHideProvider
from providers.custom import CustomProvider
from providers.dns_ai import DnsAiProvider


class Regressions(unittest.TestCase):
    @classmethod
    def setUpClass(cls):
        cls.app = QApplication.instance() or QApplication([])

    def setUp(self):
        self.tmp = tempfile.TemporaryDirectory()
        self.root = Path(self.tmp.name)
        self.hosts = self.root / 'hosts'
        self.hosts.write_text('127.0.0.1 localhost\n8.8.8.8 example.com keep.example # My Note\n')
        self.hm = HostsManager(str(self.hosts), str(self.root / 'backups'))
        self.storage = StorageManager(str(self.root / 'data'))
        self.providers = ProviderManager()
        for provider in self.providers.list_providers():
            if hasattr(provider, 'resolve_domain_doh'):
                provider.resolve_domain_doh = MagicMock(return_value=[])
            if hasattr(provider, '_resolve_doh'):
                provider._resolve_doh = MagicMock(return_value=[])
        self.service = ServiceDef(id='example', name='Example', category='Test',
            primary_domain='example.com', domains=['example.com', 'api.example.com'])

    def tearDown(self):
        self.tmp.cleanup()

    def test_invalid_hosts_input_leaves_file_and_backups_unchanged(self):
        before = self.hosts.read_bytes()
        for ip, domain in [('1.1.1.1\n8.8.8.8 evil.com', 'example.com'),
                           ('127.0.0.1', 'example.com'), ('1.1.1.1', 'example.com\nevil.com')]:
            with self.assertRaises(ValueError):
                self.hm.update_service_ip('Example', ip, [domain])
        self.assertEqual(before, self.hosts.read_bytes())
        self.assertEqual(self.hm.list_backups(), [])

    def test_shared_line_comment_and_unrelated_alias_survive(self):
        original = self.hosts.read_bytes()
        self.hm.update_service_ip('Example', '1.1.1.1', ['example.com'])
        self.assertEqual(self.hm._split_managed(self.hm.read_file_safely(self.hosts)[0])[1].encode('utf-8'), original)
        content = self.hosts.read_text()
        self.assertIn('keep.example # My Note', content)
        self.assertNotIn('evil', content)

    def test_add_update_remove_preserves_original_bytes(self):
        original = b'# User note\r\n8.8.8.8 EXAMPLE.com alias.example # Keep\n# Tail'
        self.hosts.write_bytes(original)
        self.hm.update_service_ip('Example', '1.1.1.1', ['example.com'])
        self.hm.update_service_ip('Example', '8.8.4.4', ['example.com'])
        self.assertEqual(self.hm._split_managed(self.hm.read_file_safely(self.hosts)[0])[1].encode('utf-8'), original)
        self.assertEqual(self.hosts.read_text().count(f"{'8.8.4.4':<16} example.com"), 1)
        self.assertEqual(self.hm.get_conflicts({'example.com': '8.8.4.4'}), {})
        self.hm.remove_service_entries('Example', ['example.com'])
        self.assertEqual(self.hosts.read_bytes(), original)

    def test_overrides_survive_restart_and_reset_services_independently(self):
        original = b'8.8.8.8 Example.com other.example keep.example # Keep\r\n'
        self.hosts.write_bytes(original)
        self.hm.update_service_ip('Example', '1.1.1.1', ['example.com'])
        self.hm.update_service_ip('Other', '9.9.9.9', ['other.example'])
        self.assertEqual(self.hm.parse_all_entries()['keep.example'], ['8.8.8.8'])
        restarted = HostsManager(str(self.hosts), str(self.root / 'restart-backups'))
        restarted.remove_service_entries('Example', ['example.com'])
        active = restarted.parse_all_entries()
        self.assertEqual(active['example.com'], ['8.8.8.8'])
        self.assertEqual(active['other.example'], ['9.9.9.9'])
        restarted.remove_all_managed_entries()
        self.assertEqual(self.hosts.read_bytes(), original)

    def test_override_reset_restores_encodings_and_missing_final_newline(self):
        for encoding in ('utf-8-sig', 'cp1251', 'latin-1'):
            with self.subTest(encoding=encoding):
                note = 'Заметка' if encoding == 'cp1251' else 'caf' + chr(233)
                text = '# Keep\r\n8.8.8.8 example.com keep.example # ' + note
                original = text.encode(encoding)
                self.hosts.write_bytes(original)
                self.hm.update_service_ip('Example', '1.1.1.1', ['example.com'])
                self.assertEqual(self.hm.parse_all_entries()['example.com'], ['1.1.1.1'])
                self.hm.remove_all_managed_entries()
                self.assertEqual(self.hosts.read_bytes(), original)

    def test_manually_edited_override_is_never_silently_discarded(self):
        self.hm.update_service_ip('Example', '1.1.1.1', ['example.com'])
        content, encoding = self.hm.read_file_safely(self.hosts)
        self.hm.write_file_safely(self.hosts, content.replace(
            '\r\n8.8.8.8    keep.example # My Note\r\n', '\r\n8.8.8.8    manually.edited.example # My Note\r\n'), encoding)
        before = self.hosts.read_bytes()
        with self.assertRaises(ValueError):
            self.hm.remove_all_managed_entries()
        self.assertEqual(self.hosts.read_bytes(), before)

    def test_reset_all_restores_original_bytes_including_foreign_routes(self):
        original = b'# GeoHide / custom\r\n8.8.8.8 example.com other.example # Keep\n# Tail'
        self.hosts.write_bytes(original)
        self.hm.update_service_ip('Example', '1.1.1.1', ['example.com'])
        self.hm.update_service_ip('Removed from catalog', '8.8.4.4', ['removed.example'])
        self.assertTrue(self.hm.remove_all_managed_entries())
        self.assertEqual(self.hosts.read_bytes(), original)
        self.assertFalse(self.hm.remove_all_managed_entries())

    def test_rotation_never_reapplies_current_ip_even_after_a_full_circle(self):
        self.hm.update_service_ip('Example', '1.1.1.1', ['example.com'])
        self.storage.config.rejected_routes['example'] = ['1.1.1.1', '8.8.4.4']
        candidates = [CandidateIP('1.1.1.1', 'manual', 'Current'),
                      CandidateIP('8.8.4.4', 'manual', 'Alternative')]
        worker = VerificationWorker([self.service], self.hm, self.providers, self.storage, True, rotate=True)
        with patch.object(self.providers, 'get_candidates', return_value=candidates), \
             patch.object(ServiceVerifier, 'verify_candidate', side_effect=lambda ip, domain, **kw:
                 self._result(ip, domain, ServiceStatus.OK)):
            worker.run()
        self.assertEqual(self.hm.parse_all_entries()['example.com'][0], '8.8.4.4')

    def test_rotation_with_only_current_ip_does_not_write(self):
        self.hm.update_service_ip('Example', '1.1.1.1', ['example.com'])
        before = self.hosts.read_bytes()
        results = []
        worker = VerificationWorker([self.service], self.hm, self.providers, self.storage, True, rotate=True)
        worker.service_result.connect(lambda sid, result, provider: results.append(result))
        with patch.object(self.providers, 'get_candidates', return_value=[CandidateIP('1.1.1.1', 'manual', 'Same IP')]), \
             patch.object(ServiceVerifier, 'verify_candidate') as probe:
            worker.run()
            probe.assert_not_called()
        self.assertEqual(self.hosts.read_bytes(), before)
        self.assertEqual(results[0].route_message, 'Других маршрутов нет')

    def test_rotation_can_keep_the_only_working_api_ip(self):
        self.hm.update_service_ip('Example', '1.1.1.1', ['example.com', 'api.example.com'])
        self.storage.config.rejected_routes['example'] = ['1.1.1.1']
        worker = VerificationWorker([self.service], self.hm, self.providers, self.storage, True, rotate=True)
        def candidates(domain, cancellation=None):
            return [CandidateIP('8.8.4.4' if domain == 'example.com' else '1.1.1.1', 'manual', 'Test')]
        with patch.object(self.providers, 'get_candidates', side_effect=candidates), \
             patch.object(ServiceVerifier, 'verify_candidate', side_effect=lambda ip, domain, **kw:
                 self._result(ip, domain, ServiceStatus.OK)):
            worker.run()
        self.assertEqual(self.hm.parse_all_entries()['example.com'][0], '8.8.4.4')
        self.assertEqual(self.hm.parse_all_entries()['api.example.com'], ['1.1.1.1'])

    def test_rotation_starts_new_circle_when_unvisited_routes_are_dead(self):
        self.hm.update_service_ip('Example', '1.1.1.1', ['example.com', 'api.example.com'])
        self.storage.config.rejected_routes['example'] = ['1.1.1.1', '8.8.4.4']
        pool = [CandidateIP(ip, 'manual', 'Test') for ip in ['1.1.1.1', '8.8.4.4', '9.9.9.9']]
        worker = VerificationWorker([self.service], self.hm, self.providers, self.storage, True, rotate=True)
        with patch.object(self.providers, 'get_candidates', return_value=pool), \
             patch.object(ServiceVerifier, 'verify_candidate', side_effect=lambda ip, domain, **kw:
                 self._result(ip, domain, ServiceStatus.DEAD if ip == '9.9.9.9' else ServiceStatus.OK)):
            worker.run()
        self.assertEqual(self.hm.parse_all_entries()['example.com'][0], '8.8.4.4')

    def test_full_route_replacement_drops_only_stale_managed_domains(self):
        original = self.hosts.read_bytes()
        self.hm.update_service_ip('Example', '1.1.1.1', ['example.com', 'old.example'])
        self.hm.update_multiple_services([dict(service_name='Example', target_ip='8.8.4.4',
            domains=['example.com', 'api.example.com'], replace=True)])
        self.assertNotIn('old.example', self.hm.parse_all_entries())
        self.assertEqual(self.hm._split_managed(self.hm.read_file_safely(self.hosts)[0])[1].encode('utf-8'), original)

    def test_cloudflare_challenge_is_not_a_working_route(self):
        result = VerificationResult('1.1.1.1', 'example.com', ServiceStatus.PARTIAL, 1,
            'Cloudflare challenge', 'HTTP', 200)
        self.assertFalse(result.is_routable)
        result.details = 'Generic access denied'
        self.assertFalse(result.is_routable)

    def test_critical_api_uses_the_available_pool_instead_of_two_dead_ips(self):
        candidates = [CandidateIP('1.1.1.1', 'manual', 'First'), CandidateIP('8.8.4.4', 'manual', 'Second'),
                      CandidateIP('9.9.9.9', 'manual', 'Third')]
        worker = VerificationWorker([self.service], self.hm, self.providers, self.storage, True)
        with patch.object(self.providers, 'get_candidates', return_value=candidates), \
             patch.object(ServiceVerifier, 'verify_candidate', side_effect=lambda ip, domain, **kw:
                 self._result(ip, domain, ServiceStatus.OK if ip == '9.9.9.9' else ServiceStatus.DEAD)):
            result = worker._domain_route(('api.example.com', '/', 'API', (401,)), candidates[0], {})
        self.assertTrue(result['ok'])
        self.assertEqual(result['ip'], '9.9.9.9')

    def test_cross_host_redirect_uses_resolved_target_and_rejects_geoblock(self):
        for body, expected in [(b'Welcome', ServiceStatus.OK),
                               (b'not available in your country', ServiceStatus.DEAD)]:
            with patch('socket.socket'), patch('ssl.create_default_context') as context:
                first, second = MagicMock(), MagicMock()
                context.return_value.wrap_socket.side_effect = [first, second]
                first.recv.side_effect = [b'HTTP/1.1 301 Moved\r\nLocation: https://www.example.com/app\r\nContent-Length: 0\r\n\r\n']
                second.recv.side_effect = [b'HTTP/1.1 200 OK\r\n\r\n' + body, b'']
                result = ServiceVerifier.verify_candidate('1.1.1.1', 'example.com', redirect_resolver=lambda host: ['8.8.4.4'])
                self.assertEqual(result.status, expected)
                self.assertEqual(context.return_value.wrap_socket.call_args.kwargs['server_hostname'], 'www.example.com')

    def test_broken_managed_marker_fails_without_deleting_data(self):
        original = b'# === DNS Switcher Managed: Broken ===\n8.8.8.8 original.example\n'
        self.hosts.write_bytes(original)
        with self.assertRaises(ValueError):
            self.hm.update_service_ip('Example', '1.1.1.1', ['example.com'])
        self.assertEqual(self.hosts.read_bytes(), original)

    def test_retired_twitch_cleanup_preserves_foreign_entries_and_other_services(self):
        from main import _remove_retired_services
        original = b'# Keep\r\n8.8.8.8 twitch.tv www.twitch.tv # User entry\r\n'
        self.hosts.write_bytes(original)
        self.hm.update_service_ip('Twitch', '1.1.1.1', ['www.twitch.tv', 'gql.twitch.tv'])
        self.hm.update_service_ip('Example', '9.9.9.9', ['example.com'])
        self.storage.config.active_routes['twitch'] = {'ip': '1.1.1.1'}
        self.storage.config.active_routes['example'] = {'ip': '9.9.9.9'}
        self.storage.config.favorites.append('twitch')
        self.assertTrue(_remove_retired_services(self.hm, self.storage))
        self.assertEqual(self.hm._split_managed(self.hm.read_file_safely(self.hosts)[0])[1].encode('utf-8'), original)
        self.assertNotIn('DNS Switcher Managed: Twitch', self.hosts.read_text())
        self.assertEqual(self.hm.parse_all_entries()['example.com'], ['9.9.9.9'])
        self.assertNotIn('twitch', self.storage.config.active_routes)
        self.assertNotIn('twitch', self.storage.config.favorites)
        self.assertIn('example', self.storage.config.active_routes)
        before = self.hosts.read_bytes()
        self.assertFalse(_remove_retired_services(self.hm, self.storage))
        self.assertEqual(self.hosts.read_bytes(), before)

    def test_catalog_focus_and_stable_priority(self):
        services = Catalog().list_all()
        self.assertEqual(len(services), 19)
        self.assertEqual([s.id for s in services[:4]], ['chatgpt', 'gemini', 'claude', 'elevenlabs'])
        self.assertEqual({s.id for s in Catalog().list_favorites()}, {'spotify', 'chatgpt', 'gemini', 'claude'})
        self.assertTrue({'steam', 'ea', 'battlenet', 'epicgames', 'xbox', 'playstation', 'twitter', 'youtube', 'discord', 'twitch', 'opencode', 'windsurf', 'disneyplus', 'paramountplus'}.isdisjoint({s.id for s in services}))
        self.assertEqual(len({s.id for s in services}), len(services))
        self.assertEqual(sum(s.category == 'Нейросети' for s in services), 14)
        self.assertEqual(sum(s.category == 'Музыка, видео и общение' for s in services), 5)

    def test_existing_favorites_migrate_once_without_changing_routes(self):
        import json
        self.storage.config_path.write_text(json.dumps(dict(favorites=['claude', 'spotify'],
            active_routes={'chatgpt': {'ip': '1.1.1.1'}}, monitoring_enabled=False)))
        migrated = StorageManager(str(self.storage.data_dir))
        self.assertEqual(migrated.config.favorites, ['spotify', 'chatgpt', 'gemini', 'claude'])
        self.assertEqual(migrated.config.active_routes['chatgpt']['ip'], '1.1.1.1')
        migrated.config.favorites.append('elevenlabs')
        migrated.save_config()
        self.assertIn('elevenlabs', StorageManager(str(self.storage.data_dir)).config.favorites)

    def test_partial_update_preserves_old_managed_domain(self):
        self.hm.update_service_ip('Example', '1.1.1.1', ['example.com', 'api.example.com'])
        self.hm.update_service_ip('Example', '8.8.4.4', ['example.com'])
        self.assertEqual(self.hm.parse_all_entries()['api.example.com'], ['1.1.1.1'])
        self.assertEqual(self.hm.parse_all_entries()['example.com'], ['8.8.4.4'])

    def test_domain_specific_ips_and_unique_backups(self):
        self.hm.update_multiple_services([dict(service_name='Example', target_ip='1.1.1.1',
            domains=self.service.domains, domain_ips={'api.example.com': '8.8.4.4'})])
        self.assertEqual(self.hm.parse_all_entries()['api.example.com'], ['8.8.4.4'])
        first = self.hm.create_backup(); second = self.hm.create_backup()
        self.assertNotEqual(first, second)

    def test_empty_favorites_and_catalog_instances_are_independent(self):
        self.assertEqual(AppConfig(favorites=[]).favorites, [])
        first, second = Catalog(), Catalog()
        first.set_favorite('spotify', False)
        self.assertTrue(second.get_service('spotify').is_favorite)

    def test_403_is_not_success(self):
        with patch('socket.socket') as sock, patch('ssl.create_default_context') as context:
            tls = context.return_value.wrap_socket.return_value
            tls.recv.side_effect = [b'HTTP/1.1 403 Forbidden\r\n\r\nAccess denied', b'']
            result = ServiceVerifier.verify_candidate('1.1.1.1', 'example.com')
        self.assertEqual(result.status, ServiceStatus.PARTIAL)

    def test_dns_ai_uses_http2_and_clears_old_error(self):
        import dns.message, dns.rrset
        provider = DnsAiProvider()
        provider.last_error = 'HTTP 505'
        query = dns.message.make_query('gemini.google.com', 'A')
        answer = dns.message.make_response(query)
        answer.answer.append(dns.rrset.from_text('gemini.google.com.', 60, 'IN', 'A', '1.1.1.1'))
        with patch('providers.dns_ai.httpx.Client') as client:
            response = client.return_value.__enter__.return_value.post.return_value
            response.status_code = 200
            response.content = answer.to_wire()
            self.assertEqual(provider.resolve_domain_doh('gemini.google.com'), ['1.1.1.1'])
            self.assertTrue(client.call_args.kwargs['http2'])
            self.assertIsNone(provider.last_error)

    def test_cloudflare_route_is_never_applied_even_after_explicit_switch(self):
        for mode in ({}, {'rotate': True}, {'forced': ('1.1.1.1', 'Test')}):
            with self.subTest(mode=mode):
                service = ServiceDef(id='gemini', name='Gemini', category='AI',
                                     primary_domain='gemini.google.com', domains=['gemini.google.com'])
                before = self.hosts.read_bytes()
                worker = VerificationWorker([service], self.hm, self.providers, self.storage, True, **mode)
                challenge = VerificationResult('1.1.1.1', service.primary_domain, ServiceStatus.PARTIAL,
                    1, 'Cloudflare challenge: JavaScript required', 'HTTP', 403)
                with patch.object(self.providers, 'get_candidates', return_value=[CandidateIP('1.1.1.1', 'manual', 'Test')]), \
                     patch.object(ServiceVerifier, 'verify_candidate', return_value=challenge):
                    worker.run()
                self.assertEqual(self.hosts.read_bytes(), before)
                self.assertIsNone(self.storage.get_active_route('gemini'))

    def test_failed_provider_api_does_not_stop_the_next_provider(self):
        pool = [CandidateIP('1.1.1.1', 'first', 'First'), CandidateIP('8.8.4.4', 'second', 'Second')]
        worker = VerificationWorker([self.service], self.hm, self.providers, self.storage, True)
        def probe(ip, domain, **kwargs):
            status = ServiceStatus.DEAD if domain == 'api.example.com' and ip == '1.1.1.1' else ServiceStatus.OK
            return self._result(ip, domain, status)
        with patch.object(self.providers, 'get_candidates', return_value=pool), \
             patch.object(ServiceVerifier, 'verify_candidate', side_effect=probe):
            worker.run()
        route = self.storage.get_active_route('example')
        self.assertIn(route['ip'], {'1.1.1.1', '8.8.4.4'})
        self.assertEqual(route['domain_ips']['api.example.com'], '8.8.4.4')

    def test_primary_and_api_from_different_sources_are_combined_when_both_pass(self):
        pool = [CandidateIP('1.1.1.1', 'first', 'First'), CandidateIP('8.8.4.4', 'second', 'Second')]
        before = self.hosts.read_bytes()
        worker = VerificationWorker([self.service], self.hm, self.providers, self.storage, True)
        def probe(ip, domain, **kwargs):
            good = (domain == 'example.com' and ip == '1.1.1.1') or (domain == 'api.example.com' and ip == '8.8.4.4')
            return self._result(ip, domain, ServiceStatus.OK if good else ServiceStatus.DEAD)
        with patch.object(self.providers, 'get_candidates', return_value=pool), \
             patch.object(ServiceVerifier, 'verify_candidate', side_effect=probe):
            worker.run()
        self.assertEqual(self.storage.get_active_route('example')['domain_ips'],
                         {'example.com': '1.1.1.1', 'api.example.com': '8.8.4.4'})

    def test_verified_response_has_priority_over_cloudflare_challenge(self):
        self.hm.update_service_ip('Example', '9.9.9.9', self.service.domains)
        candidates = [CandidateIP('1.1.1.1', 'geohide-eu', 'GeoHide'),
                      CandidateIP('8.8.4.4', 'manual', 'Other')]
        worker = VerificationWorker([self.service], self.hm, self.providers, self.storage, True, rotate=True)
        def probe(ip, domain, **kwargs):
            if ip == '1.1.1.1':
                return VerificationResult(ip, domain, ServiceStatus.PARTIAL, 10,
                    'Cloudflare challenge: browser required', 'HTTP', 403)
            return self._result(ip, domain, ServiceStatus.OK)
        with patch.object(self.providers, 'get_candidates', return_value=candidates), \
             patch.object(ServiceVerifier, 'verify_candidate', side_effect=probe):
            worker.run()
        route = self.storage.get_active_route(self.service.id)
        self.assertEqual(route['ip'], '8.8.4.4')
        self.assertEqual(route['status'], 'OK')

    def test_explicit_rotation_changes_ip_for_every_builtin_service(self):
        pool = [CandidateIP(ip, 'manual', 'Test') for ip in ('1.1.1.1', '8.8.4.4', '9.9.9.9')]
        def verified(ip, domain, **kwargs):
            return VerificationResult(ip, domain, ServiceStatus.OK, 10, 'Verified endpoint', 'HTTP', 200)
        for service in Catalog().list_all():
            with self.subTest(service=service.id):
                original = ('127.0.0.1 localhost\r\n' +
                    f'1.1.1.1 {service.primary_domain} keep.example # Keep\n' +
                    f'8.8.8.8 {service.primary_domain}\r\n' +
                    f'2606:4700:4700::1111 {service.primary_domain}').encode('utf-8')
                self.hosts.write_bytes(original)
                self.hm.update_service_ip(service.name, '1.1.1.1', service.domains)
                previous = '1.1.1.1'
                self.storage.config.rejected_routes[service.id] = []
                for _ in range(2):
                    self.storage.config.rejected_routes[service.id].append(previous)
                    worker = VerificationWorker([service], self.hm, self.providers, self.storage, True, rotate=True)
                    with patch.object(self.providers, 'get_candidates', return_value=pool), \
                         patch.object(ServiceVerifier, 'verify_candidate', side_effect=verified):
                        worker.run()
                    route = self.storage.get_active_route(service.id)
                    self.assertIsNotNone(route)
                    self.assertNotEqual(route['ip'], previous)
                    self.assertEqual(route['status'], 'OK')
                    self.assertFalse(route['confirmed'])
                    self.assertEqual(self.hm.parse_all_entries()[service.primary_domain], [route['ip']])
                    self.assertEqual(self.hm.parse_all_entries()['keep.example'], ['1.1.1.1'])
                    previous = route['ip']
                self.hm.remove_service_entries(service.name, service.domains)
                self.assertEqual(self.hosts.read_bytes(), original)

    def test_api_failure_rejects_a_working_homepage(self):
        self.hosts.write_text('127.0.0.1 localhost\n')
        worker = VerificationWorker([self.service], self.hm, self.providers, self.storage, True,
                                    forced=('1.1.1.1', 'DNS-AI'))
        def probe(ip, domain, **kw):
            return self._result(ip, domain, ServiceStatus.OK if domain == 'example.com' else ServiceStatus.DEAD)
        with patch.object(ServiceVerifier, 'verify_candidate', side_effect=probe):
            worker.run()
        self.assertIsNone(self.storage.get_active_route('example'))
        self.assertEqual(self.hosts.read_text(), '127.0.0.1 localhost\n')

    def test_geoblock_body_is_dead(self):
        with patch('socket.socket'), patch('ssl.create_default_context') as context:
            context.return_value.wrap_socket.return_value.recv.side_effect = [
                b'HTTP/1.1 403 Forbidden\r\n\r\n{"code":"unsupported_country_region_territory"}', b'']
            result = ServiceVerifier.verify_candidate('1.1.1.1', 'example.com')
        self.assertEqual(result.status, ServiceStatus.DEAD)

    def test_geohide_refresh_replaces_ips_and_filters_unsupported_domains(self):
        provider = GeoHideProvider()
        with patch('providers.geohide.httpx.Client') as client:
            response = client.return_value.__enter__.return_value.get.return_value
            response.text = '1.1.1.1 example.com # note\n0.0.0.0 blocked.example\n'
            response.content = response.text.encode()
            self.assertTrue(provider.update_database())
        self.assertEqual([c.ip for c in provider.fetch_candidates('example.com')], ['1.1.1.1'])
        self.assertEqual(provider.fetch_candidates('unsupported.example'), [])
        self.assertNotIn('note', provider.supported_domains)

    def test_custom_empty_download_fails_and_cache_id_cannot_escape(self):
        with self.assertRaises(ValueError):
            CustomProvider('../escape', 'Bad', 'manual', '')
        provider = CustomProvider('test', 'Test', 'hosts_url', 'https://example.com/hosts')
        with patch('providers.custom.httpx.Client') as client:
            client.return_value.__enter__.return_value.get.return_value.status_code = 404
            self.assertFalse(provider.update_database())

    def test_second_instance_is_rejected_then_lock_is_reusable(self):
        first, second = SingleInstance(self.tmp.name), SingleInstance(self.tmp.name)
        self.assertTrue(first.acquire())
        self.assertFalse(second.acquire())
        self.app.processEvents()
        first.close()
        self.assertTrue(second.acquire())
        second.close()

    @unittest.skipUnless(os.name == 'nt', 'Windows mutex')
    def test_mutex_blocks_another_version_even_with_a_different_temp_lock(self):
        from PySide6.QtCore import QLockFile
        first, second = SingleInstance(self.tmp.name), SingleInstance(self.tmp.name)
        second.name += '-other-version'
        second.lock = QLockFile(str(self.root / 'different-temp.lock'))
        self.assertTrue(first.acquire())
        try:
            self.assertFalse(second.acquire())
        finally:
            first.close()
        self.assertTrue(second.acquire())
        second.close()

    def _result(self, ip, domain, status):
        return VerificationResult(ip, domain, status, 1, 'Mock')

    def test_partial_candidate_is_not_applied(self):
        before = self.hosts.read_bytes()
        worker = VerificationWorker([self.service], self.hm, self.providers, self.storage, True)
        candidate = CandidateIP('1.1.1.1', 'test', 'Test')
        with patch.object(self.providers, 'get_candidates', return_value=[candidate]), \
             patch.object(ServiceVerifier, 'verify_candidate', side_effect=lambda ip, domain, **kw: self._result(ip, domain, ServiceStatus.PARTIAL)):
            worker.run()
        self.assertEqual(before, self.hosts.read_bytes())
        self.assertIsNone(self.storage.get_active_route('example'))

    def test_probe_does_not_save_suggested_route(self):
        worker = VerificationWorker([self.service], self.hm, self.providers, self.storage, False)
        candidate = CandidateIP('1.1.1.1', 'test', 'Test')
        def probe(ip, domain, **kw):
            return self._result(ip, domain, ServiceStatus.OK if ip == '1.1.1.1' else ServiceStatus.DEAD)
        before = self.hosts.read_bytes()
        with patch.object(self.providers, 'get_candidates', return_value=[candidate]), \
             patch.object(ServiceVerifier, 'verify_candidate', side_effect=probe):
            worker.run()
        self.assertEqual(before, self.hosts.read_bytes())
        self.assertIsNone(self.storage.get_active_route('example'))

    def test_cancelled_worker_never_writes(self):
        worker = VerificationWorker([self.service], self.hm, self.providers, self.storage, True)
        worker.cancel()
        with patch.object(self.hm, 'update_multiple_services') as write:
            worker.run()
            write.assert_not_called()

    def test_unsupported_streaming_and_dpi_never_rewrite_hosts(self):
        services = [ServiceDef('unsupported', 'Unsupported', 'Test', 'example.org', ['example.org'], routing_mode='unverified')]
        worker = VerificationWorker(services, self.hm, self.providers, self.storage, True)
        before = self.hosts.read_bytes()
        with patch.object(ServiceVerifier, 'verify_candidate') as probe:
            worker.run()
            probe.assert_not_called()
        self.assertEqual(before, self.hosts.read_bytes())

    def test_tray_default_migration_preserves_custom_favorites(self):
        import json
        self.storage.config_path.write_text(json.dumps(dict(catalog_revision=3,
            favorites=['spotify'], minimize_to_tray=False)))
        migrated = StorageManager(str(self.storage.data_dir))
        self.assertTrue(migrated.config.minimize_to_tray)
        self.assertEqual(migrated.config.favorites, ['spotify'])

    def test_old_migration_does_not_force_retired_preferences(self):
        import json
        self.storage.config_path.write_text(json.dumps(dict(catalog_revision=4,
            favorites=['spotify'], hidden_services=['claude', 'netflix'])))
        migrated = StorageManager(str(self.storage.data_dir))
        self.assertEqual(migrated.config.favorites, ['spotify'])
        self.assertEqual(migrated.config.hidden_services, ['claude', 'netflix'])
        migrated.save_config()
        self.assertNotIn('claude', StorageManager(str(self.storage.data_dir)).config.favorites)

    def test_bad_auxiliary_domain_is_not_repointed(self):
        worker = VerificationWorker([self.service], self.hm, self.providers, self.storage, True,
                                    forced=('1.1.1.1', 'Test'))
        def probe(ip, domain, **kw):
            return self._result(ip, domain, ServiceStatus.OK if domain == 'example.com' else ServiceStatus.DEAD)
        with patch.object(ServiceVerifier, 'verify_candidate', side_effect=probe):
            worker.run()
        entries = self.hm.parse_all_entries()
        self.assertEqual(entries['example.com'], ['8.8.8.8'])
        self.assertNotIn('api.example.com', entries)
        self.assertIsNone(self.storage.get_active_route('example'))

    def test_geo_error_in_http_200_or_redirect_is_rejected(self):
        for payload in [b'HTTP/1.1 200 OK\r\n\r\nUser location is not supported',
                        b'HTTP/1.1 302 Found\r\nLocation: /unsupported-country\r\n\r\n']:
            with patch('socket.socket'), patch('ssl.create_default_context') as context:
                context.return_value.wrap_socket.return_value.recv.side_effect = [payload, b'']
                self.assertEqual(ServiceVerifier.verify_candidate('1.1.1.1', 'example.com').status,
                                 ServiceStatus.DEAD)

    def test_chatgpt_files_failure_never_applies_homepage_only_route(self):
        service = Catalog().get_service('chatgpt')
        self.storage.set_active_route('chatgpt', '8.8.8.8', 'Previous', 'OK', 1)
        self.storage.get_active_route('chatgpt')['confirmed'] = True
        worker = VerificationWorker([service], self.hm, self.providers, self.storage, True,
                                    forced=('1.1.1.1', 'Test'))
        def probe(ip, domain, **kwargs):
            return self._result(ip, domain, ServiceStatus.DEAD if domain == 'files.oaiusercontent.com' else ServiceStatus.OK)
        before = self.hosts.read_bytes()
        with patch.object(ServiceVerifier, 'verify_candidate', side_effect=probe):
            worker.run()
        self.assertEqual(self.hosts.read_bytes(), before)
        self.assertEqual(self.storage.get_active_route('chatgpt')['status'], 'OK')
        self.assertTrue(self.storage.get_active_route('chatgpt')['confirmed'])

    def test_cancel_does_not_wait_for_provider_query_or_write(self):
        from threading import Event
        import time
        entered, release = Event(), Event()
        def slow(domain):
            entered.set()
            release.wait(2)
            return [CandidateIP('1.1.1.1', 'test', 'Test')]
        worker = VerificationWorker([self.service], self.hm, self.providers, self.storage, True, rotate=True)
        before = self.hosts.read_bytes()
        with patch.object(self.providers.get_provider('geohide-ru'), 'fetch_candidates', side_effect=slow):
            for provider in self.providers.list_providers():
                provider.enabled = provider.id == 'geohide-ru'
            worker.start()
            self.assertTrue(entered.wait(1))
            started = time.monotonic()
            worker.cancel()
            stopped = worker.wait(500)
            release.set()
            self.assertTrue(stopped)
            self.assertLess(time.monotonic() - started, .5)
        self.assertEqual(self.hosts.read_bytes(), before)

    def test_cancel_while_operation_lock_is_busy(self):
        worker = VerificationWorker([self.service], self.hm, self.providers, self.storage, True)
        with self.providers.operation_lock:
            worker.start()
            worker.cancel()
            self.assertTrue(worker.wait(500))

    def test_working_external_hosts_route_is_kept_without_fetching_a_pool(self):
        self.hosts.write_text('8.8.8.8 example.com api.example.com\n')
        before = self.hosts.read_bytes()
        worker = VerificationWorker([self.service], self.hm, self.providers, self.storage, True)
        results = []
        worker.service_result.connect(lambda sid, result, provider: results.append(result))
        with patch.object(self.providers, 'get_candidates') as pool, \
             patch.object(ServiceVerifier, 'verify_candidate', side_effect=lambda ip, domain, **kw:
                 self._result(ip, domain, ServiceStatus.OK)):
            worker.run()
            pool.assert_not_called()
        self.assertEqual(before, self.hosts.read_bytes())
        self.assertEqual(results[0].status, ServiceStatus.OK)
        self.assertEqual(results[0].ip, '8.8.8.8')
        self.assertFalse(results[0].applied)

    def test_current_probe_failure_does_not_mark_service_as_inaccessible(self):
        worker = VerificationWorker([self.service], self.hm, self.providers, self.storage, False)
        results = []
        worker.service_result.connect(lambda sid, result, provider: results.append(result))
        with patch.object(ServiceVerifier, 'verify_candidate', side_effect=lambda ip, domain, **kw:
                self._result(ip, domain, ServiceStatus.DEAD)):
            worker.run()
        self.assertEqual(results[0].status, ServiceStatus.UNKNOWN)

    def test_new_selection_prefers_low_latency_after_validation(self):
        self.hosts.write_text('127.0.0.1 localhost\n')
        candidates = [CandidateIP('1.1.1.1', 'manual', 'Slow'), CandidateIP('8.8.4.4', 'manual', 'Fast')]
        worker = VerificationWorker([self.service], self.hm, self.providers, self.storage, True, rotate=True)
        def probe(ip, domain, **kwargs):
            return VerificationResult(ip, domain, ServiceStatus.OK, 150 if ip == '1.1.1.1' else 20)
        with patch.object(self.providers, 'get_candidates', return_value=candidates), \
             patch.object(ServiceVerifier, 'verify_candidate', side_effect=probe):
            worker.run()
        self.assertEqual(self.storage.get_active_route('example')['ip'], '8.8.4.4')

    def test_geohide_beats_a_faster_non_geohide_route(self):
        self.hosts.write_text('127.0.0.1 localhost\n')
        candidates = [CandidateIP('1.1.1.1', 'zapret-dns', 'Zapret'),
                      CandidateIP('8.8.4.4', 'geohide-eu', 'GeoHide (EU)')]
        worker = VerificationWorker([self.service], self.hm, self.providers, self.storage, True, rotate=True)
        with patch.object(self.providers, 'get_candidates', return_value=candidates), \
             patch.object(ServiceVerifier, 'verify_candidate', side_effect=lambda ip, domain, **kw:
                 VerificationResult(ip, domain, ServiceStatus.OK, 1 if ip == '1.1.1.1' else 150)):
            worker.run()
        route = self.storage.get_active_route('example')
        self.assertEqual(route['ip'], '8.8.4.4')
        self.assertEqual(route['domain_ips']['api.example.com'], '8.8.4.4')

    def test_upgrade_preserves_disabled_geohide_regions(self):
        import json
        self.storage.config_path.write_text(json.dumps(dict(catalog_revision=5,
            providers_enabled={'geohide-ru': True, 'geohide-eu': False, 'geohide-us': False})))
        migrated = StorageManager(str(self.storage.data_dir))
        self.assertFalse(migrated.config.providers_enabled['geohide-eu'])
        self.assertFalse(migrated.config.providers_enabled['geohide-us'])
        migrated.config.providers_enabled['geohide-eu'] = False
        migrated.save_config()
        self.assertFalse(StorageManager(str(self.storage.data_dir)).config.providers_enabled['geohide-eu'])

    def test_suspicious_traffic_is_rejected_even_with_http_200(self):
        for response in (b'HTTP/1.1 200 OK\r\n\r\nOur systems have detected unusual traffic',
                         b'HTTP/1.1 302 Found\r\nLocation: https://www.google.com/sorry/index\r\n\r\n'):
            with patch('socket.socket'), patch('ssl.create_default_context') as context:
                context.return_value.wrap_socket.return_value.recv.side_effect = [response, b'']
                result = ServiceVerifier.verify_candidate('1.1.1.1', 'gemini.google.com')
                self.assertFalse(result.is_routable)

    def test_current_homepage_success_cannot_hide_failed_api(self):
        self.hosts.write_text('8.8.8.8 example.com api.example.com\n')
        worker = VerificationWorker([self.service], self.hm, self.providers, self.storage, False)
        results = []
        worker.service_result.connect(lambda sid, result, provider: results.append(result))
        with patch.object(ServiceVerifier, 'verify_candidate', side_effect=lambda ip, domain, **kw:
             self._result(ip, domain, ServiceStatus.OK if domain == 'example.com' else ServiceStatus.DEAD)):
            worker.run()
        self.assertEqual(results[0].status, ServiceStatus.UNKNOWN)

    def test_finished_pool_restarts_from_geohide_priority(self):
        self.hosts.write_text('127.0.0.1 localhost\n')
        self.storage.config.rejected_routes['example'] = ['1.1.1.1', '8.8.4.4']
        candidates = [CandidateIP('1.1.1.1', 'manual', 'GeoHide'), CandidateIP('8.8.4.4', 'manual', 'DNS-AI')]
        worker = VerificationWorker([self.service], self.hm, self.providers, self.storage, True)
        with patch.object(self.providers, 'get_candidates', return_value=candidates), \
             patch.object(ServiceVerifier, 'verify_candidate', side_effect=lambda ip, domain, **kw: self._result(ip, domain, ServiceStatus.OK)):
            worker.run()
        self.assertEqual(self.storage.get_active_route('example')['provider_name'], 'GeoHide')
        self.assertNotIn('example', self.storage.config.rejected_routes)

    def test_cancel_closes_registered_socket(self):
        from core.network import Cancellation, Cancelled
        token = Cancellation()
        sock = MagicMock()
        token.track(sock)
        token.cancel()
        sock.shutdown.assert_called_once()
        sock.close.assert_called_once()
        with self.assertRaises(Cancelled):
            token.check()

    def test_parallel_probes_overlap_instead_of_waiting_sequentially(self):
        from core.network import parallel
        import time
        def probe(value):
            time.sleep(.12)
            return value
        started = time.monotonic()
        self.assertEqual(parallel(range(4), probe, timeout=1), [0, 1, 2, 3])
        self.assertLess(time.monotonic() - started, .4)

    def test_cancellation_interrupts_real_local_socket_io(self):
        # Только loopback: внешние сервисы и системный hosts не используются.
        import socket
        from threading import Thread, Event
        from core.network import Cancellation, Cancelled
        accepted, released, done = Event(), Event(), Event()
        listener = socket.socket()
        listener.bind(('127.0.0.1', 0))
        listener.listen(1)
        port = listener.getsockname()[1]
        def server():
            connection, _ = listener.accept()
            accepted.set()
            released.wait(2)
            connection.close()
        Thread(target=server, daemon=True).start()
        token = Cancellation()
        def client():
            try:
                ServiceVerifier.verify_candidate('127.0.0.1', 'example.com', port=port,
                                                  timeout=2, cancellation=token)
            except Cancelled:
                pass
            finally:
                done.set()
        thread = Thread(target=client, daemon=True)
        thread.start()
        try:
            self.assertTrue(accepted.wait(1))
            token.cancel()
            self.assertTrue(done.wait(.5))
        finally:
            released.set()
            listener.close()

    def test_selection_checks_all_nodes_and_rejects_previously_bad_route(self):
        self.hosts.write_text('127.0.0.1 localhost\n')
        self.storage.config.rejected_routes['example'] = ['1.1.1.1']
        worker = VerificationWorker([self.service], self.hm, self.providers, self.storage, True)
        candidates = [CandidateIP('1.1.1.1', 'manual', 'Bad'), CandidateIP('8.8.4.4', 'manual', 'Test')]
        with patch.object(self.providers, 'get_candidates', return_value=candidates), \
             patch.object(ServiceVerifier, 'verify_candidate', side_effect=lambda ip, domain, **kw: self._result(ip, domain, ServiceStatus.OK)) as probe:
            worker.run()
        route = self.storage.get_active_route('example')
        self.assertEqual(route['ip'], '8.8.4.4')
        self.assertFalse(route['confirmed'])
        self.assertEqual(route['status'], 'OK')
        self.assertFalse(any(call.args[0] == '1.1.1.1' and call.args[1] == self.service.primary_domain
                             for call in probe.call_args_list))
        self.assertEqual(set(route['domain_ips']), set(self.service.domains))

    def test_pool_checks_all_waves_without_global_deadline_or_provider_cascade(self):
        worker = VerificationWorker([self.service], self.hm, self.providers, self.storage, True)
        pool = [CandidateIP(f'8.8.4.{i}', 'same-provider', 'Same') for i in range(1, 22)]
        def verify(ip, domain, **kwargs):
            return VerificationResult(ip, domain, ServiceStatus.OK if ip.endswith('.21') else ServiceStatus.DEAD,
                                      1, 'TCP timed out', 'TCP')
        with patch.object(ServiceVerifier, 'verify_candidate', side_effect=verify):
            results = worker._test_pool(pool, 'example.com', '/', (), 'example')
        self.assertEqual(len([r for r in results if r]), 21)
        self.assertTrue(results[-1].is_routable)
        self.assertEqual(len(worker._detail_rows['example']['example.com']), 21)

    def test_cross_host_redirect_without_resolver_is_unknown(self):
        with patch('socket.socket') as socket_factory, patch('ssl.create_default_context') as context:
            response = context.return_value.wrap_socket.return_value
            response.recv.return_value = b'HTTP/1.1 302 Found\r\nLocation: https://other.example/\r\n\r\n'
            result = ServiceVerifier.verify_candidate('1.1.1.1', 'example.com')
            self.assertEqual(result.status, ServiceStatus.UNKNOWN)
            self.assertEqual(socket_factory.call_count, 1)

    def test_redirect_checks_alternative_ips_independently(self):
        original = ServiceVerifier.verify_candidate
        def verify(ip, domain, **kwargs):
            if domain == 'other.example':
                return VerificationResult(ip, domain, ServiceStatus.OK if ip == '8.8.4.4' else ServiceStatus.DEAD,
                                          1, 'answer', 'HTTP', 200 if ip == '8.8.4.4' else 503)
            return original(ip, domain, **kwargs)
        with patch('socket.socket'), patch('ssl.create_default_context') as context, \
             patch.object(ServiceVerifier, 'verify_candidate', side_effect=verify):
            context.return_value.wrap_socket.return_value.recv.return_value = b'HTTP/1.1 302 Found\r\nLocation: https://other.example/\r\n\r\n'
            result = ServiceVerifier.verify_candidate('1.1.1.1', 'example.com',
                redirect_resolver=lambda host: ['8.8.8.8', '8.8.4.4'])
        self.assertTrue(result.is_routable)
        self.assertEqual(result.redirect_checks[0]['ip'], '8.8.4.4')
        self.assertEqual(len(result.redirect_attempts), 2)



if __name__ == '__main__':
    unittest.main()
