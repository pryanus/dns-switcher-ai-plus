"""
BaseProvider: Abstract base class for all DNS / Smart DNS / SNI proxy providers.
"""

from abc import ABC, abstractmethod
from typing import List, Dict, Optional
import time


class CandidateIP:
    def __init__(self, ip: str, provider_id: str, provider_name: str, region: str = ""):
        self.ip = ip.strip()
        self.provider_id = provider_id
        self.provider_name = provider_name
        self.region = region

    def to_dict(self) -> Dict:
        return {
            "ip": self.ip,
            "provider_id": self.provider_id,
            "provider_name": self.provider_name,
            "region": self.region,
        }

    def __repr__(self):
        return f"<CandidateIP {self.ip} ({self.provider_name})>"


class BaseProvider(ABC):
    def __init__(
        self,
        id: str,
        name: str,
        enabled: bool = True,
        priority: int = 10,
        cache_dir: Optional[str] = None
    ):
        self.id = id
        self.name = name
        self.enabled = enabled
        self.priority = priority
        self.cache_dir = cache_dir
        self.last_updated: Optional[str] = None
        self.last_error: Optional[str] = None

    @abstractmethod
    def fetch_candidates(self, domain: str) -> List[CandidateIP]:
        """Returns candidate IPs for the target domain."""
        pass

    @abstractmethod
    def update_database(self) -> bool:
        """Refreshes provider database / cache from remote official source."""
        pass

    def is_available(self) -> bool:
        """Quick healthcheck for provider source availability."""
        return True

    def to_dict(self) -> Dict:
        return {
            "id": self.id,
            "name": self.name,
            "enabled": self.enabled,
            "priority": self.priority,
            "last_updated": self.last_updated,
            "last_error": self.last_error,
        }
