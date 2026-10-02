from __future__ import annotations

from pathlib import Path

import typer

from patina.autonomy.actions import (
    approve_action,
    list_pending,
    reject_action,
)
from patina.autonomy.evaluate import evaluate_autonomy
from patina.autonomy.levels import (
    DOMAINS,
    can_advance,
    current_level,
    is_frozen,
    level_description,
    set_level,
)
from patina.autonomy.tracker import (
    check_demotion,
    clear_anti_pattern,
    get_anti_patterns,
)
from patina.beliefs.contradictions import find_contradictions_tier1
from patina.beliefs.decay import get_stale_beliefs
from patina.beliefs.relationships import get_relationship_map
from patina.decisions import record_decision
from patina.graph import count_entities, count_observations
from patina.ingest import ingest_from_export
from patina.llm import MockLLM
from patina.priority.catch_up import catch_up as do_catch_up
from patina.priority.catch_up import priorities as do_priorities
from patina.priority.objectives import (
    add_objective,
    list_objectives,
    remove_objective,
)
from patina.store import connect, get_db_path, init_db
from patina.style.consolidator import build_all_profiles
from patina.style.draft import generate_draft, load_style_profile

app = typer.Typer(help="Patina — a cognitive app that compounds.")
objectives_app = typer.Typer(help="Manage objectives.")
app.add_typer(objectives_app, name="objectives")
style_app = typer.Typer(help="Style profiles.")
app.add_typer(style_app, name="style")
autonomy_app = typer.Typer(help="Autonomy system.")
app.add_typer(autonomy_app, name="autonomy")
entity_app = typer.Typer(help="Entity maintenance.")
app.add_typer(entity_app, name="entity")
heartbeat_app = typer.Typer(help="Background heartbeat tasks.")
app.add_typer(heartbeat_app, name="heartbeat")
owner_app = typer.Typer(help="Owner entity management.")
app.add_typer(owner_app, name="owner")


def _bootstrap_home(home_dir: Path) -> None:
    home_dir.mkdir(parents=True, exist_ok=True)
    (home_dir / "journal").mkdir(exist_ok=True)
    (home_dir / "style").mkdir(exist_ok=True)

    soul = home_dir / "SOUL.md"
    if not soul.exists():
        soul.write_text(
            "# SOUL.md\n"
            "#\n"
            "# Define how the agent communicates.\n"
            "# This file is read-only to the agent — it cannot modify its own personality.\n"
            "#\n"
            "# Examples:\n"
            "#   - Be direct and concise\n"
            "#   - No emojis\n"
            "#   - Push back when I'm stalling\n"
            "#   - Match my energy — casual in DMs, formal in client channels\n"
            "\n"
            "## Context Persistence\n"
            "- After significant decisions or insights → call `journal_write` "
            "immediately\n"
            "- After learning a user correction or preference → journal it\n"
            "- After career/strategic discussions → journal the key takeaways\n"
            "- Before ending a long session → checkpoint what matters to the "
            "journal\n"
            "- Context is working memory. Journal is long-term memory. Never rely "
            "on\n"
            "  context alone for anything that matters beyond this moment.\n"
            "\n"
            "## Journal Search\n"
            '- Never say "I don\'t have context" or "we haven\'t discussed this" '
            "without\n"
            "  first calling `journal_search`\n"
            "- If a user asks about a prior conversation, search the journal "
            "before\n"
            "  responding\n"
            "- The journal is your long-term memory — use it\n"
        )

    profile = home_dir / "PROFILE.md"
    if not profile.exists():
        profile.write_text(
            "# PROFILE.md\n"
            "#\n"
            "# Auto-generated summary of the user from the belief graph.\n"
            "# Will be populated after ingestion and processing.\n"
        )

    style_self = home_dir / "style" / "self.md"
    if not style_self.exists():
        style_self.write_text(
            "# self.md\n"
            "#\n"
            "# Your observed communication patterns.\n"
            "# Populated by `patina style build`.\n"
        )

    import yaml

    config = home_dir / "config.yaml"
    if not config.exists():
        default_config = {
            "owner": {"user_ids": [], "name": ""},
            "adapters": {"chat": [], "email": []},
            "heartbeat": {
                "enabled": True,
                "interval_minutes": 30,
                "tasks": {
                    "ingest": True,
                    "decay": True,
                    "escalation_check": True,
                    "profile_refresh": False,
                },
            },
        }
        config.write_text(yaml.dump(default_config, default_flow_style=False))

    gateway_config = home_dir / "gateway.yaml"
    if not gateway_config.exists():
        default_gateway = {
            "adapters": {
                "telegram": {
                    "enabled": False,
                    "token": "${TELEGRAM_BOT_TOKEN}",
                    "allowed_users": [],
                },
            },
            "agent_url": "http://127.0.0.1:8321",
        }
        gateway_config.write_text(yaml.dump(default_gateway, default_flow_style=False))


@app.command()
def init(
    home: Path | None = typer.Option(None, "--home", help="Custom home directory"),
) -> None:
    """Initialize the Patina database and home directory."""
    import yaml

    from patina.store import DEFAULT_HOME

    home_dir = home or DEFAULT_HOME
    _bootstrap_home(home_dir)
    db_path = get_db_path(home)
    init_db(db_path)

    config_path = home_dir / "config.yaml"
    with open(config_path) as f:
        config = yaml.safe_load(f) or {}

    owner = config.setdefault("owner", {})
    if not owner.get("user_ids"):
        typer.echo()
        typer.echo("Your messaging user ID (e.g., Slack member ID, email address).")
        typer.echo("Leave blank to set later in config.yaml.")
        user_id = input("> ").strip()
        if user_id:
            owner["user_ids"] = [user_id]
            if not owner.get("name"):
                name = input("Your display name: ").strip()
                if name:
                    owner["name"] = name
            with open(config_path, "w") as f:
                yaml.dump(config, f, default_flow_style=False)
            typer.echo(f"Owner set: {user_id}")

    typer.echo(f"Initialized Patina at {home_dir}")


