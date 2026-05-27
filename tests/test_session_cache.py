from __future__ import annotations

import threading
import time
from unittest.mock import patch

from patina.agent.session_cache import SessionCache


def test_get_unknown_returns_none():
    cache = SessionCache(ttl_seconds=300)
    assert cache.get("unknown") is None


def test_set_then_get():
    cache = SessionCache(ttl_seconds=300)
    cache.set("key1", "session-abc")
    assert cache.get("key1") == "session-abc"


def test_get_returns_none_after_ttl():
    cache = SessionCache(ttl_seconds=1)
    cache.set("key1", "session-abc")

    with patch("patina.agent.session_cache.time") as mock_time:
        mock_time.time.return_value = time.time() + 2
        assert cache.get("key1") is None


def test_invalidate_removes_entry():
    cache = SessionCache(ttl_seconds=300)
    cache.set("key1", "session-abc")
    cache.invalidate("key1")
    assert cache.get("key1") is None


def test_cleanup_removes_expired():
    cache = SessionCache(ttl_seconds=1)
    cache.set("key1", "session-1")
    cache.set("key2", "session-2")

    with patch("patina.agent.session_cache.time") as mock_time:
        mock_time.time.return_value = time.time() + 2
        removed = cache.cleanup()
        assert removed == 2


def test_thread_safety():
    cache = SessionCache(ttl_seconds=300)
    errors: list[Exception] = []

    def writer():
        try:
            for i in range(100):
                cache.set(f"key-{i}", f"session-{i}")
        except Exception as e:
            errors.append(e)

    def reader():
        try:
            for i in range(100):
                cache.get(f"key-{i}")
        except Exception as e:
            errors.append(e)

    threads = [threading.Thread(target=writer), threading.Thread(target=reader)]
    for t in threads:
        t.start()
    for t in threads:
        t.join()

    assert errors == []
