import os
import shutil
import tempfile
import unittest
from pathlib import Path
import sys

# Ensure src is in pythonpath
sys.path.insert(0, str(Path(__file__).parent.parent / "src"))

from core.hosts_manager import HostsManager


class TestHostsManager(unittest.TestCase):
    def setUp(self):
        self.temp_dir = tempfile.mkdtemp(prefix="dns_switcher_test_")
        self.sample_fixture = Path(__file__).parent.parent / "fixtures" / "sample_geohide_hosts.txt"
        self.test_hosts = Path(self.temp_dir) / "hosts"
        
        # Copy fixture to test hosts
        if self.sample_fixture.exists():
            shutil.copy2(str(self.sample_fixture), str(self.test_hosts))
        else:
            # Create a mock hosts
            self.test_hosts.write_text(
                "127.0.0.1 localhost\n"
                "149.154.167.220 t.me\n"
                "159.194.200.33 chatgpt.com\n"
                "159.194.200.33 api.openai.com\n",
                encoding="utf-8-sig"
            )

        self.backup_dir = Path(self.temp_dir) / "backups"
        self.manager = HostsManager(hosts_path=str(self.test_hosts), backup_dir=str(self.backup_dir))

    def tearDown(self):
        shutil.rmtree(self.temp_dir, ignore_errors=True)

    def test_parse_entries(self):
        entries = self.manager.parse_all_entries()
        self.assertIn("t.me", entries)
        self.assertIn("chatgpt.com", entries)
        # Verify telegram IP is preserved
        self.assertEqual(entries["t.me"], ["149.154.167.220"])

    @unittest.skipUnless(os.name == 'nt', 'Windows file sharing')
    def test_write_when_windows_allows_writing_but_denies_replacement(self):
        import ctypes
        from ctypes import wintypes
        kernel = ctypes.WinDLL('kernel32', use_last_error=True)
        kernel.CreateFileW.argtypes = [wintypes.LPCWSTR, wintypes.DWORD, wintypes.DWORD,
            ctypes.c_void_p, wintypes.DWORD, wintypes.DWORD, wintypes.HANDLE]
        kernel.CreateFileW.restype = wintypes.HANDLE
        kernel.CloseHandle.argtypes = [wintypes.HANDLE]
        # Аналог открытого DNS Client файла: чтение/запись разрешены, удаление/rename — нет.
        handle = kernel.CreateFileW(str(self.test_hosts), 0x80000000, 3, None, 3, 0x80, None)
        self.assertNotEqual(handle, ctypes.c_void_p(-1).value)
        try:
            self.manager.update_service_ip('Test', '1.1.1.1', ['example.com'])
            self.assertEqual(self.manager.parse_all_entries()['example.com'], ['1.1.1.1'])
            self.assertTrue(self.manager.list_backups())
        finally:
            kernel.CloseHandle(handle)

    def test_admin_write_failure_does_not_request_elevation_again(self):
        from unittest.mock import patch
        before = self.test_hosts.read_bytes()
        with patch('core.hosts_manager.ElevationHelper.copy_file_direct', side_effect=PermissionError('Denied')), \
             patch('core.hosts_manager.ElevationHelper.is_admin', return_value=True), \
             patch('core.hosts_manager.ElevationHelper.copy_file_elevated') as elevate:
            with self.assertRaisesRegex(PermissionError, 'Повторное повышение прав не требуется'):
                self.manager.update_service_ip('Test', '1.1.1.1', ['example.com'])
            elevate.assert_not_called()
        self.assertEqual(before, self.test_hosts.read_bytes())

    def test_backup_and_restore(self):
        original_content = self.test_hosts.read_text(encoding="utf-8", errors="ignore")
        backup_path = self.manager.create_backup(tag="test_backup")
        self.assertTrue(backup_path.exists())
        self.assertTrue(backup_path.name.startswith("hosts.bak_"))

        # Modify hosts
        self.test_hosts.write_text("127.0.0.1 corrupted", encoding="utf-8-sig")
        self.assertNotEqual(self.test_hosts.read_text(encoding="utf-8", errors="ignore"), original_content)

        # Restore
        self.manager.restore_backup(str(backup_path))
        restored_content = self.test_hosts.read_text(encoding="utf-8", errors="ignore")
        self.assertEqual(restored_content, original_content)

    def test_surgical_update_service(self):
        chatgpt_domains = ["chatgpt.com", "api.openai.com", "oaistatic.com"]
        new_ip = "193.233.112.68"

        # Check before update
        initial_telegram_ips = self.manager.parse_all_entries().get("t.me")
        self.assertEqual(initial_telegram_ips, ["149.154.167.220"])

        # Update ChatGPT to new IP
        success = self.manager.update_service_ip("ChatGPT", new_ip, chatgpt_domains, provider_name="GeoHide RU")
        self.assertTrue(success)

        # Verify parsed entries
        entries = self.manager.parse_all_entries()
        self.assertEqual(entries["chatgpt.com"][0], new_ip)
        self.assertEqual(entries["api.openai.com"][0], new_ip)
        self.assertEqual(entries["oaistatic.com"][0], new_ip)

        # Verify Telegram and localhost remained completely untouched
        self.assertEqual(entries.get("t.me"), ["149.154.167.220"])
        self.assertEqual(entries.get("my.telegram.org"), ["149.154.167.220"])

        # Verify managed section exists
        content = self.test_hosts.read_text(encoding="utf-8", errors="ignore")
        self.assertIn("# === DNS Switcher Managed: ChatGPT ===", content)
        self.assertIn("# === End DNS Switcher: ChatGPT ===", content)

    def test_remove_service_entries(self):
        chatgpt_domains = ["chatgpt.com", "api.openai.com"]
        original = self.test_hosts.read_bytes()
        self.manager.update_service_ip("ChatGPT", "193.233.112.68", chatgpt_domains)
        self.assertIn("chatgpt.com", self.manager.parse_all_entries())

        self.manager.remove_service_entries("ChatGPT", chatgpt_domains)
        self.assertEqual(self.test_hosts.read_bytes(), original)
        self.assertIn("t.me", self.manager.parse_all_entries())


if __name__ == "__main__":
    unittest.main()
