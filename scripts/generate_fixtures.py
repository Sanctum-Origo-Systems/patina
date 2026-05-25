"""Generate deterministic Slack export fixture for testing.

Produces fixtures/demo/slack-export.zip with ~1000 messages, 21 users, 5 channels, 30 days.
"""

from __future__ import annotations

import json
import random
import zipfile
from datetime import UTC, datetime, timedelta
from pathlib import Path

SEED = 42
NUM_MESSAGES = 1000
NUM_DAYS = 30

SELF_USER = {"id": "U000SELF", "real_name": "You (Self)", "name": "self"}

USERS = [
    SELF_USER,
    {"id": "U001MGR", "real_name": "Jordan Park", "name": "jordan.park"},
    {"id": "U002PEER", "real_name": "Priya Sharma", "name": "priya.sharma"},
    {"id": "U003PEER", "real_name": "Marcus Chen", "name": "marcus.chen"},
    {"id": "U004PEER", "real_name": "Lena Novak", "name": "lena.novak"},
    {"id": "U005TEAM", "real_name": "Sam Okafor", "name": "sam.okafor"},
    {"id": "U006TEAM", "real_name": "Aisha Patel", "name": "aisha.patel"},
    {"id": "U007TEAM", "real_name": "Derek Liu", "name": "derek.liu"},
    {"id": "U008TEAM", "real_name": "Rosa Martinez", "name": "rosa.martinez"},
    {"id": "U009TEAM", "real_name": "James Wright", "name": "james.wright"},
    {"id": "U010TEAM", "real_name": "Nina Volkov", "name": "nina.volkov"},
    {"id": "U011TEAM", "real_name": "Carlos Reyes", "name": "carlos.reyes"},
    {"id": "U012TEAM", "real_name": "Fatima Al-Hassan", "name": "fatima.alhassan"},
    {"id": "U013TEAM", "real_name": "Tommy Nguyen", "name": "tommy.nguyen"},
    {"id": "U014TEAM", "real_name": "Grace Kim", "name": "grace.kim"},
    {"id": "U015EXT", "real_name": "Alex Rivera (Vendor)", "name": "alex.rivera"},
    {"id": "U016EXT", "real_name": "Morgan Taylor (Client)", "name": "morgan.taylor"},
    {"id": "U017EXT", "real_name": "Kai Tanaka (Partner)", "name": "kai.tanaka"},
    {"id": "U018EXT", "real_name": "Dana Brooks (Legal)", "name": "dana.brooks"},
    {"id": "U019EXT", "real_name": "Ravi Gupta (Contractor)", "name": "ravi.gupta"},
    {"id": "U020EXT", "real_name": "Olivia Foster (Sales)", "name": "olivia.foster"},
]

CHANNELS = [
    {"id": "C001GEN", "name": "general"},
    {"id": "C002PRJ", "name": "project-atlas"},
    {"id": "C003PRJ", "name": "project-beacon"},
    {"id": "C004TEAM", "name": "eng-team"},
    {"id": "C005EXT", "name": "client-comms"},
]

SELF_ID = SELF_USER["id"]
MANAGER_ID = "U001MGR"
PEER_IDS = ["U002PEER", "U003PEER", "U004PEER"]
TEAM_IDS = [u["id"] for u in USERS if "TEAM" in u["id"]]
EXT_IDS = [u["id"] for u in USERS if "EXT" in u["id"]]
ALL_OTHER_IDS = [u["id"] for u in USERS if u["id"] != SELF_ID]

GENERAL_MESSAGES = [
    "Good morning everyone!",
    "Quick update: standup is at 10am today",
    "Has anyone seen the latest dashboard numbers?",
    "Reminder: retro is tomorrow at 2pm",
    "Happy Friday team!",
    "Who's around for a quick sync?",
    "Just pushed the latest changes to staging",
    "Can someone review my PR?",
    "Heads up: deploying to prod at 3pm",
    "Thanks for the great work this sprint!",
    "Office hours are 2-4pm today if anyone needs help",
    "Welcome to the team!",
    "FYI the API docs have been updated",
    "Anyone up for lunch?",
    "Great work on the release everyone",
]

