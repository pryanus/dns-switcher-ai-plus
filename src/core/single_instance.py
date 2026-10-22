"""Один экземпляр приложения; повторный запуск показывает открытое окно."""
import hashlib
import os
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

    def acquire(self):
        if not self.lock.tryLock(100):
            socket = QLocalSocket()
            socket.connectToServer(self.name)
            if socket.waitForConnected(2000):
                socket.write(b'show')
                socket.waitForBytesWritten(1000)
                socket.disconnectFromServer()
            return False
        QLocalServer.removeServer(self.name)
        if not self.server.listen(self.name):
            self.lock.unlock()
            raise RuntimeError(self.server.errorString())
        return True

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
