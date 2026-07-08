"""AutoLoop configuration: dataclass + TOML loader with env-var overrides."""

from __future__ import annotations

import os
import subprocess
import tomllib
from dataclasses import dataclass, field
from pathlib import Path

DEFAULT_CONFIG_PATH = Path(__file__).resolve().parent.parent / "autoloop.toml"


@dataclass
class AutoLoopConfig:
    repo: str = "Sanctum-Origo-Systems/patina"
    triage_model: str = "sonnet"
    impl_model: str = "claude-opus-4-6[1m]"
    impl_timeout: int = 900
    triage_timeout: int = 90
    test_timeout: int = 120
    pr_reviewer: str = "andywidjaja"
    max_retries: int = 3
    max_story_points: int = 2
    tree_truncation: int = 3000
    diff_truncation: int = 8000
    error_truncation: int = 2000
    spec_truncation: int = 4000
    verify_command: str = "uv run pytest"
    lint_command: str = "uv run ruff check && uv run ruff format --check"
    triage_labels: list[str] = field(
        default_factory=lambda: [
            "ready",
            "rejected",
            "needs-decomposition",
            "in-progress",
            "in-review",
            "needs-human",
        ]
    )


_ENV_MAP: dict[str, tuple[str, type]] = {
    "PATINA_AIDLC_TRIAGE_MODEL": ("triage_model", str),
    "PATINA_AIDLC_IMPL_MODEL": ("impl_model", str),
    "PATINA_AIDLC_TIMEOUT": ("impl_timeout", int),
    "PATINA_AIDLC_TRIAGE_TIMEOUT": ("triage_timeout", int),
    "PATINA_AIDLC_TEST_TIMEOUT": ("test_timeout", int),
    "PATINA_AIDLC_REVIEWER": ("pr_reviewer", str),
    "PATINA_AIDLC_MAX_RETRIES": ("max_retries", int),
    "PATINA_AIDLC_MAX_STORY_POINTS": ("max_story_points", int),
    "PATINA_AIDLC_REPO": ("repo", str),
}


def load_config(path: Path | None = None) -> AutoLoopConfig:
    """Load config with precedence: env vars > TOML file > dataclass defaults.

    Raises FileNotFoundError when the resolved config path does not exist.
    """
    config_path = path or DEFAULT_CONFIG_PATH
    if not config_path.exists():
        raise FileNotFoundError(f"Config file not found: {config_path}")
    config = AutoLoopConfig()

    with open(config_path, "rb") as f:
        data = tomllib.load(f)

    for key in (
        "repo",
        "triage_model",
        "impl_model",
        "pr_reviewer",
        "verify_command",
        "lint_command",
    ):
        if key in data:
            setattr(config, key, data[key])

    for key in (
        "impl_timeout",
        "triage_timeout",
        "test_timeout",
        "max_retries",
        "max_story_points",
        "tree_truncation",
        "diff_truncation",
        "error_truncation",
        "spec_truncation",
    ):
        if key in data:
            setattr(config, key, int(data[key]))

    if "triage_labels" in data:
        config.triage_labels = list(data["triage_labels"])

    for env_var, (attr, coerce) in _ENV_MAP.items():
        if value := os.environ.get(env_var):
            setattr(config, attr, coerce(value))

    return config


def verify_implementation(config: AutoLoopConfig) -> int:
    """Run the shell command in *config.verify_command* and return its exit code.

    Uses ``subprocess.run`` with ``shell=True``, waits for the command to
    complete, and returns the integer exit code without raising on non-zero.
    """
    result = subprocess.run(
        config.verify_command,
        shell=True,
        capture_output=True,
    )
    return result.returncode