PROJECT_MESSAGES = [
    "Sprint planning notes are in the doc",
    "Blocked on the API integration — waiting on vendor response",
    "The migration script ran successfully in staging",
    "Need to revisit the data model before we proceed",
    "Performance tests look good — 200ms p99",
    "I'll handle the frontend changes for this",
    "The design review went well, few minor tweaks needed",
    "Can we get a status update on the auth flow?",
    "Database indexes added, query time down 40%",
    "QA found a regression in the search feature",
    "Deployment pipeline is green",
    "Updated the architecture diagram",
    "We need to scope the next milestone",
    "The vendor API is returning 500s intermittently",
    "Feature flag is live for 10% of users",
]

MENTION_TEMPLATES = [
    "<@{uid}> can you take a look at this?",
    "<@{uid}> FYI this landed",
    "Hey <@{uid}>, quick question about the rollout",
    "<@{uid}> thoughts on the approach?",
    "Looping in <@{uid}> for visibility",
    "<@{uid}> when you get a chance, the PR is ready",
    "<@{uid}> the tests are failing on your branch",
    "cc <@{uid}> <@{uid2}>",
]

COMMITMENT_MESSAGES = [
    "I'll have the report ready by end of day",
    "I'll get back to you by tomorrow",
    "Will send the updated spec by Friday",
    "I'll take care of the deployment",
    "Let me follow up with the vendor on this",
    "I'll review and merge by EOD",
    "I'll set up the meeting for next week",
    "Will update the ticket after I investigate",
]

SEVERITY_MESSAGES = [
    "SEV2: production API latency spike detected",
    "URGENT: client reporting data loss in dashboard",
    "P1: authentication service is returning 503",
    "CRITICAL: database replication lag at 30 seconds",
    "INCIDENT: payment processing failing for EU region",
    "SEV1: complete outage on mobile endpoints",
]

REACTIONS = [
    [{"name": "thumbsup", "users": [SELF_ID]}],
    [{"name": "eyes", "users": [SELF_ID]}],
    [{"name": "white_check_mark", "users": [SELF_ID]}],
    [{"name": "rocket", "users": [SELF_ID]}],
    [{"name": "pray", "users": [SELF_ID]}],
]

THREAD_REPLIES = [
    "Got it, thanks!",
    "Makes sense, I'll update accordingly",
    "Good point — let me check",
    "Done",
    "Agreed, let's go with that approach",
    "+1",
    "I'll take this one",
    "Nice catch!",
    "Following up on this",
    "Updated in the doc",
]

USER_MAP = {u["id"]: u for u in USERS}


def _weighted_sender(rng: random.Random) -> str:
    r = rng.random()
    if r < 0.24:
        return SELF_ID
    elif r < 0.34:
        return MANAGER_ID
    elif r < 0.55:
        return rng.choice(PEER_IDS)
    elif r < 0.85:
        return rng.choice(TEAM_IDS)
    else:
        return rng.choice(EXT_IDS)


def _weighted_channel(rng: random.Random) -> dict:
    r = rng.random()
    if r < 0.30:
        return CHANNELS[0]
    elif r < 0.55:
        return CHANNELS[1]
    elif r < 0.75:
        return CHANNELS[2]
    elif r < 0.90:
        return CHANNELS[3]
    else:
        return CHANNELS[4]


def _business_hour_ts(rng: random.Random, base_date: datetime, day_offset: int) -> float:
    day = base_date + timedelta(days=day_offset)
    weekday = day.weekday()

    if weekday >= 5:
        hour = rng.randint(10, 18)
    else:
        r = rng.random()
        if r < 0.05:
            hour = rng.randint(22, 23)
        elif r < 0.15:
            hour = rng.randint(7, 8)
        else:
            hour = rng.randint(9, 17)

    minute = rng.randint(0, 59)
    second = rng.randint(0, 59)
    ts_dt = day.replace(hour=hour, minute=minute, second=second)
    return ts_dt.timestamp()


