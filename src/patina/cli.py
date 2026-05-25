from __future__ import annotations

from pathlib import Path

import typer

from patina.graph import count_entities, count_observations
from patina.ingest import ingest_from_export
from patina.store import connect, get_db_path, init_db

app = typer.Typer(help="Patina — a cognitive app that compounds.")


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