@app.command("extract")
def extract_cmd(
    batch_size: int = typer.Option(10, "--batch-size", help="Messages per LLM call"),
    limit: int = typer.Option(500, "--limit", help="Max observations to process"),
    model: str = typer.Option("sonnet", "--model", help="Claude model to use"),
    dry_run: bool = typer.Option(False, "--dry-run", help="Count without calling LLM"),
    reprocess: bool = typer.Option(
        False, "--reprocess", help="Reset processed flag before extracting"
    ),
    since: str | None = typer.Option(
        None, "--since", help="Reprocess observations since DATE (ISO)"
    ),
    source: str | None = typer.Option(
        None, "--source", help="Reprocess observations from this source"
    ),
    home: Path | None = typer.Option(None, "--home", help="Custom home directory"),
) -> None:
    """Extract beliefs from unprocessed observations via LLM."""
    if reprocess:
        from patina.maintenance import reprocess_observations

        db_path = get_db_path(home)
        if not db_path.exists():
            typer.echo("Patina not initialized. Run 'patina init' first.", err=True)
            raise typer.Exit(1)

        conn = connect(db_path)
        try:
            result = reprocess_observations(conn, since=since, source=source, dry_run=dry_run)
            mode = "Would reset" if dry_run else "Reset"
            typer.echo(f"{mode} {result['reset_count']} observations for reprocessing.")
        finally:
            conn.close()

        if dry_run:
            return

    from patina.beliefs.extractor import extract_beliefs

    extract_beliefs(
        batch_size=batch_size,
        limit=limit,
        model=model,
        dry_run=dry_run,
        home=home,
    )


def _get_discovery_threshold(home: Path | None) -> int:
    import yaml

    from patina.store import DEFAULT_HOME

    config_path = (home or DEFAULT_HOME) / "config.yaml"
    if not config_path.exists():
        return 3
    try:
        with open(config_path) as f:
            config = yaml.safe_load(f) or {}
    except Exception:
        return 3
    return config.get("discovery", {}).get("zero_streak_threshold", 3)


def _write_journal_warning(home: Path | None, warning: str) -> None:
    import hashlib
    from datetime import UTC, datetime

    db_path = get_db_path(home)
    init_db(db_path)
    conn = connect(db_path)
    try:
        now = datetime.now(UTC).isoformat()
        today = datetime.now(UTC).strftime("%Y-%m-%d")
        entry_id = hashlib.sha256(f"journal:{today}:{now}".encode()).hexdigest()[:16]
        conn.execute(
            """INSERT INTO journal (id, date, body, entry_type, created_at)
               VALUES (?, ?, ?, 'note', ?)""",
            (entry_id, today, warning, now),
        )
        conn.commit()
    finally:
        conn.close()


@app.command()
def ingest(
    from_export: Path | None = typer.Option(None, "--from-export", help="Path to Slack export zip"),
    lookback_days: int = typer.Option(3, "--lookback-days", help="Days to look back for messages"),
    home: Path | None = typer.Option(None, "--home", help="Custom home directory"),
) -> None:
    """Ingest messages from export file or configured live adapters."""
    if from_export:
        if not from_export.exists():
            typer.echo(f"Error: {from_export} not found", err=True)
            raise typer.Exit(1)
        result = ingest_from_export(from_export, home=home)
    else:
        from patina.ingest import ingest_all

        result = ingest_all(home=home, lookback_days=lookback_days)
        adapters_run = result.get("adapters_run", 0)
        if adapters_run == 0:
            typer.echo(
                "No adapters configured. Use 'patina connect slack' "
                "or 'patina ingest --from-export <path>'."
            )
            return

    non_person = result.get("non_person_skipped", 0)
    non_person_msg = f", {non_person} non-person senders skipped" if non_person else ""
    typer.echo(
        f"Done. Inserted {result['messages_inserted']} messages "
        f"({result['messages_skipped']} skipped{non_person_msg}). "
        f"{result['entities_created']} entities found. "
        f"Total: {result['total_observations']} observations, "
        f"{result['total_entities']} entities."
    )

    channels_seen = result.get("channels_seen", 0)
    newly_watched = result.get("newly_watched", 0)
    typer.echo(f"Discovery: {channels_seen} channels seen, {newly_watched} newly watched")

    zero_streak = result.get("zero_streak", 0)
    threshold = _get_discovery_threshold(home)
    if channels_seen == 0 and zero_streak >= threshold:
        warning = (
            f"Warning: discovery returned 0 channels for "
            f"{zero_streak} consecutive runs. "
            f"Likely causes: adapter/bridge response-shape change, "
            f"permission loss, or no group DMs."
        )
        typer.echo(warning)
        _write_journal_warning(home, warning)


@app.command()
def status(
    home: Path | None = typer.Option(None, "--home", help="Custom home directory"),
) -> None:
    """Show database status."""
    db_path = get_db_path(home)
    if not db_path.exists():
        typer.echo("Patina not initialized. Run 'patina init' first.", err=True)
        raise typer.Exit(1)

    conn = connect(db_path)
    try:
        obs = count_observations(conn)
        people = count_entities(conn, "person")
        topics = count_entities(conn, "topic")
        refs = count_entities(conn, "reference")
        total = count_entities(conn)
        typer.echo(f"Observations: {obs}")
        typer.echo(f"Entities: {total} ({people} people, {topics} topics, {refs} references)")
    finally:
        conn.close()


def _format_age(staleness_days: float) -> str:
    if staleness_days < 1.0:
        hours = staleness_days * 24
        return f"{hours:.0f}h ago"
    return f"{staleness_days:.1f}d"


def _truncate(text: str, length: int = 60) -> str:
    if len(text) <= length:
        return text
    return text[: length - 3] + "..."


@app.command("catch-up")
def catch_up_cmd(
    days: int = typer.Option(3, "--days", help="Look back N days"),
    home: Path | None = typer.Option(None, "--home", help="Custom home directory"),
) -> None:
    """Show what needs your attention."""
    result = do_catch_up(home=home, days=days)

    typer.echo("── NEEDS ACTION NOW ──────────────────────────────")
    if result["needs_action"]:
        for item in result["needs_action"]:
            age = _format_age(item["staleness_days"])
            typer.echo(
                f"  ⚠ [{item['id'][:8]}] "
                f"{item['sender_name']}: "
                f"{_truncate(item['text'])} ({age} overdue)"
            )
    else:
        typer.echo("  (none)")

    typer.echo()
    typer.echo("── NEW ───────────────────────────────────────────")
    if result["new"]:
        for item in result["new"]:
            age = _format_age(item["staleness_days"])
            typer.echo(
                f"  • [{item['id'][:8]}] {item['sender_name']}: {_truncate(item['text'])} ({age})"
            )
    else:
        typer.echo("  (none)")

    typer.echo()
    typer.echo("── WAITING ───────────────────────────────────────")
    if result["waiting"]:
        for item in result["waiting"]:
            age = _format_age(item["staleness_days"])
            esc = item.get("escalation") or ""
            suffix = f", {esc}" if esc else ""
            typer.echo(
                f"  • [{item['id'][:8]}] "
                f"{item['sender_name']}: "
                f"{_truncate(item['text'])} ({age}{suffix})"
            )
    else:
        typer.echo("  (none)")


