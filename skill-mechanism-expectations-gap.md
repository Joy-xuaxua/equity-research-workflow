# Why the expectations-gap spine exists in Steps 2/3 — reconcile, forensic accounting, and the 9 chapters

Great question — this gets at the load-bearing logic of the whole design. Let me take it in the three parts you asked, and then connect them, because the connection is the actual answer to "why does the spine exist in Steps 2/3."

# 1. Why the expectations-gap spine needs Step 2 before it can exist

Recall what the gap actually is — a **two-sided comparison**:

```
              Market-implied expectations          My independent expectations
              (decoded from price via              (built from reported
               reverse DCF + consensus)             fundamentals + my analysis)
                          └────────── the GAP ──────────┘
                    "market thinks X, I think Y, because Z, provable by W(date)"
```

Step 2 exists because **both sides of that comparison are only as good as the data underneath them**, and the two failure modes are different:

**Reconciliation protects the *comparison itself*.** The gap is meaningless unless both sides are measured on the same basis. If your revenue figure is FY2024-as-restated and consensus is FY2024-as-originally-reported; or one side is GAAP EPS and the other is non-GAAP; or the company has a March fiscal year-end and the consensus is calendarized — you will either **manufacture a fake gap** (looks like a variant view, is actually a units error) or **hide a real one**. A fake gap is worse than no gap: the skill's rule is "没有可证伪的分歧就不给买卖动作" (no falsifiable divergence → no buy/sell action), and a units-error gap passes the falsifiability test while being wrong. Reconciliation is the procedure that makes "market-implied vs. mine" a valid subtraction.

**Forensic accounting protects *your side* of the gap.** Your expectations are formed by extrapolating reported performance. If reported performance is inflated — receivables spiking, revenue pulled forward, expenses capitalized — then your "independent expectation" is just a projection of the manipulation. Meanwhile the market may be pricing those same manipulated numbers. So the gap you compute could be fiction in *both* directions. Hence the skill's discipline line (`SKILL.md:29`): **先验真后估值 — "suspicious profits don't deserve to be discounted."** The A–D grade isn't a risk footnote at the end; it's a **gate on whether the gap analysis is built on real ground** — grade C caps the action at "wait," grade D declares the entire valuation chapter meaningless.

So the mechanism is: **Step 2 manufactures the verified ground truth; Step 3 states the gap on that ground and threads it through every chapter.** The spine "exists" in Steps 2/3 because that's where it's *constructed* — Chapter 1 merely *displays* it.

# 2. What "reconcile" concretely is

From `references/data-sources.md` §7 — it's a fixed procedure for when sources disagree:

1. **First check for definitional artifacts**: is the conflict actually a difference in period, currency, unit, accounting standard, GAAP/non-GAAP, basic/diluted shares, or intraday-vs-close? (Most "conflicts" dissolve here — but only if you look.)
2. **If still conflicting, resolve by tier**: Tier 1 (regulatory filing) beats Tier 3 (Bloomberg) beats Tier 5 (media). Within a tier: closer-to-original > newer > more complete definition > downloadable/recomputable.
3. **Never silently pick one.** Keep both conflicting values, their sources, their dates, and your reasoning for which you adopted. "不悄悄选一个" — silent selection is the exact behavior this rule exists to prevent in AI-generated research.
4. **If unresolvable**: present a range or write "无法判断" (cannot determine), and state the sensitivity of the valuation to the ambiguity.

Plus fairness rules that serve the gap: **the same evidence bar for bull and bear cases** (you may not use company-口径 numbers for the bull thesis while demanding regulatory evidence for the bear); peer comparisons normalized for fiscal year/standards/FX/leases/SBC/one-offs; and if the company doesn't disclose a KPI, a modeled estimate must be labeled "我的估算" (my estimate) with a range — never presented as fact.

Step 2 also produces the **source+timestamp ledger** (every key number with origin and date) and the **fact/judgment layering** — the raw material the report's appendix and the checker will later audit.

# 3. What forensic accounting concretely is

From `references/forensic-accounting.md` — five checks, mostly computable by the checker script from a financials CSV:

| Check | What it measures | Red flag |
|---|---|---|
| **Accrual quality** (Sloan) | Earnings = cash + accruals. Total accrual ratio = (net income − CFO) ÷ avg total assets; cash conversion = CFO ÷ net income over 3–5 yrs | Accruals > 10%; cash conversion chronically < 80% and falling while profit grows |
| **Beneish M-Score** | 8-variable manipulation model (DSRI, GMI, AQI, SGI, DEPI, SGAI, TATA, LVGI) comparing this year vs. last | M > −1.78 → "possible manipulation zone" — not a conviction, a trigger for line-by-line manual review |
| **Revenue recognition** | DSO divergence (receivables growing faster than revenue for 2+ yrs), deferred-revenue divergence (the subscription killer), channel stuffing, Q4 spikes, related-party circular trades, restatements/segment re-draws | Revenue accelerating while deferred revenue decelerates = growth borrowed from the future |
| **Capitalization & smoothing** | Dev-cost capitalization, capex > 2× D&A with no turnover improvement, finished-goods inventory piling, counter-cyclical provision rates, "one-time" items recurring 3+ years | Expenses hiding in the balance sheet |
| **Governance/audit** | Auditor changes, CFO/audit-chair exits, delayed filings, SEC comment letters, short-seller allegations, incentives tied to adjusted metrics | Structural motive to manipulate |

