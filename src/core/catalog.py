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


# AI и повседневные сервисы. Источники: GeoHide и Zapret DNS.
RETIRED_SERVICES = {'claude': 'Claude (Anthropic)', 'elevenlabs': 'ElevenLabs', 'cursor': 'Cursor', 'openrouter': 'OpenRouter', 'manus': 'Manus', 'genspark': 'Genspark', 'stitch': 'Google Stitch', 'sora': 'Sora', 'githubcopilot': 'GitHub Copilot', 'cerebras': 'Cerebras', 'reve': 'Reve', 'hume': 'Hume AI', 'deezer': 'Deezer', 'crunchyroll': 'Crunchyroll', 'notion': 'Notion', 'canva': 'Canva', 'twitch': 'Twitch'}

BUILTIN_SERVICES: List[ServiceDef] = [
    ServiceDef.from_dict({'id': 'chatgpt', 'name': 'ChatGPT (OpenAI)', 'category': 'Нейросети', 'primary_domain': 'chatgpt.com', 'domains': ['ab.chatgpt.com', 'android.chat.openai.com', 'api.openai.com', 'auth.openai.com', 'auth0.openai.com', 'bps.openai.com', 'cdn.oaistatic.com', 'cdn.platform.openai.com', 'chat.openai.com', 'chatgpt.com', 'developers.openai.com', 'files.oaiusercontent.com', 'ios.chat.openai.com', 'oaistatic.com', 'oaiusercontent.com', 'openai.com', 'operator.chatgpt.com', 'platform.openai.com', 'sdmntpritalynorth.oaiusercontent.com', 'sdmntprnortheu.oaiusercontent.com', 'sdmntprpolandcentral.oaiusercontent.com', 'sdmntprukwest.oaiusercontent.com', 'tcr9i.chat.openai.com', 'videos.openai.com', 'webrtc.chatgpt.com', 'www.chatgpt.com', 'www.oaistatic.com', 'www.oaiusercontent.com', 'www.openai.com'], 'test_path': '/', 'is_favorite': True, 'is_custom': False, 'description': 'Есть в списках GEO-обхода провайдеров. Подбор проверяет сетевые узлы; нужные функции подтвердите в своём аккаунте.', 'icon': 'sparkles', 'routing_mode': 'geo'}),
    ServiceDef.from_dict({'id': 'gemini', 'name': 'Google Gemini', 'category': 'Нейросети', 'primary_domain': 'gemini.google.com', 'domains': ['alkalimakersuite-pa.clients6.google.com', 'bard.google.com', 'geller-pa.googleapis.com', 'gemini.google', 'gemini.google.com', 'geminiweb-pa.clients.google.com', 'geminiweb-pa.clients6.google.com', 'generativelanguage.googleapis.com', 'people-pa.clients6.google.com', 'proactivebackend-pa.googleapis.com', 'robinfrontend-pa.googleapis.com', 'signaler-pa.clients6.google.com', 'waa-pa.clients6.google.com'], 'test_path': '/', 'is_favorite': True, 'is_custom': False, 'description': 'Есть в списках GEO-обхода провайдеров. Подбор проверяет сетевые узлы; нужные функции подтвердите в своём аккаунте.', 'icon': 'sparkles', 'routing_mode': 'geo'}),
    ServiceDef.from_dict({'id': 'spotify', 'name': 'Spotify', 'category': 'Музыка, видео и общение', 'primary_domain': 'open.spotify.com', 'domains': ['accounts.scdn.co', 'accounts.spotify.com', 'aet.spotify.com', 'api-partner.spotify.com', 'api.spotify.com', 'encore.scdn.co', 'gew1-dealer.spotify.com', 'gew1-spclient.spotify.com', 'login5.spotify.com', 'open.spotify.com', 'scdn.co', 'spclient.wg.spotify.com', 'spotify.com', 'spotify.dev', 'www-growth.scdn.co', 'www.scdn.co', 'www.spotify.com', 'www.spotify.dev'], 'test_path': '/', 'is_favorite': True, 'is_custom': False, 'description': 'GEO-маршруты провайдеров. Проверьте вход и воспроизведение под своим аккаунтом.', 'icon': 'music', 'routing_mode': 'geo'}),
]

_DEFAULT_FAVORITES = ["spotify", "chatgpt", "gemini"]
_RANK = {'chatgpt': 0, 'gemini': 1, 'spotify': 2}

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
            existing = self.find_by_domain(primary)
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
