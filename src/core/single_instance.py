"""Один экземпляр приложения; повторный запуск показывает открытое окно."""
import hashlib
import os
import ctypes
from ctypes import wintypes
from PySide6.QtCore import QDir, QLockFile
from PySide6.QtNetwork import QLocalServer, QLocalSocket


class SingleInstance:
    def __init__(self, scope=''):
        user = os.environ.get('USERDOMAIN', '') + os.environ.get('USERNAME', '')
        key = hashlib.sha256((user + scope).encode()).hexdigest()[:24]
        self.name = 'DNS-Switcher-' + key
        self.lock = QLockFile(QDir.tempPath() + '/' + self.name + '.lock')
        self.lock.setStaleLockTime(0)
        self.server = QLocalServer()
        self._mutex = None
        self._scope = scope

    def acquire(self):
        if os.name == 'nt':
            kernel = ctypes.WinDLL('kernel32', use_last_error=True)
            kernel.CreateMutexW.argtypes = [ctypes.c_void_p, wintypes.BOOL, wintypes.LPCWSTR]
            kernel.CreateMutexW.restype = wintypes.HANDLE
            kernel.CloseHandle.argtypes = [wintypes.HANDLE]
            # Имя не зависит от EXE, его версии, каталога или TEMP администратора.
            suffix = '-' + hashlib.sha256(self._scope.encode()).hexdigest()[:24] if self._scope else ''
            ctypes.set_last_error(0)
            handle = kernel.CreateMutexW(None, False, 'Local\\DNS-Switcher-AI-Plus' + suffix)
            exists = ctypes.get_last_error() == 183
            if not handle or exists:
                if handle:
                    kernel.CloseHandle(handle)
                self._show_existing()
                return False
            self._mutex = handle
        if not self.lock.tryLock(100):
            self._show_existing()
            self.close()
            return False
        QLocalServer.removeServer(self.name)
        if not self.server.listen(self.name):
            self.close()
            raise RuntimeError(self.server.errorString())
        return True

    def _show_existing(self):
        socket = QLocalSocket()
        socket.connectToServer(self.name)
        if socket.waitForConnected(300):
            socket.write(b'show')
            socket.waitForBytesWritten(300)
            socket.disconnectFromServer()

    def connect_window(self, window):
        def activate():
            while self.server.hasPendingConnections():
                socket = self.server.nextPendingConnection()
                socket.disconnectFromServer()
                socket.deleteLater()
            window.showNormal()
            window.raise_()
            window.activateWindow()
        self.server.newConnection.connect(activate)

    def close(self):
        self.server.close()
        self.lock.unlock()
        if self._mutex:
            kernel = ctypes.WinDLL('kernel32', use_last_error=True)
            kernel.CloseHandle.argtypes = [wintypes.HANDLE]
            kernel.CloseHandle(self._mutex)
            self._mutex = None
