# W2/W3 拆分与对账机制改造 · 实施全程流水账

> 记录日期：2026-08-22。本文是本轮改造（6 次提交：嵌套 `d92a57e`→`5bcfca7`→`a367f48`→`3aa6508`，外层 `5870a00`→`f06c0d5`）的逐步执行流水账，含自我迭代（错误在哪一层被抓掉）与两个夹具逼出的设计修正。执行计划全文见 `~/.claude/plans/fizzy-baking-bumblebee.md`。

## 阶段 0：开工准备

1. **建任务清单**：TaskCreate ×6（提交①②③嵌套 / 提交④外层 / 端到端验收 / 记忆收尾），对应计划里的 4 次提交 + 验收 + 收尾。
2. **基线验证**：嵌套仓库（`.claude/skills/equity-research-skill/`）跑 `python -m unittest discover tests` → 7 tests OK；两仓库 `git status` 干净；嵌套 HEAD=`3d94e64`，与计划记录一致。

## 阶段 1：提交①——登记清单与契约文档

3. **读 data-sources.md L140–169**：确认 §7（数据对账与公允性规则）在 L161 结束、`## 8` 从 L163 开始——这是 §7.1 的插入锚点。
4. **新建 `references/collision-metrics.json`**（~120 行）：
   - `units` 表 27 条：股份类（股/万股/亿股…）、货币类（元/万元/亿元…CNY + 港元/亿美元…HKD/USD 各档）、倍、%、人、元/股三类——每条 `{dim, factor, ccy}` 三元组；
   - `_unit_parse` 规则：整串命中 → 抽币种前缀后命中 → 失败 P2 不参与比较；同 dim 同 ccy 才归一；
   - `crosschecks` 6 条：市值=价×股本(3%)、资产=负债+权益(1%)、fcf=cfo−capex(5%)、pe(25%/P2)、收入=Σ分部(3%)、eps(20%/P2)；
   - `metrics` 25 条：每条 name_zh/unit/lines_by_mode（full 与 earnings 的线 slug 不同）/关联勾稽。
5. **Edit data-sources.md**：在 L161 与 `## 8` 之间插入 §7.1（三段：采集端登记块格式、对账端两脚本流程、collection 永不修改）。
6. **验证**：内联 python 校验 JSON——version=1、25 个 metric 的 unit 全部命中 units 表、metric↔crosscheck 双向引用闭合、crosscheck inputs 全是合法 key。输出 `OK: 27 units, 6 crosschecks, 25 metrics`。
7. **提交** `d92a57e`（嵌套）。

## 阶段 2：提交②——对撞脚本

8. **读惯例母本**：check_research_output.py 的 L1–135（`Issue` dataclass、`add()`、`[P?] CODE [file]: message` 输出行格式）、L715–794（`run()` 退出码逻辑：P0/P1→1，--strict 加 P2）、test_check_research_output.py 头部（importlib 按路径加载 + unittest 模式）。
9. **写 collision_check.py 第一版**（~340 行）。
10. **自查发现 6 处缺陷，整文件重写**：
    - H 期间正则分组错位；
    - 对撞 detail 引用 `unit_display` 字段但校验函数从未设置（必 KeyError）；
    - 登记块被 parse 两遍（副作用重复）；
    - `build_report` 边遍历边变异 issues 列表；
    - 勾稽因行情指标"最新"回退会在多个财年期间重复触发；
    - 跨币种值被放进同一 distinct 集合数值比较（P2 之外又误产 P1）——重写为按 `(dim, ccy)` 分桶，桶内才比值。
11. **写 tests/test_collision_check.py**（20 个用例）：RegistryTests（加载/版本守卫）、ParserTests（期间归一变体、松散数值/区间、单位复合解析）、CollisionTests（跨文件分歧/跨单位等值不立案/跨币种 P2/区间重叠/自相矛盾/未知 key/scope 缺失/锚不唯一/表未登记）、CrosscheckTests（市值恒等式过/资产负债恒等式败/分部加总败/pe 回退）、LegacyDowngradeTests（无登记块降级 P2 退出 0/strict 退出 1/报告分节）。
12. **首跑 3 失败，逐一定性**：
    - `1H2025→None`：**脚本真 bug**——重写为两条显式正则（`(\d{4})H([12])` 与 `([12])H(\d{4})`）；
    - 跨文件分歧测试期望退出 1 实得 0：**测试数据错**——46,562万股 vs 4.66亿股归一后只差 0.08%，低于 0.5% 立案阈值（脚本正确吸收舍入），换成真实案例 2.41 亿股（差 48%）；
    - 报告体检节缺失断言：**测试期望错**——该节按设计只在非空时渲染，给夹具补一条锚重复条目凑出 P2。
