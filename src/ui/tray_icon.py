"""
TrayIconManager: System tray icon with context menu and desktop notifications.
"""

from typing import Optional, Callable
from PySide6.QtCore import Qt, QObject, Signal
from PySide6.QtGui import QIcon, QPixmap, QPainter, QColor, QFont
from PySide6.QtWidgets import QSystemTrayIcon, QMenu, QWidget


class TrayIconManager(QObject):
    open_requested = Signal()
    fix_favorites_requested = Signal()
    fix_all_requested = Signal()
    settings_requested = Signal()
    exit_requested = Signal()

    def __init__(self, parent: Optional[QWidget] = None):
        super().__init__(parent)
        self.tray_icon = QSystemTrayIcon(parent)
        self._init_icon()
        self._init_menu()
        self.tray_icon.activated.connect(self._on_activated)

    def _init_icon(self) -> None:
        from pathlib import Path
        self.tray_icon.setIcon(QIcon(str(Path(__file__).resolve().parents[1] / 'assets/icon.png')))
        self.tray_icon.setToolTip('DNS Switcher AI+')

    def _init_menu(self) -> None:
        self.menu = QMenu()

        act_open = self.menu.addAction("Открыть DNS Switcher AI+")
        act_open.triggered.connect(self.open_requested.emit)

        self.menu.addSeparator()

        act_fix_fav = self.menu.addAction("Исправить избранные")
        act_fix_fav.triggered.connect(self.fix_favorites_requested.emit)

        act_fix_all = self.menu.addAction("Исправить всё")
        act_fix_all.triggered.connect(self.fix_all_requested.emit)

        self.menu.addSeparator()

        act_settings = self.menu.addAction("Настройки")
        act_settings.triggered.connect(self.settings_requested.emit)

        self.menu.addSeparator()

        act_exit = self.menu.addAction("Выход")
        act_exit.triggered.connect(self.exit_requested.emit)

        self.tray_icon.setContextMenu(self.menu)

    def show(self) -> None:
        self.tray_icon.show()

    def hide(self) -> None:
        self.tray_icon.hide()

    def notify(self, title: str, message: str, is_error: bool = False) -> None:
        icon = QSystemTrayIcon.Warning if is_error else QSystemTrayIcon.Information
        self.tray_icon.showMessage(title, message, icon, 4000)

    def _on_activated(self, reason: QSystemTrayIcon.ActivationReason) -> None:
        if reason in (QSystemTrayIcon.Trigger, QSystemTrayIcon.DoubleClick):
            self.open_requested.emit()