@app.command("priorities")
def priorities_cmd(
    days: int = typer.Option(7, "--days", help="Look back N days"),
    home: Path | None = typer.Option(None, "--home", help="Custom home directory"),
) -> None:
    """Show items grouped by priority quadrant."""
    result = do_priorities(home=home, days=days)

    labels = {
        "Q1": "Q1 — DO NOW (urgent + important)",
        "Q2": "Q2 — DELEGATE/DECLINE (urgent + not important)",
        "Q3": "Q3 — SCHEDULE (not urgent + important)",
        "Q4": "Q4 — DROP (not urgent + not important)",
    }

    for q in ["Q1", "Q2", "Q3", "Q4"]:
        typer.echo(f"── {labels[q]} ──")
        items = result[q]
        if items:
            for item in items:
                age = _format_age(item["staleness_days"])
                typer.echo(
                    f"  [{item['id'][:8]}] {item['sender_name']}: {_truncate(item['text'])} ({age})"
                )
        else:
            typer.echo("  (none)")
        typer.echo()


@app.command()
def dismiss(
    item_id: str = typer.Argument(..., help="Observation ID to dismiss"),
    home: Path | None = typer.Option(None, "--home", help="Custom home directory"),
) -> None:
    """Dismiss an observation."""
    db_path = get_db_path(home)
    if not db_path.exists():
        typer.echo("Patina not initialized. Run 'patina init' first.", err=True)
        raise typer.Exit(1)

    conn = connect(db_path)
    try:
        row = conn.execute(
            "SELECT id FROM observations WHERE id LIKE ?",
            (item_id + "%",),
        ).fetchone()
        if not row:
            typer.echo(f"No observation found matching '{item_id}'", err=True)
            raise typer.Exit(1)

        record_decision(conn, row["id"], "dismissed")
        typer.echo(f"Dismissed [{row['id'][:8]}]")
    finally:
        conn.close()


@objectives_app.command("add")
def objectives_add(
    label: str = typer.Argument(..., help="Objective label"),
    keywords: str = typer.Option("", "--keywords", help="Comma-separated keywords"),
    home: Path | None = typer.Option(None, "--home", help="Custom home directory"),
) -> None:
    """Add a new objective."""
    obj = add_objective(label, keywords, home=home)
    typer.echo(f"Added objective [{obj.id[:8]}] {obj.label}")


@objectives_app.command("list")
def objectives_list(
    home: Path | None = typer.Option(None, "--home", help="Custom home directory"),
) -> None:
    """List active objectives."""
    objs = list_objectives(home=home)
    if not objs:
        typer.echo("No objectives set.")
        return
    for obj in objs:
        kw = f" (keywords: {obj.keywords})" if obj.keywords else ""
        typer.echo(f"  [{obj.id[:8]}] {obj.label}{kw}")


@objectives_app.command("remove")
def objectives_remove(
    obj_id: str = typer.Argument(..., help="Objective ID to remove"),
    home: Path | None = typer.Option(None, "--home", help="Custom home directory"),
) -> None:
    """Remove an objective."""
    if remove_objective(obj_id, home=home):
        typer.echo(f"Removed objective [{obj_id[:8]}]")
    else:
        typer.echo(f"No objective found matching '{obj_id}'", err=True)
        raise typer.Exit(1)


def _find_entity_by_name(conn, name: str):
    row = conn.execute(
        "SELECT id, name FROM entities WHERE LOWER(name) LIKE ?",
        (f"%{name.lower()}%",),
    ).fetchone()
    return row


@style_app.command("build")
def style_build(
    home: Path | None = typer.Option(None, "--home", help="Custom home directory"),
) -> None:
    """Build style profiles from sent messages."""
    db_path = get_db_path(home)
    if not db_path.exists():
        typer.echo("Patina not initialized. Run 'patina init' first.", err=True)
        raise typer.Exit(1)

    conn = connect(db_path)
    try:
        from patina.owner import get_owner_entity_id

        owner_id = get_owner_entity_id(conn)
        if not owner_id:
            typer.echo(
                "No owner entity found. Run 'patina init' and set your user ID, "
                "then ingest messages first.",
                err=True,
            )
            raise typer.Exit(1)

        count = build_all_profiles(conn, owner_id)
        typer.echo(f"Built {count} style profile(s).")
    finally:
        conn.close()


@style_app.command("show")
def style_show(
    entity_name: str = typer.Argument(..., help="Entity name to look up"),
    home: Path | None = typer.Option(None, "--home", help="Custom home directory"),
) -> None:
    """Show style profile for an entity."""
    db_path = get_db_path(home)
    if not db_path.exists():
        typer.echo("Patina not initialized. Run 'patina init' first.", err=True)
        raise typer.Exit(1)

    conn = connect(db_path)
    try:
        row = _find_entity_by_name(conn, entity_name)
        if not row:
            typer.echo(f"No entity found matching '{entity_name}'", err=True)
            raise typer.Exit(1)

        import json

        profile = load_style_profile(conn, row["id"])
        if not profile:
            typer.echo(f"No style profile for {row['name']}.")
            return

        data = json.loads(profile)
        typer.echo(f"Style profile for {row['name']}:")
        for key, val in data.items():
            typer.echo(f"  {key}: {val}")
    finally:
        conn.close()


@app.command("draft")
def draft_cmd(
    to: str = typer.Option(..., "--to", help="Recipient entity name"),
    context: str = typer.Option(..., "--context", help="What to write about"),
    home: Path | None = typer.Option(None, "--home", help="Custom home directory"),
) -> None:
    """Generate a draft message."""
    db_path = get_db_path(home)
    if not db_path.exists():
        typer.echo("Patina not initialized. Run 'patina init' first.", err=True)
        raise typer.Exit(1)

    conn = connect(db_path)
    try:
        row = _find_entity_by_name(conn, to)
        if not row:
            typer.echo(f"No entity found matching '{to}'", err=True)
            raise typer.Exit(1)

        llm = MockLLM()
        draft_text = generate_draft(
            context=context,
            recipient_entity_id=row["id"],
            llm=llm,
            conn=conn,
        )
        typer.echo(f"Draft to {row['name']}:")
        typer.echo(draft_text)
    finally:
        conn.close()