13. **重跑 20/20 OK**。
14. **智谱真实 workdir 干跑**（--out 指 tmp 不污染原件）：无登记块 → 4×P2、退出 0、降级说明行——降级路径符合设计。
15. **全量回归（27 tests）+ 提交** `5bcfca7`。

## 阶段 3：提交③——回写脚本

16. **写 reconcile_merge.py 第一版**：load_adjudications（手动 schema 校验：version/generated 格式/id `C\d{1,3}` 去重/status 枚举/note≤120/files 的 file 正则+anchor≥8+side 枚举）→ canonical_sha8（对 adjudications 内容规范序列化取 sha256 前 8 位，保证幂等指纹）→ compose_stamp 三态模板 → find_registry_span / strip_appendix_lines → apply_stamps → run。
17. **自查抓出 2 处**：
    - `stamped_lines` 索引追踪在同文件多次插戳后因行号下移而错位 → 改为**按内容排除**（戳行以 `▶ ` 开头，天然不会被当作锚命中行）；
    - `import glob` 挪到顶部。
18. **写 tests/test_reconcile_merge.py**（12 用例）：共享 BODY_01（含登记块的 01 线）/BODY_02 夹具，AnchorTests（双文件双锚/登记块锚排除/坏锚 P1 部分落盘/锚歧义/目标文件缺失）、SchemaTests（坏版本不重建/坏 status/空裁决仅重建）、IdempotencyTests（重跑逐字节一致/strip-appendix）、ReadOnlyTests（collection 哈希不变/头部指纹）。
19. **首跑 1 失败**：锚歧义测试数据自错（第二行"口径**乙**重复"不含锚点"口径**甲**"）→ 改成"重复一次总市值约100亿港元口径甲的表述"。
20. **全量 39 tests OK + 提交** `a367f48`。

## 阶段 4：提交④——agent 拆分（重点）

21. **并行读三个文件**：equity-data-collector.md 全文（81 行）、equity-chapter-writer.md 全文（76 行）、lint_contract.py 全文（273 行）。旧 equity-forensic-reconciler.md 全文在规划期已读过（60 行，7 个动作）。

### 21a. 拆分的核心操作：旧 reconciler 的动作逐条分家

旧文件动作序列 → 新归属的映射：

| 旧 equity-forensic-reconciler 动作 | 去向 |
|---|---|
| ①通读 collection/ | **W2 data-reconciler 动作①**（追加"含各线指标登记块"） |
| ②对账四步 | **W2 动作④**（原文逐字照抄：口径检查→Tier 裁决→绝不悄悄选→无法解决留区间） |
| ③构建 financials.csv | **W2 动作⑤**（原文照抄：18 列名、full≥5 财年深度） |
| ④跑检查器（应计/M-Score） | **W2 动作⑥**，定位改为"出厂自检，产物供 W3 消费与独立复算" |
| ⑤五项 forensic 检查 | **W3 forensic-accountant 动作②** |
| ⑥评级 A–D | **W3 动作④** |
| ⑦WebFetch 回源核验 | **W2 动作⑨**（验证来源是对账职责） |
| 输出 earnings-quality/grade | **W3 独有**，路径改 quality/ |

W2 新增的四个机械动作（来自 v1 机制计划）：②跑 collision_check、③候选并入冲突清单统一 Cxx、⑦写 adjudications.json、⑧跑 reconcile_merge；W3 新增动作①**交接验收**（CSV 列/期间核对、ledger↔CSV 抽查 3 行、Bash 重跑恒等式、复算 checker——验不过升级不猜数）。

