"""Обновления из фиксированного GitHub-репозитория с проверкой SHA-256."""
import base64
import hashlib
import json
import os
from pathlib import Path
import re
import shutil
import subprocess
import sys
import tempfile
import time
from urllib.parse import urlparse

import httpx
from PySide6.QtCore import QThread, Signal
from core.network import Cancellation, Cancelled

VERSION = '1.1.0'
REPOSITORY = 'pryanus/dns-switcher-ai-plus'
ASSET_NAME = 'DNS_Switcher_AI_Plus.exe'
API_URL = f'https://api.github.com/repos/{REPOSITORY}/releases/latest'
MAX_SIZE = 128 * 1024 * 1024
CDN_HOSTS = {'github.com', 'release-assets.githubusercontent.com',
             'objects.githubusercontent.com', 'github-releases.githubusercontent.com'}


def version_tuple(value):
    if not isinstance(value, str) or not re.fullmatch(r'v?\d+\.\d+\.\d+', value):
        raise ValueError('Неподдерживаемый номер версии')
    return tuple(map(int, value.lstrip('v').split('.')))


def validate_download_url(url, initial=False):
    parsed = urlparse(url)
    if (parsed.scheme != 'https' or parsed.username or parsed.password or
            parsed.port not in (None, 443) or parsed.hostname not in CDN_HOSTS):
        raise ValueError('Недоверенный адрес загрузки')
    if initial and (parsed.hostname != 'github.com' or not parsed.path.startswith(
            f'/{REPOSITORY}/releases/download/') or not parsed.path.endswith('/' + ASSET_NAME)):
        raise ValueError('Обновление не принадлежит репозиторию приложения')


def parse_release(data, current=VERSION, current_digest=None):
    if not isinstance(data, dict) or data.get('draft') or data.get('prerelease'):
        raise ValueError('Релиз не является стабильной версией')
    tag = data.get('tag_name', '')
    newer = version_tuple(tag) > version_tuple(current)
    same_build_channel = version_tuple(tag) == version_tuple(current) and current_digest is not None
    result = dict(version=tag.lstrip('v'), available=newer)
    if not newer and not same_build_channel:
        return result
    asset = next((a for a in data.get('assets', []) if a.get('name') == ASSET_NAME), None)
    if not asset:
        raise ValueError('В релизе ещё нет готового EXE. Попробуйте позже.')
    url = asset.get('browser_download_url', '')
    validate_download_url(url, initial=True)
    size, digest = asset.get('size'), asset.get('digest', '')
    if type(size) is not int or not 0 < size <= MAX_SIZE:
        raise ValueError('Некорректный размер обновления')
    if not re.fullmatch(r'sha256:[0-9a-fA-F]{64}', digest):
        raise ValueError('У релиза нет контрольной суммы SHA-256')
    if same_build_channel:
        result['available'] = digest.split(':')[1].lower() != current_digest
    result.update(url=url, size=size, sha256=digest.split(':')[1].lower())
    return result


def download_release(info, client, token, progress=lambda value: None):
    validate_download_url(info['url'], initial=True)
    if not 0 < info['size'] <= MAX_SIZE or not re.fullmatch(r'[0-9a-f]{64}', info['sha256']):
        raise ValueError('Некорректные данные обновления')
    directory = Path(tempfile.mkdtemp(prefix='dns-switcher-update-'))
    path = directory / ASSET_NAME
    started, total, digest = time.monotonic(), 0, hashlib.sha256()
    try:
        url = info['url']
        for _ in range(6):
            token.check()
            validate_download_url(url)
            with client.stream('GET', url) as response:
                if response.status_code in (301, 302, 303, 307, 308):
                    url = str(response.url.join(response.headers['location']))
                    continue
                response.raise_for_status()
                with path.open('wb') as stream:
                    for chunk in response.iter_bytes(65536):
                        token.check()
                        if time.monotonic() - started > 180:
                            raise TimeoutError('Загрузка заняла больше трёх минут')
                        total += len(chunk)
                        if total > info['size'] or total > MAX_SIZE:
                            raise ValueError('Размер файла отличается от релиза')
                        digest.update(chunk)
                        stream.write(chunk)
                        progress(int(total * 100 / info['size']))
                break
        else:
            raise ValueError('Слишком много перенаправлений')
        if total != info['size'] or digest.hexdigest() != info['sha256']:
            raise ValueError('Контрольная сумма обновления не совпала. Установка отменена.')
        with path.open('rb') as stream:
            if stream.read(2) != b'MZ':
                raise ValueError('Получен некорректный EXE')
        return str(path)
    except Exception:
        shutil.rmtree(directory, ignore_errors=True)
        raise


