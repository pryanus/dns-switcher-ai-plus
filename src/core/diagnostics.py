"""Тот же подбор Canva/Claude на временном hosts, без изменения настроек пользователя."""
import json
import os
from pathlib import Path
from tempfile import TemporaryDirectory
from datetime import datetime, timezone
from PySide6.QtCore import QCoreApplication, Qt
from providers.manager import ProviderManager
from providers.custom import CustomProvider
from core.catalog import Catalog
from core.monitor import VerificationWorker
from core.hosts_manager import HostsManager
from core.storage import StorageManager


def run(output, data_dir=None):
    app = QCoreApplication.instance() or QCoreApplication([])
    config_path = Path(data_dir or Path(os.environ.get('APPDATA', Path.home())) / 'DNS-Switcher') / 'config.json'
    config = json.loads(config_path.read_text(encoding='utf-8')) if config_path.exists() else {}
    report = dict(timestamp=datetime.now(timezone.utc).isoformat(), sources=[], services=[], errors=[])
    with TemporaryDirectory() as folder:
        root = Path(folder)
        manager = ProviderManager(str(root / 'cache'))
        for pid, enabled in config.get('providers_enabled', {}).items():
            manager.set_provider_enabled(pid, enabled)
        for definition in config.get('custom_providers', []):
            try:
                manager.add_custom_provider(CustomProvider.from_dict(definition, str(root / 'cache')))
            except (ValueError, KeyError) as error:
                report['errors'].append(str(error))
        updates = manager.update_all_databases()
        report['sources'] = [dict(provider=p.name, enabled=p.enabled, updated=updates.get(p.id),
                                  last_updated=p.last_updated, error=p.last_error)
                             for p in manager.list_providers()]
        for sid in ('canva', 'claude'):
            service = Catalog().get_service(sid)
            storage = StorageManager(str(root / sid))
            hosts = root / (sid + '-hosts')
            hosts.write_text('127.0.0.1 localhost\n', encoding='utf-8')
            worker = VerificationWorker([service], HostsManager(str(hosts), str(root / 'backups')),
                                        manager, storage, auto_fix=True)
            results = []
            worker.service_result.connect(lambda name, result, provider: results.append(result), Qt.DirectConnection)
            worker.error_occurred.connect(report['errors'].append, Qt.DirectConnection)
            worker.run()
            report['services'].append(dict(service=sid, result=results[0].to_dict() if results else None,
                candidates=worker._detail_rows.get(sid, {}), discovery=dict(manager.discovery),
                checked=getattr(results[0], 'checked_count', 0) if results else 0,
                skipped=getattr(results[0], 'skipped_count', 0) if results else 0))
            Path(output).write_text(json.dumps(report, ensure_ascii=False, indent=2), encoding='utf-8')
    return report
