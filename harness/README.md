# harness — Phase-1 Python orchestrator for equity research

Replaces the LLM orchestrator of `.claude/skills/equity-research-orchestration/SKILL.md` with a Python
state machine. The research method is unchanged: every LLM agent still runs on its own
`.claude/agents/<name>.md` body, used verbatim as the system prompt. What moves to Python:

| Was done by the LLM orchestrator or by agents in tool loops | Now done by |
|---|---|
| Wave sequencing, PARAMS block, G2/G3 gate decisions, failure paths, append-only `orchestration-log.md` | `pipeline.py` (state machine, per-step checkpoints in `<workdir>/.harness/state.json`) |
| `collision_check.py`, `check_research_output.py --financials`, market-cap triple check, `reconcile_merge.py`, `derive_metrics.py`, merging the ledger §2.x summary | `steps.py`, run around the W2 reconciler; script failures go back to the agent as fix rounds |
| Header and chapter assembly (SKILL.md §6), `lint_contract.py`, checker, appendix, md→PDF, file naming | `steps.py` / `pdf.py` (W8 is deterministic; the deliverer LLM is called **only** when the checker reports P0/P1) |
| Reading the must-read list one file per turn (11–37 turns per agent) | `roles.py` puts exactly those files / reference sections in the first message; Read/Grep stay available as a fallback |
| Re-launching an agent after a 429 / 400 / empty reply | `backend.py` backs off and **resumes the same session** (work in context and on disk is kept) |
| Spotting contract defects at W8 | `validators.py` checks at each handoff: registry YAML (W1→W2), W2 outputs, `grade.json` plus the grade-letter lint rule, chapter contract, dcf provenance, red-team sidecar, verdict restatement |

G3 is now code: the red team also writes `redteam/redteam-findings.json` (one entry per finding, with
its strength and write-back targets). The harness validates this file against the markdown table and
routes each 中强/强 finding to the valuation revision round, a chapter writer, or W7.

## Usage

```bash
python -m venv harness/.venv && harness/.venv/Scripts/python -m pip install -r harness/requirements.txt

# Benchmark fixture: fresh workdir from a finished run's archived collection, then W2→W8
harness/.venv/Scripts/python -m harness.run_pipeline fixture --source research/安莉芳_1388HK_20260923 --workdir research/安莉芳_1388HK_20261017-harness

# New research: Step 0, then W1→W8
harness/.venv/Scripts/python -m harness.run_pipeline init --workdir research/X_0000HK_20261017 --company X --ticker 0000.HK --exchange HKEX --currency 港元
harness/.venv/Scripts/python -m harness.run_pipeline run --workdir research/X_0000HK_20261017

# Resume after a crash (always continues from the first unfinished step); --from / --stop-after for partial reruns
harness/.venv/Scripts/python -m harness.run_pipeline run --workdir <dir>
harness/.venv/Scripts/python -m harness.run_pipeline status --workdir <dir>

# Offline end-to-end test of the state machine (no LLM): replay a finished run's agent outputs
harness/.venv/Scripts/python -m harness.run_pipeline fixture --source research/安莉芳_1388HK_20260923 --workdir <tmp> --backend replay

# Tokens per wave versus the recorded baseline (same method: usage per message id from transcripts)
harness/.venv/Scripts/python -m harness.tokens --baseline-session 182f7618-9cf8-457c-bf0b-ab730c0e9653 --workdir <harness workdir>

# Unit tests
harness/.venv/Scripts/python -m unittest discover -s harness/tests -t .
```

### Model, endpoint and authentication

Nothing is hardcoded. The spawned Claude Code CLI inherits this process's environment
(`ANTHROPIC_BASE_URL`, `ANTHROPIC_MODEL`, proxy variables, credentials), the same as the user's
Claude Code. `model` and `effort` are passed explicitly. They come from `--model`/`--effort`,
falling back to `ANTHROPIC_MODEL`, `CLAUDE_EFFORT` and then `effortLevel` in `~/.claude/settings.json`.
The run log records them on the `Harness | 启动` line. `--cli-path` or `HARNESS_CLI_PATH` selects a
specific `claude.exe`; the default is the one bundled with the SDK.

The CLI needs its own credentials. A CLI started by the desktop app is authenticated by the app, so a
harness launched from a desktop session gets `Not logged in`. Before running, either run `claude` once
in a terminal and `/login`, or export `CLAUDE_CODE_OAUTH_TOKEN` (from `claude setup-token`) or
`ANTHROPIC_API_KEY` / `ANTHROPIC_AUTH_TOKEN` for a compatible endpoint. On an auth error the harness
stops with exit code 3. After fixing auth, `run` resumes from the same step.

## Layout

| File | Role |
|---|---|
| `run_pipeline.py` | CLI (`fixture` / `init` / `run` / `status`) |
| `pipeline.py` | Wave/gate state machine: W1, G1, H1 (registry handoff), W2…W8, assembly D/F, failure paths |
| `roles.py` | Per-agent preload manifest, harness-mode addendum (appended to the agent body), task, HARNESS_REPORT schema |
| `backend.py` | `SDKBackend` (Claude Agent SDK, retry/backoff by session resume) and `ReplayBackend` (offline) |
| `validators.py` | Handoff validators; reuses `collision_check` / `reconcile_merge` / `lint_contract` as libraries |
| `steps.py` | Deterministic steps: scripts, ledger merge, header/assembly, lint, checker, appendix, naming |
| `pdf.py` | md→HTML→PDF (headless Edge/Chrome, then pandoc/wkhtmltopdf), checked with pypdf |
| `docs.py` | Markdown section extraction (`§7`, `7.1`, `二、`), ignoring headings inside code fences |
| `tokens.py` | Token measurement for the baseline and harness runs |
| `state.py` / `orchlog.py` | Checkpoints and resume / append-only orchestration log |

## Phase 2 (not in this phase)

- **W1 collector redesign:** pre-extract PDFs and pages in Python (text and tables, cut to the
  sections that `data-requirements.md` asks for), so that whole annual reports no longer sit in the
  agent loop. Collector 01 peaked at 1.39M tokens of context in the baseline run. W1 was 17.2M of the
  51M baseline, mostly from relaunches and whole-PDF context. Phase 1 keeps W1 dispatch (with
  must-read preloading and in-session retries) but leaves its tool loop unchanged. The benchmark
  starts at W2.
- Targeted re-collection (`recollect_round`) and the W8 rework routing are implemented but were not
  exercised by the fixture run (the fixture is not re-collected, and the checker reported no P0/P1).
