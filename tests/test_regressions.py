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
        self.assertTrue(self.hosts.read_bytes().endswith(original))
        content = self.hosts.read_text()
        self.assertIn('keep.example # My Note', content)
        self.assertNotIn('evil', content)

    def test_add_update_remove_preserves_original_bytes(self):
        original = b'# User note\r\n8.8.8.8 EXAMPLE.com alias.example # Keep\n# Tail'
        self.hosts.write_bytes(original)
        self.hm.update_service_ip('Example', '1.1.1.1', ['example.com'])
        self.hm.update_service_ip('Example', '8.8.4.4', ['example.com'])
        self.assertTrue(self.hosts.read_bytes().endswith(original))
        self.assertEqual(self.hosts.read_text().count('8.8.4.4\texample.com'), 1)
        self.assertEqual(self.hm.get_conflicts({'example.com': '8.8.4.4'}), {'example.com': ['8.8.8.8']})
        self.hm.remove_service_entries('Example', ['example.com'])
        self.assertEqual(self.hosts.read_bytes(), original)

    def test_broken_managed_marker_fails_without_deleting_data(self):
        original = b'# === DNS Switcher Managed: Broken ===\n8.8.8.8 original.example\n'
        self.hosts.write_bytes(original)
        with self.assertRaises(ValueError):
            self.hm.update_service_ip('Example', '1.1.1.1', ['example.com'])
        self.assertEqual(self.hosts.read_bytes(), original)

    def test_catalog_focus_and_stable_priority(self):
        services = Catalog().list_all()
        self.assertEqual(len(services), 31)
        self.assertEqual([s.id for s in services[:4]], ['chatgpt', 'gemini', 'claude', 'elevenlabs'])
        self.assertEqual({s.id for s in Catalog().list_favorites()}, {'spotify', 'chatgpt', 'gemini', 'claude'})
        self.assertTrue({'steam', 'ea', 'battlenet', 'epicgames', 'xbox', 'playstation', 'twitter', 'hume', 'opencode', 'cerebras'}.isdisjoint({s.id for s in services}))
        self.assertEqual(len({s.id for s in services}), len(services))
        self.assertEqual(sum(s.category == 'Нейросети' for s in services), 16)
        self.assertEqual(sum(s.category == 'Музыка, видео и общение' for s in services), 15)

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
        self.assertEqual(self.hm.parse_all_entries()['example.com'], ['8.8.4.4', '8.8.8.8'])

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

    def test_cloudflare_route_can_be_selected_without_claiming_full_access(self):
        service = ServiceDef(id='gemini', name='Gemini', category='AI',
                             primary_domain='gemini.google.com', domains=['gemini.google.com'])
        worker = VerificationWorker([service], self.hm, self.providers, self.storage, True,
                                    forced=('1.1.1.1', 'DNS-AI'))
        challenge = VerificationResult('1.1.1.1', service.primary_domain, ServiceStatus.PARTIAL,
            1, 'HTTP 403 (Cloudflare challenge active)', 'HTTP', 403)
        self.assertTrue(challenge.is_routable)
        with patch.object(ServiceVerifier, 'verify_candidate', return_value=challenge):
            worker.run()
        self.assertEqual(self.hm.parse_all_entries()[service.primary_domain], ['1.1.1.1'])
        self.assertEqual(self.storage.get_active_route('gemini')['provider_name'], 'DNS-AI')
        self.assertEqual(self.storage.get_active_route('gemini')['status'], 'PARTIAL')

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
        services = [Catalog().get_service(sid) for sid in ('youtube', 'discord', 'netflix')]
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
        self.assertEqual(self.storage.get_active_route('chatgpt')['status'], 'DEAD')
        self.assertFalse(self.storage.get_active_route('chatgpt')['confirmed'])

    def test_cancel_does_not_wait_for_provider_query_or_write(self):
        from threading import Event
        import time
        entered, release = Event(), Event()
        def slow(domain):
            entered.set()
            release.wait(2)
            return [CandidateIP('1.1.1.1', 'test', 'Test')]
        worker = VerificationWorker([self.service], self.hm, self.providers, self.storage, True)
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
        self.assertEqual(route['status'], 'PARTIAL')
        self.assertFalse(any(call.args[0] == '1.1.1.1' for call in probe.call_args_list))
        self.assertEqual(set(route['domain_ips']), set(self.service.domains))



if __name__ == '__main__':
    unittest.main()
