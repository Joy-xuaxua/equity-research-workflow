# Equity Research Workflow

**A multi-agent workflow that researches a single publicly-traded company and produces an institutional-grade research report. Its one analytical focus: finding the gap between what the market price already implies and the company's actual situation.**

Covers US, Hong Kong and China A-share listed companies, including A/H dual listings and China concept stocks (VIE/ADR structures). Reports can be produced in English or Chinese — the workflow follows your language.

## Built on [equity-research-skill]

Many thanks to [@rollingSirius](https://github.com/rollingSirius) for [equity-research-skill](https://github.com/rollingSirius/equity-research-skill), a great skill that automates equity research for a single stock. This repository is based on that skill: it embeds the skill **unmodified** (under `.claude/skills/equity-research-skill/`) as the methodological source of truth, and adds an orchestration layer on top that aims for:

- **Better report quality** — staged pipeline with quality gates, adversarial review, and script-computed valuations instead of one long free-form conversation;
- **Fewer errors and less LLM hallucination** — through better context management (see below);
- **Easier to trace** — every important intermediate file, decision and log is saved on disk, so any number in the report can be traced back to its source.

## How it works

This workflow is itself a skill that starts and orchestrates subagents. When you ask about a stock, an orchestrator dispatches **8 specialized subagents** through a strict sequence of waves, with gates between them:

```text
W1  Data collection (×4 in parallel: disclosures / market & valuation / consensus & calls / industry)
G1  Industry classification
W2  Data reconciliation — scripted cross-checking of every collected number
W3  Forensic quality check — independent re-verification, grades data quality A–D
G2  Gate — poor data quality caps or vetoes the conclusion
W4  Chapter writing (×5 in parallel)
W5  Valuation — always computed by scripts, never by mental math
W6  Red team — an independent agent argues against the draft
G3  Gate — strong objections trigger a revision round
W7  Verdict & calibration
W8  Final checks and PDF delivery
```

Everything each agent reads, writes and decides is saved in a per-run research directory, plus an append-only orchestration log — the full audit trail of how the report was produced. See the `archive/` folder for an example of the files a real run produces.

## Installation (no technical background needed)

You need three things: an AI coding agent to run it (Claude Code recommended), **Python 3** installed on your machine (used by the valuation and checking scripts — get it from [python.org](https://www.python.org/downloads/)), and internet access. A full run dispatches ~20 subagent tasks, so expect it to consume a noticeable amount of tokens/credits.

### Option A — Claude Code (recommended, works out of the box)

1. Install [Claude Code](https://claude.com/claude-code) and log in (requires a Claude subscription or API key).
2. Download this repository and open it in Claude Code:
   - With git: `git clone https://github.com/Joy-xuaxua/equity-research-workflow.git`, then `cd equity-research-workflow` and run `claude`.
   - Without git: click **Code → Download ZIP** on the GitHub page, unzip it, open a terminal in that folder, and type `claude`.
3. That's it — Claude Code automatically loads the workflow (skills and subagents) from the `.claude/` folder of the project. No further setup.

### Option B — Codex or any other general agent

The whole workflow is plain Markdown files — nothing to compile or serve:

- `.claude/skills/equity-research-orchestration/` — the orchestrator skill (the entry point);
- `.claude/skills/equity-research-skill/` — the embedded upstream skill (research methodology);
- `.claude/agents/*.md` — the 8 subagent definitions.

To run it elsewhere, copy those folders into your agent's equivalent skills/agents locations (see your agent's documentation for "skills" and "subagents"). The host agent must support launching subagents with restricted tool sets. If it doesn't, you can still use the original [equity-research-skill](https://github.com/rollingSirius/equity-research-skill) on its own.

## Running it

Just talk to the agent in plain language — no commands or options to remember. The workflow may ask you one short confirming question (e.g. which listing, report language), then runs autonomously to completion.

### Full research report (the default)

Ask for research, analysis or a valuation of a company:

- "Research NVIDIA (NVDA) and write me a full research report."
- "帮我研究一下腾讯（0700.HK），写一份个股投研报告。"
- "Is TSMC a buy at the current price? 值不值得买？"

This produces a nine-chapter initiation-style report (business, competition, governance, financials, valuation, analyst view, catalysts, conclusion). You get a PDF (default) plus Markdown in:

```text
research/<company>_<ticker>_<date>/final/    ← the report
```

### Earnings mode

Mention the earnings, quarterly/annual results, earnings call or guidance, and the same pipeline runs in earnings mode automatically — no flag to set:

- "Analyze Apple's FY2026 Q3 earnings and the earnings call."
- "分析智谱 2025 财年年报，我的观点要不要更新？"

Earnings mode keeps the full pipeline depth (4 collection lines, reconciliation, forensic check, red team, scripted valuation) but focuses on the reporting period, and delivers an earnings deep-dive report.

### What you get with every run

Besides the report itself, the run directory keeps: collected source excerpts with citations and timestamps, the reconciliation ledger with every conflict adjudication, the data-quality grade, valuation assumptions and raw script outputs, the red-team critique, and the orchestration log.

## Major differences from the original skill

The original skill runs the whole research inside one conversation. This workflow restructures it into an orchestrated pipeline of specialized subagents, with two main ideas:

### 1. Each stage is worked by a subagent with only the context it needs — and nothing else

Every subagent receives exactly the files and parameters its stage requires, and no more. Chapter writers never see raw collected web content — they work only from the reconciled dataset. The forensic checker is deliberately offline: it judges data quality from already-reconciled evidence, not by re-searching the web, so its verdict stays independent. Even the orchestrator follows a "thin control loop": it never reads report bodies or raw sources, only small summary files, so its routing decisions cannot be swayed by a narrative. Each agent owns its own directory — no agent edits another agent's files.

Less context noise per agent means fewer opportunities for the LLM to hallucinate, mix up numbers across stages, or carry an early mistake silently into the final report.

### 2. Much more rigorous reconciliation

In a single-conversation run, conflicting numbers from different sources get reconciled informally, inside one context. Here, reconciliation is a first-class, scripted stage:

- Every collected metric is registered with an anchor — a unique verbatim excerpt from its source;
- A script collides the same metric across the collection lines and recomputes accounting identities (cross-footing) to surface hidden conflicts;
- Maker–checker separation: one agent reconciles and adjudicates every conflict, recording the reason in a ledger; a second, independent agent audits that output, re-executes the checks, and grades the data quality A–D;
- The grade is a hard gate: C caps the conclusion at "watch"; D vetoes it and forces the valuation chapter to be rebuilt around the veto;
- Downstream agents read only stamped, reconciled copies — the original collection files are never modified.

The result: disagreements between sources become visible and adjudicated, instead of being silently averaged away, and every number in the report traces to a source.

## Repository layout

```text
.claude/
  skills/
    equity-research-orchestration/   # the orchestrator skill (entry point of this workflow)
    equity-research-skill/           # embedded upstream skill — used unmodified
  agents/                            # 8 subagent definitions
research/                            # one directory per run (created at runtime)
archive/                             # archived previous runs
review/                              # design review notes
```

## Disclaimer

Reports are AI-generated research material, for information only — not investment advice. Verify any number you rely on against the cited primary sources (all saved in the run directory), and make your own decisions.
