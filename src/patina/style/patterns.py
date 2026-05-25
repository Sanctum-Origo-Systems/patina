from __future__ import annotations

import re
from dataclasses import dataclass

_GREETING_RE = re.compile(
    r"^(hi|hey|hello|good morning|good afternoon|good evening|morning)\b",
    re.IGNORECASE,
)

_SIGNOFF_RE = re.compile(
    r"(thanks|cheers|best|regards|take care|talk soon|thank you|thx)\s*[,.]?\s*$",
    re.IGNORECASE | re.MULTILINE,
)

_EMOJI_RE = re.compile(
    r":[a-z_]+:|[\U0001f600-\U0001f64f\U0001f300-\U0001f5ff"
    r"\U0001f680-\U0001f6ff\U0001f900-\U0001f9ff]",
)

_CONTRACTION_RE = re.compile(
    r"\b(can't|won't|don't|isn't|aren't|wasn't|weren't|I'm|you're|"
    r"they're|we're|it's|that's|there's|he's|she's|let's|"
    r"couldn't|shouldn't|wouldn't|didn't|hasn't|haven't|hadn't|"
    r"I'll|you'll|we'll|they'll|I've|you've|we've|they've|"
    r"gonna|wanna|gotta|u|ur)\b",
    re.IGNORECASE,
)


@dataclass
class StylePatterns:
    avg_length: float
    greeting: str | None
    sign_off: str | None
    formality: float
    emoji_rate: float
    question_rate: float
    sample_count: int


def detect_patterns(messages: list[str]) -> StylePatterns:
    if not messages:
        return StylePatterns(
            avg_length=0,
            greeting=None,
            sign_off=None,
            formality=0.5,
            emoji_rate=0,
            question_rate=0,
            sample_count=0,
        )

    total_len = sum(len(m) for m in messages)
    avg_length = total_len / len(messages)

    greeting = _detect_greeting(messages)
    sign_off = _detect_signoff(messages)
    formality = _compute_formality(messages)
    emoji_rate = _compute_emoji_rate(messages)
    question_rate = sum(1 for m in messages if "?" in m) / len(messages)

    return StylePatterns(
        avg_length=avg_length,
        greeting=greeting,
        sign_off=sign_off,
        formality=formality,
        emoji_rate=emoji_rate,
        question_rate=question_rate,
        sample_count=len(messages),
    )


def _detect_greeting(messages: list[str]) -> str | None:
    counts: dict[str, int] = {}
    for msg in messages:
        first_line = msg.split("\n")[0].strip()
        match = _GREETING_RE.match(first_line)
        if match:
            greeting = match.group(1).lower()
            counts[greeting] = counts.get(greeting, 0) + 1

    if not counts:
        return None
    return max(counts, key=counts.get)  # type: ignore[arg-type]


def _detect_signoff(messages: list[str]) -> str | None:
    counts: dict[str, int] = {}
    for msg in messages:
        match = _SIGNOFF_RE.search(msg)
        if match:
            signoff = match.group(1).lower()
            counts[signoff] = counts.get(signoff, 0) + 1

    if not counts:
        return None
    return max(counts, key=counts.get)  # type: ignore[arg-type]


def _compute_formality(messages: list[str]) -> float:
    if not messages:
        return 0.5

    total_words = 0
    total_contractions = 0
    total_sentences = 0
    total_sentence_words = 0

    for msg in messages:
        words = msg.split()
        total_words += len(words)
        total_contractions += len(_CONTRACTION_RE.findall(msg))
        sentences = re.split(r"[.!?]+", msg)
        sentences = [s.strip() for s in sentences if s.strip()]
        total_sentences += len(sentences)
        for s in sentences:
            total_sentence_words += len(s.split())

    if total_words == 0:
        return 0.5

    contraction_ratio = total_contractions / total_words
    avg_sentence_len = total_sentence_words / max(total_sentences, 1)
    sentence_len_score = min(avg_sentence_len / 20.0, 1.0)

    formality = (1.0 - contraction_ratio * 5) * 0.5 + sentence_len_score * 0.5
    return max(0.0, min(1.0, formality))


def _compute_emoji_rate(messages: list[str]) -> float:
    if not messages:
        return 0.0
    total_emoji = sum(len(_EMOJI_RE.findall(m)) for m in messages)
    return total_emoji / len(messages)
