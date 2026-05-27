from __future__ import annotations

import threading
import time
from dataclasses import dataclass


@dataclass
class CachedSession:
    session_id: str
    last_active: float


class SessionCache:
    def __init__(self, ttl_seconds: int = 300) -> None:
        self._cache: dict[str, CachedSession] = {}
        self._ttl = ttl_seconds
        self._lock = threading.Lock()

    def get(self, key: str) -> str | None:
        with self._lock:
            entry = self._cache.get(key)
            if entry is None:
                return None
            if time.time() - entry.last_active > self._ttl:
                del self._cache[key]
                return None
            return entry.session_id

    def set(self, key: str, session_id: str) -> None:
        with self._lock:
            self._cache[key] = CachedSession(session_id=session_id, last_active=time.time())

    def invalidate(self, key: str) -> None:
        with self._lock:
            self._cache.pop(key, None)

    def cleanup(self) -> int:
        now = time.time()
        with self._lock:
            expired = [k for k, v in self._cache.items() if now - v.last_active > self._ttl]
            for k in expired:
                del self._cache[k]
            return len(expired)
