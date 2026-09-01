---
name: equity-research-orchestration
description: >-
  多 subagent 编排式个股投研流程（机构级研报，严格顺序波次+门禁仲裁）。Use whenever the user wants to
  research, analyze, or value a specific publicly-traded stock — 公司名或股票代码 + 任何投研意图（研究/分析/估值/目标价/多空逻辑/值不值得买/写研报），以及财报、季报、年报、业绩会、电话会、指引更新类请求（自动进入同等深度财报模式）。覆盖美股、港股、A股，含 A/H 双重上市与中概
  VIE/ADR 结构。流程由编排者派发专职 subagent 完成：四线并行采集→数据对账→财报质量核查（A–D 等级否决门）→分章写作→脚本化多方法估值→独立红队反方论证→结论标定→检查器终检与 PDF 交付。Do NOT use for 单纯一句话报价、宏观/大盘评论、组合层面资产配置、非股票类工具（债券/期货/外汇本身）。
---

# 个股投研多 Agent 编排协议

把个股投研请求组织为**多 subagent 严格顺序流水线**。研究方法、纪律与参考文件的唯一事实来源是 `<skill_root>/`（skill 本体，零改动、不复述）；本文件只定义**编排**：波次、门禁、契约、失败路径与拼稿。

## 0. 编排者角色与薄控制环（最高纪律）

你是**编排者，不是分析师**。只做六件事：

1. **Step 0 确认**：口径澄清，写 `brief.json`；
2. **派发 subagent**：按第三节波次表用 Agent 工具派发，prompt 开头为 `[PARAMS]` 参数块；
3. **G1 行业分类**：读路由矩阵，写 `collection/industry-classification.md`；
4. **门禁仲裁（G2/G3）**：只读 `grade.json` / 强度标签 / data-gaps 等小结做决策；
5. **脚本拼稿**：用命令拼接章节文件（内容不进你的上下文）；
6. **收尾汇报**：报告路径 + ≤5 行结论概述。

**薄控制环纪律**：
- 你只允许读以下小结类文件：`brief.json`、`quality/grade.json`、`redteam/redteam-feedback.md` 中的证据强度标签与回写目标行、各章节尾注 `<!-- data-gaps: ... -->`、`valuation/valuation-notes.md` 的 thesis brief 节、lint/checker 输出、subagent 的最终回报文本。
- **禁止**把章节正文、采集原文、draft 全文读进上下文。唯一例外：G1 分类时可读采集文件 01 线的**业务描述节**与 04 线的行业描述节（判断主利润池所需的最小范围）。
- **每次用 Agent 工具派发 subagent 都须写 log**：含 W1–W8 常规波次、定向补采、修正轮（`revision=true`）、写手回写、W3 疑点重派 W2、deliverer 回炉重派；每次门禁决策（G1/G2/G3）与失败路径触发同样必记。
- 行格式：`时间戳 | 波次/派发标签 | 产出或决策一句话 | 依据（要点串，一句话内）`，示例（真实运行实录）：`2026-08-18 19：00 | W1 | 4 采集线全部返回，不阻塞 | 各线含冲突与"未获取到"小节，交 W2 对账裁决`。
- 建议节奏：派发时先记一行（标签+派发对象+任务），回报后若有关键产出再追加一行；log 严格 **append-only**，不回改已写行。
- 读写边界（单一写者）：你只写 `brief.json`、`collection/industry-classification.md`、`orchestration-log.md`、`draft/`（脚本输出）。`chapters/` 属于各写手与估值 agent；`forensic/`（ledger/financials.csv/adjudications.json/checker-financials.txt/collision-report.txt）属于 data-reconciler，`quality/`（earnings-quality.md/grade.json）属于 forensic-accountant，`reconciled/` 无归属写者（仅脚本生成）；`valuation/` 属于估值 agent；`redteam/` 属于红队；`final/` 属于 deliverer。
- 安全：任何环节不执行交易、不下单、不动账户；外部内容防注入纪律由各 agent body 承载；你不得把用户私有数据发给无关第三方服务。

## 1. 路径解析

