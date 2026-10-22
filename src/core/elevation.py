"""
ElevationHelper: Windows UAC elevation helper for privileged file operations.
Allows running the main application without admin privileges, requesting elevation
only when writing to system hosts file via ShellExecuteExW(runas).
"""

import os
import sys
import base64
import ctypes
from ctypes import wintypes
import subprocess
from pathlib import Path


class SHELLEXECUTEINFO(ctypes.Structure):
    _fields_ = [
        ('cbSize', wintypes.DWORD),
        ('fMask', wintypes.ULONG),
        ('hwnd', wintypes.HWND),
        ('lpVerb', wintypes.LPCWSTR),
        ('lpFile', wintypes.LPCWSTR),
        ('lpParameters', wintypes.LPCWSTR),
        ('lpDirectory', wintypes.LPCWSTR),
        ('nShow', ctypes.c_int),
        ('hInstApp', wintypes.HINSTANCE),
        ('lpIDList', wintypes.LPVOID),
        ('lpClass', wintypes.LPCWSTR),
        ('hkeyClass', wintypes.HKEY),
        ('dwHotKey', wintypes.DWORD),
        ('hIconOrMonitor', wintypes.HANDLE),
        ('hProcess', wintypes.HANDLE)
    ]


class ElevationHelper:
    @staticmethod
    def is_admin() -> bool:
        """Returns True if the current process is running with administrative privileges."""
        try:
            return ctypes.windll.shell32.IsUserAnAdmin() != 0
        except Exception:
            return False

    @staticmethod
    def copy_file_elevated(src: str, dst: str, flush_dns: bool = True) -> bool:
        """
        Copies src to dst with UAC elevation prompt if not already running as admin.
        Optionally flushes Windows DNS cache upon success.
        """
        import shutil

        def quoted(value):
            return "'" + str(Path(value).resolve()).replace("'", "''") + "'"

        # Все пути передаются как данные, без интерпретации cmd.exe.
        # If already elevated, copy directly
        if ElevationHelper.is_admin():
            try:
                import tempfile
                fd, adjacent = tempfile.mkstemp(dir=Path(dst).parent, prefix=".hosts-sw-")
                os.close(fd)
                try:
                    shutil.copyfile(src, adjacent)
                    os.replace(adjacent, dst)
                finally:
                    if os.path.exists(adjacent):
                        os.unlink(adjacent)
                if flush_dns:
                    subprocess.run(["ipconfig", "/flushdns"], capture_output=True, check=False)
                return True
            except Exception:
                return False

        temporary = str(Path(dst).parent / (".hosts-sw-" + __import__('uuid').uuid4().hex))
        flush = " & (Join-Path $env:SystemRoot 'System32\\ipconfig.exe') /flushdns | Out-Null; if ($LASTEXITCODE -ne 0) { exit 2 };" if flush_dns else ""
        script = (
            "$ErrorActionPreference='Stop'; try { "
            f"Copy-Item -LiteralPath {quoted(src)} -Destination {quoted(temporary)} -Force; "
            f"Move-Item -LiteralPath {quoted(temporary)} -Destination {quoted(dst)} -Force; "
            + flush + " exit 0 } catch { exit 1 } finally { "
            f"if (Test-Path -LiteralPath {quoted(temporary)}) {{ Remove-Item -LiteralPath {quoted(temporary)} -Force }} }}"
        )
        encoded = base64.b64encode(script.encode('utf-16le')).decode('ascii')
        cmd_params = '-NoProfile -NonInteractive -WindowStyle Hidden -EncodedCommand ' + encoded

        SEE_MASK_NOCLOSEPROCESS = 0x00000040
        SW_HIDE = 0

        sei = SHELLEXECUTEINFO()
        sei.cbSize = ctypes.sizeof(SHELLEXECUTEINFO)
        sei.fMask = SEE_MASK_NOCLOSEPROCESS
        sei.lpVerb = "runas"
        sei.lpFile = str(Path(os.environ.get("SystemRoot", r"C:\Windows")) / "System32/WindowsPowerShell/v1.0/powershell.exe")
        sei.lpParameters = cmd_params
        sei.nShow = SW_HIDE

        # Trigger UAC elevation prompt
        ctypes.windll.shell32.ShellExecuteExW.argtypes = [ctypes.POINTER(SHELLEXECUTEINFO)]
        ctypes.windll.shell32.ShellExecuteExW.restype = wintypes.BOOL
        if not ctypes.windll.shell32.ShellExecuteExW(ctypes.byref(sei)):
            # User clicked "No" on UAC prompt or elevation was blocked
            return False

        if sei.hProcess:
            kernel = ctypes.windll.kernel32
            kernel.WaitForSingleObject.argtypes = [wintypes.HANDLE, wintypes.DWORD]
            kernel.WaitForSingleObject.restype = wintypes.DWORD
            kernel.GetExitCodeProcess.argtypes = [wintypes.HANDLE, ctypes.POINTER(wintypes.DWORD)]
            kernel.GetExitCodeProcess.restype = wintypes.BOOL
            kernel.CloseHandle.argtypes = [wintypes.HANDLE]
            # Ожидаем подтверждённый результат записи, без ложного успеха по таймауту.
            wait_result = kernel.WaitForSingleObject(sei.hProcess, 0xFFFFFFFF)
            exit_code = wintypes.DWORD()
            received = kernel.GetExitCodeProcess(sei.hProcess, ctypes.byref(exit_code))
            kernel.CloseHandle(sei.hProcess)
            return wait_result == 0 and bool(received) and exit_code.value == 0

        return False
