from __future__ import annotations

import sys
import threading

_FRAMES = "⠋⠙⠹⠸⠼⠴⠦⠧⠇⠏"


class Spinner:
    def __init__(self, message: str = "Thinking") -> None:
        self._message = message
        self._stop_event = threading.Event()
        self._thread: threading.Thread | None = None

    def start(self) -> None:
        self._stop_event.clear()
        self._thread = threading.Thread(target=self._spin, daemon=True)
        self._thread.start()

    def stop(self) -> None:
        self._stop_event.set()
        if self._thread:
            self._thread.join(timeout=1.0)
            self._thread = None
        sys.stderr.write(f"\r{' ' * (len(self._message) + 4)}\r")
        sys.stderr.flush()

    def _spin(self) -> None:
        i = 0
        while not self._stop_event.is_set():
            frame = _FRAMES[i % len(_FRAMES)]
            sys.stderr.write(f"\r{frame} {self._message}...")
            sys.stderr.flush()
            i += 1
            self._stop_event.wait(0.1)

    def __enter__(self) -> Spinner:
        self.start()
        return self

    def __exit__(self, *args) -> None:
        self.stop()