Banks/insurers/REITs swap in industry-specific checks (loan migration, provision coverage, Level 3 assets) since accrual analysis doesn't apply to balance-sheet businesses.

**Output and wiring**: an evidence table + a grade with pre-registered consequences:

- **A** (clean, cash conversion ≥90%, accruals <5%) → no restriction
- **B** (1–2 mild flags, explained) → no restriction, but monitored
- **C** (M-Score breach, persistent divergence, recurring "non-recurring," 1 serious governance flag) → **action capped at "wait and see"**, warning in Chapter 1
- **D** (multiple serious flags / suspected fraud / qualified audit) → **avoid**; valuation chapter replaced by "valuation is meaningless until credibility recovers"

And the one rule that gives it teeth: **"cheap" may never offset a credibility problem** — 便宜是造假最常见的伪装 ("cheapness is fraud's most common disguise"). This is why it's a *veto*, not a discount you can price in.

# 4. The 9 chapters — and what each contributes to the gap argument

This is the part that answers your earlier question about "one coherent argument." The chapters aren't a generic institutional template; each one is a **load-bearing element of the gap case**:

| # | Chapter | Its job in the gap argument |
|---|---|---|
| 1 | **Executive Summary** | *States* the gap: verdict box (decision trichotomy: intrinsic value / 1–3mo market direction / action) → tearsheet (every row source+timestamped) → **Gap table** (market-implied vs. mine vs. base-rate percentile per driver, net direction) → 3 bull + 3 bear falsifiable points |
| 2 | **Business detail** | Gives you the structural knowledge to judge whether *your* growth/margin expectations are physically achievable — revenue by line/region/customer, concentration, value-chain position |
| 3 | **Competition & moat** | The **structural reason you're allowed to deviate from base rates**. You claim 18% CAGR (85th percentile historically)? Only a moat justifies that. Moat scorecard must cross-check with Ch6's EPV/book ratio — qualitative and financial evidence must agree |
| 4 | **Management, governance, capital allocation** | Whether the value you've identified can actually reach shareholders (buybacks above intrinsic value, M&A impairment history, reinvestment ROIIC, dilution). A poor scorecard enters veto consideration; governance flags feed the Ch5 grade |
| 5 | **Financials + earnings quality** | Where the forensic evidence table and the **A–D grade live**. The 5-yr trend tables are the raw material of "my expectations" |
| 6 | **Valuation** | Where the gap is *quantified*: reverse DCF + PVGO decode the market's side; scenario DCF/EPV/EVA build your side; football field + sensitivity show where price sits between them. Scenario probabilities must state evidence strength |
| 7 | **Analyst consensus** | The market's **explicit** expectations (targets, estimates) to complement the **implicit** ones decoded from price. "Consensus vs. my divergence points" — the skill calls this the most valuable section |
| 8 | **News, catalysts + forecast register** | **When and how the gap closes** — which dated event forces the market to re-price. The forecast register (baseline, range, validation date, leading indicators, invalidation conditions) makes the gap *testable after publication* |
| 9 | **Verdict, counter-case, sizing** | The action the gap justifies + the pre-mortem attacking your own gap claim + sizing (EV, asymmetry, Kelly-lite) + monitoring list + confidence self-assessment |

So "the spine exists in Steps 2/3" in this sense: Step 2 builds the verified facts both sides of the gap stand on; Step 3 distributes the gap across nine chapters, each supplying one piece of evidence for one side or the other.

# 5. One mechanism detail that matters for your reconstruction decision

The **document is conclusion-first, but production is analysis-first**. Chapter 1 (the Gap table, the verdict box) *displays* the output of Step 4's reverse DCF and scenario work — meaning Chapter 1 is literally the **last thing that can be finalized**, not the first. The "Steps" are analytical phases, not document sections; a literal "write chapter 1, then 2, then 3…" execution would be structurally impossible under this skill's own rules. If you ever reconstruct it, the orchestration must allow the conclusion to be written after the analysis, then *placed* at the front — and the checker (`check_research_output.py`) exists precisely to catch the inconsistencies that this non-linear production order invites (Ch1 label vs. Ch9 label vs. recalculable calibration).
