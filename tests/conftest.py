from __future__ import annotations

import pytest

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
