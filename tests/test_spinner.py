from __future__ import annotations

import time

from patina.spinner import Spinner


def test_start_and_stop():
    spinner = Spinner("Testing")
    spinner.start()
    time.sleep(0.15)
    spinner.stop()
    assert spinner._thread is None


def test_stop_is_idempotent():
    spinner = Spinner("Testing")
    spinner.start()
    spinner.stop()
    spinner.stop()
    assert spinner._thread is None


def test_context_manager():
    with Spinner("Testing") as s:
        time.sleep(0.15)
    assert s._thread is None


def test_stop_without_start():
    spinner = Spinner("Testing")
    spinner.stop()
    assert spinner._thread is None
