from __future__ import annotations

from pathlib import Path

import typer

from patina.autonomy.actions import (
    approve_action,
    list_pending,
    reject_action,
)
from patina.autonomy.levels import (
    can_advance,
    current_level,
    is_frozen,
    level_description,
    set_level,
)
from patina.autonomy.tracker import (
    clear_anti_pattern,
    get_accuracy_stats,
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
heartbeat_app = typer.Typer(help="Background heartbeat tasks.")
app.add_typer(heartbeat_app, name="heartbeat")


@app.command()
def init(
    home: Path | None = typer.Option(None, "--home", help="Custom home directory"),
) -> None:
    """Initialize the Patina database."""
    db_path = get_db_path(home)
    init_db(db_path)
    typer.echo(f"Initialized Patina at {db_path}")


@app.command()
def ingest(
    from_export: Path | None = typer.Option(None, "--from-export", help="Path to Slack export zip"),
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

        result = ingest_all(home=home)
        adapters_run = result.get("adapters_run", 0)
        if adapters_run == 0:
            typer.echo(
                "No adapters configured. Use 'patina connect slack' "
                "or 'patina ingest --from-export <path>'."
            )
            return

    typer.echo(
        f"Done. Inserted {result['messages_inserted']} messages "
        f"({result['messages_skipped']} skipped). "
        f"{result['entities_created']} entities found. "
        f"Total: {result['total_observations']} observations, "
        f"{result['total_entities']} entities."
    )


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
    user: str = typer.Option("U000SELF", "--user", help="User entity ID"),
) -> None:
    """Build style profiles from sent messages."""
    db_path = get_db_path(home)
    if not db_path.exists():
        typer.echo("Patina not initialized. Run 'patina init' first.", err=True)
        raise typer.Exit(1)

    conn = connect(db_path)
    try:
        from patina.extraction import _make_id

        user_eid = _make_id("person", user)
        count = build_all_profiles(conn, user_eid)
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
                "SELECT id, type, name FROM entities ORDER BY type, name"
            ).fetchall()
        else:
            entities = conn.execute(
                "SELECT id, type, name FROM entities WHERE type = ? ORDER BY name",
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
    """Show autonomy level and stats."""
    db_path = get_db_path(home)
    if not db_path.exists():
        typer.echo("Patina not initialized. Run 'patina init' first.", err=True)
        raise typer.Exit(1)

    conn = connect(db_path)
    try:
        level = current_level(conn)
        desc = level_description(level)
        frozen = is_frozen(conn)
        stats = get_accuracy_stats(conn)
        patterns = get_anti_patterns(conn)
        can, reason = can_advance(conn, level)

        typer.echo(f"Level: {level} — {desc}")
        typer.echo(f"Frozen: {'yes' if frozen else 'no'}")
        typer.echo(
            f"Accuracy: {stats['accuracy_rate']:.0%} ({stats['correct']}/{stats['total']} correct)"
        )
        typer.echo(f"Anti-patterns: {len(patterns)}")
        if can:
            typer.echo(f"Ready to advance: {reason}")
        else:
            typer.echo(f"Next advancement: {reason}")
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
        typer.echo(f"  Ingest: {i['messages_inserted']} new, {i['messages_skipped']} skipped")
    if result.get("decay"):
        typer.echo(f"  Decay: {result['decay']['stale_count']} beliefs below threshold")
    if result.get("escalation"):
        typer.echo(f"  Escalation: {result['escalation']['shifts']} urgency shifts detected")
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
