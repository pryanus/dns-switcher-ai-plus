import os
import shutil
import tempfile
import unittest
from pathlib import Path
import sys
from unittest.mock import patch, MagicMock

os.environ["QT_QPA_PLATFORM"] = "offscreen"
sys.path.insert(0, str(Path(__file__).parent.parent / "src"))

from PySide6.QtWidgets import QApplication
from core import autostart
from core.catalog import Catalog
from core.hosts_manager import HostsManager
from core.monitor import BackgroundMonitorThread
from core.storage import StorageManager
from core.verifier import ServiceStatus, VerificationResult
from providers.manager import ProviderManager
from ui.main_window import MainWindow
from ui.settings_dialog import SettingsDialog


class TestAutostartAndMonitor(unittest.TestCase):
    @classmethod
    def setUpClass(cls):
        cls.app = QApplication.instance() or QApplication(sys.argv)

    def setUp(self):
        self.temp_dir = tempfile.mkdtemp(prefix="dns_sw_auto_mon_")
        self.hosts_file = Path(self.temp_dir) / "hosts"
        self.hosts_file.write_text("127.0.0.1 localhost\n", encoding="utf-8")
        self.data_dir = Path(self.temp_dir) / "data"
        self.storage = StorageManager(data_dir=str(self.data_dir))
        self.hosts_mgr = HostsManager(hosts_path=str(self.hosts_file))
        self.provider_mgr = ProviderManager(cache_dir=str(self.data_dir / "cache"))
        self.catalog = Catalog()

    def tearDown(self):
        shutil.rmtree(self.temp_dir, ignore_errors=True)

    def test_task_xml_elevated_interactive_without_battery_or_timeout_limits(self):
        xml = autostart.build_task_xml(
            r"C:\Tools\DNS & AI\DNS_Switcher_AI_Plus.exe",
            "--minimized",
            r"C:\Tools\DNS & AI",
            user_id=r"HOMIE\Pryanick",
        )
        self.assertIn("<RunLevel>HighestAvailable</RunLevel>", xml)
        self.assertIn("<LogonType>InteractiveToken</LogonType>", xml)
        self.assertIn("<DisallowStartIfOnBatteries>false</DisallowStartIfOnBatteries>", xml)
        self.assertIn("<StopIfGoingOnBatteries>false</StopIfGoingOnBatteries>", xml)
        self.assertIn("<ExecutionTimeLimit>PT0S</ExecutionTimeLimit>", xml)
        self.assertIn("<Arguments>--minimized</Arguments>", xml)
        self.assertIn("DNS &amp; AI", xml)

    def test_set_autostart_admin_and_uac_fallback(self):
        fake_ok = MagicMock(returncode=0, stdout="", stderr="")
        with patch("core.autostart.ElevationHelper.is_admin", return_value=True), \
             patch("core.autostart.subprocess.run", return_value=fake_ok) as run_mock:
            self.assertTrue(autostart.set_autostart(True))
            args = run_mock.call_args.args[0]
            self.assertIn("/Create", args)
            self.assertIn(autostart.TASK_NAME, args)

            self.assertTrue(autostart.set_autostart(False))
            args_del = run_mock.call_args.args[0]
            self.assertIn("/Delete", args_del)

        with patch("core.autostart.ElevationHelper.is_admin", return_value=False), \
             patch("core.autostart.ElevationHelper.run_elevated_powershell", return_value=False):
            with self.assertRaises(PermissionError):
                autostart.set_autostart(True)

    def test_settings_autostart_checkbox_reverts_on_failure(self):
        with patch("core.autostart.is_autostart_enabled", return_value=False), \
             patch("core.autostart.set_autostart", side_effect=PermissionError("Denied")), \
             patch("ui.settings_dialog.QMessageBox.warning") as warn_mock:
            dlg = SettingsDialog(self.storage, self.hosts_mgr, self.provider_mgr)
            self.assertTrue(dlg.autostart_cb.isEnabled())
            self.assertFalse(dlg.autostart_cb.isChecked())
            dlg.autostart_cb.setChecked(True)
            self.assertFalse(dlg.autostart_cb.isChecked())
            self.assertFalse(self.storage.config.autostart)
            warn_mock.assert_called_once()
            dlg.reject()

    def test_background_monitor_defers_startup_and_skips_when_locked(self):
        self.storage.config.monitoring_enabled = True
        self.storage.config.auto_update_db = True
        self.storage.config.monitor_interval_minutes = 5
        thread = BackgroundMonitorThread(self.catalog, self.hosts_mgr, self.provider_mgr, self.storage)
        self.assertGreater(thread._last_check_at, 0)
        self.assertGreater(thread._next_update, 0)

        # Simulate elapsed interval while another thread holds the lock.
        import threading
        held, release = threading.Event(), threading.Event()
        def hold_lock():
            with self.provider_mgr.operation_lock:
                held.set()
                release.wait(2)
        holder = threading.Thread(target=hold_lock)
        holder.start()
        held.wait(2)
        thread._last_check_at = 0.0
        try:
            with patch("core.monitor.VerificationWorker") as worker_cls:
                thread._tick()
                worker_cls.assert_not_called()
        finally:
            release.set()
            holder.join(2)

        # Simulate interval elapsed when lock is free and auto_update_db due.
        thread._next_update = 0.0
        thread._last_check_at = 0.0
        with patch.object(self.provider_mgr, "update_all_databases", return_value={"geodema-dns": True}) as upd_mock, \
             patch("core.monitor.VerificationWorker.run") as run_mock:
            thread._tick()
            upd_mock.assert_called_once()
            self.assertIsNotNone(upd_mock.call_args.args[0])
            run_mock.assert_called_once()

    def test_monitoring_and_worker_produce_no_toast_notifications_and_update_card_in_place(self):
        window = MainWindow(self.catalog, self.hosts_mgr, self.provider_mgr, self.storage)
        try:
            with patch.object(window.tray, "notify") as notify_mock, \
                 patch.object(window, "_populate_services") as pop_mock:
                res = VerificationResult("179.236.130.10", "chatgpt.com", ServiceStatus.OK, 120)
                res.applied = True
                res.details = "HTTPS доступен"
                window._on_monitor_service_result("chatgpt", res, "Geodema DNS")
                window._on_worker_finished({"total": 1, "ok": 1, "fixed": 0, "failed": 0})
                self.storage.config.minimize_to_tray = True
                window.close()
                notify_mock.assert_not_called()
                pop_mock.assert_not_called()
                self.assertIn("chatgpt", window._session_results)
                self.assertIn("179.236.130.10", window.service_cards["chatgpt"].ip_badge.text())
        finally:
            if window.monitor_thread:
                window.monitor_thread.stop()
                window.monitor_thread.wait(1000)


if __name__ == "__main__":
    unittest.main()