@app.command("beliefs")
def beliefs_cmd(
    entity_type: str = typer.Option("all", "--type", help="Filter: person, topic, or all"),
    home: Path | None = typer.Option(None, "--home", help="Custom home directory"),
) -> None:
    """List entities with claim counts."""
    db_path = get_db_path(home)
    if not db_path.exists():
        typer.echo("Patina not initialized. Run 'patina init' first.", err=True)
        raise typer.Exit(1)

    conn = connect(db_path)
    try:
        if entity_type == "all":
            entities = conn.execute(
                "SELECT id, type, name FROM entities WHERE is_owner = 0 ORDER BY type, name"
            ).fetchall()
        else:
            entities = conn.execute(
                "SELECT id, type, name FROM entities WHERE type = ? AND is_owner = 0 ORDER BY name",
                (entity_type,),
            ).fetchall()

        if not entities:
            typer.echo("No entities found.")
            return

        for ent in entities:
            claim_count = conn.execute(
                "SELECT COUNT(*) AS c FROM claims WHERE subject_id = ?",
                (ent["id"],),
            ).fetchone()["c"]
            rel_count = conn.execute(
                "SELECT COUNT(*) AS c FROM relationships WHERE subject_id = ? OR object_id = ?",
                (ent["id"], ent["id"]),
            ).fetchone()["c"]
            typer.echo(
                f"  [{ent['type']}] {ent['name']}: {claim_count} claims, {rel_count} relationships"
            )
    finally:
        conn.close()


@app.command("stale")
def stale_cmd(
    threshold: float = typer.Option(0.3, "--threshold", help="Confidence threshold"),
    home: Path | None = typer.Option(None, "--home", help="Custom home directory"),
) -> None:
    """Show beliefs below confidence threshold."""
    db_path = get_db_path(home)
    if not db_path.exists():
        typer.echo("Patina not initialized. Run 'patina init' first.", err=True)
        raise typer.Exit(1)

    conn = connect(db_path)
    try:
        stale = get_stale_beliefs(conn, threshold)
        if not stale:
            typer.echo("No stale beliefs found.")
            return

        typer.echo(f"Stale beliefs (confidence < {threshold}):")
        for item in stale:
            typer.echo(
                f"  [{item['type']}] {item['subject_name']} "
                f"{item['predicate']} {item['object']} "
                f"(conf={item['effective_confidence']:.2f}, "
                f"{item['days_since_confirmed']:.0f}d old)"
            )
    finally:
        conn.close()


@app.command("contradictions")
def contradictions_cmd(
    home: Path | None = typer.Option(None, "--home", help="Custom home directory"),
) -> None:
    """Find contradictory claims."""
    db_path = get_db_path(home)
    if not db_path.exists():
        typer.echo("Patina not initialized. Run 'patina init' first.", err=True)
        raise typer.Exit(1)

    conn = connect(db_path)
    try:
        results = find_contradictions_tier1(conn)
        if not results:
            typer.echo("No contradictions found.")
            return

        typer.echo(f"Found {len(results)} contradiction(s):")
        for item in results:
            typer.echo(
                f"  {item['subject']} {item['predicate']}:\n"
                f"    A: {item['object_1']} (conf={item['confidence_1']:.2f})\n"
                f"    B: {item['object_2']} (conf={item['confidence_2']:.2f})"
            )
    finally:
        conn.close()


@app.command("relationships")
def relationships_cmd(
    top: int = typer.Option(20, "--top", help="Number of relationships to show"),
    home: Path | None = typer.Option(None, "--home", help="Custom home directory"),
) -> None:
    """Show relationship map."""
    db_path = get_db_path(home)
    if not db_path.exists():
        typer.echo("Patina not initialized. Run 'patina init' first.", err=True)
        raise typer.Exit(1)

    conn = connect(db_path)
    try:
        rels = get_relationship_map(conn, top_n=top)
        if not rels:
            typer.echo("No relationships found.")
            return

        typer.echo(f"{'Name':<25} {'Trust':<7} {'Activity':<15} {'Msgs/wk':<9} {'Last'}")
        typer.echo("─" * 70)
        for r in rels:
            days = f"{r['days_since_last']:.0f}d ago" if r["days_since_last"] else "never"
            typer.echo(
                f"  {r['name']:<23} {r['trust_level']:<7.2f} "
                f"{r['activity_status']:<15} {r['avg_per_week']:<9.1f} {days}"
            )
    finally:
        conn.close()


@autonomy_app.command("status")
def autonomy_status(
    home: Path | None = typer.Option(None, "--home", help="Custom home directory"),
) -> None:
    """Show autonomy level and stats per domain."""
    db_path = get_db_path(home)
    if not db_path.exists():
        typer.echo("Patina not initialized. Run 'patina init' first.", err=True)
        raise typer.Exit(1)

    conn = connect(db_path)
    try:
        typer.echo(f"{'Domain':<10} {'Level':<8} {'Description':<40} {'Frozen':<8} {'Advance'}")
        typer.echo("─" * 90)
        for domain in DOMAINS:
            level = current_level(conn, domain)
            desc = level_description(level)
            frozen = is_frozen(conn, domain)
            can, reason = can_advance(conn, level, domain)
            advance = f"Ready: {reason}" if can else reason
            typer.echo(
                f"  {domain:<8} {level:<8} {desc:<40} {'yes' if frozen else 'no':<8} {advance}"
            )
    finally:
        conn.close()


@autonomy_app.command("pending")
def autonomy_pending(
    home: Path | None = typer.Option(None, "--home", help="Custom home directory"),
) -> None:
    """List proposed actions awaiting approval."""
    db_path = get_db_path(home)
    if not db_path.exists():
        typer.echo("Patina not initialized. Run 'patina init' first.", err=True)
        raise typer.Exit(1)

    conn = connect(db_path)
    try:
        pending = list_pending(conn)
        if not pending:
            typer.echo("No pending actions.")
            return
        for item in pending:
            typer.echo(
                f"  [{item['id'][:8]}] {item['action_type']} "
                f"(conf={item['confidence']:.2f}, level={item['autonomy_level']})"
            )
    finally:
        conn.close()


