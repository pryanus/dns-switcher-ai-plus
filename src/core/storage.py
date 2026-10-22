"""
Storage: Local persistent configuration, history, active routes, and cached states.
"""

import json
import os
import sys
import tempfile
from threading import RLock
from pathlib import Path
from typing import Dict, List, Optional, Any


class AppConfig:
    def __init__(
        self,
        theme: str = "dark",
        favorites: Optional[List[str]] = None,
        providers_enabled: Optional[Dict[str, bool]] = None,
        auto_update_db: bool = False,
        auto_update_interval_hours: int = 24,
        monitoring_enabled: bool = False,
        auto_fix_favorites: bool = False,
        monitor_interval_minutes: int = 30,
        minimize_to_tray: bool = True,
        autostart: bool = False,
        last_db_update: str = "",
        custom_services: Optional[List[Dict]] = None,
        custom_providers: Optional[List[Dict]] = None,
        active_routes: Optional[Dict[str, Dict]] = None,
        catalog_revision: int = 4,
        hidden_services=None,
        rejected_routes=None
    ):
        self.catalog_revision = catalog_revision
        self.hidden_services = list(hidden_services or [])
        self.rejected_routes = rejected_routes or {}
        self.theme = theme
        self.favorites = list(favorites) if favorites is not None else ["spotify", "chatgpt", "gemini", "claude"]
        self.providers_enabled = providers_enabled or {
            "geohide-ru": True,
            "geohide-eu": True,
            "geohide-us": True,
            "malw-dns": True,
            "zapret-dns": True,
            "dns-ai": True
        }
        self.auto_update_db = auto_update_db
        self.auto_update_interval_hours = auto_update_interval_hours
        self.monitoring_enabled = monitoring_enabled
        self.auto_fix_favorites = auto_fix_favorites
        self.monitor_interval_minutes = monitor_interval_minutes
        self.minimize_to_tray = minimize_to_tray
        self.autostart = autostart
        self.last_db_update = last_db_update
        self.custom_services = custom_services or []
        self.custom_providers = custom_providers or []
        self.active_routes = active_routes or {}

    def to_dict(self) -> Dict[str, Any]:
        return {
            "catalog_revision": self.catalog_revision,
            "hidden_services": self.hidden_services,
            "rejected_routes": self.rejected_routes,
            "theme": self.theme,
            "favorites": self.favorites,
            "providers_enabled": self.providers_enabled,
            "auto_update_db": self.auto_update_db,
            "auto_update_interval_hours": self.auto_update_interval_hours,
            "monitoring_enabled": self.monitoring_enabled,
            "auto_fix_favorites": self.auto_fix_favorites,
            "monitor_interval_minutes": self.monitor_interval_minutes,
            "minimize_to_tray": self.minimize_to_tray,
            "autostart": self.autostart,
            "last_db_update": self.last_db_update,
            "custom_services": self.custom_services,
            "custom_providers": self.custom_providers,
            "active_routes": self.active_routes,
        }

    @classmethod
    def from_dict(cls, data: Dict[str, Any]) -> "AppConfig":
        return cls(
            catalog_revision=data.get("catalog_revision", 1),
            hidden_services=data.get("hidden_services", []),
            rejected_routes=data.get("rejected_routes", {}),
            theme=data.get("theme", "dark"),
            favorites=data.get("favorites", ["spotify", "chatgpt", "gemini", "claude"]),
            providers_enabled=data.get("providers_enabled", {}),
            auto_update_db=data.get("auto_update_db", False),
            auto_update_interval_hours=data.get("auto_update_interval_hours", 24),
            monitoring_enabled=data.get("monitoring_enabled", False),
            auto_fix_favorites=data.get("auto_fix_favorites", False),
            monitor_interval_minutes=data.get("monitor_interval_minutes", 30),
            minimize_to_tray=data.get("minimize_to_tray", True),
            autostart=data.get("autostart", False),
            last_db_update=data.get("last_db_update", ""),
            custom_services=data.get("custom_services", []),
            custom_providers=data.get("custom_providers", []),
            active_routes=data.get("active_routes", {}),
        )


class StorageManager:
    def __init__(self, data_dir: Optional[str] = None):
        self._lock = RLock()
        if data_dir:
            self.data_dir = Path(data_dir)
        else:
            # Portable preference: if local data folder exists next to script/exe, use it
            app_dir = Path(sys.executable).parent if getattr(sys, "frozen", False) else Path(__file__).parent.parent.parent
            local_data = app_dir / "data"
            if local_data.exists():
                self.data_dir = local_data
            else:
                # Fallback to APPDATA
                appdata = os.environ.get("APPDATA", str(Path.home()))
                self.data_dir = Path(appdata) / "DNS-Switcher"

        self.data_dir.mkdir(parents=True, exist_ok=True)
        self.config_path = self.data_dir / "config.json"
        self.config: AppConfig = self.load_config()
        if self.config.catalog_revision < 3:
            self.config.favorites = ["spotify", "chatgpt", "gemini", "claude"]
            self.config.theme = "dark"
            self.config.catalog_revision = 3
            self.config.minimize_to_tray = False
            for route in self.config.active_routes.values():
                route.update(status='UNKNOWN', confirmed=False, confirmable=False,
                             details='Маршрут из предыдущей версии. Нажмите «Подобрать» для проверки входа, API и файлов.')
            self.save_config()

        if self.config.catalog_revision < 4:
            self.config.catalog_revision = 4
            self.config.minimize_to_tray = True
            self.save_config()

    def load_config(self) -> AppConfig:
        if self.config_path.exists():
            try:
                data = json.loads(self.config_path.read_text(encoding="utf-8"))
                return AppConfig.from_dict(data)
            except Exception:
                pass
        return AppConfig()

    def save_config(self) -> None:
        with self._lock:
            fd, temporary = tempfile.mkstemp(dir=self.data_dir, suffix=".json.tmp")
            try:
                with os.fdopen(fd, "w", encoding="utf-8") as stream:
                    json.dump(self.config.to_dict(), stream, indent=2, ensure_ascii=False)
                    stream.flush()
                    os.fsync(stream.fileno())
                os.replace(temporary, self.config_path)
            finally:
                if os.path.exists(temporary):
                    os.unlink(temporary)

    def get_active_route(self, service_id: str) -> Optional[Dict]:
        return self.config.active_routes.get(service_id.lower())

    def set_active_route(
        self,
        service_id: str,
        ip: str,
        provider_name: str,
        status: str,
        latency_ms: int
    ) -> None:
        self.config.active_routes[service_id.lower()] = {
            "ip": ip,
            "provider_name": provider_name,
            "status": status,
            "latency_ms": latency_ms,
            "timestamp": os.path.getmtime(self.config_path) if self.config_path.exists() else 0
        }
        self.save_config()

    def remove_active_route(self, service_id: str) -> None:
        s_id = service_id.lower()
        if s_id in self.config.active_routes:
            del self.config.active_routes[s_id]
            self.save_config()
