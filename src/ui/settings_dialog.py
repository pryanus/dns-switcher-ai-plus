"""
SettingsDialog: Configuration dialog for providers, update intervals, hosts backups, and monitoring.
"""

from typing import List, Dict, Optional
from PySide6.QtCore import Qt, Signal
from PySide6.QtWidgets import (
    QDialog, QVBoxLayout, QHBoxLayout, QLabel, QPushButton,
    QCheckBox, QSpinBox, QListWidget, QListWidgetItem, QWidget,
    QTabWidget, QFileDialog, QMessageBox, QGroupBox
)

from core.storage import StorageManager
from core.hosts_manager import HostsManager
from providers.manager import ProviderManager


class SettingsDialog(QDialog):
    app_update_requested = Signal(str, str)
    db_updated = Signal()
    backup_restored = Signal()
    hosts_imported = Signal(str)

    def __init__(
        self,
        storage: StorageManager,
        hosts_manager: HostsManager,
        provider_manager: ProviderManager,
        parent: Optional[QWidget] = None
    ):
        super().__init__(parent)
        self.setWindowTitle("Настройки DNS Switcher AI+")
        self.resize(700, 650)
        self.setMinimumSize(640, 600)
        self.setModal(True)
        from ui.theme import DARK_THEME_QSS
        self.setStyleSheet(DARK_THEME_QSS)

        self.storage = storage
        self.hosts_manager = hosts_manager
        self.provider_manager = provider_manager

        self.update_worker = None
        self.app_update_worker = None
        self.available_release = None
        self._closing = False
        self._init_ui()

    def _init_ui(self) -> None:
        main_layout = QVBoxLayout(self)
        main_layout.setContentsMargins(16, 16, 16, 16)
        main_layout.setSpacing(12)

        tabs = QTabWidget(self)

        # Tab 1: Providers & Databases
        prov_tab = QWidget()
        self._init_prov_tab(prov_tab)
        tabs.addTab(prov_tab, "Провайдеры")

        # Tab 2: Monitoring & Automation
        mon_tab = QWidget()
        self._init_mon_tab(mon_tab)
        tabs.addTab(mon_tab, "Автоматизация")

        # Tab 3: Hosts Backups & Import
        backup_tab = QWidget()
        self._init_backup_tab(backup_tab)
        tabs.addTab(backup_tab, "Бэкапы hosts")

        app_tab = QWidget()
        self._init_app_update_tab(app_tab)
        tabs.addTab(app_tab, 'Обновление')
        main_layout.addWidget(tabs)

        # Bottom buttons
        btn_layout = QHBoxLayout()
        from core.updater import VERSION
        ver_lbl = QLabel(f'Версия {VERSION} · DNS Switcher AI+', self)
        ver_lbl.setStyleSheet("color: #aaaab2; font-size: 14px;")
        btn_layout.addWidget(ver_lbl)
        btn_layout.addStretch()

        close_btn = QPushButton("Закрыть", self)
        close_btn.setCursor(Qt.PointingHandCursor)
        close_btn.clicked.connect(self.accept)
        btn_layout.addWidget(close_btn)

        main_layout.addLayout(btn_layout)

    def _init_app_update_tab(self, tab):
        from core.updater import VERSION
        layout = QVBoxLayout(tab)
        layout.addWidget(QLabel(f'Установлена версия {VERSION}'))
        self.app_update_status = QLabel('Проверка стабильной версии в sasha59/dns-switcher-ai-plus.')
        self.app_update_status.setWordWrap(True)
        layout.addWidget(self.app_update_status)
        self.check_app_btn = QPushButton('Проверить обновления')
        self.check_app_btn.clicked.connect(lambda: self._start_app_update(False))
        layout.addWidget(self.check_app_btn)
        self.install_app_btn = QPushButton('Скачать и установить')
        self.install_app_btn.setEnabled(False)
        self.install_app_btn.clicked.connect(lambda: self._start_app_update(True))
        layout.addWidget(self.install_app_btn)
        note = QLabel('Обновление загрузится с GitHub, пройдёт проверку SHA-256 и заменит EXE после выхода. '
                      'Программа перезапустится; прежний EXE сохранится рядом как .previous-…')
        note.setWordWrap(True)
        layout.addWidget(note)
        layout.addStretch()

    def _start_app_update(self, install):
        if self.app_update_worker is not None:
            return
        from core.updater import AppUpdateWorker
        self.check_app_btn.setEnabled(False)
        self.install_app_btn.setEnabled(False)
        self.app_update_status.setText('Загрузка обновления…' if install else 'Проверка GitHub…')
        worker = AppUpdateWorker(self.available_release if install else None, self)
        self.app_update_worker = worker
        worker.completed.connect(self._app_update_ready)
        worker.failed.connect(self._app_update_failed)
        worker.progress.connect(lambda value: self.app_update_status.setText(f'Загрузка: {value}%'))
        worker.finished.connect(self._app_update_finished)
        worker.start()

    def _app_update_ready(self, result):
        if self._closing:
            return
        if result.get('path'):
            self.app_update_status.setText('Файл проверен. Перезапуск для установки…')
            self.app_update_requested.emit(result['path'], result['sha256'])
        elif result.get('available'):
            self.available_release = result
            self.app_update_status.setText(f"Доступна версия {result['version']} · {result['size'] / 1048576:.1f} МБ")
        else:
            self.available_release = None
            self.app_update_status.setText('Установлена последняя стабильная версия.')

    def _app_update_failed(self, message):
        self.app_update_status.setText('Ошибка обновления: ' + message)

    def _app_update_finished(self):
        worker = self.app_update_worker
        self.app_update_worker = None
        if worker:
            worker.deleteLater()
        self.check_app_btn.setEnabled(True)
        self.install_app_btn.setEnabled(bool(self.available_release))
        if self._closing:
            self.reject()

    def _init_prov_tab(self, tab: QWidget) -> None:
        layout = QVBoxLayout(tab)
        layout.setContentsMargins(12, 12, 12, 12)
        layout.setSpacing(10)

        layout.addWidget(QLabel("<b>Активные DNS/SNI провайдеры:</b>"))

        self.prov_checkboxes: Dict[str, QCheckBox] = {}
        for p in self.provider_manager.list_providers():
            cb = QCheckBox(f"{p.name}", self)
            cb.setChecked(p.enabled)
            cb.toggled.connect(lambda checked, pid=p.id: self._on_provider_toggle(pid, checked))
            self.prov_checkboxes[p.id] = cb
            layout.addWidget(cb)

        layout.addSpacing(10)
        layout.addWidget(QLabel("<b>Обновление баз провайдеров:</b>"))

        update_row = QHBoxLayout()
        self.update_db_btn = QPushButton("Обновить базы сейчас", self)
        self.update_db_btn.setCursor(Qt.PointingHandCursor)
        self.update_db_btn.clicked.connect(self._on_update_databases)
        update_row.addWidget(self.update_db_btn)

        self.db_status_lbl = QLabel(self)
        self.db_status_lbl.setStyleSheet("font-size: 14px; color: #aaaab2;")
        self._refresh_db_label()
        update_row.addWidget(self.db_status_lbl)
        layout.addLayout(update_row)

        self.auto_update_cb = QCheckBox("Автоматически проверять обновления баз", self)
        self.auto_update_cb.setChecked(self.storage.config.auto_update_db)
        self.auto_update_cb.toggled.connect(self._on_auto_update_toggled)
        layout.addWidget(self.auto_update_cb)

        layout.addStretch()

    def _init_mon_tab(self, tab: QWidget) -> None:
        layout = QVBoxLayout(tab)
        layout.setContentsMargins(12, 12, 12, 12)
        layout.setSpacing(10)

        # Monitoring group
        mon_group = QGroupBox("Фоновый мониторинг избранных сервисов")
        mon_layout = QVBoxLayout(mon_group)
        mon_layout.setSpacing(8)

        self.mon_enable_cb = QCheckBox("Следить за избранными сайтами", self)
        self.mon_enable_cb.setChecked(self.storage.config.monitoring_enabled)
        self.mon_enable_cb.toggled.connect(self._on_mon_enable_toggled)
        mon_layout.addWidget(self.mon_enable_cb)

        self.auto_fix_cb = QCheckBox("Автоматически исправлять при подтверждённом сбое", self)
        self.auto_fix_cb.setChecked(self.storage.config.auto_fix_favorites)
        self.auto_fix_cb.toggled.connect(self._on_auto_fix_toggled)
        mon_layout.addWidget(self.auto_fix_cb)

        interval_row = QHBoxLayout()
        interval_row.addWidget(QLabel("Интервал мониторинга (минут):"))
        self.mon_interval_spin = QSpinBox(self)
        self.mon_interval_spin.setRange(5, 1440)
        self.mon_interval_spin.setValue(self.storage.config.monitor_interval_minutes)
        self.mon_interval_spin.valueChanged.connect(self._on_mon_interval_changed)
        interval_row.addWidget(self.mon_interval_spin)
        interval_row.addStretch()
        mon_layout.addLayout(interval_row)

        layout.addWidget(mon_group)

        # General behavior
        gen_group = QGroupBox("Поведение программы")
        gen_layout = QVBoxLayout(gen_group)
        gen_layout.setSpacing(8)

        self.tray_cb = QCheckBox("Сворачивать в системный трей при закрытии", self)
        self.tray_cb.setChecked(self.storage.config.minimize_to_tray)
        self.tray_cb.toggled.connect(self._on_tray_toggled)
        gen_layout.addWidget(self.tray_cb)

        self.autostart_cb = QCheckBox("Запуск вместе с Windows (автозагрузка)", self)
        self.autostart_cb.setChecked(False)
        self.autostart_cb.setEnabled(False)
        self.autostart_cb.setToolTip("Автозагрузка пока не настроена; используйте ярлык Windows.")
        self.autostart_cb.toggled.connect(self._on_autostart_toggled)
        gen_layout.addWidget(self.autostart_cb)

        layout.addWidget(gen_group)
        layout.addStretch()

    def _init_backup_tab(self, tab: QWidget) -> None:
        layout = QVBoxLayout(tab)
        layout.setContentsMargins(12, 12, 12, 12)
        layout.setSpacing(10)

        # Import external hosts
        import_row = QHBoxLayout()
        import_btn = QPushButton("Импортировать hosts файл...", self)
        import_btn.setCursor(Qt.PointingHandCursor)
        import_btn.clicked.connect(self._on_import_hosts)
        import_row.addWidget(import_btn)

        create_bak_btn = QPushButton("Создать бэкап сейчас", self)
        create_bak_btn.setCursor(Qt.PointingHandCursor)
        create_bak_btn.clicked.connect(self._on_create_manual_backup)
        import_row.addWidget(create_bak_btn)
        layout.addLayout(import_row)

        layout.addWidget(QLabel("<b>Резервные копии hosts:</b>"))

        self.backups_list = QListWidget(self)
        self.backups_list.setStyleSheet("background-color: #232326; border: 1px solid #35353b; border-radius: 6px;")
        layout.addWidget(self.backups_list)
        self._refresh_backups_list()

        # Restore button
        restore_btn = QPushButton("Восстановить выбранный бэкап", self)
        restore_btn.setCursor(Qt.PointingHandCursor)
        restore_btn.clicked.connect(self._on_restore_backup)
        layout.addWidget(restore_btn)

    def _refresh_db_label(self) -> None:
        last = self.storage.config.last_db_update
        if last:
            self.db_status_lbl.setText(f"Обновлено: {last}")
        else:
            self.db_status_lbl.setText("Ещё не обновлялось")

    def _on_provider_toggle(self, provider_id: str, enabled: bool) -> None:
        self.provider_manager.set_provider_enabled(provider_id, enabled)
        self.storage.config.providers_enabled[provider_id] = enabled
        self.storage.save_config()

    def _on_update_databases(self) -> None:
        if self.update_worker and self.update_worker.isRunning():
            return
        from core.monitor import DatabaseUpdateWorker
        self.update_db_btn.setEnabled(False)
        self.update_db_btn.setText("Обновление…")
        self.update_worker = DatabaseUpdateWorker(self.provider_manager, self.storage, self)
        self.update_worker.completed.connect(self._databases_updated)
        self.update_worker.finished.connect(lambda: self.reject() if self._closing else None)
        self.update_worker.start()

    def _databases_updated(self, results):
        if self._closing:
            return
        self.update_db_btn.setEnabled(True)
        self.update_db_btn.setText("Обновить базы сейчас")
        self._refresh_db_label()
        failed = [p.name + ": " + (p.last_error or "нет ответа")
                  for p in self.provider_manager.list_providers() if results.get(p.id) is False]
        success = sum(results.values())
        message = f"Обновлено: {success} из {len(results)}."
        if failed:
            QMessageBox.warning(self, "Обновление баз", message + "\n\n" + "\n".join(failed))
        else:
            QMessageBox.information(self, "Обновление баз", message)
        self.db_updated.emit()

    def reject(self):
        if self.app_update_worker and self.app_update_worker.isRunning():
            self._closing = True
            self.app_update_worker.cancel()
            return
        if self.update_worker and self.update_worker.isRunning():
            self._closing = True
            self.update_worker.cancel()
            return
        super().reject()

    def accept(self):
        if self.app_update_worker and self.app_update_worker.isRunning():
            self._closing = True
            self.app_update_worker.cancel()
            return
        if self.update_worker and self.update_worker.isRunning():
            self._closing = True
            self.update_worker.cancel()
            return
        super().accept()

    def _on_auto_update_toggled(self, checked: bool) -> None:
        self.storage.config.auto_update_db = checked
        self.storage.save_config()

    def _on_mon_enable_toggled(self, checked: bool) -> None:
        self.storage.config.monitoring_enabled = checked
        self.storage.save_config()

    def _on_auto_fix_toggled(self, checked: bool) -> None:
        self.storage.config.auto_fix_favorites = checked
        self.storage.save_config()

    def _on_mon_interval_changed(self, val: int) -> None:
        self.storage.config.monitor_interval_minutes = val
        self.storage.save_config()

    def _on_tray_toggled(self, checked: bool) -> None:
        self.storage.config.minimize_to_tray = checked
        self.storage.save_config()

    def _on_autostart_toggled(self, checked: bool) -> None:
        self.storage.config.autostart = checked
        self.storage.save_config()

    def _refresh_backups_list(self) -> None:
        self.backups_list.clear()
        backups = self.hosts_manager.list_backups()
        for b in backups:
            size_kb = max(1, b["size"] // 1024)
            item = QListWidgetItem(f"{b['created']} — {b['filename']} ({size_kb} KB)")
            item.setData(Qt.UserRole, b["path"])
            self.backups_list.addItem(item)

    def _on_create_manual_backup(self) -> None:
        try:
            bak = self.hosts_manager.create_backup(tag="manual")
            self._refresh_backups_list()
            QMessageBox.information(self, "Бэкап создан", f"Резервная копия сохранена:\n{bak.name}")
        except Exception as e:
            QMessageBox.critical(self, "Ошибка", f"Не удалось создать бэкап: {e}")

    def _on_restore_backup(self) -> None:
        item = self.backups_list.currentItem()
        if not item:
            QMessageBox.warning(self, "Предупреждение", "Выберите бэкап из списка.")
            return

        path = item.data(Qt.UserRole)
        confirm = QMessageBox.question(
            self,
            "Восстановление hosts",
            f"Вы уверены, что хотите восстановить hosts из бэкапа?\n{item.text()}\nТекущий файл будет предварительно забэкаплен.",
            QMessageBox.Yes | QMessageBox.No
        )
        if confirm == QMessageBox.Yes:
            try:
                self.hosts_manager.restore_backup(path)
                self._refresh_backups_list()
                QMessageBox.information(self, "Успех", "Файл hosts успешно восстановлен!")
                self.backup_restored.emit()
            except Exception as e:
                QMessageBox.critical(self, "Ошибка", f"Ошибка восстановления: {e}")

    def _on_import_hosts(self) -> None:
        path, _ = QFileDialog.getOpenFileName(
            self,
            "Выберите файл hosts для импорта",
            "",
            "Hosts files (hosts* *.*);;All files (*.*)"
        )
        if path:
            self.hosts_imported.emit(path)
            QMessageBox.information(self, "Импорт", f"Файл hosts выбран для анализа:\n{path}")