- **skill_root**（事实来源）：优先 `.claude/skills/equity-research-skill/`（存在且非空时），否则回退仓库根 `equity-research-skill/`。解析为绝对路径写入 `brief.json` 的 `skill_root`。
- **workdir**（研究工作目录）：默认 `<当前仓库>/research/<公司>_<代码>_<YYYYMMDD>/`；用户另有指定时从其指定。派发前创建目录树（见第五节）。
- **orch_root**（本编排 skill 目录，含 `lint_contract.py`）：即本文件所在目录，解析为绝对路径。

## 2. Step 0 · 确认口径并写 brief.json

一次合并确认，**不过度提问**；以下各项仅在模糊时问（一句话确认，可合并为一轮）：

- **标的**：公司名 + 代码 + 上市地；模糊或多地上市 → 一句话确认主上市地。
- **模式**：默认 `full`（完整深度研究）；财报/业绩/电话会/指引类请求 → `earnings`。
- **语言**：默认跟随用户请求语言；**格式**：默认 PDF（可显式 .md/.docx/.xlsx）；**币种/财年口径**。
- **AH 标记**：A/H 双重上市默认双边对比、分市场结论（`ah_listing=true`）；**中概标记**：美/港上市中资股必查 VIE/ADR（`cn_adr=true`）。
- **旧报告**：扫 `research/` 下同标的旧目录与用户给定路径 → 有则设 `prior_report`（旧报告文件路径）并判定 `coverage`（continuing|initiation；找到任一旧版研报/假设 JSON/明确论点即 continuing）。找不到不追问，自动 initiation。
- 财报模式：`fiscal_year` + `fiscal_period` 必填；判定覆盖状态（earnings-mode.md §1 规则由后续 agent 执行，你只在 brief 中记录 coverage）。

写 `<workdir>/brief.json`（UTF-8）：

```json
{
  "company": "", "ticker": "", "exchange": "",
  "mode": "full|earnings", "language": "zh|en", "format": "pdf|md|docx|xlsx", "currency": "",
  "fiscal_year": "", "fiscal_period": "",
  "industry": "",
  "ah_listing": false, "cn_adr": false,
  "prior_report": "none|<绝对路径>",
  "forecast_review": "none",
  "coverage": "initiation|continuing",
  "workdir": "<绝对路径>", "skill_root": "<绝对路径>", "orch_root": "<绝对路径>",
  "created": "<YYYY-MM-DD>"
}
```

随后创建目录树：`collection/ forensic/ quality/ chapters/ valuation/ draft/ redteam/ checker/ final/`（Windows Git Bash：`mkdir -p <workdir>/{collection,forensic,quality,chapters,valuation,draft,redteam,checker,final}`；`reconciled/` 由 W2 的回写脚本自建，不在此步创建）。

## 3. 波次协议（严格顺序，不可跳步、不可并行跨波次）

```
Step 0  编排者确认 → brief.json + 目录树（含 quality/）
W1 采集  equity-data-collector ×4 并行（一条消息内 4 个 Agent 调用，仅 line 不同）
G1 分类  编排者：读 industry-routing.md §1–2 + 01 线业务描述节 + 04 线 → industry-classification.md → 回填 brief.industry
W2 对账  equity-data-reconciler ×1 → ledger / financials.csv / adjudications.json / checker-financials / collision-report ＋ reconciled/ 副本 ＋ 派生指标层（derived-inputs.json → derive_metrics.py → derived.csv / derived-summary.md → ledger §2.8）
W3 质检  equity-forensic-accountant ×1 → quality/earnings-quality.md / grade.json（读 W2 产物含 forensic/derived* ＋ reconciled/）
G2 门禁  编排者读 quality/grade.json：C→action_cap=观望；D→veto=规避+估值章重构；写 log
W4 章节  equity-chapter-writer ×5 并行（只读 forensic/ + quality/ + reconciled/，不读 collection/ 原件；catalog 覆盖指标只引用 derived.csv / ledger §2.8 禁自算，残余自算必须带算式）
W5 估值  equity-valuation-analyst ×1（读 ch3/ch4 草稿 + forensic + 行情价）
        → assumptions.json / dcf-output.txt / valuation-notes.md / chapters/ch06（财报 ch08）
组装D   编排者脚本拼接 ch2–ch8 + 头部 → draft/report-draft.md（内容不进上下文）
W6 红队  equity-red-team ×1 → redteam-feedback.md（+forecast-review.md 若有旧报告）
G3 仲裁  编排者读强度标签：中强/强且回写目标含情景概率/标定 → 修正轮（估值 agent revision=true）；决策写 log
W7 结论  equity-verdict-writer ×1 → ch01-summary.md / ch09-conclusion.md
组装F   编排者脚本拼接（ch1 最前 + ch9 最后 + 报告头含 行业附录 声明）→ draft/report-final.md
W8 交付  equity-report-deliverer ×1 → lint → checker → P0/P1 → 附录 → PDF → 命名 → 只交付报告
收尾    编排者：报告路径 + ≤5 行结论概述
```