22. **写 `.claude/agents/equity-data-reconciler.md`**（新，~85 行）：
    - description：W2 派发、跨线对撞+四步裁决、产出 ledger/financials/adjudications/reconciled/、是 W3 与下游的数据地基；
    - tools：`Read, Write, Glob, Grep, Bash, WebFetch, WebSearch`（Bash 跑三个脚本，Web 回源）；
    - PARAMS 表：与旧文件**全量相同**（prior_report/coverage 留下——决定 CSV 深度）；
    - 必读：data-sources.md §7–8 含 §7.1、collision-metrics.json 全文、earnings 模式加读 §4 引导段（L57–61 单季推导/重述拆股口径——只给对账相关的引导段，不给 4.1–4.5 分析节）、ah/cn 加读 markets-cn-hk §4–5；
    - 动作⑨条如上映射；收尾纪律一句："collection/ 只读——你的修改只发生在 forensic/ 与 reconciled/（后者仅经脚本）"；
    - 输出契约 6 行（ledger 的"关键数字台账"一条加了强化语："**登记清单内指标无论有无冲突一律入账，不以'是否冲突'筛选**"——这是审计发现的病根，写进契约）；
    - 回报：CSV 行数、冲突三态条数、reconciled 状态（P1 锚失败数）、缺口、升级项——**不再有 grade**。
23. **写 `.claude/agents/equity-forensic-accountant.md`**（新，~65 行）：
    - description：W3 派发、独立审核者（交接验收+重新执行）、**故意无联网**；
    - tools：`Read, Write, Glob, Grep, Bash`（有 Bash 算比率，无 Web）；
    - PARAMS：砍掉 prior_report/coverage（它不需要），保留 industry（行业替代检查）等；
    - 必读 7 项：forensic-accounting.md 全文、**ledger.md 全文（明确写"冲突裁决记录与'我的判断'分层是你的审计底稿与线索源"）**、csv+checker-financials.txt、reconciled/01–04（治理/审计师定性证据在 01 线；双值/悬置戳引用须注明）、行业附录、earnings §4.2–4.3+§8、markets-cn-hk；
    - 动作 5 条（交接验收→五项检查→计算纪律→评级→写产物）；
    - 输出契约 2 行：`quality/earnings-quality.md`、`quality/grade.json`（格式照旧契约逐字，仅 `evidence_ref` 改 `"quality/earnings-quality.md"`）。
24. **`git rm` 旧 equity-forensic-reconciler.md**。

### 21b. collector 的 4 处编辑（登记块的采集端）

25. 必读清单第 1 条（data-sources.md 全文）追加："；加读 collision-metrics.json（本线应登记的指标清单与单位/期间写法）"。
26. 纪律"冲突上报不裁决"条追加："**清单内指标无论有无冲突一律写入「指标登记」块——跨线冲突由对账脚本对撞发现，不依赖你自报**"。
27. 输出契约 fence 里 `## 发现` 与 `## 冲突` 之间插入 `## 指标登记` 节说明（字段 key/value/unit/period/scope/source/tier/ts/anchor，anchor≥10 字符唯一原文片段，补采轮更新不追加）。
28. 回报格式加一行"登记块指标条数（与冲突条数分列）"。

### 21c. chapter-writer 的 8 处编辑（W3→W4 + 读本切换）

29. description：`W3 派发`→`W4 派发`；"只读 forensic/"→"只读 forensic/ + quality/ 与对账后采集副本（reconciled/ 的发现节与裁决戳，**不读 collection/ 原件与原文附录**）"。
30. 引言（L9）同步：W4 波次 + 数据输入描述改写。
31. 章节注册表 3 处路径：full ch4、full ch5、earnings ch4 的 `forensic/earnings-quality.md` → `quality/earnings-quality.md`。
32. 必读第 4 条改为：`forensic/ledger.md、forensic/financials.csv、quality/earnings-quality.md、reconciled/01–04-*.md（读「发现」节与裁决戳，跳过「原文附录」节）、brief.json`。
33. 野数据句扩为"禁止引用 forensic/、quality/、reconciled/ 与必读文件以外"。
34. **新增一条通用纪律**（机制的关键约束）："财务数字一律以 financials.csv 与 ledger.md 为准（reconciled/ 仅作背景与冲突语境）；冲突状态以裁决戳为准——`▶ 双值@`/`▶ 悬置@` 指标**不得只写单值**；戳与 CSV/ledger 矛盾按 data-gaps 上报，不得自行取舍。"