@autonomy_app.command("set-level")
def autonomy_set_level(
    level: int = typer.Argument(..., help="Level to set (0-6)"),
    home: Path | None = typer.Option(None, "--home", help="Custom home directory"),
) -> None:
    """Manually set autonomy level."""
    if level < 0 or level > 6:
        typer.echo("Level must be 0-6", err=True)
        raise typer.Exit(1)

    db_path = get_db_path(home)
    if not db_path.exists():
        typer.echo("Patina not initialized. Run 'patina init' first.", err=True)
        raise typer.Exit(1)

    conn = connect(db_path)
    try:
        set_level(conn, level)
        typer.echo(f"Set autonomy level to {level} — {level_description(level)}")
    finally:
        conn.close()


@autonomy_app.command("anti-patterns")
def autonomy_anti_patterns(
    home: Path | None = typer.Option(None, "--home", help="Custom home directory"),
) -> None:
    """List stored anti-patterns."""
    db_path = get_db_path(home)
    if not db_path.exists():
        typer.echo("Patina not initialized. Run 'patina init' first.", err=True)
        raise typer.Exit(1)

    conn = connect(db_path)
    try:
        patterns = get_anti_patterns(conn)
        if not patterns:
            typer.echo("No anti-patterns stored.")
            return
        for p in patterns:
            kw = ", ".join(p["text_keywords"]) if p["text_keywords"] else "none"
            typer.echo(
                f"  [{p['id'][:8]}] {p['pattern_type']} "
                f"(from level {p['from_level']}): "
                f"keywords=[{kw}] "
                f"wrong={p['wrong_action']} correct={p['correct_action']}"
            )
    finally:
        conn.close()


@autonomy_app.command("clear-pattern")
def autonomy_clear_pattern(
    pattern_id: str = typer.Argument(..., help="Anti-pattern ID to remove"),
    home: Path | None = typer.Option(None, "--home", help="Custom home directory"),
) -> None:
    """Remove an anti-pattern."""
    db_path = get_db_path(home)
    if not db_path.exists():
        typer.echo("Patina not initialized. Run 'patina init' first.", err=True)
        raise typer.Exit(1)

    conn = connect(db_path)
    try:
        if clear_anti_pattern(conn, pattern_id):
            typer.echo(f"Removed anti-pattern [{pattern_id[:8]}]")
        else:
            typer.echo(f"No anti-pattern found matching '{pattern_id}'", err=True)
            raise typer.Exit(1)
    finally:
        conn.close()


@autonomy_app.command("evaluate")
def autonomy_evaluate(
    dry_run: bool = typer.Option(False, "--dry-run", help="Preview without changing state"),
    home: Path | None = typer.Option(None, "--home", help="Custom home directory"),
) -> None:
    """Evaluate one step of the autonomy ladder."""
    db_path = get_db_path(home)
    if not db_path.exists():
        typer.echo("Patina not initialized. Run 'patina init' first.", err=True)
        raise typer.Exit(1)

    conn = connect(db_path)
    try:
        if dry_run:
            level = current_level(conn)
            should_demote, reason, _items = check_demotion(conn, level)
            if should_demote:
                typer.echo(f"Would demote: level {level} → {level - 1} ({reason})")
                return
            can, reason = can_advance(conn, level)
            if can:
                typer.echo(f"Would advance: level {level} → {level + 1} ({reason})")
                return
            typer.echo(f"No change (level {level}): {reason}")
        else:
            result = evaluate_autonomy(conn)
            if result:
                typer.echo(
                    f"Level {result['from']} → {result['to']} "
                    f"({result['direction']}): {result['reason']}"
                )
            else:
                level = current_level(conn)
                typer.echo(f"No change (level {level})")
    finally:
        conn.close()


@app.command("approve")
def approve_cmd(
    action_id: str = typer.Argument(..., help="Action ID to approve"),
    home: Path | None = typer.Option(None, "--home", help="Custom home directory"),
) -> None:
    """Approve a proposed action."""
    db_path = get_db_path(home)
    if not db_path.exists():
        typer.echo("Patina not initialized. Run 'patina init' first.", err=True)
        raise typer.Exit(1)

    conn = connect(db_path)
    try:
        if approve_action(conn, action_id):
            typer.echo(f"Approved [{action_id[:8]}]")
        else:
            typer.echo(f"No pending action found matching '{action_id}'", err=True)
            raise typer.Exit(1)
    finally:
        conn.close()


@app.command("reject")
def reject_cmd(
    action_id: str = typer.Argument(..., help="Action ID to reject"),
    home: Path | None = typer.Option(None, "--home", help="Custom home directory"),
) -> None:
    """Reject a proposed action (freezes advancement)."""
    db_path = get_db_path(home)
    if not db_path.exists():
        typer.echo("Patina not initialized. Run 'patina init' first.", err=True)
        raise typer.Exit(1)

    conn = connect(db_path)
    try:
        if reject_action(conn, action_id):
            typer.echo(f"Rejected [{action_id[:8]}]. Advancement frozen for 7 days.")
        else:
            typer.echo(f"No pending action found matching '{action_id}'", err=True)
            raise typer.Exit(1)
    finally:
        conn.close()


@entity_app.command("merge")
def entity_merge_cmd(
    keep: str = typer.Argument(..., help="Entity ID to keep"),
    drop: str = typer.Argument(..., help="Entity ID to merge into keep and delete"),
    dry_run: bool = typer.Option(False, "--dry-run", help="Preview without writing"),
    home: Path | None = typer.Option(None, "--home", help="Custom home directory"),
) -> None:
    """Merge entity DROP into KEEP, rewiring all references."""
    from patina.maintenance import backup_store, merge_entities

    db_path = get_db_path(home)
    if not db_path.exists():
        typer.echo("Patina not initialized. Run 'patina init' first.", err=True)
        raise typer.Exit(1)

    conn = connect(db_path)
    try:
        keep_rows = conn.execute(
            "SELECT id, name FROM entities WHERE id LIKE ?",
            (keep + "%",),
        ).fetchall()
        drop_rows = conn.execute(
            "SELECT id, name FROM entities WHERE id LIKE ?",
            (drop + "%",),
        ).fetchall()

        if not keep_rows:
            typer.echo(f"No entity found matching '{keep}'", err=True)
            raise typer.Exit(1)
        if len(keep_rows) > 1:
            matches = ", ".join(f"{r['id']} ({r['name']})" for r in keep_rows)
            typer.echo(
                f"Ambiguous keep ID '{keep}' matches {len(keep_rows)} entities: {matches}",
                err=True,
            )
            raise typer.Exit(1)
        if not drop_rows:
            typer.echo(f"No entity found matching '{drop}'", err=True)
            raise typer.Exit(1)
        if len(drop_rows) > 1:
            matches = ", ".join(f"{r['id']} ({r['name']})" for r in drop_rows)
            typer.echo(
                f"Ambiguous drop ID '{drop}' matches {len(drop_rows)} entities: {matches}",
                err=True,
            )
            raise typer.Exit(1)

        keep_row = keep_rows[0]
        drop_row = drop_rows[0]

        if not dry_run:
            backup_path = backup_store(db_path)
            typer.echo(f"Backup: {backup_path}")

        result = merge_entities(conn, keep_row["id"], drop_row["id"], dry_run=dry_run)

        mode = "Would merge" if dry_run else "Merged"
        typer.echo(f"{mode} '{result['drop_name']}' into '{result['keep_name']}'")
        typer.echo(f"  Observations: {result['observations_moved']}")
        typer.echo(f"  Claims: {result['claims_moved']}")
        typer.echo(f"  Relationships: {result['relationships_moved']}")
    except ValueError as e:
        typer.echo(f"Error: {e}", err=True)
        raise typer.Exit(1)
    finally:
        conn.close()


