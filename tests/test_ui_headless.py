import os
import shutil
import tempfile
import unittest
from pathlib import Path
import sys

# Ensure offscreen Qt platform
os.environ["QT_QPA_PLATFORM"] = "offscreen"

sys.path.insert(0, str(Path(__file__).parent.parent / "src"))

from PySide6.QtWidgets import QApplication
from core.catalog import Catalog, ServiceDef
from core.hosts_manager import HostsManager
from core.storage import StorageManager
from providers.manager import ProviderManager
from ui.main_window import MainWindow
from ui.add_dialog import AddDialog
from ui.settings_dialog import SettingsDialog


class TestUIHeadless(unittest.TestCase):
    @classmethod
    def setUpClass(cls):
        cls.app = QApplication.instance() or QApplication(sys.argv)

    def setUp(self):
        self.temp_dir = tempfile.mkdtemp(prefix="dns_sw_ui_test_")
        self.hosts_file = Path(self.temp_dir) / "test_hosts"
        self.data_dir = Path(self.temp_dir) / "test_data"
        self.fixture_file = Path(__file__).parent.parent / "fixtures" / "sample_geohide_hosts.txt"

        if self.fixture_file.exists():
            shutil.copy2(str(self.fixture_file), str(self.hosts_file))
        else:
            self.hosts_file.write_text("193.233.112.68 chatgpt.com\n", encoding="utf-8-sig")

        self.storage = StorageManager(data_dir=str(self.data_dir))
        self.hosts_mgr = HostsManager(hosts_path=str(self.hosts_file))
        self.provider_mgr = ProviderManager(cache_dir=str(self.data_dir / "cache"))
        self.catalog = Catalog()

        self.window = MainWindow(
            catalog=self.catalog,
            hosts_manager=self.hosts_mgr,
            provider_manager=self.provider_mgr,
            storage=self.storage
        )

    def tearDown(self):
        if hasattr(self.window, "monitor_thread") and self.window.monitor_thread:
            self.window.monitor_thread.stop()
            self.window.monitor_thread.wait(1000)
        self.window.close()
        shutil.rmtree(self.temp_dir, ignore_errors=True)

    def test_window_initialization(self):
        self.assertIsNotNone(self.window)
        self.assertTrue(len(self.window.service_cards) > 0)
        # Verify ChatGPT card exists
        self.assertIn("chatgpt", self.window.service_cards)
        self.assertEqual(self.window.tab_bar.currentIndex(), 0)
        self.assertEqual(set(self.window.service_cards), {'spotify', 'chatgpt', 'gemini', 'claude'})
        self.assertGreaterEqual(self.window.fav_layout.indexOf(self.window.service_cards['chatgpt']), 0)

    def test_search_filtering(self):
        self.window.search_edit.setText("Spotify")
        self.window._filter_services("Spotify")

        card_spotify = self.window.service_cards.get("spotify")
        self.assertFalse(card_spotify.isHidden())

        card_chatgpt = self.window.service_cards.get("chatgpt")
        self.assertTrue(card_chatgpt.isHidden())

    def test_expand_card(self):
        card = self.window.service_cards["chatgpt"]
        self.assertFalse(card.is_expanded)
        card.toggle_expanded()
        self.assertTrue(card.is_expanded)
        self.assertFalse(card.detail_widget.isHidden())

    def test_batch_button_follows_the_selected_tab(self):
        from unittest.mock import patch
        with patch.object(self.window, '_start_batch_worker') as start:
            self.window.tab_bar.setCurrentIndex(1)
            self.assertEqual(self.window.fix_fav_btn.text(), 'Подобрать всем')
            self.window.fix_fav_btn.click()
            self.assertEqual({s.id for s in start.call_args.args[0]}, {s.id for s in self.catalog.list_all() if not s.is_favorite})
            self.window.tab_bar.setCurrentIndex(0)
            self.assertEqual(self.window.fix_fav_btn.text(), 'Подобрать избранному')
            self.window.fix_fav_btn.click()
            self.assertEqual({s.id for s in start.call_args.args[0]}, {s.id for s in self.catalog.list_favorites()})

    def test_card_pick_targets_only_one_service_and_more_expands(self):
        from unittest.mock import patch
        card = self.window.service_cards['spotify']
        with patch.object(self.window, '_start_batch_worker') as start:
            card.action_btn.click()
            self.assertEqual([s.id for s in start.call_args.args[0]], ['spotify'])
            self.assertTrue(start.call_args.kwargs['auto_fix'])
        self.assertEqual(card.action_btn.text(), 'Подобрать')
        self.assertEqual(card.expand_btn.text(), 'Подробнее')
        card.expand_btn.click()
        self.assertTrue(card.is_expanded)

    def test_catalog_excludes_favorites_for_both_batch_actions(self):
        from unittest.mock import patch
        self.window.tab_bar.setCurrentIndex(1)
        favorites = {s.id for s in self.catalog.list_favorites()}
        self.assertTrue(favorites.isdisjoint(self.window.service_cards))
        with patch.object(self.window, '_start_batch_worker') as start:
            self.window.fix_fav_btn.click()
            self.assertTrue(favorites.isdisjoint(s.id for s in start.call_args.args[0]))
            self.window.fix_all_btn.click()
            self.assertTrue(favorites.isdisjoint(s.id for s in start.call_args.args[0]))
        self.window._on_favorite_toggled('chatgpt', False)
        self.assertIn('chatgpt', self.window.service_cards)
        self.window._on_favorite_toggled('chatgpt', True)
        self.assertNotIn('chatgpt', self.window.service_cards)

    def test_other_route_keeps_card_and_scroll_position(self):
        from unittest.mock import patch
        from PySide6.QtTest import QTest
        from PySide6.QtCore import Qt
        from core.verifier import VerificationResult, ServiceStatus
        self.window.resize(640, 580)
        self.window.show()
        self.app.processEvents()
        scroll = self.window.fav_scroll.verticalScrollBar()
        scroll.setValue(min(80, scroll.maximum()))
        position = scroll.value()
        card = self.window.service_cards['spotify']
        with patch('core.monitor.VerificationWorker.start'):
            QTest.mouseClick(card.next_btn, Qt.LeftButton)
            self.app.processEvents()
            self.assertIs(self.window.service_cards['spotify'], card)
            self.assertEqual(scroll.value(), position)
            result = VerificationResult('8.8.4.4', card.service.primary_domain, ServiceStatus.OK, 10)
            result.applied = True
            result.outcome = '1.1.1.1 → 8.8.4.4 · проверено 18 из 19 адресов'
            self.window._on_worker_service_result('spotify', result, 'Alternative')
            self.window._on_worker_finished(dict(total=1, fixed=1))
            self.window._on_worker_thread_finished()
            QTest.qWait(30)
            self.assertEqual(scroll.value(), position)

    def test_reset_buttons_are_visible_without_opening_details_or_switching_settings_tabs(self):
        from PySide6.QtWidgets import QTabWidget
        self.window.show()
        self.app.processEvents()
        card = self.window.service_cards['spotify']
        self.assertFalse(card.is_expanded)
        self.assertTrue(card.restore_dns_btn.isVisible())
        dialog = SettingsDialog(self.storage, self.hosts_mgr, self.provider_mgr, self.window)
        dialog.show()
        for index in range(dialog.findChild(QTabWidget).count()):
            dialog.findChild(QTabWidget).setCurrentIndex(index)
            self.app.processEvents()
            self.assertTrue(dialog.reset_all_dns_btn.isVisible())
        dialog.accept()

    def test_single_and_global_reset_preserve_foreign_hosts_and_other_services(self):
        from unittest.mock import patch
        original = self.hosts_file.read_bytes()
        spotify, chatgpt = self.catalog.get_service('spotify'), self.catalog.get_service('chatgpt')
        for service in (spotify, chatgpt):
            self.hosts_mgr.update_service_ip(service.name, '1.1.1.1', service.domains)
            self.storage.set_active_route(service.id, '1.1.1.1', 'Test', 'OK', 1)
        self.window._route_feedback('spotify', 'restore_dns')
        self.assertIsNone(self.storage.get_active_route('spotify'))
        self.assertIsNotNone(self.storage.get_active_route('chatgpt'))
        self.assertEqual(self.hosts_mgr._split_managed(self.hosts_mgr.read_file_safely(self.hosts_file)[0])[1].encode('utf-8'), original)
        dialog = SettingsDialog(self.storage, self.hosts_mgr, self.provider_mgr, self.window)
        with patch('ui.settings_dialog.QMessageBox.information'):
            dialog._reset_all_dns()
        self.assertEqual(self.hosts_file.read_bytes(), original)
        self.assertEqual(self.storage.config.active_routes, {})

    def test_old_route_does_not_claim_access_and_has_no_diagnostic_tooltip(self):
        from core.verifier import ServiceStatus, VerificationResult
        card = self.window.service_cards['spotify']
        card.set_current_ip('1.1.1.1', dict(status='DEAD', provider_name='GeoHide',
            details='A long saved diagnostic'))
        self.assertTrue(card.status_badge.isHidden())
        self.assertEqual(card.status_badge.toolTip(), '')
        self.assertTrue(card.help_label.isHidden())
        result = VerificationResult('1.1.1.1', 'open.spotify.com', ServiceStatus.DEAD, 1, 'Probe failed')
        card.set_verification_result(result, 'GeoHide')
        self.assertEqual(card.status_badge.text(), 'Не удалось проверить')
        self.assertEqual(card.status_badge.toolTip(), '')
        self.assertTrue(card.help_label.isHidden())

    def test_favorite_icon_and_current_provider_label(self):
        from core.verifier import VerificationResult, ServiceStatus
        card = self.window.service_cards['gemini']
        self.assertFalse(card.fav_btn.icon().isNull())
        self.assertEqual(card.fav_btn.toolTip(), 'Убрать из избранного')
        result = VerificationResult('1.1.1.1', 'gemini.google.com', ServiceStatus.OK, 5)
        result.applied = True
        card.set_verification_result(result, 'DNS-AI')
        self.assertIn('DNS-AI', card.ip_badge.text())
        self.assertIn('1.1.1.1', card.ip_badge.text())
        card.fav_btn.click()
        self.assertNotIn('gemini', self.storage.config.favorites)

    def test_switched_ip_and_pool_count_are_visible_on_card(self):
        from core.verifier import VerificationResult, ServiceStatus
        card = self.window.service_cards['claude']
        card.set_current_ip('1.1.1.1')
        result = VerificationResult('8.8.4.4', 'claude.ai', ServiceStatus.PARTIAL, 10)
        result.applied = True
        result.route_message = 'Нужна браузерная проверка'
        result.outcome = '1.1.1.1 → 8.8.4.4 · проверено 19 из 20 адресов'
        card.set_verification_result(result, 'GeoHide (EU)')
        card.set_candidates([dict(ip='8.8.4.4', provider_name='GeoHide (EU)', status='PARTIAL',
                                  browser_required=True) for _ in range(19)])
        self.assertIn('8.8.4.4', card.ip_badge.text())
        self.assertIn('1.1.1.1 → 8.8.4.4', card.help_label.text())
        self.assertFalse(card.help_label.isHidden())
        self.assertEqual(card.status_badge.text(), 'Нужна браузерная проверка')
        self.assertIn('19', card.expand_btn.text())

    def test_add_dialog_flow(self):
        dlg = AddDialog(existing_categories=["AI", "Dev"], parent=self.window)
        dlg.site_name_edit.setText("TestSite")
        dlg.site_domain_edit.setText("testsite.org")
        dlg.cat_combo.setCurrentText("Dev")

        captured = []
        dlg.site_added.connect(lambda s: captured.append(s))
        dlg._on_add_site()

        self.assertEqual(len(captured), 1)
        self.assertEqual(captured[0].name, "TestSite")
        self.assertEqual(captured[0].primary_domain, "testsite.org")

    def test_hidden_service_is_excluded_and_can_be_restored(self):
        before = self.hosts_file.read_bytes()
        self.window._hide_service('chatgpt')
        self.assertNotIn('chatgpt', self.window.service_cards)
        self.assertNotIn('chatgpt', [s.id for s in self.catalog.list_all()])
        self.assertNotIn('chatgpt', [s.id for s in self.catalog.list_favorites()])
        self.assertIn('chatgpt', StorageManager(str(self.data_dir)).config.hidden_services)
        self.window._restore_service('chatgpt')
        self.assertIn('chatgpt', self.window.service_cards)
        self.assertEqual(self.hosts_file.read_bytes(), before)

    def test_route_confirmation_and_reset_are_persisted(self):
        self.hosts_file.write_text('1.1.1.1 chatgpt.com\n')
        self.storage.set_active_route('chatgpt', '1.1.1.1', 'Test', 'PARTIAL', 1)
        self.storage.get_active_route('chatgpt').update(confirmable=True)
        self.window._route_feedback('chatgpt', 'confirm')
        self.assertTrue(StorageManager(str(self.data_dir)).get_active_route('chatgpt')['confirmed'])
        self.storage.config.rejected_routes['chatgpt'] = ['8.8.8.8']
        from unittest.mock import patch
        with patch.object(self.window, '_start_batch_worker') as start:
            self.window._route_feedback('chatgpt', 'reset')
            self.assertEqual(start.call_count, 1)
            self.assertTrue(start.call_args.kwargs['rotate'])
        self.assertNotIn('chatgpt', StorageManager(str(self.data_dir)).config.rejected_routes)



if __name__ == "__main__":
    unittest.main()