### 21d. 四个下游 agent 的机械编辑（各 2–3 处，共 12 处 Edit）

35. **valuation**：description 与引言 `W4`→`W5`；输入行 `forensic/earnings-quality.md、forensic/grade.json` → `quality/` 两件。
36. **red-team**：`W5`→`W6` ×2；`forensic/earnings-quality.md 与 grade.json（否决链）`→quality/ 两件。
37. **verdict**：`W6`→`W7` ×2；`forensic/grade.json + forensic/earnings-quality.md`→quality/。
38. **deliverer**：`W7`→`W8` ×2；"不修改 chapters/、forensic/、valuation/、redteam/"追加 `quality/、reconciled/`（checker 命令里的 `--financials forensic/financials.csv` **不变**——CSV 仍属 W2）。

### 21e. SKILL.md 重接线（9 组编辑，含一次返工）

39. description 流程句改"数据对账→财报质量核查"——第一次 Edit 的 old_string 只锚到尾句，**造成新旧两句拼接重复**；修复时又因 YAML 折叠块续行有前导空格而锚不中，**先 Read 再带缩进重试**才折叠干净。
40. §0：编排者可读清单 `forensic/grade.json`→`quality/grade.json`；单一写者行重写为三段归属（forensic/ 五件属 data-reconciler、quality/ 两件属 forensic-accountant、reconciled/ 无归属写者仅脚本生成）。
41. §2 mkdir 加 `quality`，并注明 reconciled/ 由 W2 脚本自建。
42. §3 波次表整体替换为 8 波（W2 对账一行产出五件+reconciled/；W3 质检一行产出 quality/ 两件；G2 读 quality/grade.json；W4–W8 顺延）。
43. 细则区整块替换：W2 拆成 W2/W3 两条（W3 含升级路径："数据不足以评级/裁决疑点→重派 W2 一轮带疑点清单，再不足按可得数据评级并在 grade.summary 注明"）；G2 的"估值章按否决重构"指向 W5；G3 修正轮 → W5；红队/结论/交付全部重编号。
44. PARAMS 注释 `# W6 起`→`# W7 起`（forecast_review）。
45. §5 目录树重写（reconciled/ 行 + forensic/ 与 quality/ 分属两行）+ 读写规则首句改"W4 起只读 forensic/ + quality/ + reconciled/"。
46. §7 失败路径：W3 写手→W4 写手；补采行追加"补采后由 W2 重跑 reconcile_merge 幂等重建"；新增两行（merge P1 处置 / W3 升级处置）。

### 21f. lint_contract.py 双代兼容（6 处编辑）

47. docstring 加第 8 条检查项说明；`check_grade`/`check_grade_consistency`/`check_structure` 各加 `new_pipeline` 参数切换 quality/ 与 forensic/ 路径（新布局时 structure 还要求 adjudications.json）；新增 `has_new_pipeline()`（标记 = adjudications.json 或 quality/ 存在）与 `check_reconciled()`；main() 接线 + JSON 输出加 new_pipeline 字段。
48. **验证批次**：py_compile 过；旧 workdir lint 8 项全为既有问题且 `new_pipeline=False`（双代证明）；grep 三连——`forensic-reconciler` 0 命中、`W2a|W2b` 0 命中、agents+SKILL 里旧 quality 路径 0 命中；波次引用分布核对。
49. **提交** `5870a00`（顺手清掉 py_compile 产生的 `__pycache__`）。

## 阶段 5：夹具验收（逼出两个设计修正）

