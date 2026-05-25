from __future__ import annotations

from pathlib import Path

import typer

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
    from_export: Path = typer.Option(..., "--from-export", help="Path to Slack export zip"),
    home: Path | None = typer.Option(None, "--home", help="Custom home directory"),
) -> None:
    """Ingest messages from a Slack export."""
    if not from_export.exists():
        typer.echo(f"Error: {from_export} not found", err=True)
        raise typer.Exit(1)

    result = ingest_from_export(from_export, home=home)
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
