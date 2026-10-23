"""Параллельный подбор с отменой и проверкой критичных узлов сервиса."""
import socket
import time
from datetime import datetime, timedelta
from threading import Event, RLock
from PySide6.QtCore import QThread, Signal, Qt
from core.network import Cancellation, Cancelled, parallel
from core.service_checks import checks_for, account_note
from core.verifier import ServiceVerifier, ServiceStatus, VerificationResult
from providers.base import CandidateIP


class VerificationWorker(QThread):
    progress = Signal(int, int, str)
    service_result = Signal(str, object, str)
    candidates_ready = Signal(str, list)
    finished_batch = Signal(dict)
    error_occurred = Signal(str)

    def __init__(self, services, hosts_manager, provider_manager, storage,
                 auto_fix=False, parent=None, forced=None, rotate=False, prefer_provider_order=False):
        super().__init__(parent)
        self.services, self.hosts_manager = services, hosts_manager
        self.provider_manager, self.storage = provider_manager, storage
        self.auto_fix, self.forced = auto_fix, forced
        self.rotate = rotate
        self.prefer_provider_order = prefer_provider_order
        self.cancellation = Cancellation()
        self._is_cancelled = False
        self._domain_pools = {}
        self._detail_rows = {}
        self._details_lock = RLock()

    def cancel(self):
        self._is_cancelled = True
        self.cancellation.cancel()

    def _probe(self, ip, domain, path='/', accepted_codes=(), provider_name='current', direct=False):
        self.cancellation.check()
        result = ServiceVerifier.verify_candidate(ip, domain, path=path, timeout=6,
            cancellation=self.cancellation, accepted_codes=accepted_codes,
            redirect_resolver=lambda host: [c.ip for c in (
                self.provider_manager.get_direct_candidates(host, self.cancellation) if direct
                else self.provider_manager.get_candidates(host, self.cancellation))])
        import json
        from pathlib import Path
        from core.hosts_manager import _HOSTS_LOCK
        record = dict(result.to_dict(), provider=provider_name,
                      redirect_attempts=getattr(result, 'redirect_attempts', []),
                      tcp='passed' if result.stage_reached in ('TLS', 'HTTP') else 'failed',
                      tls='passed' if result.stage_reached == 'HTTP' else 'failed' if result.stage_reached == 'TLS' else 'not_attempted')
        try:
            with _HOSTS_LOCK:
                folder = self.storage.data_dir / 'diagnostics'
                folder.mkdir(exist_ok=True)
                with (folder / 'routes.jsonl').open('a', encoding='utf-8') as stream:
                    stream.write(json.dumps(record, ensure_ascii=False) + '\n')
        except OSError:
            pass
        return result

    def _provider_rank(self, provider_id):
        provider = self.provider_manager.get_provider(provider_id)
        return (0 if provider_id.startswith('geohide-') else 2 if provider_id == 'google-public-dns' else 1,
                -(provider.priority if provider else 0))

    def run(self):
        summary = dict(ok=0, fixed=0, failed=0, total=0, cancelled=False)
        acquired = False
        try:
            while not acquired:
                self.cancellation.check()
                acquired = self.provider_manager.operation_lock.acquire(timeout=.05)
            for idx, service in enumerate(self.services):
                self.cancellation.check()
                if service.id in self.storage.config.hidden_services:
                    continue
                self.progress.emit(idx + 1, len(self.services), service.name)
                self._check_service(service, summary)
                summary['total'] += 1
        except Cancelled:
            pass
        except Exception as error:
            self.error_occurred.emit(str(error))
        finally:
            self.cancellation.cancel()
            if acquired:
                self.provider_manager.operation_lock.release()
            summary['cancelled'] = self._is_cancelled
            self.finished_batch.emit(summary)

    def _resolve(self, domain):
        try:
            return list(dict.fromkeys(item[4][0] for item in socket.getaddrinfo(
                domain, 443, type=socket.SOCK_STREAM)))[:2]
        except OSError:
            return []

    def _test_pool(self, candidates, domain, path, codes, sid, excluded=()):
        # Бюджет зависит от числа волн; каждый IP получает собственный таймаут.
        from threading import Lock
        lock = Lock()
        count = [0]
        def test(c):
            result = self._probe(c.ip, domain, path, codes, provider_name=c.provider_name, direct=(c.provider_id == 'direct'))
            with lock:
                count[0] += 1
                self.progress.emit(0, len(self.services),
                    f'{domain}: проверено {count[0]}, осталось {len(candidates)-count[0]}, пропущено 0')
            return result
        results = parallel(candidates, test, self.cancellation,
                           timeout=None, limit=8)
        rows = []
        for c, result in zip(candidates, results):
            sources = getattr(c, 'sources', [dict(id=c.provider_id, name=c.provider_name)])
            cache_info = [x for x in self.provider_manager.discovery.get(domain, [])
                          if x['provider'] in [s['name'] for s in sources]]
            rows.append(dict(domain=domain, ip=c.ip, provider_id=c.provider_id,
                provider_name=', '.join(source['name'] for source in sources), sources=sources,
                cache_info=cache_info,
                status=result.status.value if result else 'UNKNOWN',
                category=getattr(result, 'final_category', result.category) if result else 'SKIPPED',
                latency_ms=result.latency_ms if result else 0,
                details=result.details if result else 'Не проверен: бюджет или ошибка задачи',
                routable=bool(result and result.is_routable),
                browser_required=bool(result and result.is_browser_challenge)))
        redirect_rows = {}
        for result in results:
            for attempt in getattr(result, 'redirect_attempts', []):
                name, ip = attempt['domain'], attempt['ip']
                source_names = [x['provider'] for x in self.provider_manager.discovery.get(name, [])
                                if ip in x['ips']]
                row = dict(attempt, provider_name=', '.join(source_names) or 'Цель редиректа',
                           routable=attempt['status'] == 'OK',
                           browser_required=attempt['category'] == 'CLOUDFLARE_CHALLENGE')
                key = (name, ip)
                if key not in redirect_rows or row['routable']:
                    redirect_rows[key] = row
        rows += list(redirect_rows.values())
        rows += [dict(domain=domain, ip=c.ip, provider_name=c.provider_name, status='UNKNOWN',
                      category='SKIPPED', details='Текущий или ранее отклонённый IP исключён из этого подбора',
                      routable=False) for c in excluded]
        rows += [dict(domain=domain, ip=ip, provider_name=x['provider'], status='UNKNOWN',
                      category='SKIPPED', details=x['filter_reason'], routable=False)
                 for x in self.provider_manager.discovery.get(domain, []) for ip in x.get('excluded_ips', [])]
        rows += [dict(domain=domain, ip='', provider_name=x['provider'], status='UNKNOWN',
                      category=x['state'], details=x.get('error') or 'Нет IP для этого имени', routable=False)
                 for x in self.provider_manager.discovery.get(domain, []) if not x['ips']]
        with self._details_lock:
            self._detail_rows.setdefault(sid, {})[domain] = rows
            self.candidates_ready.emit(sid, [row for group in self._detail_rows[sid].values() for row in group])
        return results

    DIRECT_PREFERRED = {'camel', 'make', 'trae', 'hume', 'adobe', 'framer'}
    DIRECT_EXCLUDED = {'gemini', 'aistudio', 'stitch', 'githubcopilot'}

    def _domain_route(self, check, selected, entries, current=False, required=True, service_id=None, direct=False):
        domain, path, label, codes = check
        self.cancellation.check()
        if direct:
            candidates = self.provider_manager.get_direct_candidates(domain, self.cancellation)
        elif current:
            candidates = [CandidateIP(ip, 'current', 'Из hosts') for ip in entries.get(domain, []) or self._resolve(domain)]
        else:
            candidates = self.provider_manager.get_candidates(domain, self.cancellation)
        key = (domain, path, tuple(c.ip for c in candidates), tuple(codes))
        if key not in self._domain_pools:
            self._domain_pools[key] = self._test_pool(candidates, domain, path, codes, service_id)
        results = self._domain_pools[key]
        good = min((x for x in results if x and x.is_routable), key=lambda x: (x.ip != selected.ip, x.latency_ms), default=None)
        if good is None and not direct:
            good = min((x for x in results if x and x.is_browser_challenge), key=lambda x: (x.ip != selected.ip, x.latency_ms), default=None)
        names = {c.ip: c.provider_name for c in candidates}
        last = good or next((x for x in results if x), None)
        return dict(domain=domain, label=label, ok=bool(good), ip=good.ip if good else '',
                    provider=names.get(good.ip, '') if good else '',
                    details=last.details if last else 'Источник не поддерживает домен / не проверено',
                    challenge=bool(good and good.is_browser_challenge),
                    redirects=getattr(good, 'redirect_checks', []) if good else [])

    def _try_direct_route(self, service, checks, primary, entries, current_ip, summary):
        if self.forced or self.rotate or service.id in self.DIRECT_EXCLUDED:
            return False
        direct_candidates = self.provider_manager.get_direct_candidates(primary[0], self.cancellation)
        if not direct_candidates:
            return False
        direct_results = self._test_pool(direct_candidates, primary[0], primary[1], primary[3], service.id)
        good_pair = next(((c, p) for c, p in zip(direct_candidates, direct_results) if p and p.is_routable), None)
        if not good_pair:
            return False
        candidate, probe = good_pair
        other_checks = [check for check in checks if check != primary]
        reports = parallel(other_checks, lambda check: self._domain_route(
            check, candidate, entries, direct=True, service_id=service.id),
            self.cancellation, timeout=None, limit=8)
        reports = [r or dict(domain=c[0], label=c[2], ok=False, details='Тайм-аут')
                   for c, r in zip(other_checks, reports)]
        if not all(r['ok'] for r in reports):
            return False
        reports.insert(0, dict(domain=service.primary_domain, label=primary[2], ok=True,
            ip=candidate.ip, provider='Прямое подключение', details=probe.details,
            challenge=False, redirects=getattr(probe, 'redirect_checks', [])))
        if self.auto_fix:
            self.hosts_manager.remove_service_entries(service.name, service.domains)
        probe.ip = ''
        probe.status = ServiceStatus.OK
        probe.applied = self.auto_fix
        probe.is_current = not self.auto_fix
        probe.confirmable = True
        probe.browser_required = False
        probe.route_message = 'Работает напрямую'
        probe.outcome = ('Старые записи hosts удалены → Прямое подключение'
                         if (self.auto_fix and current_ip)
                         else 'Прямое подключение подтверждено (записи в hosts не требуются)')
        probe.details = '\n'.join(
            f"{r['label']}: HTTPS доступен · Прямое подключение ({r['ip']})" for r in reports
        ) + '\n' + account_note(service.id)
        if self.auto_fix or not current_ip:
            self.storage.set_active_route(service.id, '', 'Прямое подключение', 'OK', probe.latency_ms)
            route = self.storage.get_active_route(service.id)
            route.update(direct=True, domain_ips={}, details=probe.details,
                         checks=reports, confirmable=True, confirmed=False)
            self.storage.save_config()
        self.service_result.emit(service.id, probe, 'Прямое подключение')
        summary['fixed' if (self.auto_fix and current_ip) else 'ok'] += 1
        return True

    def _check_service(self, service, summary):
        if service.routing_mode != 'geo':
            result = VerificationResult('', service.primary_domain, ServiceStatus.PARTIAL, 0, service.description)
            result.applied = False
            result.confirmable = False
            self.service_result.emit(service.id, result, '')
            summary['failed'] += 1
            return
        entries = self.hosts_manager.get_service_current_ips(service.domains)
        current_ips = entries.get(service.primary_domain, [])
        current_ip = current_ips[0] if current_ips else ''
        checks = checks_for(service)
        primary = next((c for c in checks if c[0] == service.primary_domain),
                       (service.primary_domain, service.test_path, 'Приложение', ()))
        if not self.rotate and not self.forced:
            ips = current_ips
            if not ips and not self.auto_fix:
                resolved = parallel([service.primary_domain], self._resolve,
                                    self.cancellation, timeout=1.5)[0]
                ips = resolved or []
            probes = parallel(ips[:2], lambda ip: self._probe(ip, primary[0], primary[1], primary[3]),
                              self.cancellation, timeout=7)
            good = next((probe for probe in probes if probe and probe.is_routable), None)
            if good:
                selected_current = CandidateIP(good.ip, 'current', 'Из hosts')
                critical = parallel([c for c in checks if c[0] != service.primary_domain],
                    lambda c: self._domain_route(c, selected_current, entries, current=True),
                    self.cancellation, timeout=12, limit=8)
                if not all(row and row['ok'] for row in critical):
                    good = None
            if good:
                active = dict(self.storage.get_active_route(service.id) or {})
                provider_name = active.get('provider_name') if active.get('ip') == good.ip else None
                if not provider_name:
                    for provider in self.provider_manager.list_providers():
                        cached = getattr(provider, '_domain_ips', getattr(provider, '_ip_cache', {}))
                        if good.ip in cached.get(service.primary_domain, []):
                            provider_name = provider.name
                            break
                provider_name = provider_name or ('Из hosts' if current_ips else 'Системный DNS')
                good.status = ServiceStatus.OK
                good.applied = False
                good.is_current = True
                good.confirmable = True
                good.details = 'Сетевые узлы отвечают; работа аккаунта без авторизации не подтверждена. ' + good.details
                if current_ips:
                    active.update(ip=good.ip, provider_name=provider_name, status='OK',
                        latency_ms=good.latency_ms, network_ok=True, confirmable=True,
                        checked_at=time.time(), details=good.details)
                    self.storage.config.active_routes[service.id] = active
                    self.storage.save_config()
                self.service_result.emit(service.id, good, provider_name)
                summary['ok'] += 1
                return
            if not self.auto_fix:
                result = VerificationResult(current_ip, service.primary_domain, ServiceStatus.UNKNOWN,
                    0, 'Автоматическая проверка не дала ответа. Текущие адреса не изменены.')
                result.is_current = True
                result.confirmable = bool(current_ip)
                self.service_result.emit(service.id, result, 'Из hosts' if current_ip else 'Системный DNS')
                summary['failed'] += 1
                return
        if service.id in self.DIRECT_PREFERRED and self.auto_fix and not self.rotate and not self.forced:
            if self._try_direct_route(service, checks, primary, entries, current_ip, summary):
                return
        rejected = set(self.storage.config.rejected_routes.get(service.id, []))
        # Подбор всегда перебирает провайдеров: рабочая витрина не доказывает работу приложения.
        if self.forced:
            provider_id = next((p.id for p in self.provider_manager.list_providers()
                                if p.name == self.forced[1]), 'manual')
            candidates = [CandidateIP(self.forced[0], provider_id, self.forced[1])]
        elif not self.auto_fix:
            resolved = parallel([service.primary_domain], self._resolve,
                                self.cancellation, timeout=1.5)[0] if not current_ips else current_ips
            candidates = [CandidateIP(ip, 'current', 'Из hosts' if current_ip else 'Системный DNS')
                          for ip in (resolved or [])]
        else:
            candidates = self.provider_manager.get_candidates(service.primary_domain, self.cancellation)
        pool = candidates
        candidates = pool if self.forced else [c for c in pool if c.ip not in rejected]
        if pool and not candidates and self.auto_fix and not self.forced:
            # Закончен круг: ранее пропущенные маршруты снова доступны.
            self.storage.config.rejected_routes.pop(service.id, None)
            self.storage.save_config()
            candidates = pool

        if self.rotate and not self.forced:
            # Неисправные непосещённые IP не должны навсегда блокировать новый круг.
            candidates = [c for c in pool if c.ip != current_ip]

        self.progress.emit(self.services.index(service) + 1, len(self.services),
                           f'{service.name}: {len(candidates)} IP, всего в пуле {len(pool)}')
        results = self._test_pool(candidates, primary[0], primary[1], primary[3], service.id,
                                  excluded=[c for c in pool if c not in candidates])
        checked = []
        viable = []
        for candidate, probe in zip(candidates, results):
            checked.append(dict(ip=candidate.ip, provider_id=candidate.provider_id, provider_name=candidate.provider_name,
                status=probe.status.value if probe else 'UNKNOWN', latency_ms=probe.latency_ms if probe else 0,
                details=probe.details if probe else 'Тайм-аут', routable=bool(probe and probe.is_routable),
                browser_required=bool(probe and probe.is_browser_challenge)))
            if probe and (probe.is_routable or probe.is_browser_challenge):
                viable.append((candidate, probe))
        # Работоспособность проверяем первой; задержка сортирует подходящие кандидаты.
        if self.prefer_provider_order:
            viable.sort(key=lambda item: (not item[1].is_routable,))
        else:
            viable.sort(key=lambda item: (not item[1].is_routable,
                                          item[0].ip in rejected,
                                          self._provider_rank(item[0].provider_id),
                                          item[1].latency_ms))
        selected = best = report = None
        failure_report = []
        for candidate, probe in viable:
            self.cancellation.check()
            self.progress.emit(self.services.index(service) + 1, len(self.services),
                               service.name + ': вход, API, файлы — ' + candidate.provider_name)
            current = candidate.provider_id == 'current'
            other_checks = [check for check in checks if check != primary]
            reports = parallel(other_checks, lambda check: self._domain_route(check, candidate, entries, current,
                               service_id=service.id),
                               self.cancellation, timeout=None, limit=8)
            reports = [r or dict(domain=c[0], label=c[2], ok=False, details='Тайм-аут')
                       for c, r in zip(other_checks, reports)]
            reports.insert(0, dict(domain=service.primary_domain, label=primary[2], ok=True,
                ip=candidate.ip, provider=candidate.provider_name, details=probe.details,
                challenge=probe.is_browser_challenge, redirects=getattr(probe, 'redirect_checks', [])))
            failure_report = reports
            if all(r['ok'] for r in reports):
                selected, best, report = candidate, probe, reports
                break
        self.cancellation.check()
        if selected is None:
            if self._try_direct_route(service, checks, primary, entries, current_ip, summary):
                return
            challenges = sum(bool(probe and probe.is_browser_challenge) for probe in results)
            details = ('Других подходящих маршрутов сейчас нет. Текущий адрес сохранён.' if self.rotate else
                       'Проверенные маршруты не отвечают на нужные запросы. Текущий адрес сохранён.')
            if challenges:
                details = (f'{challenges} IP отвечают Cloudflare challenge. Автоматический GET не подтверждает '
                           'доступ в браузере; эти IP не признаны неработающими. Текущий адрес сохранён.')
            details += '\n' + '\n'.join(dict.fromkeys(
                probe.ip + ': ' + probe.details for probe in results if probe))
            if rejected:
                details += ' Ранее отклонённые адреса пропущены; сброс доступен в деталях.'
            if failure_report:
                details += '\n' + '\n'.join(r['label'] + ' (' + r['domain'] + '): ' +
                    ('HTTPS доступен' if r['ok'] else r['details']) for r in failure_report)
            result = VerificationResult(current_ip, service.primary_domain, ServiceStatus.UNKNOWN, 0, details)
            result.applied = False
            result.confirmable = bool(current_ip)
            result.alternative_failed = self.rotate
            result.route_message = 'Других маршрутов нет' if self.rotate else 'Подбор без изменений'
            if challenges:
                result.route_message = 'Cloudflare: доступ не подтверждён'
                result.browser_required = True
            result.pool_size = len(pool)
            result.checked_count = sum(probe is not None for probe in results)
            result.skipped_count = len(pool) - result.checked_count
            result.remaining_count = 0
            result.outcome = f'IP не изменён · проверено {sum(probe is not None for probe in results)} из {len(pool)} адресов'
            self.service_result.emit(service.id, result, '')
            summary['failed'] += 1
            return

        mappings = {r['domain']: r['ip'] for r in report}
        for row in report:
            for target in row.get('redirects', []):
                if target['status'] == 'OK': mappings[target['domain']] = target['ip']
        if self.rotate and selected.ip in rejected:
            self.storage.config.rejected_routes[service.id] = [current_ip] if current_ip else []
            self.storage.save_config()
        if self.auto_fix:
            extra = [d for d in service.domains if d not in mappings]
            # Базы провайдеров могут пополняться новыми точными именами хранилищ файлов.
            if service.id == 'chatgpt':
                provider = self.provider_manager.get_provider(selected.provider_id)
                known = getattr(provider, 'supported_domains', []) if provider else []
                extra += [d for d in known if d.endswith(('.oaiusercontent.com', '.oaistatic.com'))
                          and d not in mappings and d not in extra]
            extra.sort(key=lambda d: (0 if 'oaiusercontent.com' in d else
                1 if any(part in d for part in ('cdn.', 'static', 'assets.', 'auth.', 'api.')) else 2, d))
            self.progress.emit(self.services.index(service) + 1, len(self.services), service.name + ': ресурсы и CDN')
            extras = parallel(extra, lambda d: self._domain_route((d, '/', d, (400, 401, 403, 404, 405, 421, 301, 302, 303, 307, 308)),
                selected, entries, required=False, service_id=service.id), self.cancellation,
                timeout=None, limit=8)
            for row in extras:
                if row and row['ok']:
                    mappings[row['domain']] = row['ip']
                    for target in row.get('redirects', []):
                        if target['status'] == 'OK': mappings[target['domain']] = target['ip']
            report += [row or dict(domain=domain, label=domain, ok=False,
                                   details='Не подтверждён за отведённое время')
                       for domain, row in zip(extra, extras)]
            self.cancellation.check()
            if service.id in self.storage.config.hidden_services:
                return
            self.progress.emit(self.services.index(service) + 1, len(self.services),
                               service.name + ': запись hosts · при запросе подтвердите UAC')
            self.hosts_manager.update_multiple_services([dict(service_name=service.name,
                target_ip=selected.ip, domains=list(mappings), domain_ips=mappings,
                provider_name=selected.provider_name, replace=True)])
        old = self.storage.get_active_route(service.id) or {}
        confirmed = bool(old.get('confirmed') and old.get('domain_ips') == mappings and
                         old.get('ip') == selected.ip)
        conflicts = self.hosts_manager.get_conflicts(mappings)
        browser_required = any(row.get('challenge') for row in report)
        best.status = ServiceStatus.PARTIAL if browser_required else ServiceStatus.OK
        best.applied = self.auto_fix
        best.is_current = not self.auto_fix
        best.confirmable = (self.auto_fix or bool(current_ip)) and not bool(conflicts) and not browser_required
        best.pool_size = len(pool)
        best.checked_count = sum(probe is not None for probe in results)
        best.skipped_count = len(pool) - best.checked_count
        best.remaining_count = 0
        best.browser_required = browser_required
        best.route_message = 'Нужна браузерная проверка' if browser_required else ''
        best.outcome = (f"{current_ip or 'Системный DNS'} → {selected.ip}" if self.auto_fix else selected.ip)
        best.outcome += f' · проверено {sum(probe is not None for probe in results)} из {len(pool)} адресов'
        best.details = '\n'.join(r['label'] + ': ' + ('Cloudflare: доступ к функциям не подтверждён'
            if r.get('challenge') else 'HTTPS доступен' if r['ok'] else r['details']) +
            ' · ' + r.get('provider', selected.provider_name) for r in report)
        best.details += '\n' + account_note(service.id)
        if conflicts:
            best.details += '\nКонфликт с другими строками hosts: ' + ', '.join(conflicts) + '. Приоритет IP не гарантирован.'
        if self.auto_fix or current_ip:
            self.storage.set_active_route(service.id, selected.ip, selected.provider_name,
                                          best.status.value, best.latency_ms)
            route = self.storage.get_active_route(service.id)
            route.update(domain_ips=mappings, details=best.details,
                         checks=report, confirmable=best.confirmable, confirmed=confirmed and not browser_required)
            self.storage.save_config()
        self.service_result.emit(service.id, best, selected.provider_name)
        summary['fixed' if self.auto_fix else 'ok'] += 1


