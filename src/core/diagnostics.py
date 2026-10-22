"""Прямая диагностика без записи системного hosts и изменения настроек."""
import json
from pathlib import Path
from tempfile import TemporaryDirectory
from concurrent.futures import ThreadPoolExecutor
from datetime import datetime, timezone
from providers.manager import ProviderManager
from core.catalog import Catalog
from core.verifier import ServiceVerifier

def run(output, timeout=8):
    report = {'timestamp': datetime.now(timezone.utc).isoformat(), 'sources': [], 'checks': []}
    with TemporaryDirectory() as cache:
        manager = ProviderManager(cache_dir=cache)
        catalog = Catalog()
        for provider in manager.list_providers():
            if provider.id == 'google-public-dns':
                continue
            # Свежие GeoHide/MALW загружаются отдельно от пользовательского кэша.
            refreshed = provider.update_database() if provider.id.startswith('geohide-') or provider.id == 'malw-dns' else None
            report['sources'].append({'provider': provider.name, 'refreshed': refreshed, 'error': provider.last_error})
            pairs = [(sid, domain) for sid in ('canva', 'claude') for domain in catalog.get_service(sid).domains]
            def discover(pair):
                sid, domain = pair
                candidates = provider.fetch_candidates(domain)
                return sid, domain, list(dict.fromkeys(c.ip for c in candidates))
            with ThreadPoolExecutor(max_workers=4) as pool:
                discovered = list(pool.map(discover, pairs))
            tasks = [(sid, domain, ip) for sid, domain, ips in discovered for ip in ips]
            for sid, domain, ips in discovered:
                if not ips:
                    report['checks'].append({'service': sid, 'provider': provider.name, 'domain': domain, 'ips': [], 'reason': 'Источник не вернул адрес этого домена'})
            def probe(task):
                sid, domain, ip = task
                result = ServiceVerifier.verify_candidate(ip, domain, timeout=timeout)
                stage = result.stage_reached
                return {'service': sid, 'provider': provider.name, 'domain': domain, 'ip': ip,
                        'tcp': 'passed' if stage in ('TLS', 'HTTP') else 'failed',
                        'tls': 'passed' if stage == 'HTTP' else 'failed' if stage == 'TLS' else 'not_attempted',
                        'http': result.http_code, 'status': result.status.value, 'reason': result.details}
            with ThreadPoolExecutor(max_workers=12) as pool:
                report['checks'].extend(pool.map(probe, tasks))
            Path(output).write_text(json.dumps(report, ensure_ascii=False, indent=2), encoding='utf-8')
            print(provider.name + ': done', flush=True)
    return report
