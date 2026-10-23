"""Критичные сетевые узлы. Ответ без сессии не доказывает работу аккаунта."""

# Коды относятся только к известным путям без авторизации, а не ко всему сервису.
PROFILES = {
    'githubcopilot': [('api.individual.githubcopilot.com', '/', 'Copilot API', (401, 404, 405))],
    'groq': [('console.groq.com', '/', 'Консоль Groq', (301, 302, 303, 307, 308)),
             ('api.groq.com', '/', 'API Groq', (401, 404))],
    'chatgpt': [
        ('chatgpt.com', '/api/auth/session', 'Сессия ChatGPT', (401,)),
        ('auth.openai.com', '/', 'Вход', (302, 303, 307, 308)),
        ('cdn.oaistatic.com', '/', 'Ресурсы интерфейса', (404,)),
        ('files.oaiusercontent.com', '/', 'Файлы и вложения', (404,)),
    ],
    'gemini': [
        ('gemini.google.com', '/app', 'Приложение Gemini', ()),
        ('geminiweb-pa.clients6.google.com', '/', 'API Gemini', (401, 404)),
        ('geminiweb-pa.clients.google.com', '/', 'API приложения', (401, 404)),
        ('generativelanguage.googleapis.com', '/v1beta/models', 'API моделей', (401,)),
    ],
    'claude': [
        ('claude.ai', '/login', 'Вход в Claude', (301, 302, 303, 307, 308)),
        ('claude.ai', '/api/organizations', 'API аккаунта', (401, 403)),
    ],
    'antigravity': [
        ('daily-cloudcode-pa.googleapis.com', '/', 'Cloud Code API', (401, 403, 404)),
        ('antigravity.google', '/', 'Портал Antigravity', (301, 302, 303, 307, 308)),
    ],
    'grok': [
        ('grok.com', '/', 'Приложение Grok', (301, 302, 303, 307, 308)),
        ('accounts.x.ai', '/sign-in', 'Вход xAI', (301, 302, 303, 307, 308)),
    ],
    'spotify': [
        ('open.spotify.com', '/', 'Веб-плеер', (302, 307)),
        ('accounts.spotify.com', '/login', 'Вход', (302, 303, 307)),
        ('spclient.wg.spotify.com', '/', 'Воспроизведение', (401, 404)),
    ],
    'aistudio': [
        ('aistudio.google.com', '/', 'AI Studio', (301, 302, 303, 307, 308)),
    ],
    'deepl': [
        ('www.deepl.com', '/', 'Переводчик DeepL', (301, 302, 303, 307, 308)),
    ],
    'make': [
        ('www.make.com', '/en', 'Платформа Make', (301, 302, 303, 307, 308)),
    ],
    'adobe': [
        ('www.adobe.io', '/', 'Сервисы Adobe', (301, 302, 303, 307, 308)),
    ],
}


def checks_for(service):
    if service.id in PROFILES:
        return PROFILES[service.id]
    checks = [(service.primary_domain, service.test_path, 'Приложение', (302, 303, 307, 308))]
    from core.catalog import BUILTIN_SERVICES
    if service.id not in {s.id for s in BUILTIN_SERVICES}:
        for domain in service.domains:
            if domain != service.primary_domain and domain.startswith(('api.', 'auth.', 'accounts.')):
                checks.append((domain, '/', 'API / вход', (401,)))
    # Для встроенных сервисов неизвестный API / не является обязательной проверкой.
    return checks


def account_note(service_id):
    if service_id == 'chatgpt':
        return ('В браузере отправьте сообщение и прикрепите файл. Загрузки также используют '
                'динамические поддомены oaiusercontent.com: wildcard-записи hosts не поддерживает. '
                'Если вложение не загрузилось, нажмите «Другой маршрут».')
    if service_id in ('gemini', 'aistudio'):
        return ('Откройте приложение под своим аккаунтом и отправьте запрос с файлом. '
                'Публичная страница Google не подтверждает доступ к Gemini; '
                'регион аккаунта и ограничения подписки DNS не меняет.')
    return 'Откройте сервис, проверьте вход и нужную функцию. Если не работает — «Другой маршрут».'
