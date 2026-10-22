"""
AddDialog: Modal window for adding custom services or custom DNS providers.
"""

from urllib.parse import urlparse
import re
import uuid
from core.validation import domain_name, parse_hosts
from typing import List, Optional
from PySide6.QtCore import Qt, Signal
from PySide6.QtWidgets import (
    QDialog, QVBoxLayout, QHBoxLayout, QLabel, QLineEdit,
    QPushButton, QTabWidget, QWidget, QCheckBox, QComboBox,
    QTextEdit, QMessageBox
)

from core.catalog import ServiceDef
from providers.custom import CustomProvider


class AddDialog(QDialog):
    site_added = Signal(object)        # ServiceDef
    provider_added = Signal(object)    # CustomProvider

    def __init__(self, existing_categories: List[str], parent: Optional[QWidget] = None):
        super().__init__(parent)
        self.setWindowTitle("Добавить сайт или DNS-провайдер")
        self.resize(680, 620)
        self.setMinimumSize(640, 580)
        self.setModal(True)
        self.existing_categories = existing_categories

        self._init_ui()

    def _init_ui(self) -> None:
        layout = QVBoxLayout(self)
        layout.setContentsMargins(16, 16, 16, 16)
        layout.setSpacing(12)

        self.tab_widget = QTabWidget(self)

        # Tab 1: Add Site
        self.site_tab = QWidget()
        self._init_site_tab()
        self.tab_widget.addTab(self.site_tab, "Сайт / Сервис")

        # Tab 2: Add DNS Provider
        self.provider_tab = QWidget()
        self._init_provider_tab()
        self.tab_widget.addTab(self.provider_tab, "DNS-провайдер")

        layout.addWidget(self.tab_widget)

    def _init_site_tab(self) -> None:
        layout = QVBoxLayout(self.site_tab)
        layout.setContentsMargins(12, 12, 12, 12)
        layout.setSpacing(10)

        # Name
        layout.addWidget(QLabel("Название сервиса:"))
        self.site_name_edit = QLineEdit(self)
        self.site_name_edit.setPlaceholderText("Например: Midjourney")
        layout.addWidget(self.site_name_edit)

        # Primary Domain
        layout.addWidget(QLabel("Основной домен или URL:"))
        self.site_domain_edit = QLineEdit(self)
        self.site_domain_edit.setPlaceholderText("например: midjourney.com")
        layout.addWidget(self.site_domain_edit)

        # Related domains
        layout.addWidget(QLabel("Связанные домены (через запятую или пробел):"))
        self.site_related_edit = QLineEdit(self)
        self.site_related_edit.setPlaceholderText("cdn.midjourney.com, api.midjourney.com")
        layout.addWidget(self.site_related_edit)

        # Category
        layout.addWidget(QLabel("Категория:"))
        self.cat_combo = QComboBox(self)
        for cat in self.existing_categories:
            self.cat_combo.addItem(cat)
        if "Пользовательские" not in self.existing_categories:
            self.cat_combo.addItem("Пользовательские")
        self.cat_combo.setEditable(True)
        layout.addWidget(self.cat_combo)

        # Add to favorites
        self.fav_checkbox = QCheckBox("Добавить в избранное", self)
        self.fav_checkbox.setChecked(True)
        layout.addWidget(self.fav_checkbox)

        layout.addStretch()

        # Submit button
        submit_btn = QPushButton("Добавить сайт", self)
        submit_btn.setProperty("class", "primaryBtn")
        submit_btn.setCursor(Qt.PointingHandCursor)
        submit_btn.clicked.connect(self._on_add_site)
        layout.addWidget(submit_btn)

    def _init_provider_tab(self) -> None:
        layout = QVBoxLayout(self.provider_tab)
        layout.setContentsMargins(12, 12, 12, 12)
        layout.setSpacing(10)

        # Provider Name
        layout.addWidget(QLabel("Название провайдера:"))
        self.prov_name_edit = QLineEdit(self)
        self.prov_name_edit.setPlaceholderText("Например: Мой DoH Резолвер")
        layout.addWidget(self.prov_name_edit)

        # Type
        layout.addWidget(QLabel("Тип провайдера:"))
        self.prov_type_combo = QComboBox(self)
        self.prov_type_combo.addItem("DNS-over-HTTPS (DoH)", CustomProvider.TYPE_DOH)
        self.prov_type_combo.addItem("Обычный DNS (IP/Порт)", CustomProvider.TYPE_PLAIN_DNS)
        self.prov_type_combo.addItem("Источник hosts (URL / файл)", CustomProvider.TYPE_HOSTS_URL)
        self.prov_type_combo.addItem("Ручной профиль (домен -> IP)", CustomProvider.TYPE_MANUAL)
        self.prov_type_combo.currentIndexChanged.connect(self._on_prov_type_changed)
        layout.addWidget(self.prov_type_combo)

        # Endpoint / IP / URL
        self.endpoint_label = QLabel("URL DoH (эндпоинт):")
        layout.addWidget(self.endpoint_label)
        self.prov_endpoint_edit = QLineEdit(self)
        self.prov_endpoint_edit.setPlaceholderText("https://example.com/dns-query")
        layout.addWidget(self.prov_endpoint_edit)

        # Manual mappings textarea (visible only if manual)
        self.manual_label = QLabel("Пары домен -> IP (каждая пара с новой строки):")
        self.manual_label.setVisible(False)
        layout.addWidget(self.manual_label)
        self.manual_text_edit = QTextEdit(self)
        self.manual_text_edit.setPlaceholderText("193.233.112.68 chatgpt.com\n5.175.161.40 open.spotify.com")
        self.manual_text_edit.setVisible(False)
        layout.addWidget(self.manual_text_edit)

        layout.addStretch()

        # Submit button
        submit_prov_btn = QPushButton("Добавить провайдер", self)
        submit_prov_btn.setProperty("class", "primaryBtn")
        submit_prov_btn.setCursor(Qt.PointingHandCursor)
        submit_prov_btn.clicked.connect(self._on_add_provider)
        layout.addWidget(submit_prov_btn)

    def _on_prov_type_changed(self, idx: int) -> None:
        p_type = self.prov_type_combo.currentData()
        if p_type == CustomProvider.TYPE_DOH:
            self.endpoint_label.setText("URL DoH (эндпоинт):")
            self.endpoint_label.setVisible(True)
            self.prov_endpoint_edit.setVisible(True)
            self.prov_endpoint_edit.setPlaceholderText("https://example.com/dns-query")
            self.manual_label.setVisible(False)
            self.manual_text_edit.setVisible(False)
        elif p_type == CustomProvider.TYPE_PLAIN_DNS:
            self.endpoint_label.setText("IP DNS-сервера (порт 53):")
            self.endpoint_label.setVisible(True)
            self.prov_endpoint_edit.setVisible(True)
            self.prov_endpoint_edit.setPlaceholderText("например 1.1.1.1 или 1.1.1.1:53")
            self.manual_label.setVisible(False)
            self.manual_text_edit.setVisible(False)
        elif p_type == CustomProvider.TYPE_HOSTS_URL:
            self.endpoint_label.setText("Ссылка на hosts или путь к файлу:")
            self.endpoint_label.setVisible(True)
            self.prov_endpoint_edit.setVisible(True)
            self.prov_endpoint_edit.setPlaceholderText("https://.../hosts или C:\\path\\to\\hosts.txt")
            self.manual_label.setVisible(False)
            self.manual_text_edit.setVisible(False)
        elif p_type == CustomProvider.TYPE_MANUAL:
            self.endpoint_label.setVisible(False)
            self.prov_endpoint_edit.setVisible(False)
            self.manual_label.setVisible(True)
            self.manual_text_edit.setVisible(True)

    @staticmethod
    def _clean_domain(text: str) -> str:
        t = text.strip().lower()
        if t.startswith("http://") or t.startswith("https://"):
            parsed = urlparse(t)
            return parsed.netloc or parsed.path
        return t.split("/")[0]

    def _on_add_site(self) -> None:
        name = self.site_name_edit.text().strip()
        raw_domain = self.site_domain_edit.text().strip()
        if not name or not raw_domain:
            QMessageBox.warning(self, "Ошибка", "Укажите название и основной домен сервиса.")
            return

        try:
            primary_domain = domain_name(self._clean_domain(raw_domain))
        except (ValueError, UnicodeError) as error:
            QMessageBox.warning(self, 'Некорректный домен', str(error))
            return
        related_raw = self.site_related_edit.text().replace(",", " ").split()
        domains = [primary_domain]
        for r in related_raw:
            try:
                cd = domain_name(self._clean_domain(r))
            except (ValueError, UnicodeError):
                QMessageBox.warning(self, 'Некорректный домен', r)
                return
            if cd and cd not in domains:
                domains.append(cd)

        category = self.cat_combo.currentText().strip() or "Пользовательские"
        service_id = "custom_" + uuid.uuid4().hex[:12]

        new_service = ServiceDef(
            id=service_id,
            name=name,
            category=category,
            primary_domain=primary_domain,
            domains=domains,
            is_favorite=self.fav_checkbox.isChecked(),
            is_custom=True
        )
        self.site_added.emit(new_service)
        self.accept()

    def _on_add_provider(self) -> None:
        name = self.prov_name_edit.text().strip()
        p_type = self.prov_type_combo.currentData()
        endpoint = self.prov_endpoint_edit.text().strip()

        if not name:
            QMessageBox.warning(self, "Ошибка", "Укажите название DNS-провайдера.")
            return

        static_mappings = {}
        if p_type == CustomProvider.TYPE_MANUAL:
            lines = self.manual_text_edit.toPlainText().splitlines()
            for line in lines:
                parts = line.strip().split()
                if len(parts) >= 2:
                    ip = parts[0]
                    for d in parts[1:]:
                        static_mappings[d.lower().strip()] = ip
            if not static_mappings:
                QMessageBox.warning(self, "Ошибка", "Укажите хотя бы одну пару 'IP домен'.")
                return
        else:
            if not endpoint:
                QMessageBox.warning(self, "Ошибка", "Укажите эндпоинт или IP адрес провайдера.")
                return

        p_id = "custom_prov_" + uuid.uuid4().hex[:12]
        new_provider = CustomProvider(
            id=p_id,
            name=name,
            provider_type=p_type,
            endpoint_or_ip=endpoint,
            static_mappings=static_mappings
        )
        self.provider_added.emit(new_provider)
        self.accept()
