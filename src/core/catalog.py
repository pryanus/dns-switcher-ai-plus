"""
Catalog: Built-in service directory with domain sets, categories, and custom service registry.
"""

from typing import Dict, List, Optional, Set


class ServiceDef:
    def __init__(
        self,
        id: str,
        name: str,
        category: str,
        primary_domain: str,
        domains: List[str],
        test_path: str = "/",
        is_favorite: bool = False,
        is_custom: bool = False,
        description: str = "",
        icon: str = "globe",
        routing_mode: str = "geo"
    ):
        self.id = id.lower().strip()
        self.name = name.strip()
        self.category = category.strip()
        self.primary_domain = primary_domain.lower().strip()
        self.domains = sorted(list({d.lower().strip() for d in domains if d.strip()}))
        if self.primary_domain not in self.domains:
            self.domains.insert(0, self.primary_domain)
        self.test_path = test_path
        self.is_favorite = is_favorite
        self.is_custom = is_custom
        self.description = description
        self.icon = icon
        self.routing_mode = routing_mode

    def to_dict(self) -> Dict:
        return {
            "id": self.id,
            "name": self.name,
            "category": self.category,
            "primary_domain": self.primary_domain,
            "domains": self.domains,
            "test_path": self.test_path,
            "is_favorite": self.is_favorite,
            "is_custom": self.is_custom,
            "description": self.description,
            "icon": self.icon,
            "routing_mode": self.routing_mode,
        }

    @classmethod
    def from_dict(cls, data: Dict) -> "ServiceDef":
        return cls(
            id=data["id"],
            name=data["name"],
            category=data.get("category", "Другие"),
            primary_domain=data["primary_domain"],
            domains=data.get("domains", [data["primary_domain"]]),
            test_path=data.get("test_path", "/"),
            is_favorite=data.get("is_favorite", False),
            is_custom=data.get("is_custom", True),
            description=data.get("description", ""),
            icon=data.get("icon", "globe"),
            routing_mode=data.get("routing_mode", "geo")
        )

    def matches_query(self, query: str) -> bool:
        q = query.lower().strip()
        if not q:
            return True
        if q in self.name.lower() or q in self.id or q in self.category.lower():
            return True
        return any(q in d for d in self.domains)

    def __repr__(self):
        return f"<ServiceDef {self.name} ({self.id}) - {len(self.domains)} domains>"


# AI и повседневные сервисы. Источники: GeoHide, Zapret DNS, MALW DNS, DNS-AI.
RETIRED_SERVICES = {
    'twitch': 'Twitch',
    'canva': 'Canva',
    'deezer': 'Deezer',
    'sora': 'Sora',
    'elevenlabs': 'ElevenLabs',
    'reve': 'Reve',
    'cerebras': 'Cerebras',
    'genspark': 'Genspark',
    'crunchyroll': 'Crunchyroll',
}

