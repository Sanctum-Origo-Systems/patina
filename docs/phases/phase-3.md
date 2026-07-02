# Phase 3 — Style + Drafting

**Goal:** Per-entity communication fingerprints + draft generation.
After this phase: `patina style show <entity>` shows patterns, `patina draft --to <entity>` generates text.

**Depends on:** Phase 1 (store, entities, observations), Phase 2 (objectives for context)

---

## New Files

```
src/patina/
├── style/
│ ├── __init__.py
│ ├── observer.py
│ ├── patterns.py
│ ├── consolidator.py
│ ├── draft.py
│ └── denylist.py
└── llm.py

tests/
├── style/
│ ├── __init__.py
│ ├── test_observer.py
│ ├── test_patterns.py
│ ├── test_consolidator.py
│ └── test_draft.py
└── test_llm.py
```

Also update: `cli.py` (add style + draft commands)

---

## Step 1 — LLM Port (`src/patina/llm.py`)

The LLMPort interface for model-agnostic inference.

Class (Protocol):
- `LLMPort` (Protocol)
  - `tier` property → Literal[2, 3]
  - `context_window` property → int
  - `complete(prompt: str, *, max_tokens: int = 1024) -> str`
  - `extract_entities(text: str) -> list[Entity]`
  - `classify(text: str, categories: list[str]) -> str`
  - `synthesize(texts: list[str], question: str) -> str`
  - `draft(context: str, style_profile: str, recipient_profile: str) -> str`

Concrete implementation:
- `MockLLM` — returns canned responses for testing (tier=3, context_window=200000)
- `OllamaLLM` (optional, can be stub) — calls Ollama API
- `AnthropicLLM` (optional, can be stub) — calls Claude API

For Phase 3, only MockLLM is required. Real implementations come in Phase 7.

Tests:
- MockLLM satisfies Protocol
- MockLLM.complete returns a string
- MockLLM.draft returns a string

---

## Step 2 — Style Observer (`src/patina/style/observer.py`)

Extracts raw style observations from the user's sent messages.

Functions:
- `observe_sent_messages(conn, user_entity_id: str) -> list[StyleObservation]`
  - Queries observations where sender_entity_id = user
  - For each, determines recipient (from @mention or channel context)
  - Returns list of StyleObservation

Dataclass:
- `StyleObservation` (sender_entity_id, recipient_entity_id, text, timestamp, channel_name, metadata: dict)

Tests:
- Returns observations for user's sent messages
- Skips messages with no identifiable recipient
- Returns empty list if no sent messages

---

## Step 3 — Pattern Detection (`src/patina/style/patterns.py`)

Extracts communication patterns from a set of messages.

Functions:
- `detect_patterns(messages: list[str]) -> StylePatterns`
  - Analyzes: average length, greeting patterns, sign-off patterns, formality score, emoji usage, question frequency

Dataclass:
- `StylePatterns` (avg_length: float, greeting: str | None, sign_off: str | None, formality: float, emoji_rate: float, question_rate: float, sample_count: int)

Pattern detection (all regex/heuristic, no LLM):
- Greeting: first line matches "hi", "hey", "hello", "good morning", etc.
- Sign-off: last line matches "thanks", "cheers", "best", "regards", etc.
- Formality: score 0-1 based on contractions (low=informal), sentence length, punctuation
- Emoji rate: count of emoji/emoticon patterns per message
- Question rate: messages containing "?" / total messages

Tests:
- Detects greeting from "Hi team, ..."
- Detects sign-off from "Thanks,\nAlice"
- High formality for long sentences with no contractions
- Low formality for "hey can u check this"
- Emoji rate correct
- Question rate correct

---

## Step 4 — Style Consolidator (`src/patina/style/consolidator.py`)

Builds a stable per-entity style profile from multiple observations.

Functions:
- `consolidate_profile(observations: list[StyleObservation]) -> str`
  - Groups by recipient
  - Runs detect_patterns on each group
  - Returns JSON profile string for storage in style_profiles table

- `build_all_profiles(conn, user_entity_id: str) -> int`
  - Observe → detect patterns → store in style_profiles table
  - Returns count of profiles created/updated

Tests:
- Consolidates multiple messages into one profile
- Profile JSON contains expected fields
- Updates existing profile if called again

---

## Step 5 — Denylist (`src/patina/style/denylist.py`)

Function:
- `is_sensitive(text: str) -> bool`
  - Returns True if text contains patterns that shouldn't be stored (passwords, tokens, SSNs, etc.)
  - Regex: API keys, bearer tokens, password=, ssn patterns, credit card patterns

Tests:
- "my password is hunter2" → True
- "Bearer sk-ant-..." → True
- "Normal work message" → False

---

## Step 6 — Draft Generation (`src/patina/style/draft.py`)

Functions:
- `generate_draft(*, context: str, recipient_entity_id: str, llm: LLMPort, conn) -> str`
  - Loads recipient's style profile from DB
  - Loads user's own style patterns (from style/self.md — observed communication patterns)
  - Loads SOUL.md for agent personality/tone (how the agent speaks, NOT the user's style)
  - Constructs prompt with context + style instructions
  - Calls llm.draft()
  - Returns draft text

- `load_style_profile(conn, entity_id: str) -> str | None`
  - Reads from style_profiles table

Tests (using MockLLM):
- Returns a draft string
- Includes recipient profile in LLM call (verify via MockLLM recording)
- Returns fallback if no style profile exists for recipient

---

## Step 7 — CLI Updates

New commands:
- `patina style show <entity_name>` — finds entity, shows their style profile (patterns JSON pretty-printed)
- `patina style build` — runs build_all_profiles, reports count
- `patina draft --to <entity_name> --context "..."` — generates draft using MockLLM (or real if configured)

Tests:
- style show displays profile
- style build reports count
- draft produces output

---

## Checklist

- [x] All tests pass
- [x] Lint clean
- [x] `patina style build` populates profiles from Phase 1 data
- [x] `patina style show` displays a profile
- [x] `patina draft --to <name> --context "..."` produces output
- [x] Merge to main
- [x] Update Status table in app.md
