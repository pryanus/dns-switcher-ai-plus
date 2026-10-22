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
        with patch.object(self.window, '_on_check_single_service') as start:
            self.window._route_feedback('chatgpt', 'reset')
            start.assert_called_once_with('chatgpt')
        self.assertNotIn('chatgpt', StorageManager(str(self.data_dir)).config.rejected_routes)



if __name__ == "__main__":
    unittest.main()