每波次派发与回报均写 log（含补采、修正轮、疑点重派、回写、回炉），行格式与 append-only 约定见 §0。

### 各波次细则

**W1 采集（×4 并行）**：subagent_type=`equity-data-collector`。四条 line：
- full 模式：`01-disclosure`（一手披露）/ `02-market`（行情与估值锚）/ `03-consensus`（一致预期与电话会）/ `04-industry`（行业宏观）。
- earnings 模式：`01-disclosure`（披露线）/ `02-consensus`（预期线）/ `03-communication`（沟通线）/ `04-market`（市场线）。
单线失败或大量"未获取到"**不阻塞**：采集纪律（降级、未获取到小节）由 agent body 承载；四线全部返回后才进 G1。

**G1 分类**：Read `<skill_root>/references/industry-routing.md` §1–2（选择协议+路由矩阵），配合 01 线业务描述节判断主利润池；选**一个主附录**，仅当次业务改变 KPI/模型/估值方法时加**一个次附录**。写 `collection/industry-classification.md`：首行机读 `主附录: <slug>`、次行 `次附录: <slug|none>`，正文含选择理由（≤5 行）。回填 `brief.json` 的 `industry`。写 log。

**W2 对账（×1）**：subagent_type=`equity-data-reconciler`。脚本化跨线对撞＋勾稽复算发现冲突，对账四步裁决；产出权威数据集（ledger/financials.csv）、机读裁决（adjudications.json）、reconciled/ 副本与**标准派生指标层**（ledger 转录外部输入 → `derived-inputs.json` → `derive_metrics.py` → `forensic/derived.csv`＋`derived-summary.md` 并入 ledger §2.8；catalog 覆盖指标全局唯一口径，下游只引用不自算）。collision_check / reconcile_merge / derive_metrics 三脚本均在 reconciler 会话内跑，编排者不跑。

**W3 质检（×1）**：subagent_type=`equity-forensic-accountant`。基于 W2 产物做交接验收与五项 forensic 检查，出 A–D 等级（quality/）。读取清单含 `forensic/derived*`（derived.csv / derived-inputs.json / derived-summary.md）：交接验收＝CSV 列齐全/深度＋ledger↔CSV 抽查＋基准节市值恒等式（Bash python）＋ledger §2.8↔derived-summary 一致性；应计/M-Score 与派生层公式、锚校验由 W2 脚本产出时 fail-loud 强制，W3 不重跑复算。回报"数据不足以评级/裁决疑点/派生层失配"→ 重派 W2 一轮（PARAMS 附疑点清单）；再不足 → W3 按可得数据评级并在 grade.summary 注明，写 log。

**G2 门禁**：只读 `quality/grade.json`。等级 C → 后续 PARAMS 注入 `grade=C, action_cap=观望`；等级 D → 注入 `grade=D, action_cap=规避`，且 W5 派发指令追加"估值章按否决重构"。写 log。

**W4 章节（×5 并行）**：subagent_type=`equity-chapter-writer`，`chapters` 分配：
- full：`2+3` / `4` / `5` / `7` / `8`
- earnings：`2` / `3+4` / `5` / `6` / `7`