50. **复制** 智谱 workdir → `research/_fixture_merge_test`；grep 真实锚点（465,623,090 推算行、1,043 收盘、4,856.45 市值、收入 724,334 行、员工 1,094/937 两行、03 线彭博 30.72 行）；读 brief.json（full/saas/cn_adr=true）。
51. **发现设计缺陷 #1**：full 模式 04-industry 按 registry 零指标，却被要求登记块。修 collision_check：新增 `expected_registry_lines()`（从 lines_by_mode 推导）+ `read_mode()`（读 brief.json，默认 full），循环里不在预期线的文件直接跳过；报告分母改"应登记线数"。
52. 给这个修正补测试时写了一段绕弯废代码（无效路径重组+重复写 brief），当场发现并清理成两段式。
53. **全量测试 13 个瞬间全红**——豁免逻辑把所有文件都跳过了。调试打印 expected 集合：`['01-disclosure', …]`——**registry 存的是不带 .md 的 slug，我拿带 .md 的文件名比较**。修：`expected_md = {slug + ".md"}`。
54. 40 tests OK；智谱干跑变"0/3 登记、退出 0"（04 豁免生效）；**提交** `3aa6508`（嵌套）。
55. **夹具插登记块**（python 脚本在 `## 冲突` 前插入）：01 线 6 条（股本推算值、收入、净利 IFRS、净利非 IFRS——period 故意写"财年2025"变体、员工 1,094、员工 937——真实 C09 案例）、02 线 3 条（收盘价、市值、股本 4.66 亿——与 01 差 0.08% 验证跨单位等值不立案）、03 线 1 条（彭博预期 30.72 亿）。04 线**不插**（豁免）。
56. **跑对撞**：3/3 登记、**2×P1 SELF_CONTRADICTION**（net_income 期间变体归一后撞出 + employees 双值）、market_cap_identity 通过（无 CROSSCHECK_FAIL）、退出 1——全部符合预期。
57. **写 adjudications.json**（4 条）：C01 resolved 双文件双锚、C09 dual 同文件双锚、C29 dual、**C99 pending 故意坏锚**。
58. **merge 第 1 轮**：ANCHOR_NOT_FOUND P1、退出 1、**6 戳部分成功落盘**（部分成功不阻塞）；记录 collection 三文件 sha256。
59. **修 C99 锚**（指向 03 线真实行）→ **第 2 轮**：7 戳 0 失败退出 0 → **第 3 轮**：diff 逐字节一致（幂等）；`sha256sum -c` 全过（collection 零改动）；戳终态三态齐全（C01×2 两文件、C09×2、C29×2、C99×1）。
60. **lint 夹具**发现**设计缺陷 #2**：RECONCILED_STAMP_MISSING 对 04-industry 误报（无指标→无锚→不可能有戳）。修 lint：从 adjudications 的 files[] 构造 stamp_targets，只要求被指向的文件有戳。复跑：夹具剩 3 项（1 既有 CSV 行数 + 2 待 W3 产物）；旧 workdir 仍 8 项（双代稳定）。
61. **派 W3 冒烟**：Agent 工具报 `equity-forensic-accountant` 不存在——**agent 注册表会话启动时加载，不热刷新**。改用 general-purpose 承载：把新 body 全文注入 prompt、加"本轮禁用联网工具"补齐工具差异、附 PARAMS 与夹具说明（旧布局 forensic/earnings-quality.md 不读不受影响）。
62. 等待期间**更新记忆文件**（任务⑥）：8 agent、8 波、目录归属、两脚本、lint 双代、注册表不热载的坑。
63. **提交** `f06c0d5`（外层：lint 修正 + gitlink→3aa6508）。

## 阶段 6：冒烟返回与收尾

64. **W3 冒烟结果**：grade=**B**、veto null——与原 hybrid 产出一致（接缝成立）；交接验收通过（CSV 18 列、台账抽查 6/6、恒等式 465,623,090×1,043≈4,856 亿精确勾稽、checker 复算吻合）；五项检查可计算项/未获取到项如实分列；**以审计师姿态留了一条注记：reconciled/03 的 C99 悬置戳在 ledger 无对应记录**——这正是合成夹具的已知瑕疵，说明它真的在核对戳与台账；另提 3 条升级回流项（年报原文回源 CFO/D&A、8-31 后 DSO 复核、C28 科目标签终核）。
65. **终检**：grade.json 格式逐字段符合契约（evidence_ref 指向 quality/）；earnings-quality.md 头部自我声明独立判断；lint 终态 7 项全为旧文件既有的字母提取局限类，无新布局结构性问题。
66. **清理**：删夹具目录与 /tmp 中间产物，确认零残留；任务⑤⑥关闭。

## 最终状态

嵌套仓库 4 个提交（`d92a57e`→`5bcfca7`→`a367f48`→`3aa6508`，40 tests 绿），外层 2 个提交（`5870a00`→`f06c0d5`，gitlink 指向 `3aa6508`）；agents 目录 8 个文件（2 新增 1 删除 5 修改）；`.claude/` 下无任何旧名残留。