@entity_app.command("dedup")
def entity_dedup_cmd(
    dry_run: bool = typer.Option(False, "--dry-run", help="Preview without writing"),
    home: Path | None = typer.Option(None, "--home", help="Custom home directory"),
) -> None:
    """Deduplicate entities by normalized name."""
    from patina.maintenance import backup_store, dedup_entities

    db_path = get_db_path(home)
    if not db_path.exists():
        typer.echo("Patina not initialized. Run 'patina init' first.", err=True)
        raise typer.Exit(1)

    conn = connect(db_path)
    try:
        if not dry_run:
            backup_path = backup_store(db_path)
            typer.echo(f"Backup: {backup_path}")

        result = dedup_entities(conn, dry_run=dry_run)

        if result["groups"] == 0:
            typer.echo("No duplicate entities found.")
            return

        mode = "Dry run" if dry_run else "Dedup"
        typer.echo(f"{mode}: {result['groups']} group(s), {result['entities_merged']} merge(s)")
        for merge in result["merges"]:
            typer.echo(f"  '{merge['drop_name']}' -> '{merge['keep_name']}'")
    finally:
        conn.close()


@entity_app.command("prune")
def entity_prune_cmd(
    non_person: bool = typer.Option(False, "--non-person", help="Remove non-person entities"),
    dry_run: bool = typer.Option(False, "--dry-run", help="Preview without writing"),
    home: Path | None = typer.Option(None, "--home", help="Custom home directory"),
) -> None:
    """Prune entities matching filter criteria."""
    from patina.maintenance import backup_store, prune_non_person_entities

    if not non_person:
        typer.echo("Specify a filter: --non-person", err=True)
        raise typer.Exit(1)

    db_path = get_db_path(home)
    if not db_path.exists():
        typer.echo("Patina not initialized. Run 'patina init' first.", err=True)
        raise typer.Exit(1)

    conn = connect(db_path)
    try:
        if not dry_run:
            backup_path = backup_store(db_path)
            typer.echo(f"Backup: {backup_path}")

        result = prune_non_person_entities(conn, dry_run=dry_run)

        if result["pruned"] == 0:
            typer.echo("No non-person entities found.")
            return

        mode = "Would prune" if dry_run else "Pruned"
        typer.echo(f"{mode} {result['pruned']} non-person entity(ies):")
        for ent in result["entities"]:
            typer.echo(f"  {ent['name']}")
    finally:
        conn.close()


@entity_app.command("list")
def entity_list_cmd(
    entity_type: str = typer.Option(
        "all", "--type", help="Filter: person, topic, reference, or all"
    ),
    home: Path | None = typer.Option(None, "--home", help="Custom home directory"),
) -> None:
    """List all entities."""
    db_path = get_db_path(home)
    if not db_path.exists():
        typer.echo("Patina not initialized. Run 'patina init' first.", err=True)
        raise typer.Exit(1)

    conn = connect(db_path)
    try:
        if entity_type == "all":
            rows = conn.execute(
                "SELECT id, type, name FROM entities ORDER BY type, name"
            ).fetchall()
        else:
            rows = conn.execute(
                "SELECT id, type, name FROM entities WHERE type = ? ORDER BY name",
                (entity_type,),
            ).fetchall()

        if not rows:
            typer.echo("No entities found.")
            return

        for r in rows:
            typer.echo(f"  [{r['type']}] {r['id'][:8]} {r['name']}")
    finally:
        conn.close()


@app.command("backfill-decisions")
def backfill_decisions_cmd(
    dry_run: bool = typer.Option(False, "--dry-run", help="Preview count without writing"),
    home: Path | None = typer.Option(None, "--home", help="Custom home directory"),
) -> None:
    """Backfill decisions from historical reactions by the owner."""
    from patina.backfill import run_backfill

    result = run_backfill(home=home, dry_run=dry_run)

    if result.get("error") == "no_owner_ids":
        typer.echo(
            "No owner user IDs configured. Set owner.user_ids in config.yaml first.",
            err=True,
        )
        raise typer.Exit(1)

    mode = "Dry run" if dry_run else "Backfill"
    typer.echo(f"{mode} complete.")
    typer.echo(f"  Observations with reactions: {result['scanned']}")
    typer.echo(f"  Decisions inserted: {result['inserted']}")
    typer.echo(f"  Already had decision: {result['skipped']}")


connect_app = typer.Typer(help="Connect live data sources.")
app.add_typer(connect_app, name="connect")


def _ensure_config(home: Path | None) -> Path:
    import yaml

    config_dir = home or (Path.home() / ".patina")
    config_dir.mkdir(parents=True, exist_ok=True)
    config_path = config_dir / "config.yaml"
    if not config_path.exists():
        config_path.write_text(yaml.dump({"adapters": {"chat": [], "email": []}}))
    return config_path


@connect_app.command("slack")
def connect_slack(
    token: str = typer.Option(..., "--token", help="Slack bot or user token"),
    home: Path | None = typer.Option(None, "--home", help="Custom home directory"),
) -> None:
    """Connect a Slack workspace."""
    import yaml

    config_path = _ensure_config(home)
    with open(config_path) as f:
        config = yaml.safe_load(f) or {}

    adapters = config.setdefault("adapters", {})
    chat_list = adapters.setdefault("chat", [])

    for existing in chat_list:
        if existing.get("provider") == "slack":
            existing["token"] = token
            break
    else:
        chat_list.append({"provider": "slack", "token": token})

    with open(config_path, "w") as f:
        yaml.dump(config, f)

    typer.echo(f"Slack connected. Token saved to {config_path}")