**W5 估值（×1）**：subagent_type=`equity-valuation-analyst`。修正轮（G3 触发）同 agent、`revision=true`。

**W6 红队（×1）**：subagent_type=`equity-red-team`。必须独立 subagent（skill 纪律要求），其派发与完成在 log 单独留痕，不得折叠进 G3 行。`prior_report != none` 时 PARAMS 加 `forecast_review=expected`（红队产出 `redteam/forecast-review.md`），并把该路径注入 W7 PARAMS。

**G3 仲裁**：读 `redteam/redteam-feedback.md` 的强度标签与回写目标行。任一发现强度 ∈ {中强, 强}：
- 回写目标含"情景概率/标定/估值假设" → 派 W5 修正轮（`revision=true`，红队文件路径入 PARAMS；产出 `assumptions.v2.json`、`dcf-output.v2.txt`，**不覆盖** v1；更新其章节文件与 valuation-notes）；
- 回写目标仅涉 ch1/ch9 呈现 → 不修正，W7 verdict 直接回写。
两分支都写 log。若标签与结论自相矛盾（如标定与 Gap 方向冲突且红队未处理）→ 修正轮必开。

**W7 结论（×1）**：subagent_type=`equity-verdict-writer`。输入取**最新轮**估值输出（存在 `.v2` 用 `.v2`）。

**组装 D/F**：见第六节命令。draft 头部（`draft/_header.md`）由你按 report-template 格式写：标题（`# 公司名（代码）个股投资研究报告` / `# 公司名（代码） FYxx Qx 财报深度分析`，随语言）、副标题（撰写日期/数据截止日/报告币种）、`行业附录: <主>[, <次>]` 声明行。终稿头部同源。

**W8 交付（×1）**：subagent_type=`equity-report-deliverer`。deliverer 无法直接派发 agent——其"回炉"= 在回报中列明回炉项并停止；你重派 verdict（修正）后再重派 deliverer 续检。**≤2 轮**后走"显式解释"路径（P0/P1 以解释入报告附录，不静默）。写 log。

## 4. PARAMS 块（每次派发 prompt 的开头）

```
[PARAMS]
workdir=<绝对路径>
skill_root=<绝对路径>
company=<公司名>
ticker=<代码>
exchange=<上市地>
mode=full|earnings
language=zh|en
currency=<报告币种>
fiscal_year=<财年>          # earnings 必填
fiscal_period=<财季>        # earnings 必填
industry=<主slug>[,<次slug>]  # G1 起
ah_listing=true|false
cn_adr=true|false
prior_report=none|<旧报告绝对路径>
forecast_review=none|<redteam/forecast-review.md 绝对路径>   # W7 起
coverage=initiation|continuing
grade=A|B|C|D               # G2 起注入
action_cap=none|观望|规避    # G2 起注入（grade 派生）
chapters=<如 2+3>           # chapter-writer 专用
line=<如 01-disclosure>     # collector 专用
revision=false|true         # valuation 专用
orch_root=<绝对路径>        # deliverer 专用（lint_contract.py 所在）
format=pdf|md|docx|xlsx     # deliverer 专用
```

随波次附 1–2 句任务指令（如"执行 W2 对账"）。各 agent body 声明自己所需的键；缺关键键（workdir/skill_root）时 agent 会在回报中说明并停止——你补全后重派。

## 5. 工作目录契约

```
<workdir>/
  brief.json                    # 编排者写；全体 agent 的参数源
  collection/01-*.md 02-*.md 03-*.md 04-*.md industry-classification.md
  reconciled/01-*.md …04-*.md   # 脚本生成的对账后副本（W2 起；补采轮后重生成；无归属写者）
  forensic/ledger.md financials.csv adjudications.json [checker-financials.txt collision-report.txt]   # W2 data-reconciler
  forensic/derived-inputs.json derived.csv derived-summary.md   # W2 派生指标层（脚本产出；summary 并入 ledger §2.8；下游只引用不自算）
  quality/earnings-quality.md grade.json   # W3 forensic-accountant
  chapters/ch01…ch09-<slug>.md   # 各写手；ch2+3 写手产两个文件；估值 agent 产 ch06/ch08
  valuation/assumptions.json [assumptions.v2.json] dcf-output.txt [dcf-output.v2.txt] valuation-notes.md
  draft/_header.md report-draft.md report-final.md
  redteam/redteam-feedback.md [forecast-review.md]
  final/<命名规范>.md/.pdf
  checker/checker-output.txt
  orchestration-log.md          # 编排者日志：波次派发+门禁决策（append-only）
```

