"""Критичные сетевые узлы. Ответ без сессии не доказывает работу аккаунта."""

# Коды относятся только к известным путям без авторизации, а не ко всему сервису.
PROFILES = {
    'githubcopilot': [('api.githubcopilot.com', '/', 'Copilot API', (401, 404, 405))],
    'groq': [('console.groq.com', '/', 'Консоль Groq', (301, 302, 303, 307, 308)),
             ('api.groq.com', '/', 'API Groq', (401, 404))],
    'cerebras': [('cerebras.ai', '/', 'Cerebras', (301, 302, 303, 307, 308)),
                 ('api.cerebras.ai', '/', 'API Cerebras', (401, 404))],
    'sora': [('sora.com', '/', 'Sora', (301, 302, 303, 307, 308))],
    'chatgpt': [
        ('chatgpt.com', '/api/auth/session', 'Сессия ChatGPT', (401,)),
        ('auth.openai.com', '/', 'Вход', (302, 303, 307, 308)),
        ('cdn.oaistatic.com', '/', 'Ресурсы интерфейса', (404,)),
        ('files.oaiusercontent.com', '/', 'Файлы и вложения', (404,)),
    ],
    'gemini': [
        ('gemini.google.com', '/app', 'Приложение Gemini', (302, 303, 307, 308)),
        ('geminiweb-pa.clients6.google.com', '/', 'API Gemini', (401, 404)),
    ],
    'claude': [
        ('claude.ai', '/api/organizations', 'API аккаунта', (401,)),
        ('cdn.claude.ai', '/', 'Ресурсы интерфейса', (404,)),
    ],
    'spotify': [
        ('open.spotify.com', '/', 'Веб-плеер', (302, 307)),
        ('accounts.spotify.com', '/login', 'Вход', (302, 303, 307)),
        ('spclient.wg.spotify.com', '/', 'Воспроизведение', (401, 404)),
    ],
    'elevenlabs': [
        ('elevenlabs.io', '/app', 'Приложение', (302, 307)),
        ('api.elevenlabs.io', '/v1/user', 'API аккаунта', (401,)),
    ],
    'aistudio': [
        ('aistudio.google.com', '/', 'Приложение', (302, 303, 307)),
        ('generativelanguage.googleapis.com', '/v1beta/models', 'API моделей', (401,)),
    ],
}


def checks_for(service):
    if service.id in PROFILES:
        return PROFILES[service.id]
    checks = [(service.primary_domain, service.test_path, 'Приложение', (302, 303, 307, 308))]
    for domain in service.domains:
        if domain != service.primary_domain and domain.startswith(('api.', 'auth.', 'accounts.')):
            checks.append((domain, '/', 'API / вход', (401,)))
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