class DatabaseUpdateWorker(QThread):
    completed = Signal(dict)

    def __init__(self, provider_manager, storage, parent=None):
        super().__init__(parent)
        self.provider_manager, self.storage = provider_manager, storage
        self.cancellation = Cancellation()

    def cancel(self):
        self.cancellation.cancel()

    def run(self):
        try:
            self._update()
        except Cancelled:
            self.completed.emit({})
        except Exception:
            self.completed.emit({p.id: False for p in self.provider_manager.list_providers() if p.enabled})

    def _update(self):
        acquired = False
        try:
            while not acquired:
                self.cancellation.check()
                acquired = self.provider_manager.operation_lock.acquire(timeout=.05)
            results = self.provider_manager.update_all_databases(self.cancellation)
            if any(results.values()):
                self.storage.config.last_db_update = datetime.now().strftime('%Y-%m-%d %H:%M:%S')
                self.storage.save_config()
        finally:
            if acquired:
                self.provider_manager.operation_lock.release()
        self.completed.emit(results)


class BackgroundMonitorThread(QThread):
    service_alert = Signal(str, str, str)

    def __init__(self, catalog, hosts_manager, provider_manager, storage, parent=None):
        super().__init__(parent)
        self.catalog, self.hosts_manager = catalog, hosts_manager
        self.provider_manager, self.storage = provider_manager, storage
        self._stop = Event()
        self._worker = None
        self._next_check = 0
        self._next_update = 0

    def stop(self):
        self._stop.set()
        if self._worker:
            self._worker.cancel()

    def run(self):
        while not self._stop.is_set():
            try:
                self._tick()
            except Exception as error:
                self.service_alert.emit('Мониторинг', 'Ошибка', str(error))
            self._stop.wait(1)

    def _tick(self):
        config = self.storage.config
        if config.auto_update_db and time.monotonic() >= self._next_update:
            try:
                due = datetime.fromisoformat(config.last_db_update) + timedelta(hours=config.auto_update_interval_hours)
            except ValueError:
                due = datetime.min
            if datetime.now() >= due and self.provider_manager.operation_lock.acquire(blocking=False):
                try:
                    token = Cancellation()
                    token.event = self._stop
                    results = parallel([None], lambda _: self.provider_manager.update_all_databases(),
                                       token, timeout=12)
                    if results[0] and any(results[0].values()):
                        config.last_db_update = datetime.now().strftime('%Y-%m-%d %H:%M:%S')
                        self.storage.save_config()
                except Cancelled:
                    return
                finally:
                    self.provider_manager.operation_lock.release()
            self._next_update = time.monotonic() + 300
        if config.monitoring_enabled and time.monotonic() >= self._next_check and not self._stop.is_set():
            self._worker = VerificationWorker(self.catalog.list_favorites(), self.hosts_manager,
                self.provider_manager, self.storage, config.auto_fix_favorites)
            self._worker.service_result.connect(lambda sid, result, provider:
                self.service_alert.emit(sid, result.status.value, result.details), Qt.DirectConnection)
            if self._stop.is_set():
                self._worker.cancel()
            self._worker.run()
            self._worker = None
            self._next_check = time.monotonic() + max(60, config.monitor_interval_minutes * 60)
