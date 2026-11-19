"""Refresh a recorded key set in tests/adapters/recorded_keysets/ (#689).

Reads one tool payload, reduces it to the items the adapter sees, and rewrites
``recorded_keysets/<tool>.json`` as a map of dotted key path to JSON type name
(the ``tests.adapters.keyset`` format). Only key names and type names are
written or printed, never payload values.

The payload comes from ``--payload-file``, from stdin when no source flag is
given, or with ``--live`` from one ``call_tool`` call on the MCP bridge that
``patina.ingest._make_mcp_adapter`` builds from ``~/.patina/config.yaml``.
On any error the recorded file is left unchanged.

Usage:
    uv run python scripts/refresh_keyset.py --tool TOOL [--payload-file PATH | --live]
        [--channel ID]
"""

from __future__ import annotations

import argparse
import json
import os
import sys
import tempfile
from dataclasses import dataclass, field
from datetime import date, timedelta
from pathlib import Path
from typing import Any

sys.path.insert(0, str(Path(__file__).resolve().parent.parent))

import yaml
from tests.adapters.keyset import RECORDED_DIR, extract_items_keyset

import patina.ingest as ingest
import patina.store as store_module
from patina.adapters._mcp_client import parse_json_content, parse_outlook_content
from patina.adapters.outlook_mcp import _unwrap_email_list


@dataclass(frozen=True)
class ToolSpec:
    section: str  # adapters.<section> in config.yaml
    provider: str
    mcp_tool: str
    arguments: dict = field(default_factory=dict)


TOOLS = {
    "email_inbox": ToolSpec(
        "email", "outlook_mcp", "email_inbox", {"limit": 50, "unreadOnly": False}
    ),
    "calendar_view": ToolSpec("calendar", "outlook_mcp", "calendar_view"),
    "slack_get_messages": ToolSpec("chat", "slack_mcp", "get_messages", {"limit": 50}),
}


class RefreshError(Exception):
    """The payload could not be read or reduced to a key set."""


def payload_items(tool: str, payload: Any) -> list:
    """The items the adapter for ``tool`` reads out of a decoded payload."""
    if tool == "email_inbox":
        items = _unwrap_email_list(payload)
    elif tool == "calendar_view":
        items = payload if isinstance(payload, list) else [payload]
    elif isinstance(payload, dict):
        items = payload.get("messages", [])
    else:
        items = payload
    return [item for item in items if isinstance(item, dict)] if isinstance(items, list) else []


def keyset_for(tool: str, payload: Any) -> dict[str, str]:
    """Key path -> JSON type for ``payload``; raises ``RefreshError`` when there are no items."""
    items = payload_items(tool, payload)
    if not items:
        raise RefreshError(f"payload has no {tool} items")
    try:
        return extract_items_keyset(items)
    except ValueError as exc:
        raise RefreshError(str(exc)) from exc


def read_payload(payload_file: Path | None) -> Any:
    """Decode the JSON payload from ``payload_file``, or from stdin when None."""
    source = "stdin" if payload_file is None else str(payload_file)
    try:
        text = sys.stdin.read() if payload_file is None else payload_file.read_text()
    except OSError as exc:
        raise RefreshError(f"cannot read payload {source}: {exc.strerror}") from exc
    except UnicodeDecodeError as exc:
        raise RefreshError(f"cannot read payload {source}: not {exc.encoding} text") from exc
    try:
        return json.loads(text)
    except json.JSONDecodeError as exc:
        # The decode error names a position only, never the payload text.
        raise RefreshError(f"payload {source} is not valid JSON: {exc}") from exc


def _adapter_config(spec: ToolSpec) -> dict:
    config_path = store_module.DEFAULT_HOME / "config.yaml"
    try:
        with open(config_path) as f:
            config = yaml.safe_load(f) or {}
    except (OSError, yaml.YAMLError) as exc:
        raise RefreshError(f"cannot read config {config_path}: {exc}") from exc
    for cfg in (config.get("adapters") or {}).get(spec.section) or []:
        if isinstance(cfg, dict) and cfg.get("provider") == spec.provider:
            return cfg
    raise RefreshError(f"no {spec.provider} adapter under adapters.{spec.section} in {config_path}")


def _live_arguments(tool: str, spec: ToolSpec, channel: str | None) -> dict:
    arguments = dict(spec.arguments)
    if tool == "calendar_view":
        today = date.today()
        arguments.update(
            start_date=today.strftime("%m-%d-%Y"),
            end_date=(today + timedelta(days=7)).strftime("%m-%d-%Y"),
            view="week",
        )
    elif tool == "slack_get_messages":
        if not channel:
            raise RefreshError("--live --tool slack_get_messages needs --channel")
        arguments["channel"] = channel
    return arguments


def fetch_live(tool: str, channel: str | None = None) -> Any:
    """One ``call_tool`` call on the configured MCP bridge; the decoded payload."""
    spec = TOOLS[tool]
    arguments = _live_arguments(tool, spec, channel)
    try:
        adapter = ingest._make_mcp_adapter(spec.provider, _adapter_config(spec))
    except Exception as exc:
        raise RefreshError(f"cannot start {spec.provider}: {type(exc).__name__}") from exc
    try:
        result = adapter._bridge.call_tool(spec.mcp_tool, arguments)
        if spec.provider == "outlook_mcp":
            return parse_outlook_content(result)
        return parse_json_content(result)
    except Exception as exc:
        # Error text from the server can quote message content; report the type only.
        raise RefreshError(f"live {spec.mcp_tool} call failed: {type(exc).__name__}") from exc
    finally:
        adapter.close()


def write_keyset(path: Path, keyset: dict[str, str]) -> None:
    """Replace ``path`` with the sorted key set in one step."""
    text = json.dumps(dict(sorted(keyset.items())), indent=2) + "\n"
    fd, tmp = tempfile.mkstemp(dir=path.parent, prefix=f".{path.stem}-", suffix=".json")
    try:
        with os.fdopen(fd, "w") as f:
            f.write(text)
        os.replace(tmp, path)
    except BaseException:
        Path(tmp).unlink(missing_ok=True)
        raise


def main(argv: list[str] | None = None) -> int:
    """Rewrite the recorded key set; return 1 on any payload or bridge error, else 0."""
    parser = argparse.ArgumentParser(description=__doc__.splitlines()[0])
    parser.add_argument("--tool", required=True, choices=sorted(TOOLS))
    source = parser.add_mutually_exclusive_group()
    source.add_argument("--payload-file", type=Path, default=None, help="JSON payload to read")
    source.add_argument("--live", action="store_true", help="call the tool on its MCP server")
    parser.add_argument("--channel", default=None, help="channel ID for live slack_get_messages")
    args = parser.parse_args(argv)

    try:
        payload = (
            fetch_live(args.tool, args.channel) if args.live else read_payload(args.payload_file)
        )
        keyset = keyset_for(args.tool, payload)
    except RefreshError as exc:
        print(f"error: {exc}", file=sys.stderr)
        return 1
    path = RECORDED_DIR / f"{args.tool}.json"
    write_keyset(path, keyset)
    print(f"wrote {len(keyset)} key paths to {path}")
    return 0


if __name__ == "__main__":
    sys.exit(main())
