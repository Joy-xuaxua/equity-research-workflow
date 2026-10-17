"""Path resolution and runtime configuration.

Nothing model- or endpoint-specific is hardcoded: the spawned Claude Code CLI inherits this
process's environment (ANTHROPIC_BASE_URL, ANTHROPIC_MODEL, proxy vars, auth), exactly like
the user's own Claude Code. The harness only *reads* those values to report them and to pass
`model` / `effort` explicitly so a run is reproducible from its log.
"""
from __future__ import annotations

import json
import os
from dataclasses import dataclass, field
from pathlib import Path
from typing import Optional

REPO_ROOT = Path(__file__).resolve().parent.parent


def resolve_skill_root(repo_root: Path = REPO_ROOT) -> Path:
    """SKILL.md §1: `.claude/skills/equity-research-skill/` when present and non-empty, else `equity-research-skill/`."""
    primary = repo_root / ".claude" / "skills" / "equity-research-skill"
    if primary.is_dir() and any(primary.iterdir()):
        return primary
    return repo_root / "equity-research-skill"


SKILL_ROOT = resolve_skill_root()
ORCH_ROOT = REPO_ROOT / ".claude" / "skills" / "equity-research-orchestration"
AGENTS_DIR = REPO_ROOT / ".claude" / "agents"
SCRIPTS = SKILL_ROOT / "scripts"
REFS = SKILL_ROOT / "references"
INDUSTRIES = SKILL_ROOT / "industries"


def _user_settings() -> dict:
    path = Path.home() / ".claude" / "settings.json"
    try:
        return json.loads(path.read_text(encoding="utf-8"))
    except (OSError, ValueError):
        return {}


@dataclass
class RuntimeConfig:
    """How agents are launched. Every field defaults to what the user's Claude Code already uses."""

    model: Optional[str] = None           # None → ANTHROPIC_MODEL (inherited) → CLI default
    effort: Optional[str] = None          # None → CLAUDE_EFFORT env → ~/.claude/settings.json effortLevel
    cli_path: Optional[str] = None        # None → HARNESS_CLI_PATH env → SDK-bundled claude.exe
    max_parallel: int = 5                 # W4 writers run concurrently (SKILL.md: ×5 并行)
    max_attempts: int = 6                 # API-level retries per agent call (resume same session)
    max_fix_rounds: int = 2               # validator → agent fix rounds per handoff
    backoff_base: float = 30.0            # seconds; exponential for 5xx/empty/400
    backoff_cap: float = 15 * 60.0
    rate_limit_cap: float = 5.5 * 3600.0  # longest wait for a usage-window reset (429)
    env_overrides: dict = field(default_factory=dict)

    def resolved_model(self) -> Optional[str]:
        return self.model or os.environ.get("ANTHROPIC_MODEL") or None

    def resolved_effort(self) -> Optional[str]:
        val = self.effort or os.environ.get("CLAUDE_EFFORT") or _user_settings().get("effortLevel")
        return val or None

    def resolved_cli_path(self) -> Optional[str]:
        return self.cli_path or os.environ.get("HARNESS_CLI_PATH") or None

    def banner(self) -> str:
        """One line for the run log; never includes credentials."""
        return (f"model={self.resolved_model() or '<CLI default>'} effort={self.resolved_effort() or '<default>'} "
                f"ANTHROPIC_BASE_URL={os.environ.get('ANTHROPIC_BASE_URL', '<unset>')} "
                f"cli={self.resolved_cli_path() or '<sdk bundled>'}")
