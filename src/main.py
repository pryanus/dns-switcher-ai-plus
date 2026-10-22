"""
DNS Switcher - Application Entrypoint.
Lightweight, portable Windows utility for diagnosing and repairing access to web services via hosts & Smart DNS.
"""

import sys
import os
import argparse
from pathlib import Path

# Add src to sys.path
sys.path.insert(0, str(Path(__file__).parent))

from PySide6.QtCore import Qt
from PySide6.QtWidgets import QApplication

from core.storage import StorageManager
from core.hosts_manager import HostsManager
from core.catalog import Catalog, ServiceDef, RETIRED_SERVICES
from providers.manager import ProviderManager
from providers.custom import CustomProvider
from ui.main_window import MainWindow


def _remove_retired_services(hosts_manager, storage):
    config = storage.config
    # Явно добавленные пользователем сервисы не относятся к стандартному каталогу.
    custom_ids = {service.get('id') for service in config.custom_services}
    retired = {sid: name for sid, name in RETIRED_SERVICES.items() if sid not in custom_ids}
    removed = hosts_manager.remove_services_entries(retired.values())
    changed = removed or bool(set(config.active_routes).intersection(retired))
    changed = changed or bool(set(config.rejected_routes).intersection(retired))
    changed = changed or bool(set(config.favorites).intersection(retired))
    changed = changed or bool(set(config.hidden_services).intersection(retired))
    config.active_routes = {sid: route for sid, route in config.active_routes.items() if sid not in retired}
    config.rejected_routes = {sid: ips for sid, ips in config.rejected_routes.items() if sid not in retired}
    config.favorites = [sid for sid in config.favorites if sid not in retired]
    config.hidden_services = [sid for sid in config.hidden_services if sid not in retired]
    if changed:
        storage.save_config()
    return removed


def main():
    parser = argparse.ArgumentParser(description="DNS Switcher - Smart DNS & Hosts Manager")
    parser.add_argument("--hosts-path", type=str, default=None, help="Custom path to hosts file (for testing/mocking)")
    parser.add_argument("--data-dir", type=str, default=None, help="Custom data directory")
    parser.add_argument("--minimized", action="store_true", help="Start minimized to tray")
    parser.add_argument('--diagnose', action='store_true', help='Read-only Canva/Claude diagnosis')
    parser.add_argument('--output', default='dns-diagnostics.json')
    args = parser.parse_args()
    if args.diagnose:
        from core.diagnostics import run
        run(args.output, data_dir=args.data_dir)
        return


    # Qt High DPI setup
    QApplication.setHighDpiScaleFactorRoundingPolicy(
        Qt.HighDpiScaleFactorRoundingPolicy.PassThrough
    )

    QApplication.setAttribute(Qt.AA_DontUseNativeDialogs, True)
    app = QApplication(sys.argv)
    app.setApplicationName("DNS Switcher AI+")
    from core.updater import VERSION
    app.setApplicationVersion(VERSION)
    app.setOrganizationName("InternetHelper")
    app.setQuitOnLastWindowClosed(False)

    from core.single_instance import SingleInstance
    instance = SingleInstance()
    if not instance.acquire():
        return
    app.aboutToQuit.connect(instance.close)
    from PySide6.QtGui import QFont, QFontDatabase
    font_file = Path(__file__).parent / "assets/fonts/onest-variable.ttf"
    if font_file.exists():
        font_id = QFontDatabase.addApplicationFont(str(font_file))
        families = QFontDatabase.applicationFontFamilies(font_id)
        if families:
            font = QFont(families[0])
            font.setPixelSize(16)
            app.setFont(font)
    app.setStyle("Fusion")
    from ui.theme import apply_dark_palette
    apply_dark_palette(app)

    # Set Application Icon
    icon_path = Path(__file__).parent / "assets" / "icon.png"
    if icon_path.exists():
        from PySide6.QtGui import QIcon
        app.setWindowIcon(QIcon(str(icon_path)))

    # 1. Initialize Storage
    storage = StorageManager(data_dir=args.data_dir)

    # 2. Initialize HostsManager (with safe user-writable backup dir)
    backup_dir = str(storage.data_dir / "backups")
    hosts_mgr = HostsManager(hosts_path=args.hosts_path, backup_dir=backup_dir)
    try:
        _remove_retired_services(hosts_mgr, storage)
    except (OSError, ValueError) as error:
        from PySide6.QtWidgets import QMessageBox
        QMessageBox.warning(None, 'Очистка старых маршрутов',
                            'Не удалось удалить маршруты исключённых сервисов из hosts: ' + str(error))

    # 3. Initialize ProviderManager
    cache_dir = str(storage.data_dir / "cache")
    provider_mgr = ProviderManager(cache_dir=cache_dir)

    # Apply saved provider enabled states
    for pid, enabled in storage.config.providers_enabled.items():
        provider_mgr.set_provider_enabled(pid, enabled)

    # Restore custom providers
    for cp_data in storage.config.custom_providers:
        try:
            cp = CustomProvider.from_dict(cp_data, cache_dir=cache_dir)
            provider_mgr.add_custom_provider(cp)
        except Exception:
            pass

    # 4. Initialize Catalog
    custom_services = []
    for cs_data in storage.config.custom_services:
        try:
            cs = ServiceDef.from_dict(cs_data)
            custom_services.append(cs)
        except Exception:
            pass

    catalog = Catalog(custom_services=custom_services)

    # Apply favorite states from config
    for service in catalog.list_all():
        catalog.set_favorite(service.id, service.id in storage.config.favorites)

    # 5. Create Main Window
    window = MainWindow(
        catalog=catalog,
        hosts_manager=hosts_mgr,
        provider_manager=provider_mgr,
        storage=storage,
        auto_check=True
    )

    instance.connect_window(window)

    if not args.minimized:
        window.show()

    sys.exit(app.exec())


if __name__ == "__main__":
    main()
