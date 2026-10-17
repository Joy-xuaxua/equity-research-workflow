"""Phase-1 Python harness for the equity-research orchestration skill.

Replaces the LLM orchestrator of `.claude/skills/equity-research-orchestration/SKILL.md`
with a deterministic state machine: Python owns waves, gates, scripts, assembly, lint,
checker, appendix, PDF and naming; LLM agents (Claude Agent SDK) only do judgment work,
with their must-read files preloaded into the first message.
"""

__version__ = "0.1.0"
