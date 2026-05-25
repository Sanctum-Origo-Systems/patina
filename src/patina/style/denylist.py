from __future__ import annotations

import re

_SENSITIVE_PATTERNS = re.compile(
    r"("
    r"password\s*[=:]\s*\S+"
    r"|Bearer\s+\S+"
    r"|sk-ant-\S+"
    r"|xoxb-\S+"
    r"|xoxp-\S+"
    r"|api[_-]?key\s*[=:]\s*\S+"
    r"|secret\s*[=:]\s*\S+"
    r"|token\s*[=:]\s*\S+"
    r"|\b\d{3}-\d{2}-\d{4}\b"
    r"|\b\d{4}[\s-]?\d{4}[\s-]?\d{4}[\s-]?\d{4}\b"
    r")",
    re.IGNORECASE,
)


def is_sensitive(text: str) -> bool:
    return bool(_SENSITIVE_PATTERNS.search(text))