BUILTIN_SERVICES: List[ServiceDef] = [
    ServiceDef.from_dict({'id': 'chatgpt', 'name': 'ChatGPT (OpenAI)', 'category': 'Нейросети', 'primary_domain': 'chatgpt.com', 'domains': ['ab.chatgpt.com', 'android.chat.openai.com', 'api.openai.com', 'auth.openai.com', 'auth0.openai.com', 'bps.openai.com', 'cdn.oaistatic.com', 'cdn.platform.openai.com', 'chat.openai.com', 'chatgpt.com', 'developers.openai.com', 'files.oaiusercontent.com', 'ios.chat.openai.com', 'oaistatic.com', 'oaiusercontent.com', 'openai.com', 'operator.chatgpt.com', 'platform.openai.com', 'sdmntpritalynorth.oaiusercontent.com', 'sdmntprnortheu.oaiusercontent.com', 'sdmntprpolandcentral.oaiusercontent.com', 'sdmntprukwest.oaiusercontent.com', 'tcr9i.chat.openai.com', 'videos.openai.com', 'webrtc.chatgpt.com', 'www.chatgpt.com', 'www.oaistatic.com', 'www.oaiusercontent.com', 'www.openai.com'], 'test_path': '/', 'is_favorite': True, 'is_custom': False, 'description': 'Есть в списках GEO-обхода провайдеров. Подбор проверяет сетевые узлы; нужные функции подтвердите в своём аккаунте.', 'icon': 'sparkles', 'routing_mode': 'geo'}),
    ServiceDef.from_dict({'id': 'gemini', 'name': 'Google Gemini', 'category': 'Нейросети', 'primary_domain': 'gemini.google.com', 'domains': ['alkalimakersuite-pa.clients6.google.com', 'bard.google.com', 'geller-pa.googleapis.com', 'gemini.google', 'gemini.google.com', 'geminiweb-pa.clients.google.com', 'geminiweb-pa.clients6.google.com', 'generativelanguage.googleapis.com', 'people-pa.clients6.google.com', 'proactivebackend-pa.googleapis.com', 'robinfrontend-pa.googleapis.com', 'signaler-pa.clients6.google.com', 'waa-pa.clients6.google.com'], 'test_path': '/', 'is_favorite': True, 'is_custom': False, 'description': 'Есть в списках GEO-обхода провайдеров. Подбор проверяет сетевые узлы; нужные функции подтвердите в своём аккаунте.', 'icon': 'sparkles', 'routing_mode': 'geo'}),
    ServiceDef.from_dict({'id': 'claude', 'name': 'Claude (Anthropic)', 'category': 'Нейросети', 'primary_domain': 'claude.ai', 'domains': ['a-api.anthropic.com', 'a-cdn.anthropic.com', 'a.claude.ai', 'anthropic.com', 'api.anthropic.com', 'assets-proxy.anthropic.com', 'claude.ai', 'claude.com', 'claudeusercontent.com', 'console.anthropic.com', 'downloads.claude.ai', 'platform.claude.com', 's-cdn.anthropic.com', 'status.anthropic.com', 'support.anthropic.com', 'www.anthropic.com', 'www.claude.ai', 'www.claude.com', 'www.claudeusercontent.com'], 'test_path': '/login', 'is_favorite': True, 'is_custom': False, 'description': 'Есть в списках GEO-обхода провайдеров. Подбор проверяет сетевые узлы; нужные функции подтвердите в своём аккаунте.', 'icon': 'sparkles', 'routing_mode': 'geo'}),
    ServiceDef.from_dict({'id': 'antigravity', 'name': 'Google Antigravity', 'category': 'Нейросети', 'primary_domain': 'daily-cloudcode-pa.googleapis.com', 'domains': ['antigravity-pa.googleapis.com', 'antigravity-unleash.goog', 'antigravity.google', 'antigravity.googleapis.com', 'cloudcode-pa.googleapis.com', 'daily-cloudcode-pa.googleapis.com', 'www.antigravity-unleash.goog', 'www.antigravity.google'], 'test_path': '/', 'is_favorite': False, 'is_custom': False, 'description': 'Сервисы Google Antigravity IDE и Cloud Code API. Проверяются узлы авторизации и генерации кода.', 'icon': 'code', 'routing_mode': 'geo'}),
    ServiceDef.from_dict({'id': 'grok', 'name': 'Grok', 'category': 'Нейросети', 'primary_domain': 'grok.com', 'domains': ['accounts.x.ai', 'api.x.ai', 'assets.grok.com', 'assets.x.ai', 'grok.com', 'grok.x.ai', 'www.grok.com', 'www.x.ai', 'x.ai'], 'test_path': '/', 'is_favorite': False, 'is_custom': False, 'description': 'Нейросеть Grok (xAI). Проверяется основной сайт, авторизация accounts.x.ai и API.', 'icon': 'sparkles', 'routing_mode': 'geo'}),
    ServiceDef.from_dict({'id': 'cursor', 'name': 'Cursor', 'category': 'Нейросети', 'primary_domain': 'cursor.com', 'domains': ['agentn.api2.cursor.sh', 'agentn.api3.cursor.sh', 'agentn.api4.cursor.sh', 'agentn.api5.cursor.sh', 'agentn.global.api2.cursor.sh', 'agentn.global.api3.cursor.sh', 'agentn.global.api4.cursor.sh', 'agentn.global.api5.cursor.sh', 'api2.cursor.sh', 'api3.cursor.sh', 'api4.cursor.sh', 'api5.cursor.sh', 'authenticate.cursor.sh', 'authenticator.cursor.sh', 'cursor.com', 'cursor.sh', 'downloads.cursor.com', 'origin.cursor.com', 'repo42.cursor.sh', 'us-asia.gcpp.cursor.sh', 'us-eu.gcpp.cursor.sh', 'us-only.gcpp.cursor.sh', 'www.cursor.com'], 'test_path': '/', 'is_favorite': False, 'is_custom': False, 'description': 'Есть в списках GEO-обхода провайдеров. Подбор проверяет сетевые узлы; нужные функции подтвердите в своём аккаунте.', 'icon': 'code', 'routing_mode': 'geo'}),
    ServiceDef.from_dict({'id': 'trae', 'name': 'Trae.ai', 'category': 'Нейросети', 'primary_domain': 'www.trae.ai', 'domains': ['api-sg-central.trae.ai', 'api.trae.ai', 'trae.ai', 'www.trae.ai'], 'test_path': '/', 'is_favorite': False, 'is_custom': False, 'description': 'AI-среда разработки Trae.ai. Поддерживает прямое подключение или обход через Smart DNS.', 'icon': 'code', 'routing_mode': 'geo'}),
    ServiceDef.from_dict({'id': 'copilot', 'name': 'Microsoft Copilot', 'category': 'Нейросети', 'primary_domain': 'copilot.microsoft.com', 'domains': ['copilot.microsoft.com', 'designer.microsoft.com', 'edgeservices.bing.com', 'sydney.bing.com'], 'test_path': '/', 'is_favorite': False, 'is_custom': False, 'description': 'Microsoft Copilot и Designer. Доступ восстанавливается через Zapret DNS, MALW и DNS-AI.', 'icon': 'sparkles', 'routing_mode': 'geo'}),
    ServiceDef.from_dict({'id': 'aistudio', 'name': 'Google AI Studio & NotebookLM', 'category': 'Нейросети', 'primary_domain': 'aistudio.google.com', 'domains': ['ai.google.dev', 'aistudio.google.com', 'makersuite.google.com', 'notebooklm.google', 'notebooklm.google.com'], 'test_path': '/', 'is_favorite': False, 'is_custom': False, 'description': 'Google AI Studio и NotebookLM. Восстановление доступа через Smart DNS провайдеров.', 'icon': 'sparkles', 'routing_mode': 'geo'}),
    ServiceDef.from_dict({'id': 'openrouter', 'name': 'OpenRouter', 'category': 'Нейросети', 'primary_domain': 'openrouter.ai', 'domains': ['eu.openrouter.ai', 'openrouter.ai', 'us.openrouter.ai', 'www.openrouter.ai'], 'test_path': '/', 'is_favorite': False, 'is_custom': False, 'description': 'Есть в списках GEO-обхода провайдеров. Подбор проверяет сетевые узлы; нужные функции подтвердите в своём аккаунте.', 'icon': 'sparkles', 'routing_mode': 'geo'}),
    ServiceDef.from_dict({'id': 'groq', 'name': 'Groq', 'category': 'Нейросети', 'primary_domain': 'console.groq.com', 'domains': ['api.groq.com', 'console.groq.com', 'groq.com', 'www.groq.com'], 'test_path': '/', 'is_favorite': False, 'is_custom': False, 'description': 'Быстрый инференс GroqCloud и API. Доступ через Zapret DNS, GeoHide и MALW.', 'icon': 'sparkles', 'routing_mode': 'geo'}),
    ServiceDef.from_dict({'id': 'manus', 'name': 'Manus', 'category': 'Нейросети', 'primary_domain': 'manus.im', 'domains': ['api.manus.im', 'manus.im', 'www.manus.im'], 'test_path': '/', 'is_favorite': False, 'is_custom': False, 'description': 'Есть в списках GEO-обхода провайдеров. Подбор проверяет сетевые узлы; нужные функции подтвердите в своём аккаунте.', 'icon': 'globe', 'routing_mode': 'geo'}),
    ServiceDef.from_dict({'id': 'stitch', 'name': 'Google Stitch', 'category': 'Нейросети', 'primary_domain': 'stitch.withgoogle.com', 'domains': ['stitch.withgoogle.com'], 'test_path': '/', 'is_favorite': False, 'is_custom': False, 'description': 'Есть в списках GEO-обхода провайдеров. Подбор проверяет сетевые узлы; нужные функции подтвердите в своём аккаунте.', 'icon': 'globe', 'routing_mode': 'geo'}),
    ServiceDef.from_dict({'id': 'githubcopilot', 'name': 'GitHub Copilot', 'primary_domain': 'api.individual.githubcopilot.com', 'domains': ['api.individual.githubcopilot.com', 'proxy.individual.githubcopilot.com'], 'category': 'Нейросети', 'is_favorite': False, 'is_custom': False, 'routing_mode': 'geo', 'description': 'GEO-маршруты из списков GeoHide / Zapret DNS. При подборе проверяется доступность адресов; функции аккаунта проверяются в сервисе.'}),
    ServiceDef.from_dict({'id': 'camel', 'name': 'Camel AI', 'category': 'Нейросети', 'primary_domain': 'camelai.com', 'domains': ['camelai.com', 'stream.camelai.com', 'www.camelai.com'], 'test_path': '/', 'is_favorite': False, 'is_custom': False, 'description': 'Платформа анализа данных Camel AI. Поддерживает прямое подключение с автоматической очисткой устаревших записей hosts.', 'icon': 'sparkles', 'routing_mode': 'geo'}),
    ServiceDef.from_dict({'id': 'hume', 'name': 'Hume AI', 'primary_domain': 'www.hume.ai', 'domains': ['hume.ai', 'www.hume.ai'], 'category': 'Нейросети', 'is_favorite': False, 'is_custom': False, 'routing_mode': 'geo', 'description': 'Голосовой ИИ Hume AI. Поддерживает прямое подключение или обход через Smart DNS.'}),
    ServiceDef.from_dict({'id': 'nvidia', 'name': 'NVIDIA AI (NIM / NGC)', 'category': 'Нейросети', 'primary_domain': 'build.nvidia.com', 'domains': ['build.nvidia.com', 'developer.nvidia.com', 'ngc.nvidia.com'], 'test_path': '/', 'is_favorite': False, 'is_custom': False, 'description': 'Каталог нейросетей NVIDIA NIM и портал разработчиков.', 'icon': 'sparkles', 'routing_mode': 'geo'}),
    ServiceDef.from_dict({'id': 'spotify', 'name': 'Spotify', 'category': 'Музыка, видео и общение', 'primary_domain': 'open.spotify.com', 'domains': ['accounts.scdn.co', 'accounts.spotify.com', 'aet.spotify.com', 'api-partner.spotify.com', 'api.spotify.com', 'encore.scdn.co', 'gew1-dealer.spotify.com', 'gew1-spclient.spotify.com', 'login5.spotify.com', 'open.spotify.com', 'scdn.co', 'spclient.wg.spotify.com', 'spotify.com', 'spotify.dev', 'www-growth.scdn.co', 'www.scdn.co', 'www.spotify.com', 'www.spotify.dev'], 'test_path': '/', 'is_favorite': True, 'is_custom': False, 'description': 'GEO-маршруты провайдеров. Проверьте вход и воспроизведение под своим аккаунтом.', 'icon': 'music', 'routing_mode': 'geo'}),
    ServiceDef.from_dict({'id': 'deepl', 'name': 'DeepL', 'primary_domain': 'www.deepl.com', 'domains': ['api-free.deepl.com', 'api.deepl.com', 'auth.deepl.com', 'deepl.com', 'login-wall.deepl.com', 'static.deepl.com', 'w.deepl.com', 'write-free.www.deepl.com', 'www.deepl.com', 'www2.deepl.com'], 'category': 'Перевод и продуктивность', 'description': 'Онлайн-переводчик и DeepL Write. Обход региональной блокировки (HTTP 451) через Zapret DNS и DNS-AI.'}),
    ServiceDef.from_dict({'id': 'notion', 'name': 'Notion', 'category': 'Перевод и продуктивность', 'primary_domain': 'www.notion.so', 'domains': ['app.notion.com', 'calendar.notion.com', 'calendar.notion.so', 'notion.com', 'notion.so', 'www.notion.com', 'www.notion.so'], 'test_path': '/', 'is_favorite': False, 'is_custom': False, 'description': 'Рабочее пространство Notion и Notion Calendar.', 'icon': 'file-text', 'routing_mode': 'geo'}),
    ServiceDef.from_dict({'id': 'jetbrains', 'name': 'JetBrains', 'category': 'Перевод и продуктивность', 'primary_domain': 'www.jetbrains.com', 'domains': ['account.jetbrains.com', 'api.jetbrains.ai', 'download.jetbrains.com', 'jetbrains.com', 'plugins.jetbrains.com', 'www.jetbrains.com'], 'test_path': '/', 'is_favorite': False, 'is_custom': False, 'description': 'Сервисы JetBrains, маркетплейс плагинов и JetBrains AI.', 'icon': 'code', 'routing_mode': 'geo'}),
    ServiceDef.from_dict({'id': 'make', 'name': 'Make', 'primary_domain': 'www.make.com', 'domains': ['make.com', 'www.make.com'], 'test_path': '/en', 'category': 'Перевод и продуктивность', 'description': 'Платформа автоматизации Make.com. Поддерживает прямое подключение с очисткой устаревших записей hosts.'}),
    ServiceDef.from_dict({'id': 'adobe', 'name': 'Adobe / Firefly', 'primary_domain': 'adobe.com', 'domains': ['adobe.com', 'adobe.io', 'www.adobe.com', 'www.adobe.io'], 'test_path': '/robots.txt', 'category': 'Перевод и продуктивность', 'description': 'Сервисы Adobe и генеративный ИИ Firefly. Поддерживает прямое подключение и Smart DNS.'}),
    ServiceDef.from_dict({'id': 'capcut', 'name': 'CapCut', 'primary_domain': 'www.capcut.com', 'domains': ['capcut.com', 'www.capcut.com'], 'category': 'Музыка, видео и общение', 'description': 'Видеоредактор и облачные сервисы CapCut.'}),
    ServiceDef.from_dict({'id': 'framer', 'name': 'Framer', 'primary_domain': 'www.framer.com', 'domains': ['framer.com', 'www.framer.com'], 'category': 'Перевод и продуктивность', 'description': 'Платформа веб-дизайна Framer. Поддерживает прямое подключение и Smart DNS.'}),
    ServiceDef.from_dict({'id': 'slack', 'name': 'Slack', 'primary_domain': 'slack.com', 'domains': ['slack-edge.com', 'slack-files.com', 'slack-imgs.com', 'slack.com', 'www.slack.com'], 'category': 'Музыка, видео и общение', 'description': 'Корпоративный мессенджер Slack.'}),
    ServiceDef.from_dict({'id': 'atlassian', 'name': 'Atlassian (Jira / Trello)', 'primary_domain': 'www.atlassian.com', 'domains': ['atlassian.com', 'www.atlassian.com'], 'category': 'Перевод и продуктивность', 'description': 'Сервисы совместной работы Jira, Confluence и Trello.'}),
]