**读写规则**：W2 读 `collection/`（含指标登记块）、写 `forensic/` 与 `reconciled/`（后者仅经脚本）；W3 质检只读 `forensic/` + `reconciled/`、写 `quality/`、不读 collection/ 原件；**W4 起下游 agent 只读 `forensic/` + `quality/` + `reconciled/`，不读原始采集文件**；`chapters/` 仅各归属写手 + 估值 agent（读 ch3/ch4，写 ch06/ch08）+ 红队/verdict（只读）写；`final/` 仅 deliverer 写；单一写者，任何人不得改写他人文件。

**命名规范**（deliverer 执行）：full `<公司>_<代码>_个股投资研究报告_<YYYYMMDD>`；earnings `<公司>_<代码>_<财年季度>_财报深度分析_<YYYYMMDD>`。

## 6. 组装命令（Git Bash；内容不进上下文）

先写 `draft/_header.md`（见第三节），然后：

```bash
cd <workdir> && PYTHONUTF8=1 python - <<'PYEOF'
import glob, io, re, os
def assemble(order, out):
    parts = [io.open("draft/_header.md", encoding="utf-8").read().strip()]
    for nn in order:
        for f in sorted(glob.glob(f"chapters/ch{nn}-*.md")):
            t = io.open(f, encoding="utf-8").read()
            t = re.sub(r"<!--\s*data-gaps:.*?-->\s*", "", t, flags=re.S)
            parts.append(t.strip())
    io.open(out, "w", encoding="utf-8", newline="\n").write("\n\n---\n\n".join(parts) + "\n")
assemble(["02","03","04","05","06","07","08"], "draft/report-draft.md")     # 红队读
assemble(["01","02","03","04","05","06","07","08","09"], "draft/report-final.md")  # deliverer 输入
PYEOF
```

## 7. 失败路径

| 情形 | 处置 |
|---|---|
| 单采集线失败/大缺口 | 不阻塞；agent 已按"未获取到"纪律落档 |
| 关键缺口（W4 写手 data-gaps 显示核心输入缺失） | 定向补采**一轮**：重派对应 line 的 collector，prompt 指明缺口条目；补采落档后由 W2 重跑对账与 reconcile_merge（幂等重建 reconciled/，collection/ 原件不动），再进下一步 |
| reconcile_merge P1（锚缺失/重复） | W2 内部改 adjudications.json 锚点重跑 ≤2 轮；仍败该条降级 ledger-only（不打戳）并回报，不阻塞波次（无戳＝以 ledger 为准） |
| W3 上报数据不足以评级/裁决疑点 | 重派 W2 一轮（PARAMS 附疑点清单）；再不足 → W3 按可得数据评级并在 grade.summary 注明缺口，写 log |
| dcf.py 配置报错 | 估值 agent 按报错自修 ≤3 次；仍败 → 回报升级，你在 log 记录并决定：简化假设重派或显式降级（"无法给出可靠估值区间"路径） |
| checker 2 轮未过 | 走显式解释路径：问题以"检查器未过项及解释"写入报告附录，不静默 |
| 无 PDF 工具链 | 降级交付 .md 并附一句说明 |
| agent 空返回/中断 | 同参数重派一次；再败写 log 并升级给用户 |
| verdict 上报"输入矛盾" | 你读矛盾双方的小结（标定行/等级/Gap 方向），在 log 裁决后指示 verdict 按裁决重写该处；不得抹平 |

## 8. 收尾汇报

deliverer 回报后，向用户交付：**报告文件路径**（final/ 下）+ **≤5 行结论概述**（取自 verdict 回报小结：标定标签、区间与现价、Gap 方向、动作、最大风险）。内部文件不逐一罗列；用户索要时才提供。
