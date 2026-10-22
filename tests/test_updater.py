"""Метаданные и установка обновления: только mock-сеть и временные EXE."""
import hashlib
import os
from pathlib import Path
import subprocess
import sys
import tempfile
import unittest

sys.path.insert(0, str(Path(__file__).resolve().parents[1] / 'src'))
import httpx
from core.network import Cancellation
from core.updater import parse_release, download_release, installer_script, ASSET_NAME, REPOSITORY


class Updates(unittest.TestCase):
    def info(self, body=b'MZtest'):
        return dict(tag_name='v1.6.0', draft=False, prerelease=False, assets=[dict(
            name=ASSET_NAME, size=len(body), digest='sha256:' + hashlib.sha256(body).hexdigest(),
            browser_download_url=f'https://github.com/{REPOSITORY}/releases/download/v1.6.0/{ASSET_NAME}')])

    def test_numeric_versions(self):
        self.assertTrue(parse_release(self.info(), '1.5.0')['available'])
        self.assertFalse(parse_release(self.info(), '1.10.0')['available'])

    def test_untrusted_releases_are_rejected(self):
        for field, value in [('browser_download_url', 'https://example.com/evil.exe'),
                             ('digest', ''), ('size', 999999999)]:
            release = self.info()
            release['assets'][0][field] = value
            with self.assertRaises(ValueError):
                parse_release(release)

    def test_verified_download_and_wrong_hash(self):
        data = b'MZtest'
        info = parse_release(self.info(data))
        with httpx.Client(transport=httpx.MockTransport(lambda req: httpx.Response(200, content=data))) as client:
            path = Path(download_release(info, client, Cancellation()))
            try:
                self.assertEqual(path.read_bytes(), data)
            finally:
                path.unlink(); path.parent.rmdir()
            with self.assertRaises(ValueError):
                download_release(dict(info, sha256='0' * 64), client, Cancellation())

    def test_redirect_cannot_escape_github(self):
        with httpx.Client(transport=httpx.MockTransport(lambda req:
                httpx.Response(302, headers={'location': 'https://example.com/evil.exe'}))) as client:
            with self.assertRaises(ValueError):
                download_release(parse_release(self.info()), client, Cancellation())

    @unittest.skipUnless(os.name == 'nt', 'Windows installer')
    def test_atomic_replacement_preserves_backup_and_does_not_launch_program(self):
        with tempfile.TemporaryDirectory(prefix="dns-update-quote'") as directory:
            root = Path(directory)
            source, target = root / 'download.exe', root / 'app.exe'
            source.write_bytes(b'MZnew'); target.write_bytes(b'MZold')
            # Перехватываем только запуск: заменяются исключительно наши временные файлы.
            script = "function Start-Process { param($FilePath,$ArgumentList,$WindowStyle) };\n"
            script += installer_script(source, target, hashlib.sha256(b'MZnew').hexdigest(),
                                       2147483647, ['--data-dir', "C:\\test quote's"])
            import base64
            encoded = base64.b64encode(script.encode('utf-16le')).decode()
            powershell = Path(os.environ['SystemRoot']) / 'System32/WindowsPowerShell/v1.0/powershell.exe'
            result = subprocess.run([str(powershell), '-NoProfile', '-NonInteractive', '-EncodedCommand', encoded],
                capture_output=True, timeout=15, creationflags=subprocess.CREATE_NO_WINDOW)
            self.assertEqual(result.returncode, 0)
            self.assertEqual(target.read_bytes(), b'MZnew')
            self.assertEqual(next(root.glob('app.exe.previous-*')).read_bytes(), b'MZold')
            self.assertFalse(source.exists())


if __name__ == '__main__':
    unittest.main()