class AppUpdateWorker(QThread):
    completed = Signal(dict)
    failed = Signal(str)
    progress = Signal(int)

    def __init__(self, release=None, parent=None):
        super().__init__(parent)
        self.release = release
        self.token = Cancellation()

    def cancel(self):
        self.token.cancel()

    def run(self):
        try:
            with httpx.Client(timeout=httpx.Timeout(5, connect=4), follow_redirects=False,
                    headers={'User-Agent': 'DNS-Switcher-AI-Plus/' + VERSION,
                             'Accept': 'application/vnd.github+json', 'Cache-Control': 'no-cache'}) as client:
                if self.release:
                    path = download_release(self.release, client, self.token, self.progress.emit)
                    result = dict(self.release, path=path)
                else:
                    raw = bytearray()
                    with client.stream('GET', API_URL) as response:
                        if response.status_code == 403:
                            raise ValueError('GitHub ограничил запросы. Повторите проверку позже.')
                        response.raise_for_status()
                        for chunk in response.iter_bytes():
                            self.token.check()
                            raw.extend(chunk)
                            if len(raw) > 1024 * 1024:
                                raise ValueError('Слишком большой ответ GitHub')
                    current_digest = hashlib.sha256(Path(sys.executable).read_bytes()).hexdigest() if getattr(sys, 'frozen', False) else None
                    result = parse_release(json.loads(raw), current_digest=current_digest)
                self.token.check()
                self.completed.emit(result)
        except Cancelled:
            pass
        except Exception as error:
            self.failed.emit(str(error))


def installer_script(download, target, digest, process_id, arguments):
    def quote(value):
        return "'" + str(value).replace("'", "''") + "'"
    # Все пути и аргументы передаются как данные; замена выполняется атомарно.
    source, destination = quote(download), quote(target)
    stage = quote(str(target) + '.update-' + os.urandom(6).hex())
    backup = quote(str(target) + '.previous-' + os.urandom(6).hex())
    args = quote(subprocess.list2cmdline(arguments))
    return f"""$ErrorActionPreference='Stop'; $source={source}; $target={destination};
$stage={stage}; $backup={backup}; $installed=$false;
try {{
  Copy-Item -LiteralPath $source -Destination $stage;
  $hasher=[System.Security.Cryptography.SHA256]::Create();
  try {{ $actual=[System.BitConverter]::ToString($hasher.ComputeHash([System.IO.File]::ReadAllBytes($stage))).Replace('-','').ToLower() }}
  finally {{ $hasher.Dispose() }};
  if ($actual -ne {quote(digest)}) {{ throw 'SHA-256 mismatch' }};
  Wait-Process -Id {int(process_id)} -Timeout 60 -ErrorAction SilentlyContinue;
  if (Get-Process -Id {int(process_id)} -ErrorAction SilentlyContinue) {{ throw 'Application is still running' }};
  for ($attempt=0; $attempt -lt 30; $attempt++) {{
    try {{ [System.IO.File]::Replace($stage,$target,$backup); $installed=$true; break }}
    catch {{ Start-Sleep -Milliseconds 500 }}
  }};
  if (-not $installed) {{ throw 'Executable is still locked' }};
  if ({args}.Length -gt 0) {{ Start-Process -FilePath $target -ArgumentList {args} -WindowStyle Normal }}
  else {{ Start-Process -FilePath $target -WindowStyle Normal }};
}} catch {{
  Add-Type -AssemblyName System.Windows.Forms;
  [System.Windows.Forms.MessageBox]::Show('Не удалось установить обновление. Предыдущий EXE сохранён. Запустите программу вручную.','DNS Switcher AI+');
}} finally {{
  if (Test-Path -LiteralPath $stage) {{ Remove-Item -LiteralPath $stage -Force }};
  Remove-Item -LiteralPath $source -Force -ErrorAction SilentlyContinue;
}}"""


def launch_installer(path, digest):
    if not getattr(sys, 'frozen', False) or os.name != 'nt':
        raise ValueError('Самообновление доступно в Windows EXE; исходники обновляются через Git.')
    source, target = Path(path).resolve(), Path(sys.executable).resolve()
    if source.name != ASSET_NAME or hashlib.sha256(source.read_bytes()).hexdigest() != digest:
        raise ValueError('Файл обновления не прошёл повторную проверку')
    script = installer_script(source, target, digest, os.getpid(), sys.argv[1:])
    encoded = base64.b64encode(script.encode('utf-16le')).decode('ascii')
    powershell = Path(os.environ.get('SystemRoot', r'C:\Windows')) / 'System32/WindowsPowerShell/v1.0/powershell.exe'
    subprocess.Popen([str(powershell), '-NoProfile', '-NonInteractive', '-WindowStyle', 'Hidden',
                      '-EncodedCommand', encoded], creationflags=subprocess.CREATE_NO_WINDOW)
