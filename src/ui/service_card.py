"""Строка сервиса: состояние, текущий маршрут и подбор по кнопке."""
from pathlib import Path
from PySide6.QtGui import QIcon
from PySide6.QtCore import QSize
from typing import Optional, Dict, List
from PySide6.QtCore import Qt, Signal
from PySide6.QtWidgets import QWidget, QVBoxLayout, QHBoxLayout, QLabel, QPushButton, QToolButton, QLineEdit, QSizePolicy
from core.verifier import ServiceStatus
from core.validation import public_ip
from core.service_checks import account_note
from PySide6.QtGui import QDesktopServices
from PySide6.QtCore import QUrl


class ServiceCard(QWidget):
    check_requested = Signal(str)
    apply_ip_requested = Signal(str, str, str)
    favorite_toggled = Signal(str, bool)
    hide_requested = Signal(str)
    route_feedback = Signal(str, str)

    def __init__(self, service, current_ip=None, route_info=None, parent=None):
        super().__init__(parent)
        self.service, self.current_ip = service, current_ip
        self.route_info = route_info or {}
        self.is_expanded = False
        self.candidates = []
        self.setObjectName('serviceCard')
        self.setAttribute(Qt.WA_StyledBackground, True)
        self.setSizePolicy(QSizePolicy.Expanding, QSizePolicy.Maximum)
        self.main_layout = QVBoxLayout(self)
        self.main_layout.setContentsMargins(16, 12, 16, 12)
        self.main_layout.setSpacing(8)

        top = QHBoxLayout()
        self.name_label = QLabel(service.name)
        self.name_label.setWordWrap(True)
        self.name_label.setSizePolicy(QSizePolicy.Ignored, QSizePolicy.Preferred)
        self.name_label.setStyleSheet('font-size: 19px; font-weight: 600;')
        top.addWidget(self.name_label, 1)
        top.addStretch()
        self.status_badge = QLabel()
        top.addWidget(self.status_badge)
        self.fav_btn = QToolButton()
        self.fav_btn.setCheckable(True)
        self.fav_btn.setIconSize(QSize(22, 22))
        self.fav_btn.setFixedSize(44, 44)
        self.fav_btn.setChecked(service.is_favorite)
        self.fav_btn.setAccessibleName('Добавить в избранное')
        self.fav_btn.setToolTip('Добавить или убрать из избранного')
        self.fav_btn.clicked.connect(self._on_fav_clicked)
        top.addWidget(self.fav_btn)
        self.rotate_btn = QToolButton()
        self.rotate_btn.setFixedSize(44, 44)
        self.rotate_btn.setIconSize(QSize(20, 20))
        self.rotate_btn.setIcon(QIcon(str(Path(__file__).resolve().parents[1] / 'assets' / 'refresh.svg')))
        self.rotate_btn.setToolTip('Подобрать другой DNS из пула, если текущий не устроил')
        self.rotate_btn.setAccessibleName('Подобрать другой DNS')
        self.rotate_btn.setStyleSheet('background: #17283e; border: 1px solid #294b72; border-radius: 10px; padding: 10px;')
        self.rotate_btn.clicked.connect(lambda: self.route_feedback.emit(service.id, 'reject'))
        top.insertWidget(top.indexOf(self.fav_btn), self.rotate_btn)
        self.main_layout.addLayout(top)

        bottom = QHBoxLayout()
        info = QVBoxLayout()
        info.setSpacing(3)
        self.cat_label = QLabel(service.primary_domain)
        self.cat_label.setStyleSheet('font-size: 14px; color: #aaaab2;')
        self.ip_badge = QLabel()
        self.ip_badge.setWordWrap(True)
        self.ip_badge.setStyleSheet('font-size: 14px; color: #aaaab2;')
        info.addWidget(self.cat_label)
        info.addWidget(self.ip_badge)
        bottom.addLayout(info, 1)
        self.action_btn = QPushButton('Подобрать')
        self.action_btn.setProperty('class', 'primaryBtn')
        self.action_btn.setToolTip('Подобрать маршрут с проверкой входа, API и файлов')
        self.action_btn.clicked.connect(lambda: self.check_requested.emit(service.id))
        bottom.addWidget(self.action_btn)
        self.expand_btn = QToolButton()
        self.expand_btn.setText('Детали')
        self.expand_btn.clicked.connect(self.toggle_expanded)
        bottom.addWidget(self.expand_btn)
        self.main_layout.addLayout(bottom)

        self.help_label = QLabel()
        self.help_label.setWordWrap(True)
        self.help_label.setStyleSheet('font-size: 14px; color: #aaaab2;')
        self.main_layout.addWidget(self.help_label)
        self.feedback_row = QWidget()
        feedback_layout = QHBoxLayout(self.feedback_row)
        feedback_layout.setContentsMargins(0, 0, 0, 0)
        open_btn = QPushButton('Открыть')
        open_btn.clicked.connect(lambda: QDesktopServices.openUrl(QUrl('https://' + service.primary_domain)))
        self.confirm_btn = QPushButton('Работает')
        self.confirm_btn.clicked.connect(lambda: self.route_feedback.emit(service.id, 'confirm'))
        for button in (open_btn, self.confirm_btn):
            feedback_layout.addWidget(button)
        self.main_layout.addWidget(self.feedback_row)

        self.detail_widget = QWidget()
        self.detail_layout = QVBoxLayout(self.detail_widget)
        self.detail_layout.setContentsMargins(0, 8, 0, 0)
        self.detail_layout.setSpacing(12)
        self.domains_label = QLabel('Домены: ' + ', '.join(service.domains))
        self.domains_label.setWordWrap(True)
        self.domains_label.setStyleSheet('font-size: 14px; color: #aaaab2;')
        self.detail_layout.addWidget(self.domains_label)
        self.result_label = QLabel(self.route_info.get('details') or
            (service.description if service.routing_mode != 'geo' else account_note(service.id)))
        self.result_label.setWordWrap(True)
        self.result_label.setStyleSheet('font-size: 14px; color: #aaaab2;')
        self.detail_layout.addWidget(self.result_label)
        self.candidates_box = QVBoxLayout()
        self.detail_layout.addLayout(self.candidates_box)
        manual = QHBoxLayout()
        self.manual_ip_input = QLineEdit()
        self.manual_ip_input.setPlaceholderText('Публичный IP вручную')
        manual.addWidget(self.manual_ip_input)
        apply = QPushButton('Проверить и применить')
        apply.clicked.connect(self._on_apply_manual_ip)
        manual.addWidget(apply)
        self.detail_layout.addLayout(manual)
        controls = QHBoxLayout()
        hide_btn = QPushButton('Скрыть сервис')
        hide_btn.setToolTip('Убрать из каталога, избранного и автоматического подбора. Записи hosts сохраняются.')
        hide_btn.clicked.connect(lambda: self.hide_requested.emit(service.id))
        reset_btn = QPushButton('Сбросить пропуски')
        reset_btn.setToolTip('Снова разрешить ранее отклонённые маршруты')
        reset_btn.clicked.connect(lambda: self.route_feedback.emit(service.id, 'reset'))
        controls.addWidget(hide_btn)
        controls.addWidget(reset_btn)
        self.detail_layout.addLayout(controls)
        self.detail_widget.hide()
        self.main_layout.addWidget(self.detail_widget)
        for button in self.findChildren(QPushButton) + self.findChildren(QToolButton):
            button.setCursor(Qt.PointingHandCursor)
        self._update_display()
        if service.routing_mode != 'geo':
            self.help_label.setText(service.description)
            self.help_label.show()
            self.status_badge.setText('Нужен обход DPI' if service.routing_mode == 'dpi' else 'Обход не подтверждён')
            self.action_btn.setText('Подробнее')
            self.action_btn.clicked.disconnect()
            self.action_btn.clicked.connect(self.toggle_expanded)
            self.rotate_btn.setEnabled(False)
            self.rotate_btn.setToolTip(service.description)

    def _on_fav_clicked(self):
        self.service.is_favorite = self.fav_btn.isChecked()
        self._update_display()
        self.favorite_toggled.emit(self.service.id, self.service.is_favorite)

    def _on_apply_manual_ip(self):
        try:
            ip = public_ip(self.manual_ip_input.text())
        except ValueError:
            self.result_label.setText('Введите корректный публичный IPv4 или IPv6.')
            return
        self.apply_ip_requested.emit(self.service.id, ip, 'Вручную')

    def toggle_expanded(self):
        self.is_expanded = not self.is_expanded
        self.detail_widget.setVisible(self.is_expanded)
        self.expand_btn.setText('Свернуть' if self.is_expanded else 'Детали')

    def set_current_ip(self, ip, route_info=None):
        self.current_ip = ip
        self.route_info = route_info or {}
        self._update_display()

    def set_verification_result(self, result, provider_name=''):
        if getattr(result, 'applied', False):
            self.current_ip = result.ip
        current_provider = self.route_info.get('provider_name', '')
        if getattr(result, 'applied', False) or getattr(result, 'is_current', False):
            current_provider = provider_name
        self.route_info = dict(status=result.status.value, latency_ms=result.latency_ms,
                               details=result.details, provider_name=current_provider,
                               suggested=getattr(result, 'suggested', False),
                               confirmable=getattr(result, 'confirmable', True))
        self.result_label.setText(result.details)
        self._update_display()

    def set_candidates(self, candidates):
        self.candidates = candidates
        self._render_candidates()

    def _update_display(self):
        self.fav_btn.setText('')
        star_name = 'star-filled.svg' if self.service.is_favorite else 'star.svg'
        self.fav_btn.setIcon(QIcon(str(Path(__file__).resolve().parents[1] / 'assets' / star_name)))
        action = 'Убрать из избранного' if self.service.is_favorite else 'Добавить в избранное'
        self.fav_btn.setToolTip(action)
        self.fav_btn.setAccessibleName(action)
        self.fav_btn.setChecked(self.service.is_favorite)
        self.fav_btn.setStyleSheet('padding: 8px; border: none; background: transparent;')
        provider = self.route_info.get('provider_name', '')
        self.ip_badge.setText(f"{provider or 'Из hosts'} · {self.current_ip}" if self.current_ip else 'Системный DNS')
        status = self.route_info.get('status', 'UNKNOWN')
        label, color = {'OK': ('Работает', '#7acb9c'), 'PARTIAL': ('Откройте сервис', '#e1b36d'),
                        'DEAD': ('Нет доступа', '#f08f8f')}.get(status, ('Не проверен', '#aaaab2'))
        if self.route_info.get('suggested'):
            label, color = 'Найден маршрут', '#79adff'
        self.feedback_row.setVisible(bool(self.current_ip) or status == 'PARTIAL' or self.service.routing_mode != 'geo')
        self.confirm_btn.setEnabled(bool(self.current_ip) and self.route_info.get('confirmable', True))

        message = ''
        if status == 'PARTIAL':
            message = 'Откройте сервис, проверьте вход, запрос и файл. Затем «Работает» или синяя кнопка сверху.'
        elif status == 'DEAD':
            message = self.route_info.get('details', '').split('\n')[0]
        self.help_label.setText(message)
        self.help_label.setVisible(bool(message))
        self.status_badge.setText(label)
        if self.service.routing_mode != 'geo':
            self.help_label.setText(self.service.description)
            self.help_label.show()
            self.status_badge.setText('Нужен обход DPI' if self.service.routing_mode == 'dpi' else 'Обход не подтверждён')
        self.status_badge.setStyleSheet(f'font-size: 14px; color: {color};')
        self.status_badge.setToolTip(self.route_info.get('details', ''))

    def _render_candidates(self):
        while self.candidates_box.count():
            item = self.candidates_box.takeAt(0)
            if item.widget():
                item.widget().deleteLater()
        for candidate in self.candidates:
            row = QWidget()
            layout = QHBoxLayout(row)
            layout.setContentsMargins(0, 0, 0, 0)
            label = QLabel(f"{candidate['provider_name']}  /  {candidate['ip']}  /  {candidate['status']}")
            label.setTextFormat(Qt.PlainText)
            label.setWordWrap(True)
            label.setStyleSheet('font-size: 14px;')
            label.setToolTip(candidate.get('details', ''))
            layout.addWidget(label, 1)
            if candidate['status'] == 'OK' or candidate.get('routable'):
                button = QPushButton('Выбрать')
                button.clicked.connect(lambda checked=False, c=candidate:
                    self.apply_ip_requested.emit(self.service.id, c['ip'], c['provider_name']))
                layout.addWidget(button)
            self.candidates_box.addWidget(row)