@connect_app.command("email")
def connect_email(
    host: str = typer.Option(..., "--host", help="IMAP host"),
    port: int = typer.Option(993, "--port", help="IMAP port"),
    username: str = typer.Option(..., "--username", help="Email username"),
    password: str = typer.Option(..., "--password", help="Email password"),
    home: Path | None = typer.Option(None, "--home", help="Custom home directory"),
) -> None:
    """Connect an email account via IMAP."""
    import yaml

    config_path = _ensure_config(home)
    with open(config_path) as f:
        config = yaml.safe_load(f) or {}

    adapters = config.setdefault("adapters", {})
    email_list = adapters.setdefault("email", [])

    email_list.append(
        {
            "provider": "imap",
            "host": host,
            "port": port,
            "username": username,
            "password": password,
            "use_ssl": True,
        }
    )

    with open(config_path, "w") as f:
        yaml.dump(config, f)

    typer.echo(f"Email connected. Settings saved to {config_path}")


@heartbeat_app.command("once")
def heartbeat_once_cmd(
    home: Path | None = typer.Option(None, "--home", help="Custom home directory"),
) -> None:
    """Run all heartbeat tasks once and exit."""
    from patina.scheduler import heartbeat_once

    result = heartbeat_once(home=home)
    typer.echo(f"Heartbeat complete. Tasks run: {', '.join(result['tasks_run'])}")
    if result.get("ingest"):
        i = result["ingest"]
        np = i.get("non_person_skipped", 0)
        np_msg = f", {np} non-person skipped" if np else ""
        typer.echo(
            f"  Ingest: {i['messages_inserted']} new, {i['messages_skipped']} skipped{np_msg}"
        )
    if result.get("decay"):
        typer.echo(f"  Decay: {result['decay']['stale_count']} beliefs below threshold")
    if result.get("escalation"):
        typer.echo(f"  Escalation: {result['escalation']['shifts']} urgency shifts detected")
    if result.get("autonomy"):
        a = result["autonomy"]
        typer.echo(f"  Autonomy: level {a['from']} → {a['to']} ({a['direction']}): {a['reason']}")
    if result["errors"]:
        for err in result["errors"]:
            typer.echo(f"  Error: {err}", err=True)


@heartbeat_app.command("start")
def heartbeat_start_cmd(
    interval: int = typer.Option(30, "--interval", help="Minutes between heartbeats"),
    home: Path | None = typer.Option(None, "--home", help="Custom home directory"),
) -> None:
    """Run heartbeat continuously at configured interval."""
    from patina.scheduler import heartbeat_start

    typer.echo(f"Starting heartbeat (every {interval}m). Press Ctrl+C to stop.")
    heartbeat_start(interval_minutes=interval, home=home)


@owner_app.command("merge")
def owner_merge(
    home: Path | None = typer.Option(None, "--home", help="Custom home directory"),
    dry_run: bool = typer.Option(False, "--dry-run", help="Show candidates without modifying"),
) -> None:
    """Fold duplicate self-entities into the canonical owner entity."""
    import json

    from patina.owner import get_owner_entity_id, get_owner_identifiers, normalize_alias

    db_path = get_db_path(home)
    if not db_path.exists():
        typer.echo("Patina not initialized. Run 'patina init' first.", err=True)
        raise typer.Exit(1)

    identifiers = get_owner_identifiers(home)
    if not identifiers:
        typer.echo("No owner identifiers configured. Nothing to merge.")
        return

    conn = connect(db_path)
    try:
        owner_id = get_owner_entity_id(conn)
        if not owner_id:
            typer.echo("No canonical owner entity found (is_owner=1). Nothing to merge.")
            return

        normalized_ids = set()
        for ident in identifiers:
            normalized_ids.add(ident.lower())
            stripped = normalize_alias(ident)
            if stripped != ident:
                normalized_ids.add(stripped.lower())

        all_entities = conn.execute(
            "SELECT id, name, aliases FROM entities WHERE is_owner = 0"
        ).fetchall()

        candidates: list[tuple[str, str, str]] = []  # (entity_id, name, match_reason)
        for ent in all_entities:
            if ent["id"] == owner_id:
                continue
            name = ent["name"]
            if name.lower() in normalized_ids:
                reason = f"name '{name}' matches owner id"
                candidates.append((ent["id"], name, reason))
                continue
            stripped_name = normalize_alias(name)
            if stripped_name.lower() in normalized_ids:
                reason = f"name '{name}' matches owner id (stripped)"
                candidates.append((ent["id"], name, reason))
                continue
            aliases = json.loads(ent["aliases"] or "[]")
            for alias in aliases:
                if alias.lower() in normalized_ids:
                    reason = f"alias '{alias}' matches owner id"
                    candidates.append((ent["id"], name, reason))
                    break
                stripped_alias = normalize_alias(alias)
                if stripped_alias.lower() in normalized_ids:
                    reason = f"alias '{alias}' matches owner id (stripped)"
                    candidates.append((ent["id"], name, reason))
                    break

        if not candidates:
            typer.echo("No duplicate owner entities found. Nothing to merge.")
            return

        name_matches_owner = set()
        for ident in identifiers:
            name_matches_owner.add(ident.lower())
            s = normalize_alias(ident)
            if s != ident:
                name_matches_owner.add(s.lower())

        merge_ids = []
        for ent_id, ent_name, match_reason in candidates:
            obs_count = conn.execute(
                "SELECT COUNT(*) AS c FROM observations WHERE sender_entity_id = ?",
                (ent_id,),
            ).fetchone()["c"]
            claim_count = conn.execute(
                "SELECT COUNT(*) AS c FROM claims WHERE subject_id = ?",
                (ent_id,),
            ).fetchone()["c"]
            rel_count = conn.execute(
                "SELECT COUNT(*) AS c FROM relationships WHERE subject_id = ? OR object_id = ?",
                (ent_id, ent_id),
            ).fetchone()["c"]

            ent_name_norm = normalize_alias(ent_name).lower()
            name_is_owner = (
                ent_name.lower() in name_matches_owner or ent_name_norm in name_matches_owner
            )
            if not name_is_owner and obs_count > 0:
                typer.echo(
                    f"SKIP {ent_id} ({ent_name}): matched by {match_reason} "
                    f"but has {obs_count} sent observation(s) under non-owner identity"
                )
                continue

            if dry_run:
                typer.echo(
                    f"CANDIDATE {ent_id} ({ent_name}): {match_reason} — "
                    f"observations: {obs_count}, claims: {claim_count}, "
                    f"relationships: {rel_count}"
                )
            else:
                merge_ids.append(ent_id)

        if dry_run:
            return

        if not merge_ids:
            typer.echo("No safe candidates to merge after safety checks.")
            return

        observations_moved = 0
        claims_moved = 0
        relationships_moved = 0

        for dup_id in merge_ids:
            cursor = conn.execute(
                "UPDATE observations SET sender_entity_id = ? WHERE sender_entity_id = ?",
                (owner_id, dup_id),
            )
            observations_moved += cursor.rowcount

            dup_claims = conn.execute(
                "SELECT id, predicate, object FROM claims WHERE subject_id = ?",
                (dup_id,),
            ).fetchall()
            for claim in dup_claims:
                existing = conn.execute(
                    "SELECT id FROM claims WHERE subject_id = ? AND predicate = ? AND object = ?",
                    (owner_id, claim["predicate"], claim["object"]),
                ).fetchone()
                if existing:
                    conn.execute("DELETE FROM claims WHERE id = ?", (claim["id"],))
                else:
                    conn.execute(
                        "UPDATE claims SET subject_id = ? WHERE id = ?",
                        (owner_id, claim["id"]),
                    )
                claims_moved += 1

            dup_rels = conn.execute(
                "SELECT id, subject_id, predicate, object_id FROM relationships "
                "WHERE subject_id = ? OR object_id = ?",
                (dup_id, dup_id),
            ).fetchall()
            for rel in dup_rels:
                new_subject = owner_id if rel["subject_id"] == dup_id else rel["subject_id"]
                new_object = owner_id if rel["object_id"] == dup_id else rel["object_id"]
                existing = conn.execute(
                    "SELECT id FROM relationships "
                    "WHERE subject_id = ? AND predicate = ? AND object_id = ?",
                    (new_subject, rel["predicate"], new_object),
                ).fetchone()
                if existing:
                    conn.execute("DELETE FROM relationships WHERE id = ?", (rel["id"],))
                else:
                    conn.execute(
                        "UPDATE relationships SET subject_id = ?, object_id = ? WHERE id = ?",
                        (new_subject, new_object, rel["id"]),
                    )
                relationships_moved += 1

            conn.execute("DELETE FROM entities WHERE id = ?", (dup_id,))

        conn.commit()

        typer.echo(
            f"Merged {len(merge_ids)} duplicate(s) into owner entity. "
            f"Observations: {observations_moved}, "
            f"claims: {claims_moved}, "
            f"relationships: {relationships_moved}."
        )
    finally:
        conn.close()


