from __future__ import annotations

import pytest

import patina.store as store_module
from patina.store import connect, get_db_path, init_db


@pytest.fixture
def db_path(tmp_path):
    path = get_db_path(tmp_path)
    init_db(path)
    return path


@pytest.fixture
def db_conn(db_path):
    conn = connect(db_path)
    yield conn
    conn.close()


@pytest.fixture(autouse=True)
def _isolate_home(tmp_path, monkeypatch):
    monkeypatch.setattr(store_module, "DEFAULT_HOME", tmp_path)
    monkeypatch.setenv("PATINA_DEDUP_ALLOW_LIVE", "1")
