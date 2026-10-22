"""
MainWindow: Core graphical interface for DNS Switcher AI+.
Compact dark minimalism, responsive real-time diagnostics, smooth favorites management, and tray integration.
"""

import webbrowser
from typing import Dict, List, Optional
from PySide6.QtCore import Qt, QUrl
from PySide6.QtGui import QIcon, QDesktopServices
from PySide6.QtWidgets import (
    QMainWindow, QWidget, QVBoxLayout, QHBoxLayout, QLabel,
    QPushButton, QLineEdit, QScrollArea, QTabWidget, QProgressBar,
    QMessageBox, QToolButton, QComboBox, QMenu
)

from core.catalog import Catalog, ServiceDef
from core.hosts_manager import HostsManager
from core.storage import StorageManager
from core.verifier import ServiceVerifier, ServiceStatus, VerificationResult
from core.monitor import VerificationWorker, BackgroundMonitorThread
from providers.manager import ProviderManager
from ui.theme import DARK_THEME_QSS
from ui.service_card import ServiceCard
from ui.add_dialog import AddDialog
from ui.settings_dialog import SettingsDialog
from ui.tray_icon import TrayIconManager


class MainWindow(QMainWindow):
    GITHUB_URL = "https://github.com/pryanus/dns-switcher-ai-plus"

    def __init__(
        self,
        catalog: Catalog,
        hosts_manager: HostsManager,
        provider_manager: ProviderManager,
        storage: StorageManager,
        auto_check: bool = False
    ):
        super().__init__()
        self.catalog = catalog
        self.hosts_manager = hosts_manager
        self.provider_manager = provider_manager
        self.storage = storage
        self.catalog.hidden_services = set(storage.config.hidden_services)
        self._exiting = False
        self._session_results = {}

        self.setWindowTitle("DNS Switcher AI+")
        self.resize(780, 790)
        self.setMinimumSize(640, 580)

        # ServiceCard mapping: service_id -> ServiceCard
        self.service_cards: Dict[str, ServiceCard] = {}
        self.active_worker: Optional[VerificationWorker] = None

        # Apply dark theme
        self.setStyleSheet(DARK_THEME_QSS)

        self._init_ui()
        self._init_tray()
        self._init_monitor()
        self.tab_bar.setCurrentIndex(0)
        self._populate_services()
        if auto_check:
            from PySide6.QtCore import QTimer
            QTimer.singleShot(300, self._check_active_on_start)

    def _check_active_on_start(self):
        services = [s for s in self.catalog.list_favorites()
                    if self.hosts_manager.get_service_current_ips([s.primary_domain]).get(s.primary_domain)]
        if services and self.active_worker is None:
            self._start_batch_worker(services, auto_fix=False, silent=True)

    def _init_ui(self) -> None:
        self.central_widget = QWidget(self)
        self.central_widget.setObjectName("centralWidget")
        self.setCentralWidget(self.central_widget)

        main_layout = QVBoxLayout(self.central_widget)
        main_layout.setContentsMargins(24, 24, 24, 20)
        main_layout.setSpacing(16)

        # -------------------------------------------------------------
        # 1. Header
        # -------------------------------------------------------------
        header_layout = QHBoxLayout()
        header_layout.setSpacing(8)

        # Title and Subtitle
        title_box = QVBoxLayout()
        title_box.setSpacing(1)
        self.title_lbl = QLabel("DNS Switcher AI+", self)
        self.title_lbl.setStyleSheet("font-size: 25px; font-weight: 600; color: #f0f0f2;")
        self.sub_lbl = QLabel("AI-инструменты и любимые сервисы", self)
        self.sub_lbl.setStyleSheet("font-size: 14px; color: #aaaab2;")
        title_box.addWidget(self.title_lbl)
        title_box.addWidget(self.sub_lbl)
        header_layout.addLayout(title_box)

        header_layout.addStretch()

        # GitHub Button
        self.github_btn = QToolButton(self)
        self.github_btn.setText("GitHub")
        self.github_btn.setToolTip("Открыть проект на GitHub")
        self.github_btn.setCursor(Qt.PointingHandCursor)
        self.github_btn.clicked.connect(lambda: webbrowser.open(self.GITHUB_URL))
        header_layout.addWidget(self.github_btn)

        # Settings Button
        self.settings_btn = QToolButton(self)
        self.settings_btn.setText("Настройки")
        self.settings_btn.setStyleSheet("font-size: 14px;")
        self.settings_btn.setToolTip("Настройки программы")
        self.settings_btn.setCursor(Qt.PointingHandCursor)
        self.settings_btn.clicked.connect(self._open_settings)
        header_layout.addWidget(self.settings_btn)

        main_layout.addLayout(header_layout)

        # -------------------------------------------------------------
        # 2. Search Box
        # -------------------------------------------------------------
        self.search_edit = QLineEdit(self)
        self.search_edit.setPlaceholderText("Найти сервис или домен")
        self.search_edit.textChanged.connect(self._filter_services)
        self.search_edit.setFocus()
        main_layout.addWidget(self.search_edit)

        # -------------------------------------------------------------
        # 3. View Tabs (Favorites / Catalog)
        # -------------------------------------------------------------
        self.tab_bar = QTabWidget(self)
        self.tab_bar.currentChanged.connect(self._on_tab_changed)

        # Tab 1: Favorites
        self.fav_scroll = QScrollArea()
        self.fav_scroll.setWidgetResizable(True)
        self.fav_container = QWidget()
        self.fav_layout = QVBoxLayout(self.fav_container)
        self.fav_layout.setContentsMargins(0, 4, 0, 4)
        self.fav_layout.setSpacing(10)
        self.fav_layout.addStretch()
        self.fav_scroll.setWidget(self.fav_container)
        self.tab_bar.addTab(self.fav_scroll, "Избранное")

        # Tab 2: Catalog
        self.all_scroll = QScrollArea()
        self.all_scroll.setWidgetResizable(True)
        self.all_container = QWidget()
        self.all_layout = QVBoxLayout(self.all_container)
        self.all_layout.setContentsMargins(0, 4, 0, 4)
        self.all_layout.setSpacing(10)
        self.all_layout.addStretch()
        self.all_scroll.setWidget(self.all_container)
        self.tab_bar.addTab(self.all_scroll, " Каталог")

        filter_row = QHBoxLayout()
        self.category_combo = QComboBox()
        self.category_combo.addItem('Все категории', None)
        for category in self.catalog.get_categories():
            self.category_combo.addItem(category, category)
        self.category_combo.currentIndexChanged.connect(lambda: self._filter_services(self.search_edit.text()))
        filter_row.addWidget(self.category_combo)
        self.hidden_btn = QToolButton()
        self.hidden_btn.setText('Скрытые')
        self.hidden_btn.setPopupMode(QToolButton.InstantPopup)
        self.hidden_menu = QMenu(self.hidden_btn)
        self.hidden_btn.setMenu(self.hidden_menu)
        self.hidden_menu.aboutToShow.connect(self._populate_hidden_menu)
        filter_row.addWidget(self.hidden_btn)
        filter_row.addStretch()
        self.count_label = QLabel(f'{len(self.catalog.list_all())} сервисов · рекомендуемый порядок')
        self.count_label.setStyleSheet('font-size: 14px; color: #aaaab2;')
        filter_row.addWidget(self.count_label)
        main_layout.addLayout(filter_row)
        main_layout.addWidget(self.tab_bar)

        # -------------------------------------------------------------
        # 4. Progress Section (hidden when idle)
        # -------------------------------------------------------------
        self.progress_widget = QWidget(self)
        prog_layout = QHBoxLayout(self.progress_widget)
        prog_layout.setContentsMargins(0, 0, 0, 0)
        prog_layout.setSpacing(8)

        self.progress_bar = QProgressBar(self)
        self.progress_bar.setRange(0, 100)
        self.progress_bar.setTextVisible(True)
        prog_layout.addWidget(self.progress_bar)

        self.cancel_btn = QPushButton("Отмена", self)
        self.cancel_btn.setCursor(Qt.PointingHandCursor)
        self.cancel_btn.setStyleSheet("padding: 8px 12px; font-size: 14px;")
        self.cancel_btn.clicked.connect(self._cancel_worker)
        prog_layout.addWidget(self.cancel_btn)

        self.progress_widget.setVisible(False)
        main_layout.addWidget(self.progress_widget)

        # -------------------------------------------------------------
        # 5. Bottom Action Buttons
        # -------------------------------------------------------------
        footer_layout = QHBoxLayout()
        footer_layout.setSpacing(8)

        self.fix_fav_btn = QPushButton("Подобрать избранному", self)
        self.fix_fav_btn.setProperty("class", "primaryBtn")
        self.fix_fav_btn.setCursor(Qt.PointingHandCursor)
        self.fix_fav_btn.clicked.connect(self.fix_favorites)
        footer_layout.addWidget(self.fix_fav_btn)

        self.fix_all_btn = QPushButton("Проверить", self)
        self.fix_all_btn.setProperty("class", "secondaryBtn")
        self.fix_all_btn.setCursor(Qt.PointingHandCursor)
        self.fix_all_btn.clicked.connect(lambda: self._start_batch_worker(self.catalog.list_favorites() if self.tab_bar.currentIndex() == 0 else self.catalog.list_all(), auto_fix=False))
        footer_layout.addWidget(self.fix_all_btn)

        self.add_btn = QPushButton("+ Добавить", self)
        self.add_btn.setCursor(Qt.PointingHandCursor)
        self.add_btn.clicked.connect(self._open_add_dialog)
        footer_layout.addWidget(self.add_btn)

        main_layout.addLayout(footer_layout)
        self.note_label = QLabel("Свои записи — в отдельном блоке hosts. Исходные строки сохраняются.")
        self.note_label.setWordWrap(True)
        self.note_label.setStyleSheet("font-size: 14px; color: #aaaab2;")
        main_layout.addWidget(self.note_label)

    def _init_tray(self) -> None:
        self.tray = TrayIconManager(self)
        self.tray.open_requested.connect(self._restore_from_tray)
        self.tray.fix_favorites_requested.connect(self.fix_favorites)
        self.tray.fix_all_requested.connect(self.fix_all)
        self.tray.settings_requested.connect(self._open_settings)
        self.tray.exit_requested.connect(self._exit_app)
        self.tray.show()

    def _init_monitor(self) -> None:
        self.monitor_thread = BackgroundMonitorThread(
            catalog=self.catalog,
            hosts_manager=self.hosts_manager,
            provider_manager=self.provider_manager,
            storage=self.storage,
            parent=self
        )
        self.monitor_thread.service_alert.connect(self._on_monitor_alert)
        self.monitor_thread.start()

    def _on_monitor_alert(self, s_name: str, status: str, details: str) -> None:
        self.tray.notify(f"DNS Switcher AI+: {s_name}", f"{status}\n{details}")
        self._populate_services()

    def _populate_services(self) -> None:
        if not hasattr(self, 'count_label'):
            return
        # Clear existing
        for card in self.service_cards.values():
            self.fav_layout.removeWidget(card)
            self.all_layout.removeWidget(card)
            card.hide()
            card.deleteLater()
        self.service_cards.clear()

        query = self.search_edit.text()
        all_services = self.catalog.list_favorites() if self.tab_bar.currentIndex() == 0 else self.catalog.list_all()

        all_services = [s for s in all_services if self.tab_bar.currentIndex() == 1 or s.is_favorite]
        for s in all_services:
            current_ip = (self.hosts_manager.get_service_current_ips([s.primary_domain]).get(s.primary_domain) or [None])[0]
            route_info = self.storage.get_active_route(s.id) or {}
            if not current_ip or route_info.get('ip') != current_ip:
                route_info = {}
            if current_ip and not route_info.get('provider_name'):
                for provider in self.provider_manager.list_providers():
                    cached = getattr(provider, '_domain_ips', getattr(provider, '_ip_cache', {}))
                    if current_ip in cached.get(s.primary_domain, []):
                        route_info['provider_name'] = provider.name
                        break

            card = ServiceCard(service=s, current_ip=current_ip, route_info=route_info)
            previous = self._session_results.get(s.id)
            if previous and (not current_ip or previous[0].ip == current_ip):
                card.set_verification_result(previous[0], previous[1])
            card.check_requested.connect(self._on_check_single_service)
            card.apply_ip_requested.connect(self._on_apply_ip)
            card.favorite_toggled.connect(self._on_favorite_toggled)
            card.hide_requested.connect(self._hide_service)
            card.route_feedback.connect(self._route_feedback)

            self.service_cards[s.id] = card

            # Add to appropriate layout
            if self.tab_bar.currentIndex() == 0:
                # Insert before stretch
                self.fav_layout.insertWidget(self.fav_layout.count() - 1, card)
            else:
                self.all_layout.insertWidget(self.all_layout.count() - 1, card)
        self.count_label.setText(f'{len(self.catalog.list_all())} сервисов')
        self.hidden_btn.setText(f'Скрытые: {len(self.catalog.hidden_services)}')
        self._filter_services(query)

    def _filter_services(self, text: str) -> None:
        category = self.category_combo.currentData() if hasattr(self, 'category_combo') else None
        for s_id, card in self.service_cards.items():
            card.setVisible(card.service.matches_query(text) and (category is None or card.service.category == category))

    def _on_tab_changed(self, idx: int) -> None:
        self._populate_services()

    def _reposition_cards(self) -> None:
        """Positions cards into favorites or all services containers."""
        for s_id, card in self.service_cards.items():
            if card.service.is_favorite:
                if self.fav_layout.indexOf(card) == -1:
                    self.fav_layout.insertWidget(self.fav_layout.count() - 1, card)
            else:
                if self.all_layout.indexOf(card) == -1:
                    self.all_layout.insertWidget(self.all_layout.count() - 1, card)

    def _on_favorite_toggled(self, service_id: str, is_fav: bool) -> None:
        self.catalog.set_favorite(service_id, is_fav)
        if is_fav and service_id not in self.storage.config.favorites:
            self.storage.config.favorites.append(service_id)
        elif not is_fav and service_id in self.storage.config.favorites:
            self.storage.config.favorites.remove(service_id)
        self.storage.save_config()
        self._populate_services()

    def _hide_service(self, service_id):
        self.catalog.hidden_services.add(service_id)
        self.storage.config.hidden_services = sorted(self.catalog.hidden_services)
        self.storage.save_config()
        self._populate_services()

    def _populate_hidden_menu(self):
        self.hidden_menu.clear()
        for service_id in sorted(self.catalog.hidden_services):
            service = self.catalog.get_service(service_id)
            if service:
                action = self.hidden_menu.addAction('Вернуть ' + service.name)
                action.triggered.connect(lambda checked=False, sid=service_id: self._restore_service(sid))
        if not self.hidden_menu.actions():
            self.hidden_menu.addAction('Скрытых сервисов нет').setEnabled(False)

    def _restore_service(self, service_id):
        self.catalog.hidden_services.discard(service_id)
        self.storage.config.hidden_services = sorted(self.catalog.hidden_services)
        self.storage.save_config()
        self._populate_services()

    def _route_feedback(self, service_id, action):
        if self.active_worker and self.active_worker.isRunning():
            return
        route = self.storage.get_active_route(service_id)
        service = self.catalog.get_service(service_id)
        if action == 'reset':
            self.storage.config.rejected_routes.pop(service_id, None)
        elif action == 'confirm':
            if not route:
                actual = self.hosts_manager.get_service_current_ips([service.primary_domain]).get(service.primary_domain, [])
                if not actual:
                    return
                self.storage.set_active_route(service_id, actual[0], 'Из hosts', 'OK', 0)
                route = self.storage.get_active_route(service_id)
            actual = self.hosts_manager.get_service_current_ips([service.primary_domain]).get(service.primary_domain, [])
            if actual != [route.get('ip')]:
                return
            route.update(confirmed=True, status='OK')
            result = VerificationResult(actual[0], service.primary_domain, ServiceStatus.OK,
                route.get('latency_ms', 0), 'Работа подтверждена пользователем.')
            result.is_current = True
            result.confirmable = True
            self._session_results[service_id] = (result, route.get('provider_name', 'Из hosts'))
        elif action == 'reject':
            actual = self.hosts_manager.get_service_current_ips([service.primary_domain]).get(service.primary_domain, [])
            rejected = self.storage.config.rejected_routes.setdefault(service_id, [])
            for ip in actual:
                if ip not in rejected:
                    rejected.append(ip)
            if route:
                route.update(confirmed=False, status='DEAD', confirmable=False,
                             details='Маршрут отклонён: нужная функция не работает.')
        self.storage.save_config()
        self._populate_services()
        if action in ('reject', 'reset'):
            self._start_batch_worker([service], auto_fix=True, rotate=True, prefer_provider_order=(action == 'reset'))

    def _on_check_single_service(self, service_id: str) -> None:
        s = self.catalog.get_service(service_id)
        if not s:
            return

        self._start_batch_worker([s], auto_fix=True)

    def _on_apply_ip(self, service_id: str, ip: str, provider_name: str) -> None:
        from core.validation import public_ip
        try:
            ip = public_ip(ip)
        except ValueError as error:
            QMessageBox.warning(self, "Некорректный IP", str(error))
            return
        service = self.catalog.get_service(service_id)
        if service:
            self._start_batch_worker([service], auto_fix=True, forced=(ip, provider_name))

    def fix_favorites(self) -> None:
        favs = self.catalog.list_favorites()
        if not favs:
            QMessageBox.information(self, "Избранное", "Список избранного пуст. Добавьте нужные сервисы из каталога.")
            return
        self._start_batch_worker(favs, auto_fix=True)

    def fix_all(self) -> None:
        all_s = self.catalog.list_all()
        self._start_batch_worker(all_s, auto_fix=True)

    def _start_batch_worker(self, services: List[ServiceDef], auto_fix: bool = False, forced=None, rotate=False, prefer_provider_order=False, silent=False) -> None:
        if self.active_worker is not None:
            return

        if self._exiting:
            return
        self.progress_widget.setVisible(True)
        self.cancel_btn.setEnabled(True)
        self.tab_bar.setEnabled(False)
        self.add_btn.setEnabled(False)
        self.progress_bar.setValue(0)
        self.settings_btn.setEnabled(False)
        for card in self.service_cards.values():
            card.setEnabled(False)
        self.fix_fav_btn.setEnabled(False)
        self.fix_all_btn.setEnabled(False)

        self.active_worker = VerificationWorker(
            services=services,
            hosts_manager=self.hosts_manager,
            provider_manager=self.provider_manager,
            storage=self.storage,
            auto_fix=auto_fix,
            parent=self, forced=forced, rotate=rotate, prefer_provider_order=prefer_provider_order
        )
        self.active_worker.silent = silent
        self.active_worker.candidates_ready.connect(self._on_candidates_ready)
        self.active_worker.finished.connect(self._on_worker_thread_finished)
        self.active_worker.progress.connect(self._on_worker_progress)
        self.active_worker.service_result.connect(self._on_worker_service_result)
        self.active_worker.finished_batch.connect(self._on_worker_finished)
        self.active_worker.error_occurred.connect(self._on_worker_error)
        self.active_worker.start()

    def _on_worker_error(self, err_msg: str) -> None:
        QMessageBox.critical(self, "Ошибка обновления hosts", err_msg)
        self.tray.notify("DNS Switcher AI+: Ошибка", err_msg, is_error=True)

    def _on_worker_progress(self, current: int, total: int, s_name: str) -> None:
        if self.active_worker and self.active_worker._is_cancelled:
            return
        pct = int((current / total) * 100) if total else 0
        self.progress_bar.setValue(pct)
        self.progress_bar.setFormat(f"Проверка {current}/{total}: {s_name}")

    def _on_worker_service_result(self, service_id: str, result: VerificationResult, prov_name: str) -> None:
        if self.active_worker and self.active_worker._is_cancelled:
            return
        previous = self._session_results.get(service_id)
        if getattr(result, 'alternative_failed', False) and previous and previous[0].status == ServiceStatus.OK:
            card = self.service_cards.get(service_id)
            if card:
                card.result_label.setText(result.details)
            return
        self._session_results[service_id] = (result, prov_name)
        card = self.service_cards.get(service_id)
        if card:
            card.set_verification_result(result, provider_name=prov_name)

    def _on_worker_finished(self, summary: dict) -> None:
        self.progress_widget.setVisible(False)
        if summary.get('cancelled'):
            self.note_label.setText('Проверка отменена. Уже завершённые применения сохраняются.')
            return
        msg = (
            f"Проверка завершена!\n"
            f"Всего проверено: {summary.get('total', 0)}\n"
            f"Сетевые проверки: {summary.get('ok', 0)}\n"
            f"Применено маршрутов: {summary.get('fixed', 0)}\n"
            f"Требуют внимания: {summary.get('failed', 0)}"
        )
        if not (self.active_worker and getattr(self.active_worker, "silent", False)):
            self.tray.notify("DNS Switcher AI+: Итоги проверки", msg)

    def _cancel_worker(self) -> None:
        if self.active_worker:
            self.active_worker.cancel()
            self.progress_bar.setFormat("Отменено · завершаю текущую операцию…")
            self.cancel_btn.setEnabled(False)

    def _open_add_dialog(self) -> None:
        cats = self.catalog.get_categories()
        dlg = AddDialog(existing_categories=cats, parent=self)
        dlg.site_added.connect(self._on_custom_site_added)
        dlg.provider_added.connect(self._on_custom_provider_added)
        dlg.exec()

    def _on_custom_site_added(self, service: ServiceDef) -> None:
        self.catalog.add_service(service)
        self.storage.config.custom_services.append(service.to_dict())
        self.storage.save_config()
        self._populate_services()

    def _on_custom_provider_added(self, provider) -> None:
        self.provider_manager.add_custom_provider(provider)
        self.storage.config.custom_providers.append(provider.to_dict())
        self.storage.save_config()
        QMessageBox.information(self, "Провайдер добавлен", f"DNS-провайдер '{provider.name}' успешно зарегистрирован.")

    def _open_settings(self) -> None:
        dlg = SettingsDialog(
            storage=self.storage,
            hosts_manager=self.hosts_manager,
            provider_manager=self.provider_manager,
            parent=self
        )
        dlg.app_update_requested.connect(self._install_app_update)
        dlg.hosts_imported.connect(self._on_hosts_imported)
        dlg.backup_restored.connect(self._populate_services)
        dlg.exec()

    def _on_hosts_imported(self, path: str) -> None:
        parsed = self.hosts_manager.parse_geohide_services(path)
        added_count = self.catalog.import_hosts_services(parsed)
        self._populate_services()
        QMessageBox.information(
            self,
            "Импорт hosts",
            f"Файл успешно разобран!\nОбнаружено сервисов: {len(parsed)}\nДобавлено новых в каталог: {added_count}"
        )

    def _install_app_update(self, path, digest):
        try:
            from core.updater import launch_installer
            launch_installer(path, digest)
        except Exception as error:
            QMessageBox.warning(self, 'Обновление не установлено', str(error))
            return
        self._exit_app()

    def _restore_from_tray(self) -> None:
        self.showNormal()
        self.activateWindow()

    def closeEvent(self, event) -> None:
        event.ignore()
        if self.storage.config.minimize_to_tray:
            event.ignore()
            self.hide()
            self.tray.notify(
                "DNS Switcher AI+ свернут",
                "Программа продолжает работу в системном трее."
            )
        else:
            self._exit_app()

    def _on_candidates_ready(self, service_id, candidates):
        card = self.service_cards.get(service_id)
        if card:
            card.set_candidates(candidates)

    def _on_worker_thread_finished(self):
        worker = self.active_worker
        self.active_worker = None
        if worker:
            worker.deleteLater()
        self.progress_widget.hide()
        self.tab_bar.setEnabled(True)
        self.add_btn.setEnabled(True)
        self.fix_fav_btn.setEnabled(True)
        self.fix_all_btn.setEnabled(True)
        self.settings_btn.setEnabled(True)
        for card in self.service_cards.values():
            card.setEnabled(True)

    def _exit_app(self) -> None:
        if self._exiting:
            return
        self._exiting = True
        self.hide()
        for dialog in self.findChildren(SettingsDialog):
            dialog.reject()
        if self.monitor_thread:
            self.monitor_thread.stop()
        if self.active_worker:
            self.active_worker.cancel()
        from PySide6.QtCore import QTimer, QThread
        from PySide6.QtWidgets import QApplication
        def finish():
            if any(thread.isRunning() for thread in self.findChildren(QThread)):
                QTimer.singleShot(100, finish)
                return
            self.tray.hide()
            QApplication.instance().quit()
        finish()