def _pick_message(rng: random.Random, channel: dict, sender: str) -> str:
    r = rng.random()

    if r < 0.01:
        return rng.choice(SEVERITY_MESSAGES)
    elif r < 0.018:
        return rng.choice(COMMITMENT_MESSAGES)
    elif r < 0.098:
        tmpl = rng.choice(MENTION_TEMPLATES)
        targets = [u for u in ALL_OTHER_IDS if u != sender]
        uid = rng.choice(targets)
        uid2 = rng.choice([u for u in targets if u != uid])
        return tmpl.format(uid=uid, uid2=uid2)

    if channel["name"] in ("project-atlas", "project-beacon"):
        return rng.choice(PROJECT_MESSAGES)
    return rng.choice(GENERAL_MESSAGES)


def generate() -> Path:
    rng = random.Random(SEED)
    base_date = datetime(2025, 4, 25, tzinfo=UTC)
    output_dir = Path(__file__).parent.parent / "fixtures" / "demo"
    output_dir.mkdir(parents=True, exist_ok=True)
    zip_path = output_dir / "slack-export.zip"

    messages_by_channel_date: dict[str, dict[str, list]] = {}
    thread_parents: list[tuple[str, str, str]] = []

    for _ in range(NUM_MESSAGES):
        day_offset = rng.randint(0, NUM_DAYS - 1)
        day_weights = [1.0] * 5 + [0.3] * 2
        weekday = (base_date + timedelta(days=day_offset)).weekday()
        if rng.random() > day_weights[weekday]:
            day_offset = rng.choice(
                [d for d in range(NUM_DAYS) if (base_date + timedelta(days=d)).weekday() < 5]
            )

        sender = _weighted_sender(rng)
        channel = _weighted_channel(rng)
        ts = _business_hour_ts(rng, base_date, day_offset)
        text = _pick_message(rng, channel, sender)
        ts_str = f"{ts:.6f}"

        msg: dict = {
            "user": sender,
            "text": text,
            "ts": ts_str,
        }

        if rng.random() < 0.10:
            msg["reactions"] = rng.choice(REACTIONS)

        date_str = datetime.fromtimestamp(ts, tz=UTC).strftime("%Y-%m-%d")
        ch_name = channel["name"]

        if ch_name not in messages_by_channel_date:
            messages_by_channel_date[ch_name] = {}
        if date_str not in messages_by_channel_date[ch_name]:
            messages_by_channel_date[ch_name][date_str] = []

        messages_by_channel_date[ch_name][date_str].append(msg)

        if rng.random() < 0.20:
            thread_parents.append((ch_name, date_str, ts_str))

    for ch_name, date_str, parent_ts in thread_parents:
        if rng.random() < 0.75:
            reply_sender = _weighted_sender(rng)
            reply_text = rng.choice(THREAD_REPLIES)
            parent_float = float(parent_ts)
            reply_ts = parent_float + rng.randint(60, 7200)
            reply_date = datetime.fromtimestamp(reply_ts, tz=UTC).strftime("%Y-%m-%d")

            reply = {
                "user": reply_sender,
                "text": reply_text,
                "ts": f"{reply_ts:.6f}",
                "thread_ts": parent_ts,
            }

            if ch_name not in messages_by_channel_date:
                messages_by_channel_date[ch_name] = {}
            if reply_date not in messages_by_channel_date[ch_name]:
                messages_by_channel_date[ch_name][reply_date] = []
            messages_by_channel_date[ch_name][reply_date].append(reply)

    with zipfile.ZipFile(zip_path, "w", zipfile.ZIP_DEFLATED) as zf:
        zf.writestr("users.json", json.dumps(USERS, indent=2))
        zf.writestr("channels.json", json.dumps(CHANNELS, indent=2))

        for ch_name, dates in sorted(messages_by_channel_date.items()):
            for date_str, msgs in sorted(dates.items()):
                msgs.sort(key=lambda m: float(m["ts"]))
                zf.writestr(
                    f"{ch_name}/{date_str}.json",
                    json.dumps(msgs, indent=2),
                )

    print(f"Generated {zip_path}")
    total = sum(len(msgs) for dates in messages_by_channel_date.values() for msgs in dates.values())
    print(f"Total messages: {total}")
    print(f"Users: {len(USERS)}")
    print(f"Channels: {len(CHANNELS)}")
    print(f"Days: {NUM_DAYS}")
    return zip_path


if __name__ == "__main__":
    generate()