_DEFAULT_FAVORITES = ["spotify", "chatgpt", "gemini", "claude"]
_RANK = {
    'chatgpt': 0,
    'gemini': 1,
    'claude': 2,
    'antigravity': 3,
    'grok': 4,
    'cursor': 5,
    'trae': 6,
    'copilot': 7,
    'aistudio': 8,
    'openrouter': 9,
    'groq': 10,
    'manus': 11,
    'stitch': 12,
    'githubcopilot': 13,
    'camel': 14,
    'hume': 15,
    'nvidia': 16,
    'spotify': 17,
    'deepl': 18,
    'notion': 19,
    'jetbrains': 20,
    'make': 21,
    'adobe': 22,
    'capcut': 23,
    'framer': 24,
    'slack': 25,
    'atlassian': 26,
}

class Catalog:
    def __init__(self, custom_services: Optional[List[ServiceDef]] = None):
        self._services: Dict[str, ServiceDef] = {}
        self.hidden_services = set()
        # Load built-ins
        for s in BUILTIN_SERVICES:
            self._services[s.id] = ServiceDef.from_dict(s.to_dict())
            self._services[s.id].is_favorite = s.id in _DEFAULT_FAVORITES

        # Load custom
        if custom_services:
            for s in custom_services:
                self._services[s.id] = ServiceDef.from_dict(s.to_dict())

    def get_service(self, service_id: str) -> Optional[ServiceDef]:
        return self._services.get(service_id.lower().strip())

    def find_by_domain(self, domain: str) -> Optional[ServiceDef]:
        d = domain.lower().strip()
        for s in self._services.values():
            if d in s.domains:
                return s
        return None

    def add_service(self, service: ServiceDef) -> None:
        self._services[service.id] = service

    def remove_service(self, service_id: str) -> bool:
        s_id = service_id.lower().strip()
        if s_id in self._services:
            del self._services[s_id]
            return True
        return False

    def list_all(self, query: str = "", category: Optional[str] = None) -> List[ServiceDef]:
        results = []
        for s in self._services.values():
            if s.id in self.hidden_services:
                continue
            if category and s.category != category:
                continue
            if s.matches_query(query):
                results.append(s)
        # Sort favorites first, then by name
        return sorted(results, key=lambda s: (_RANK.get(s.id, 999), s.name.casefold()))

    def list_favorites(self) -> List[ServiceDef]:
        return sorted([s for s in self.list_all() if s.is_favorite], key=lambda s: (_DEFAULT_FAVORITES.index(s.id) if s.id in _DEFAULT_FAVORITES else 99, _RANK.get(s.id, 999)))

    def set_favorite(self, service_id: str, is_favorite: bool) -> bool:
        s = self.get_service(service_id)
        if s:
            s.is_favorite = is_favorite
            return True
        return False

    def get_categories(self) -> List[str]:
        cats = sorted(list({s.category for s in self._services.values()}))
        return cats

    def import_hosts_services(self, parsed_services: Dict[str, Dict[str, any]]) -> int:
        """
        Incorporates discovered services from an imported hosts file.
        Returns count of new services added.
        """
        added = 0
        for name, data in parsed_services.items():
            domains = data.get("domains", [])
            if not domains:
                continue
            primary = domains[0]
            # Check if domain already recognized in existing service
            existing = next((self.find_by_domain(d) for d in domains if self.find_by_domain(d)), None)
            if existing:
                # Merge any missing domains into existing
                for d in domains:
                    if d not in existing.domains:
                        existing.domains.append(d)
                continue

            # Create new custom service
            s_id = "hosts_" + "".join(c if c.isalnum() else "_" for c in name.lower()).strip("_")
            new_service = ServiceDef(
                id=s_id,
                name=name,
                category="Импортированные",
                primary_domain=primary,
                domains=domains,
                is_custom=True,
                is_favorite=False
            )
            self.add_service(new_service)
            added += 1
        return added
