# Phase 7 — Live Adapters

**Goal:** Real-time ingestion from Slack and email (not just export files).
After this phase: `patina connect slack` and `patina ingest` work for ongoing use.

**Depends on:** Phase 1 (ingest pipeline, store), Phase 4 (entity extraction feeds graph)

---

## New Files

```
src/patina/
├── adapters/
│ ├── __init__.py
│ ├── slack_live.py
│ └── email_imap.py
├── ports/
│ ├── __init__.py
│ ├── chat.py
│ ├── email.py
│ └── calendar.py
└── scheduler.py

tests/
├── adapters/
│ ├── __init__.py
│ ├── test_slack_live.py
│ └── test_email_imap.py
├── test_ports.py
└── test_scheduler.py
```

Also update: `cli.py`, `ingest.py`

---

## Step 1 — Port Interfaces (`src/patina/ports/`)

Protocol classes defining the abstract interface. Adapters implement these.

`chat.py`:
- `ChatPort` (Protocol)
  - `platform` property → str
  - `list_dm_messages(since: float) -> list[ChatMessage]`
  - `list_mentions(since: float) -> list[ChatMessage]`
  - `list_channel_messages(channel_id: str, since: float) -> list[ChatMessage]`
  - `get_thread(channel_id: str, thread_id: str) -> list[ChatMessage]`

`email.py`:
- `EmailPort` (Protocol)
  - `platform` property → str
  - `list_inbox(since: float) -> list[EmailMessage]`
  - `search_sent(query: str) -> list[EmailMessage]`

`calendar.py`:
- `CalendarPort` (Protocol)
  - `platform` property → str
  - `list_events(start: datetime, end: datetime) -> list[CalendarEvent]`

Add to models.py:
- `EmailMessage` (id, sender, subject, text, timestamp, recipients: list[str], conversation_id: str | None)
- `CalendarEvent` (id, subject, start, end, attendees: list[str], organizer: str)

Tests:
- Protocol classes are runtime_checkable
- Can verify an adapter satisfies the protocol

---

## Step 2 — Slack Live Adapter (`src/patina/adapters/slack_live.py`)

Implements ChatPort using the Slack Web API (via `slack_sdk` or raw HTTP).

Class: `SlackLiveAdapter(ChatPort)`
- `__init__(token: str)` — Slack bot/user token
- Implements all ChatPort methods by calling Slack API:
  - `list_dm_messages` → `conversations.list` (type=im) + `conversations.history`
  - `list_mentions` → `search.messages` (from user mentions)
  - `list_channel_messages` → `conversations.history`
  - `get_thread` → `conversations.replies`

Configuration:
- Token stored in `~/.patina/config.yaml` under `adapters.chat.slack.token`
- Token can be a bot token (xoxb-) or user token (xoxp-)

Tests (mocked — no real API calls):
- Adapter satisfies ChatPort protocol
- Mocked API response → correct ChatMessage output
- Handles rate limiting gracefully (retry with backoff)
- Handles auth error (raises typed exception)

---

## Step 3 — Email IMAP Adapter (`src/patina/adapters/email_imap.py`)

Implements EmailPort using IMAP (works with any email provider).

Class: `ImapEmailAdapter(EmailPort)`
- `__init__(host: str, port: int, username: str, password: str, use_ssl: bool = True)`
- Implements:
  - `list_inbox` → IMAP SEARCH since date, FETCH envelope + body
  - `search_sent` → IMAP SEARCH in Sent folder

Configuration:
- Credentials in `~/.patina/config.yaml` under `adapters.email.imap`

Tests (mocked):
- Adapter satisfies EmailPort protocol
- Mocked IMAP response → correct EmailMessage output
- Handles connection error gracefully

---

## Step 4 — Live Ingest (`src/patina/ingest.py` update)

Add function:
- `ingest_live(*, port: ChatPort | EmailPort, home: Path | None = None, lookback_days: int = 3) -> dict`
  - Same pipeline as ingest_from_export but reads from a live port instead of zip
  - Creates observations, extracts entities, upserts to graph
  - Handles deduplication (same observation ID = skip)
  - Returns same summary dict format

Also add:
- `ingest_all(*, home: Path | None = None, lookback_days: int = 3) -> dict`
  - Reads config.yaml for configured adapters
  - Calls ingest_live for each configured adapter
  - Aggregates results

Tests:
- ingest_live with MockChatPort produces observations
- ingest_all with no adapters configured returns empty result
- Deduplication works across live runs

---

## Step 5 — Heartbeat Scheduler (`src/{app}/scheduler.py`)

The heartbeat runs background tasks: ingest, decay, escalation checks.

Functions:
- `run_once(*, home: Path | None = None) -> dict` — runs all enabled tasks once and exits. Returns summary of what ran.
- `run_periodic(*, interval_minutes: int = 30, home: Path | None = None) -> None` — loop with sleep, calls run_once each interval

Tasks run by the heartbeat:
- `ingest`: call ingest_all (skip if no adapters configured)
- `decay`: run belief confidence decay pass
- `escalation_check`: detect urgency shifts (items moving from Q3 → Q1)
- `profile_refresh`: regenerate PROFILE.md from graph (optional, default off)

Configuration read from `~/.patina/config.yaml` under `heartbeat.tasks`.

Tests:
- run_once executes all enabled tasks and returns summary
- run_once skips ingest if no adapters configured
- (Don't test run_periodic in CI — it's an infinite loop)

---

## Step 6 — CLI Updates

New commands:
- `patina connect slack` — interactive: prompts for token, validates, saves to config.yaml
- `patina connect email` — interactive: prompts for IMAP settings, validates, saves
- `patina ingest` (no --from-export) — calls ingest_all with configured adapters
- `patina heartbeat once` — runs all enabled heartbeat tasks once and exits
- `patina heartbeat start` — runs heartbeat continuously at configured interval (foreground)

Update existing:
- `patina ingest --from-export <path>` — still works as before

Tests:
- connect commands write to config.yaml
- ingest without flags calls live pipeline
- ingest with --from-export still works

---

## Checklist

- [x] All tests pass
- [x] Lint clean
- [x] `patina connect slack` prompts and saves token
- [x] `patina ingest` with configured adapter fetches messages (manual test with real Slack optional)
- [x] Export ingest still works
- [x] `patina heartbeat once` runs ingest + decay + escalation
- [x] Merge to main
- [x] Update Status table in app.md