@app.command("chat")
def chat_cmd(
    home: Path | None = typer.Option(None, "--home", help="Custom home directory"),
) -> None:
    """Start interactive conversation with your cognitive partner."""
    import asyncio

    from patina.agent.config import load_config
    from patina.agent.runtime import AgentRuntime
    from patina.conversations import store_exchange

    config = load_config()
    config.repl_mode = True
    runtime = AgentRuntime(config)

    db_path = get_db_path(home)
    init_db(db_path)
    conn = connect(db_path)

    last_checkpoint = conn.execute(
        """SELECT body FROM journal WHERE entry_type = 'session_end'
           ORDER BY created_at DESC LIMIT 1"""
    ).fetchone()
    if last_checkpoint:
        typer.echo("Resuming from last session checkpoint.")
    else:
        typer.echo("Welcome to Patina. Type /quit to exit.")

    async def _chat_loop():
        import readline  # noqa: F401 — enables arrow-key history for input()

        from claude_agent_sdk import ResultMessage

        try:
            while True:
                try:
                    user_input = await asyncio.to_thread(input, "\n> ")
                except (KeyboardInterrupt, EOFError):
                    typer.echo("\nCheckpointing session...")
                    break

                if user_input.strip() in ("/quit", "/exit"):
                    typer.echo("Checkpointing session...")
                    break

                if not user_input.strip():
                    continue

                store_exchange(conn, "repl-local", "default", "user", user_input)

                from patina.spinner import Spinner

                spinner = Spinner("Thinking")
                spinner.start()
                response_parts: list[str] = []
                try:
                    async for message in runtime.query(user_input):
                        if isinstance(message, ResultMessage):
                            spinner.stop()
                            text = message.result if hasattr(message, "result") else ""
                            response_parts.append(text)
                finally:
                    spinner.stop()

                response_text = "".join(response_parts)
                if response_text:
                    from rich.console import Console
                    from rich.markdown import Markdown

                    console = Console()
                    console.print(Markdown(response_text))
                    store_exchange(conn, "repl-local", "default", "assistant", response_text)
        finally:
            conn.close()

    asyncio.run(_chat_loop())


@app.command("serve")
def serve_cmd(
    port: int = typer.Option(8321, "--port", help="Port to listen on"),
    host: str = typer.Option("127.0.0.1", "--host", help="Host to bind to"),
) -> None:
    """Start HTTP server for gateway integration."""
    import uvicorn

    from patina.serve import create_app

    http_app = create_app()
    typer.echo(f"Starting Patina server on {host}:{port}")
    uvicorn.run(http_app, host=host, port=port)


@app.command("gateway")
def gateway_cmd(
    home: Path | None = typer.Option(None, "--home", help="Custom home directory"),
) -> None:
    """Start messaging gateway (connects Telegram/Slack to agent)."""
    import asyncio

    from patina.gateway.base import load_gateway_config
    from patina.gateway.telegram import TelegramAdapter

    config = load_gateway_config()
    adapters = []

    if config.telegram.enabled:
        if not config.telegram.token:
            typer.echo("Error: Telegram token not configured", err=True)
            raise typer.Exit(1)
        adapters.append(
            TelegramAdapter(
                token=config.telegram.token,
                agent_url=config.agent_url,
                allowed_users=config.telegram.allowed_users or None,
            )
        )

    if not adapters:
        typer.echo("No adapters enabled. Configure ~/.patina/gateway.yaml first.")
        raise typer.Exit(1)

    typer.echo(f"Starting gateway with {len(adapters)} adapter(s)...")

    async def _run():
        for adapter in adapters:
            await adapter.start()
        typer.echo("Gateway running. Press Ctrl+C to stop.")
        try:
            await asyncio.Event().wait()
        except (KeyboardInterrupt, asyncio.CancelledError):
            pass
        finally:
            for adapter in adapters:
                await adapter.stop()
            typer.echo("Gateway stopped.")

    asyncio.run(_run())
