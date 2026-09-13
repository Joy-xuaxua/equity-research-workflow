# Review · 2026-08-25 运行：W1 采集文件「发现」节未按行内格式输出——subagent 会话原始记录提取

- 提取时间：2026-09-13；提取方式：脚本解析 subagent JSONL transcript（逐字摘录，标注截断）
- transcript 源：`~/.claude/projects/…/1448280e-ad28-4a61-a82f-b06c60a35c84/subagents/agent-<id>.jsonl`
- 运行时 agent body 版本：commit `5870a00`（2026-08-21，运行当天生效；`git show 5870a00:.claude/agents/equity-data-collector.md`）

## 0. 结论摘要

1. **要求在运行当天已生效**：运行时版本的输出契约与当前版本逐字一致，含「## 发现：按主题分区；每个关键数字：值｜来源（Tier 标注）｜URL 或文件名｜发布/抓取日期。」
2. **四线全部未执行行内格式**：实际产出为「主题小节（节级 Tier 标注）+ 叙述式要点行」，来源/URL/日期多挂在节标题或独立清单节（如 01 线 F 节「一手文件清单」）；行内全角竖线｜格式行占比：01=2/392、02=8/222、03=1/179、04=13/154。
3. **固定结构的其余部分全部执行**（指标登记 YAML/冲突/未获取到/原文附录四节齐全）——即偏差仅发生在「发现」节内部的行级格式。
4. **无门禁拦截**：W2 打戳依赖 anchor（正文任意唯一片段均可），31 戳/0 失败；W8 lint/checker 均不校验行内来源格式——格式偏差在整条流水线中无人检查。
5. **transcript 证据形态（thinking 全文精确计数）**：四线均无「考虑后决定不采用」的记录，但复述程度分三档——04 线 thinking 中 2 次复述「值｜来源（Tier）｜URL/文件名｜发布/抓取日期」并部分执行（条目尾三段式）；01 线复述输出契约结构骨架时把「发现」行截成只剩「按主题分区」，行内四段式从未进入其计划（'值｜'在 74,820 字符 thinking 中出现 0 次）；02/03 线 thinking 完全未复述该格式（0 次），落笔按表格/叙述式自行组织。即：格式要求只存在于 body，没有任何机制（读回检查、编排者验收、lint）把它带进落盘产物。

## 1. 契约要求（运行时版本 5870a00 之「输出契约」节，逐字）

```
## 发现
按主题分区；每个关键数字：值｜来源（Tier 标注）｜URL 或文件名｜发布/抓取日期。
（02/03 线的电话会、指引按原文引用协议处理；04 线标注行业数据定义与覆盖范围）
```

## 2. 实际产出对照（采集落档文件）

| line | 发现节组织 | 节级 Tier 标注 | 行内｜格式行数/总行数 | 来源/URL/日期放置方式 |
|---|---|---|---|---|
| 04-industry | 7 个主题小节（### ） | 5/7 小节标题含 Tier | 13/155 | 条目尾部「来源｜URL｜日期」三段式（部分执行行内式） |
| 02-market | 8 个主题小节（### ） | 1/8 小节标题含 Tier | 8/223 | 节内叙述+来源行；登记块内 key/value 制 |
| 03-consensus | 7 个主题小节（### ） | 0/7 小节标题含 Tier | 1/180 | 节内叙述，Tier 随括注；日期多为「（Tier x，YYYY-MM-DD）」式 |
| 01-disclosure | 6 个主题小节（### ） | 6/6 小节标题含 Tier | 2/393 | 节标题标注 Tier+文件名日期；URL 集中在 F 节「一手文件清单」 |

## 3. 原始会话记录（逐字摘录）

### 3.1 04-industry（agent a1fb68d97f4f62d91｜W1 采集 04 行业线）

#### 3.x.1 派发 prompt（主 agent → collector，逐字）

```
[PARAMS]
workdir=C:/Users/zliu71/Documents/equity-research-workflow/research/Zhipu_02513HK_20260825
skill_root=C:/Users/zliu71/Documents/equity-research-workflow/.claude/skills/equity-research-skill
company=智谱（Zhipu AI / Z.ai）
ticker=02513.HK
exchange=香港交易所主板
mode=full
language=zh
currency=HKD
ah_listing=false
cn_adr=true
prior_report=none
forecast_review=none
coverage=initiation
line=04-industry

执行 W1 采集：full 模式 04-industry（行业宏观线）。
```

#### 3.x.2 工具时间线（全部工具调用）

```
  行   3 10:53:58  Read       C:/Users/zliu71/Documents/equity-research-workflow/.claude/skills/equi
  行   5 10:53:59  Read       C:/Users/zliu71/Documents/equity-research-workflow/.claude/skills/equi
  行   7 10:53:59  Read       C:/Users/zliu71/Documents/equity-research-workflow/.claude/skills/equi
  行  10 10:54:01  Read       C:/Users/zliu71/Documents/equity-research-workflow/.claude/skills/equi
  行  13 10:54:08  Read       C:/Users/zliu71/Documents/equity-research-workflow/.claude/skills/equi
  行  17 10:54:31  WebSearch  智谱 02513.HK 港股上市 首日 市值
  行  18 10:54:31  WebSearch  IDC 中国大模型公有云 MaaS 市场份额 智谱 2026
  行  19 10:54:32  WebSearch  国家数据局 全国 日均 token 消耗 大模型 2026
  行  25 10:54:57  WebSearch  智谱 IDC 中国大模型市场 份额 排名 2025 2026
  行  26 10:54:57  WebSearch  国务院 深入实施"人工智能+"行动 意见 2025 政策 目标
  行  27 10:54:57  WebSearch  智谱 Zhipu 美国实体清单 制裁 芯片出口管制 影响
  行  33 10:55:38  WebSearch  工信部 中国人工智能核心产业规模 2025年 亿元 企业数量
  行  34 10:55:38  WebSearch  GLM-4.6 开源 Hugging Face 下载量 GitHub star 智谱
  行  35 10:55:39  WebSearch  MiniMax 港股上市 月之暗面 DeepSeek 2026 大模型竞争格局
  行  41 10:56:06  WebFetch   https://www.news.cn/tech/20260326/8026bd54df3f489a8c79d4438cac96b3/c.h
  行  42 10:56:06  WebSearch  阿里 腾讯 字节跳动 2026 资本开支 AI 算力 投资规模
  行  43 10:56:07  WebSearch  智谱清言 App 月活 用户 2026
  行  51 10:56:37  WebSearch  GLM-5 智谱 发布 2026年2月 开源 参数
  行  52 10:56:37  WebSearch  中国 智能算力规模 2026 EFLOPS IDC 预测
  行  56 10:56:43  WebSearch  IDC blog 中国MaaS市场进入高速增长期 Token经济从概念走向规模化实践
  行  62 10:57:10  WebFetch   https://docs.bigmodel.cn/cn/update/new-releases
  行  63 10:57:10  WebFetch   https://github.com/zai-org/GLM-4.5
  行  78 10:57:31  WebSearch  国家数据局 "140万亿" 词元调用量 意味着什么
  行  79 10:57:32  WebSearch  IDC 中国大模型公有云服务市场 79.4亿 2025 火山引擎 份额 第一
  行  80 10:57:32  WebSearch  英伟达 H20 B30 对华出口 2026 最新 政策
  行  86 10:58:05  WebSearch  CNNIC 生成式人工智能 产品 用户规模 2026 报告 亿人
  行  87 10:58:05  WebSearch  智谱 招股书 弗若斯特沙利文 大模型 MaaS 市场规模 复合增长率
  行  88 10:58:06  WebSearch  2026 大模型 政企 中标 智谱 排名 项目数
  行 100 11:01:06  Write      C:/Users/zliu71/Documents/equity-research-workflow/research/Zhipu_0251
```

#### 3.x.3 格式相关 thinking 摘录（关键词：## 发现/输出契约/格式/模板/按主题/值｜）

- **行98｜10:59:49（thinking 片段，±窗口摘录）**

  > ation pipeline), not a report file. The skill contract overrides this: files written as input to another tool are fine. This is exactly that case. I'll write the file.  Let me compose carefully, in Chinese, with the fixed structure. Each key number: 值｜来源（Tier）｜URL/文件名｜发布/抓取日期.  One more check on Tier assignments: - 国务院/工信部/CNNIC/国家数据局: Tier 1 (政府/监管/官方统计) — though relayed via media, the statements originate from government; I'll mark "Tier 1（经权威媒体/官网转载）" and note fetch limitation. - IDC reports: Tier 3 专业数据商 (行业研究)。Per data-sources.md §0.1: 行业官方统计属 Tier 2; IDC is 专业数据 → Tier 3? Actually the tier table: Tier 2 includes "行业官方统计"; IDC is a commercial research firm → Tier 3 ("专业数据" listed as Bloomberg/FactSet etc... IDC is analogous → Tier 3). I'll mark IDC as Tier 3（专业行业研究，经媒体转引）。 - Frost & Sullivan in prospectus: the prospectus is Tier 1 document, but the industry estimate is F&S's → 行业估算口 …[截断，共2044字符]

- **行102｜11:01:17（thinking 片段，±窗口摘录）**

  > .7 benchmarks from GitHub. The HF fetch also confirmed "Collection including zai-org/GLM-4.6, Updated Mar 2" and paper published Aug 8, 2025. The file's HF data row is accurate.  Now compose the final report to the orchestrator (pure data, per the 回报格式): - file path - key findings ≤5 with tier + date - conflict count + most important one; registration block metric count (0, listed separately from conflicts) - 未获取到 count + key gaps - escalation items  Keep it concise, in Chinese, no emojis.

#### 3.x.4 Write 落盘的「## 发现」节首稿摘录

- **第1次 Write｜行100｜11:01:06｜内容 11476 字符**，「## 发现」节摘录：

```
### A. 需求侧官方数据（Tier 1 政府口径）

1. 全国日均 Token 调用量时间序列（国家数据局局长刘烈宏，中国发展高层论坛 2026 年会 2026-03-23 披露；国新办发布会 2026-03-24；国家数据局官网解读《140万亿日均词元调用量意味着什么？》）：
   | 时点 | 日均 Token 调用量 | 备注 |
   |---|---|---|
   | 2024 年初 | 1000 亿 | 基准 |
   | 2025-06 底 | 30 万亿 | 一年半增长 300 多倍 |
   | 2025-09 底 | 40 万亿 | |
   | 2025 年底 | 100 万亿 | |
   | 2026-03 | 140 万亿 | 较上年末 +40%，两年增长超千倍 |
   来源（Tier 1，经新华网/腾讯云开发者社区转载，原文站点 news.cn 直抓被网络策略拦截）｜https://www.news.cn/tech/20260326/8026bd54df3f489a8c79d4438cac96b3/c.html｜新华网发布 2026-03-26，抓取 2026-08-25。
   研究含义：MaaS 推理需求仍是陡峭增长曲线，行业 beta 向上。

2. 生成式 AI 用户规模（CNNIC 第 57 次《中国互联网络发展状况统计报告》，2026-03 发布）：截至 2025-12 用户 6.02 亿人，较 2024 年底（2.49 亿）+141.7%，普及率 42.8%；2025-06 为 5.15 亿。来源（Tier 1 官方统计机构，经国家知识产权局网站转载）｜https://www.cnipa.gov.cn/art/2026/3/5/art_55_205003.html｜2026-03-05。

3. AI 核心产业规模（工信部部长李乐成，2026-03-05 十四届全国人大四次会议"部长通道"）：2025 年我国人工智能核心产业规模突破 1.2 万亿元人民币，AI 企业超 6,200 家；此前（2025-01-21 国新办，副部长张云明）口径为"2025 年预计突破 1.2 万亿元、企业超 6,000 家"。来源（Tier 1）｜https://www.news.cn/politics/20260305/e8d78b5a77c844da984d5ec442dbfa9f/c.html｜2026-03-05。覆盖范围：核心产业（芯片/软件/服务/应用），非 GDP 口径。

### B. 市场规模与竞争格局

4. IDC《中国大模型公有云服务市场分析，2025H1》（Tier 3 专业行业研究，经东方财富/雪球转引）：2025H1 中国公有云上大模型调用量 536.7 万亿 Tokens（2024 全年为 114 万亿）；火山引擎以 49.2% 份额（按调用量）居第一。来源｜https://wap.eastmoney.com/a/202510123531475336.html｜2025-10-12。
5. IDC 2025 全年口径（Tier 3，搜索摘要转引）：2025 年中国大模型训推公有云服务市场收入 79.4 亿元人民币；2025 年公有云大模型调用量 1,944 万亿 Tokens（同比 +16 倍）；IDC 预计 2026 年全年 Token 消耗量约 40,000 万亿（约 4 亿亿，较 2025 年再增约 20 倍）。抓取 2026-08-25（搜索摘要，原报告未能直抓）。
6. IDC 博客《中国 MaaS 市场进入高速增长期，Token 经济从概念走向规模化实践》（Tier 3，搜索摘要转引，原 URL 因编码问题两次抓取失败）：2025 年中国公有云 MaaS 市场收入约 30.7 亿元；2026 年预计约 186 亿元。与条目 5 的 79.4 亿元并存——口径初判见「冲突」节。
7. IDC+浪潮信息《中国人工智能计算力发展评估报告》（Tier 3，经财联社/新华网转引）：中国智能算力规模 2024 年 725.3 EFLOPS → 2025F 1,037.3 EFLOPS → 2026F 1,460.3 EFLOPS（另有版本口径 1,271.4，见冲突）→ 2028F 2,781.9 EFLOPS；未来五年智能算力 CAGR 52.3%，通用算力 CAGR 18.5%。来源｜https://www.cls.cn/detail/1230044｜抓取 2026-08-25。
8. Frost & Sullivan（智谱招股书引用，Tier 1 文件承载的第三方估算；媒体转引）：中国大语言模型市场 2024 年 53 亿元（机构客户 47 亿 + 个人 6 亿）→ 2030F 1,011 亿元，CAGR 63.5%；2024 年 CR5=33%；智谱 2024 年收入 3.12 亿元、份额 6.6%，按收入在中国通用大模型开发商中排名第二（独立大模型厂商第一，仅次于科大讯飞）。来源（招股书数据经财联社/21 经济网转引）｜https://m.cls.cn/detail/2235451 、https://www.21jingji.com/article/20251220/ ｜2025-12-20 前后。
9. 细分市场地位（IDC，Tier 3，媒体转引）：
   - AI 编程市场：2025 年 3.99 亿元，阿里 47.6% 第一、智谱第二、商汤第三、腾讯第四、百度第五；2026 年底预计 11.73 亿元。
   - 大模型应用市场：2024 年 47.9 亿元，Top8 厂商：百度、阿里云、商汤、浪潮云、智谱、中国电信 AI、创新奇智、稀宇科技。
10. 政企中标市场（第三方监测，Tier 4/5）：2025 全年统计 7,539 个大模型相关中标项目、披露金额约 295.2 亿元，科大讯飞为"标王"；智谱 2025 年中标 57 个项目、金额约 2.54 亿元（能源/政务/通信/教科等行业）。2026H1 全市场 2,770 个 AI 大模型应用项目中标（其中智能审核&分析决策类 426 个、智能客服&数字人 311 个） …[截断，共6064字符]
```

#### 3.x.6 最终回报（最后一条 text，逐字，截断 1800 字符）

（行103｜11:01:30）

```
采集完成，回报如下。

**输出文件**：`C:/Users/zliu71/Documents/equity-research-workflow/research/Zhipu_02513HK_20260825/collection/04-industry.md`

**关键发现（≤5 条）**：
1. 行业需求陡峭上行（Tier 1）：全国日均 Token 调用量 2026-03 突破 140 万亿（2024 初 1000 亿、2025 底 100 万亿），国家数据局局长刘烈宏 2026-03-23 披露；CNNIC：截至 2025-12 生成式 AI 用户 6.02 亿（+141.7%）；工信部：2025 年 AI 核心产业规模破 1.2 万亿元。
2. 市场规模：F&S（招股书引用）中国大语言模型市场 2024 年 53 亿元 → 2030F 1,011 亿元、CAGR 63.5%，智谱 2024 份额 6.6%、按收入列通用大模型开发商第二/独立厂商第一；IDC：2025 年大模型训推公有云 79.4 亿元、调用量 1,944 万亿 tokens（+16 倍），2026F token 约 4 万万亿。
3. 竞争格局：公有云调用量口径火山引擎 49.2% 第一（IDC 2025H1），阿里云以收入口径自称第一（口径冲突已上报）；C 端智谱清言未进 2026Q1 月活 TOP20（基本盘在 B/G 端与开发者）；政企中标 2025 全年智谱 57 个/2.54 亿元（科大讯飞为标王）。
4. 政策与管制（Tier 1/5）：国务院“人工智能+”意见 2025-08-26 落地（2027/2030 目标）；智谱 2025-01-15 被列美国实体清单（推定拒绝），公司文档显示 GLM-Image 已在国产芯片全流程训练（Tier 2）；2026 年 H20 对华销售规则放宽但对实体清单内标的无效。
5. 模型迭代与商业化（Tier 2，公司文档 2026-08-25 抓取）：GLM-5（2026-02-11，744B/A40B）→ 5.1（宣称全面对齐 Claude Opus 4.6、MIT 开源）→ 5.3（2026-08 上线）；GLM Coding Plan 团队订阅上线、GLM-4.5 定价“Claude 的 1/10”——开源+低价+订阅三线并进。

**冲突**：5 条；最重要一条＝智谱当前市值三口径互斥（新浪约 3,061.90 亿港元/2.41 亿股 vs 老虎约 4,692.62 亿港元/4.66 亿股 vs 虎嗅约 920 亿美元），股本数差近一倍，属 02-market 线职责，本线仅上报未裁决。

**指标登记块**：0 条（collision-metrics.json 清单内指标的 lines_by_mode 均不含 full 模式 04-industry 线，本线采得的均为清单外行业/宏观指标，块内已注明；与冲突 5 条分列）。

**未获取到**：7 条；关键缺口＝IDC MaaS 博客与 2025 全年报告原文直抓失败（数字均标“转引”）、GLM 系列 GitHub star/累计下载权威口径缺失（HF 月下载 26,180 且不含 ModelScope 主渠道）、智谱在 IDC 公有云份额榜未单列、云厂商 2026 资本开支绝对值不可靠（仅方向性采信）。

**升级项**：无标的代码解析问题。提醒两点：① cn_adr=true 与实际（港股主板 02513.HK，无 ADR 证据）不符，建议编排者核对该标记，本线已按中概结构风险（实体清单/VIE 相关政策敞口）覆盖；② 港股“大模型板块”已形成（MiniMax 00100.HK 已上市、月之暗面传闻拟 IPO 未证实），后续估值章节可作同业锚。
```

---

### 3.2 02-market（agent ab1fa32c8dc66b838｜W1 采集 02 行情线）

#### 3.x.1 派发 prompt（主 agent → collector，逐字）

```
[PARAMS]
workdir=C:/Users/zliu71/Documents/equity-research-workflow/research/Zhipu_02513HK_20260825
skill_root=C:/Users/zliu71/Documents/equity-research-workflow/.claude/skills/equity-research-skill
company=智谱（Zhipu AI / Z.ai）
ticker=02513.HK
exchange=香港交易所主板
mode=full
language=zh
currency=HKD
ah_listing=false
cn_adr=true
prior_report=none
forecast_review=none
coverage=initiation
line=02-market

执行 W1 采集：full 模式 02-market（行情与估值锚线）。
```

#### 3.x.2 工具时间线（全部工具调用）

```
  行   3 10:53:56  Read       C:/Users/zliu71/Documents/equity-research-workflow/.claude/skills/equi
  行   5 10:53:56  Read       C:/Users/zliu71/Documents/equity-research-workflow/.claude/skills/equi
  行   8 10:54:01  Read       C:/Users/zliu71/Documents/equity-research-workflow/.claude/skills/equi
  行  12 10:54:26  WebSearch  智谱 02513.HK 股价 市值 港交所
  行  13 10:54:26  WebSearch  Zhipu AI Z.ai 02513 Hong Kong IPO listing date offer price
  行  18 10:55:04  WebFetch   https://finance.yahoo.com/quote/2513.HK/
  行  19 10:55:05  WebFetch   https://hk.finance.yahoo.com/quote/2513.HK/
  行  24 10:55:14  WebFetch   https://stockanalysis.com/quote/hkg/2513/
  行  25 10:55:15  WebFetch   https://xueqiu.com/S/02513
  行  39 10:55:31  WebSearch  智谱 02513 配售 新股 2026年8月 增发 募资
  行  40 10:55:31  WebSearch  Zhipu AI 2513.HK share placement July 2026 HK$4 billion new shares
  行  86 10:58:33  WebSearch  智谱 02513 港股通 纳入 恒生科技指数 2026年6月
  行  90 11:00:22  WebSearch  智谱 2513.HK 股价 8月25日 收盘
  行  91 11:00:23  WebSearch  港元兑人民币汇率 2026年8月25日 HKD CNY
  行  92 11:00:23  WebSearch  Zhipu AI Z.AI ADR OTC 美股 存托凭证 2513
  行 108 11:05:38  Write      C:/Users/zliu71/Documents/equity-research-workflow/research/Zhipu_0251
  行 112 11:06:06  Grep       
  行 114 11:06:07  Grep       
  行 116 11:06:07  Grep       
  行 118 11:06:08  Grep       
  行 120 11:06:09  Grep       
  行 122 11:06:09  Grep       
```

#### 3.x.3 格式相关 thinking 摘录（关键词：## 发现/输出契约/格式/模板/按主题/值｜）

- **行106｜11:04:05（thinking 片段，±窗口摘录）**

  >  of Aug 2026. ✓ (Tier 4/5 corroboration of cls.cn 6/8 claim.)  Now write the file. Structure:  # 采集文件：02-market（full 模式） 头部：公司（智谱 / Z.AI Co., Ltd.，02513.HK，香港交易所主板）｜财年口径：自然年（12-31 年结，H股公司；中报未出）｜采集时间：2026-08-25｜本线范围：行情、股本与估值锚（价格/市值/倍数/52周/股本结构/公司行动）  ## 发现 ### 1. 证券标识与上市结构 ### 2. 最新行情锚（2026-08-24 收盘） ### 3. 股本结构（Tier 1） ### 4. 市值：两种口径 ### 5. IPO 与上市以来资本行动/价格路径 ### 6. 估值倍数锚 ### 7. 指数纳入与互联互通 ### 8. 数据质量警示（聚合站缓存滞后）  ## 指标登记 (YAML)  ## 冲突  ## 未获取到  ## 原文附录  Then grep anchors. Let me write carefully, keeping anchors unique.  Anchor strings (must appear exactly once each, ≥10 chars): - price_close: 「收盘 1,007.00 港元（当日 −122.00，−10.81%）」 — I'll use this exact phrase once in the 行情锚 table. Note: "1,007

- **行124｜11:06:13（thinking 片段，±窗口摘录）**

  > All six anchors: 2 occurrences each = 1 in body + 1 in ledger reference. Per the anchor uniqueness rule (剔除登记块后出现且仅出现 1 次), all anchors are valid.  Collection complete. Final report to orchestrator (pure data, per the 回报格式): - File path - Key findings ≤5 (with Tier & date) - Conflicts count & most important; ledger metric count - 未获取到 count & key gaps - Escalation items  Sources to list as markdown links per WebSearch instructions.

#### 3.x.4 Write 落盘的「## 发现」节首稿摘录

- **第1次 Write｜行108｜11:05:38｜内容 11724 字符**，「## 发现」节摘录：

```
### 1. 证券标识与上市结构

- 法定主体：北京智谱华章科技股份有限公司（H 股公司，于中华人民共和国成立的股份有限公司），每股面值人民币 0.10 元；H 股于联交所主板上市，代号 2513，每手 100 股 H 股。｜来源：Tier 1，配售公告（披露易，2026-07-09/07-13）定义节。
- 2026-07-14 公告「变更本公司英文名称及英文股份简称」，现名 Z.AI CO., LTD. - H SHARES（HKEX 官方行情页快照所示）。｜来源：Tier 1（公告标题）＋Tier 2（HKEX 页面快照），2026-08-24。
- **ADR 核查（cn_adr=true 参数校验）**：未发现任何美股 ADR／OTC 存托凭证（HKEX 页面、aastocks「美股：沒有相關股票」、多引擎检索均无 ADR 记录）。配售公告中 Rule 144A／Reg S 仅为港股配售惯常条款。结构为 H 股（内资股＋H 股），**非 VIE／开曼架构**——cn_adr=true 参数与事实不符，已作升级项上报。｜来源：Tier 1＋Tier 4，2026-08-25。
- 无 A 股上市（ah_listing=false 属实）；媒体称公司筹划科创板 A 股上市（拟发不超 8% 新股、募资 150 亿元人民币，Tier 5 线索，新浪财经 2026-06-24，未见披露易原文）。

### 2. 最新行情锚（2026-08-24 收盘，延迟 15 分钟快照）

| 项目 | 数值 | 来源（Tier）｜时点 |
|---|---|---|
| 收盘 1,007.00 港元（当日 −122.00，−10.81%） | 1,007.00 | 富途 futunn（Tier 4，2026-08-24 16:07 北京）；stockanalysis（Tier 4，2026-08-24 16:08 HKT）；Yahoo 快照（Tier 4）；HKEX 官方行情页 Google 快照 "HK$1,007.000"（Tier 2）——四源一致 |
| 前收市（2026-08-21） | 1,129.00 | 富途／stockanalysis（Tier 4） |
| 当日开市／最高／最低 | 1,150.00／1,150.00／1,000.00（富途）；stockanalysis 日区间 1,006.00–1,150.00 | Tier 4（日内低点两源差 6 元，取区间表述） |
| 成交量／成交额 | 409.35 万股（4,093,070 股）／42.89 亿港元；换手率 1.70%；振幅 13.29%；均价 1,047.824 | 富途（Tier 4，2026-08-24）；成交量与 stockanalysis 完全一致 |
| 52 周区间 116.10–2,980.00 港元 | 低 116.10（≈IPO 定价 116.20 下方）；盘中最高 2,980（未注明确切交易日，约 2026 年 7 月上中旬，见 §5 路径） | 富途「52周最高 2,980.000／52周最低 116.100」＋stockanalysis（Tier 4，2026-08-24） |
| 市盈率 TTM −90.14 倍（亏损所致负值；stockanalysis/Yahoo 列示 n/a） | −90.14 | 富途（Tier 4，2026-08-24） |
| 市净率 | −52.33（净资产为负） | 富途（Tier 4） |
| 较 IPO 定价累计 | 1,007.00／116.20 − 1 ＝ ＋766.6%（约 8.67 倍） | 本线计算 |
| 较 52 周高点回撤 | 1,007.00／2,980.00 − 1 ＝ −66.2% | 本线计算 |

### 3. 股本结构（Tier 1，披露易）

- **总股本 465,623,090 股（内资股 224,528,485 ＋ H 股 241,094,605）**，截至 2026-07-31，当月无变动。｜来源：月报表《截至二零二六年七月三十一日止月份之股份发行人的证券变动月报表》（披露易，2026-08-04 16:33 刊发）。Tier 1。
- 2026-07-31 至 2026-08-24 期间披露易无新股发行公告（该区间仅 8-18 董事会会议通知），465,623,090 股即当前有效总股本。
- 股权结构（紧随 2026-07-13 配售完成后，Tier 1）：未上市内资股 224,528,485 股（48.22%，其中单一最大股东集团 123,042,373 股／26.43%）；H 股 241,094,605 股（51.78%），其中单一最大股东集团 10,001,857 股（2.15%）、其他 H 股股东 211,312,748 股（45.38%）、配售承配人 19,780,000 股（4.25%，已成为主要股东，持股逾 10% 门槛见 7-14/7-15 翌日披露报表）。公告注明单一最大股东集团为一致行动方 grouping（含北京智谱华章发展中心等 8 名主体，含员工持股平台）。
- 一般授权：2026-06-22 AGM 授发上限 89,168,618 股（当时已发行 445,843,090 股的 20%）；配售 19,780,000 股已消耗部分授权，剩余空间约 69,388,618 股（本线按公告数字推算）。

### 4. 市值（两种口径，截至 2026-08-24 收盘）

- **总市值（含未上市内资股，研究主口径）：465,623,090 股 × 1,007.00 港元 ＝ 4,688.83 亿港元**。富途快照「总市值 4688.82 亿」逐字一致（尾差为四舍五入）；内地媒体口径同此（东方财富 7-8 报道「市值 7178 亿港元」＝ 445,843,090 × 1,610，同用总股本口径）。｜Tier 1 股本 × Tier 4 价格，2026-08-24。
- **H 股（上市证券）市值：241,094,605 × 1,007.00 ＝ 2,427.82 亿港元**。富途「流通值 2427.82 亿」逐字 …[截断，共6045字符]
```

#### 3.x.6 最终回报（最后一条 text，逐字，截断 1800 字符）

（行125｜11:06:29）

```
六个锚点均满足唯一性（正文 1 次 + 登记块引用 1 次）。W1 采集 02-market 线完成。

## 回报

**输出文件**：`C:\Users\zliu71\Documents\equity-research-workflow\research\Zhipu_02513HK_20260825\collection\02-market.md`

**关键发现（≤5 条）**
1. 股本（Tier 1，披露易月报表 2026-08-04，截至 2026-07-31）：总股本 465,623,090 股＝内资股 224,528,485＋H 股 241,094,605，7 月 31 日后无新发行公告，即当前有效股本。
2. 行情锚（Tier 4 四源一致 + HKEX 页快照，2026-08-24 收盘）：1,007.00 港元（−10.81%），前收 1,129.00（8-21），52 周区间 116.10–2,980.00（上市未满一年，高点约 7 月上中旬），自 IPO 定价 116.20 累计 +766.6%，自高点回撤 −66.2%。
3. 市值双口径（2026-08-24）：总股本口径 4,688.83 亿港元（富途逐字 4,688.82 亿）；H 股（上市证券）口径 2,427.82 亿港元——对账时须按 scope 区分；聚合站 stockanalysis/Yahoo 仍用配售前旧股本 445.84M，不可采。
4. 7 月资本行动（Tier 1）：基石解禁日 2026-07-08（收市 1,825，Tier 1）→ 7-13 完成配售 19,780,000 股新 H 股 @1,588（折让 12.99%），净筹约 313.75 亿港元（55%/15%/30% 用于研发/扩张/营运）；另媒体称筹划科创板上市（Tier 5 未溯源）。
5. 估值锚（Tier 4/计算值）：PE TTM −90.14（亏损，富途口径；stockanalysis 列 n/a）、PS TTM ≈499 倍（本线按总市值/收入 TTM 8.06 亿元 CNY、汇率 0.8585 计算，区间 495–503）、PB −52.33（净资产为负）；2026-06-08 纳入恒生科技指数并获港股通资格（Tier 5，8-24 南向净流出 8,644 万港元反证已在通）。

**冲突**：5 条（含 1 条口径并列非错误）。最重要：总市值 4,688.83 亿港元（Tier 1 股本×收盘价）vs Yahoo 4,489.64 亿/stockanalysis 5,033.6 亿——后两者沿用 7-13 配售前旧股本 445,843,090。
**指标登记**：6 条（price_close / market_cap / shares_outstanding / high_52w / pe_ttm / ps_ttm，锚点唯一性已验证）。
**未获取到**：7 条。关键缺口：① 2026-08-25 采集当日收盘（各源缓存止于 8-24，HKEX 实时接口不可直连）；② 52 周高点 2,980.00 的确切交易日；③ 南向持股余额/最新沽空比率。
**升级项**：① `cn_adr=true` 与事实不符——未发现任何 ADR/OTC 存托凭证，且公司为 H 股架构（内资股+H 股，北京智谱华章科技股份有限公司，非 VIE/开曼），建议编排端修正标记；② 披露易 PDF 中文层提取为乱码（数字无损），原文附录关键表述按标准格式复原并已标注，A/D 条引用需以原始 PDF 复核；③ 聚合站缓存严重滞后（aastocks 3-06、Google Finance 3-24、etnet 5-28），后续波次勿用其作现价。

Sources: [披露易·月报表(2026-07-31)](https://www1.hkexnews.hk/listedco/listconews/sehk/2026/0804/2026080400751_c.pdf) | [披露易·配售完成公告(2026-07-13)](https://www1.hkexnews.hk/listedco/listconews/sehk/2026/0713/2026071300663_c.pdf) |  …[截断，共2542字符]
```

---

### 3.3 03-consensus（agent aea096e0aa72f35a6｜W1 采集 03 预期线）

#### 3.x.1 派发 prompt（主 agent → collector，逐字）

```
[PARAMS]
workdir=C:/Users/zliu71/Documents/equity-research-workflow/research/Zhipu_02513HK_20260825
skill_root=C:/Users/zliu71/Documents/equity-research-workflow/.claude/skills/equity-research-skill
company=智谱（Zhipu AI / Z.ai）
ticker=02513.HK
exchange=香港交所主板
mode=full
language=zh
currency=HKD
ah_listing=false
cn_adr=true
prior_report=none
forecast_review=none
coverage=initiation
line=03-consensus

执行 W1 采集：full 模式 03-consensus（一致预期与电话会线）。
```

#### 3.x.2 工具时间线（全部工具调用）

```
  行   3 10:53:57  Read       C:/Users/zliu71/Documents/equity-research-workflow/.claude/skills/equi
  行   5 10:53:58  Read       C:/Users/zliu71/Documents/equity-research-workflow/.claude/skills/equi
  行   7 10:53:58  Read       C:/Users/zliu71/Documents/equity-research-workflow/.claude/skills/equi
  行  11 10:54:14  WebSearch  智谱 02513.HK 港股 上市
  行  12 10:54:14  WebSearch  Zhipu AI 02513 HKEX IPO listing date
  行  13 10:54:14  WebSearch  智谱 02513 分析师 目标价 评级
  行  21 10:54:42  WebSearch  智谱 2025年 年度业绩 公告 亏损 收入
  行  22 10:54:42  WebSearch  智谱 02513 2026 中期业绩 业绩会 电话会
  行  31 10:54:56  WebSearch  智谱 02513 2026 中期业绩 上半年 收入 亏损
  行  32 10:54:57  WebSearch  智谱 02513 业绩会 纪要 2026年8月
  行  37 10:55:05  WebSearch  智谱 02513 中期业绩 2026 上半年 8月 业绩发布会
  行  47 10:55:29  WebSearch  智谱 2026 中期业绩 上半年 收入 亏损 02513
  行  48 10:55:30  WebSearch  智谱 02513 业绩会 分析师会议 电话会 2026年8月
  行  49 10:55:30  WebSearch  摩根大通 智谱 目标价 2400港元
  行  57 10:56:31  WebSearch  智谱 大和 首次覆盖 买入 1500港元 Daiwa
  行  58 10:56:32  WebSearch  智谱 汇丰 目标价 1500港元 ARR 20亿美元
  行  65 10:57:10  WebSearch  智谱 2025年度业绩 业绩会 3月 管理层 唐杰 张鹏
  行  66 10:57:10  WebSearch  智谱 招股书 员工 人数 研发人员
  行  67 10:57:11  WebSearch  智谱 02513 招银国际 买入 目标价1503.9港元
  行  68 10:57:11  WebSearch  智谱 02513 中金 跑赢行业 688港元 目标价
  行  77 10:57:45  WebSearch  里昂 智谱 2061港元 跑赢大市 上调
  行  78 10:57:45  WebSearch  摩根大通 智谱 下调 1600港元 Kimi K3 竞争
  行  79 10:57:45  WebSearch  汇丰研究 智谱 目标价 1500 持有评级 下调
  行  86 10:58:00  WebFetch   http://www.aastocks.com/tc/stocks/analysis/consensus/02513
  行  87 10:58:00  WebSearch  智谱 唐杰 内部信 四大核心引擎 不追求短期变现
  行  92 10:59:07  WebFetch   https://www.shobserver.cn/wx/detail.do?id=1143340
  行  93 10:59:07  WebSearch  智谱 张鹏 业绩说明会 API调用 定价 提升83% 调用量 400%
  行  94 10:59:08  WebSearch  智谱 ARR 10亿美元 2026年7月 MaaS
  行  95 10:59:08  WebSearch  智谱 GLM-5.3 发布 2026年8月
  行 102 10:59:49  WebSearch  智谱 配售 1588港元 314亿港元 新股配售
  行 103 10:59:49  WebSearch  月之暗面 Kimi K3 发布 2026年7月 智谱 大跌
  行 104 10:59:49  WebSearch  高盛 智谱 上调 收入 预期 2026年7月
  行 105 10:59:49  WebSearch  智谱 2025年报 截至2025年12月31日 员工 人数
  行 112 11:00:16  WebSearch  "滙豐" OR "汇丰" 智譜 目標價 1,500港元 持有 提前轉盈 8月
  行 113 11:00:16  WebSearch  智谱 单日 上涨37% 7月31日 ARR
  行 122 11:01:00  WebSearch  滙豐 智譜 02513 目標價1500 持有 8月 轉盈
  行 123 11:01:01  WebSearch  里昂 智谱 维持跑赢大市 2061港元 ARR 减速 过度反应
  行 128 11:04:53  Write      C:/Users/zliu71/Documents/equity-research-workflow/research/Zhipu_0251
```

#### 3.x.3 格式相关 thinking 摘录（关键词：## 发现/输出契约/格式/模板/按主题/值｜）

- **行126｜11:03:25（thinking 片段，±窗口摘录）**

  > Files written as input to another tool are fine; this note is about report files.)" — but my role's contract explicitly requires writing the collection file (it's input to the reconciliation pipeline), so writing is correct per the agent definition (输出契约 mandates it). The system note about not writing report files is a generic agent note; my specific task contract overrides since the file is pipeline input. Yes — the采集文件 is explicitly required by the orchestrator contract.  Also anchors: ensure the exact anchor strings appear verbatim exactly once each in body text. Let me draft carefully:  Anchor 1: "2026H1 营收一致预期为 18.078 亿元人民币（标普口径，仅 1 位分析师）" — I'll place this exact sentence in the 一致预期 su

#### 3.x.4 Write 落盘的「## 发现」节首稿摘录

- **第1次 Write｜行128｜11:04:53｜内容 11116 字符**，「## 发现」节摘录：

```
### 1. 一致预期（共识）

- 分析师覆盖广度与评级分布（富途牛牛，统计时点 2026-07-26；富途搜索快照 2026-08-22 分布相同）：近三个月共 20 位分析师评级，强力推荐 80.00%、买入 20.00%、持有 0.00%、卖出 0.00%。富途财报页"分析师评级：强力推荐"更新时间 2026-08-24。（Tier 4；URL：futunn.com/stock/02513-HK/forecast、/earnings；抓取 2026-08-25）
- 目标价共识（富途，统计时点 2026-07-26）：平均 1,306.64 港元，最高 2,043.00 港元，最低 906.18 港元。（Tier 4；同上）
- 营收一致预期（富途财报页转引标普/S&P 口径，货币单位人民币，抓取 2026-08-25 实时页）：2026H1 营收一致预期为 18.078 亿元人民币（标普口径，仅 1 位分析师）。2026H2 营收一致预期为 67.675 亿元人民币（同源标普口径）。页面明示"一共 1 位分析师对营收做出预测。预测值来源于标普"。注意：单一分析师、单源聚合，未获第二独立源核对；2026H2 预测为 H1 的 3.7 倍，隐含极陡的环比爬坡，合理性待 8/31 中期业绩验证。（Tier 4）
- EPS 一致预期：未获取到（亏损期公司，免费聚合层无 EPS 预测明细，见"未获取到"）。
- 财报日历：2026H1 中期业绩定于 2026-08-31（周一）董事会会议审议并发布（董事会会议通知 2026-08-18 16:47 港交所公告；富途公告列表抓取 2026-08-25）。截至采集时点业绩未发布，本线记录的均为"财报前"预期。2025 年度业绩公告 2026-03-31 17:30，《2025 年度报告》2026-04-19 18:30。
- 上市后已有业绩事件：仅 2026-03-31 的 2025 年度业绩说明会（上市后首个业绩会，媒体到场，见第 3 节）；8/31 将为第二次。

### 2. 卖方观点与目标价（按时间序）

| 日期 | 机构 | 动作 | 评级 | 目标价(港元) | 核心观点（媒体转述） | 来源（Tier） |
|---|---|---|---|---|---|---|
| 2026-02-16 | 中金 | 首次覆盖 | 跑赢行业 | 688 | 看好基座模型能力迭代与 Coding 场景兑现，对标海外头部大模型公司估值；基于 2028 年 40x P/S、远期折现率 7%；当时上行空间约 42% | 东方财富/财联社（Tier 5） |
| 2026 年 6 月（约中旬，待核） | 中金 | 上调 | 跑赢行业（维持） | 1,250 | 维持看好 | 检索摘要（Tier 5，日期未落实） |
| 2026-06-12 | 招银国际 | 首次覆盖 | 买入 | 1,503.9 | 中国领先的独立 LLM 开发商之一，基座模型到应用全产业链 | 新浪财经（Tier 5） |
| 约 2026 年 2–4 月（待核） | 摩根大通 | 上调 800→950 | 增持 | 950 | 开放平台 API 需求强劲 | 检索摘要（Tier 5，日期未落实） |
| 2026-07-07（周二） | 摩根大通 | 上调 1,800→2,000 | 增持 | 2,000 | GLM-5.2 表现强劲 | 新浪财经 2026-07-13 报道回溯（Tier 5） |
| 2026-07-13 | 摩根大通 | 上调 2,000→2,400 | 增持（维持） | 2,400 | 收入前景更明朗；最新募资计划将助力营收增长；同日降 MiniMax 目标价至 240 | 新浪财经/AASTOCKS（Tier 5） |
| 约 2026-07-20/21（待核） | 摩根大通 | 下调 2,400→1,600 | 增持/超配（维持） | 1,600 | 月之暗面 Kimi K3 发布加剧竞争、重置前沿模型长期估值框架；认为市场回调过度（此前自高点回撤超 50%）；非看空中国大模型需求，竞争进入体系竞争阶段；下调后股价单日反弹近 37% | ZAKER 转引（Tier 5） |
| 2026-07-13 | 里昂（CLSA） | 上调 1,500→2,061，评级升至跑赢大市 | 跑赢大市 | 2,061 | GLM-5.3 后训练能力显著提升（彼时针对模型预期），复杂编码及长周期代理国内同业领先 | 新浪财经 2026-07-13（Tier 5） |
| 2026-07-13 | 瑞银证券（熊瑋，行业） | 行业主题报告 | — | — | 2026 下半年中国 AI 模型三大主题：模型能力、变现、词元 ROI（Token ROI）；编程（Coding）变现潜力大 | AASTOCKS（Tier 5） |
| 约 2026-07-27（待核，另有 8 月下旬转述版本） | 汇丰研究 | 下调 1,900→1,500（-21.1%） | 持有（维持） | 1,500 | 竞争加剧、价格战压低预期 FCF、潜在股份摊薄；但料提前转盈：2028 年盈亏平衡（早于此前预期的 2029 年），上调 2026–28 财年 Non-IFRS 盈利预测，上调 2026 年 12 月 ARR 预测至 20 亿美元；报告语境现价约 1,281 港元（2026-07-27）对应上行空间约 17.1% | Yahoo 财经香港等（Tier 5） |
| 2026-08-06/07 | 高盛 | 上调收入预期 | — | —（未见 TP） | 上调智谱 2026 年收入预期 35%；预测中国 AI 模型 2026 年底合计 ARR 130 亿美元，其中智谱 API 业务 ARR 升至 25 亿美元；中国大模型 API 及订阅收入自 2026 年 350 亿元人民币增至 2030 年 8,790 亿元；同上调 MiniMax 2026–28 收入 22%–64%；8/6 智谱盘中涨超 9% | 21 财经 2026-08-07（Tier 5） |
| 2026-08-12 | 大和（Daiw …[截断，共6523字符]
```

#### 3.x.6 最终回报（最后一条 text，逐字，截断 1800 字符）

（行131｜11:05:16）

```
采集完成。回报如下。

**文件路径**
`C:\Users\zliu71\Documents\equity-research-workflow\research\Zhipu_02513HK_20260825\collection\03-consensus.md`

**关键发现（≤5 条）**
- 覆盖与共识：近三个月 20 位分析师，强力推荐 80%/买入 20%/无卖出；目标价均值 1,306.64 港元、区间 906.18–2,043.00 港元（富途，2026-07-26 统计，Tier 4，8/22 快照分布不变）。
- 营收一致预期（标普口径经富途，仅 1 位分析师，2026-08-25 抓取，Tier 4）：2026H1E 18.078 亿元人民币、2026H2E 67.675 亿元人民币；中期业绩 2026-08-31 发布，当前均为财报前预期。
- 卖方分歧极大且方向随事件快速切换（均 Tier 5 转述）：中金 2/16 首覆 688（40x 2028 P/S）→6 月上调 1,250；摩通 7/7→2,000、7/13→2,400、7 月下旬 Kimi K3 后砍至 1,600（维持超配）；里昂 7/13 升至 2,061、8/19 重申；汇丰 1,900→1,500（持有，料 2028 提前转盈）；大和 8/12 首覆买入 1,500；招银国际 8/17 重申 1,503.9；高盛 8/6 上调 2026 收入预期 35%。
- 管理层锚点：3/31 业绩会张鹏称 2026Q1 API 定价 +83%、调用量 +400%、供不应求；ARR 自 2026 年 1 月 0.4 亿美元增至 7 月 10 亿美元（提前半年兑现市场年底 10–15 亿预期，7/21 单日 +37%）；公司无收入指引，仅有上市日唐杰内部信《巨浪已来》定性战略（不追求短期变现、四大核心引擎）。
- 7 月剧烈波动链：7/8 解禁 5.76% → 7/9-13 配售 1,588 港元/股募约 314 亿港元 → 7/16 前后 Kimi K3 发布 → 7/17-20 两日累跌约 43%（自 6/22 高点 2,980 回撤约 70%）→ 8 月分化修复。

**冲突与登记**
- 冲突表 4 条；最重要一条：2026 年底智谱 ARR 预测 汇丰 20 亿美元（约 7/27）vs 高盛 25 亿美元（8/6，表述为“API 业务 ARR”）——疑口径不同，待对账裁决。
- 指标登记块 4 条（consensus_revenue_fwd×2：2026H1/2026H2；employees×2：FY2025 1,094 人、2025H1 883 人），anchor 均唯一。

**未获取到**
- 7 条：consensus_eps_fwd（亏损期无 EPS 共识）、guidance_revenue（公司未给指引）、第二独立源一致预期（AASTOCKS 三次失败降级）、业绩会逐字稿/录音（仅媒体转述片段，已入附录 A1–A6）、汇丰研报确切日期（7/27 与 8 月下旬两窗口）、中金 6 月/摩通早期调价确切日期、2026H1 实际业绩（8/31 才发布，预期内）。

**升级项**
- 无代码解析或同名公司问题。提示两点供编排者注意：(1) 一致预期收入为富途（标普）单源单分析师，置信度有限，建议 02 线若采到 Bloomberg/LSEG 口径可对撞；(2) 研报观点全部为 Tier 5 媒体转述（无卖方原始报告权限），关键数字建议以 8/31 中期业绩与披露易原文复核。
```

---

### 3.4 01-disclosure（agent a0a00fb6a14b85a33｜W1 采集 01 披露线）

#### 3.x.1 派发 prompt（主 agent → collector，逐字）

```
[PARAMS]
workdir=C:/Users/zliu71/Documents/equity-research-workflow/research/Zhipu_02513HK_20260825
skill_root=C:/Users/zliu71/Documents/equity-research-workflow/.claude/skills/equity-research-skill
company=智谱（Zhipu AI / Z.ai）
ticker=02513.HK
exchange=香港交易所主板
mode=full
language=zh
currency=HKD
ah_listing=false
cn_adr=true
prior_report=none
forecast_review=none
coverage=initiation
line=01-disclosure

执行 W1 采集：full 模式 01-disclosure（一手披露线）。
```

#### 3.x.2 工具时间线（全部工具调用）

```
  行   3 10:53:53  Read       C:/Users/zliu71/Documents/equity-research-workflow/.claude/skills/equi
  行   5 10:53:54  Read       C:/Users/zliu71/Documents/equity-research-workflow/.claude/skills/equi
  行   7 10:53:54  Read       C:/Users/zliu71/Documents/equity-research-workflow/.claude/skills/equi
  行  11 10:54:20  WebSearch  智谱 02513.HK 港交所 上市 招股书
  行  12 10:54:20  WebSearch  Zhipu AI Z.ai 02513 HKEX IPO prospectus listing date
  行  17 10:54:51  WebFetch   https://www1.hkexnews.hk/search/prefix.do?callback=callback&lang=ZH&ty
  行  18 10:54:51  WebSearch  智谱 02513 2025年度业绩公告 年报 披露易
  行  51 10:56:10  WebFetch   
  行  82 10:57:39  WebFetch   
  行 121 10:59:52  WebSearch  智谱 02513 2026年8月 董事会会议 中期业绩 8月
  行 147 11:01:35  Glob       
  行 151 11:06:37  Write      C:/Users/zliu71/Documents/equity-research-workflow/research/Zhipu_0251
```

#### 3.x.3 格式相关 thinking 摘录（关键词：## 发现/输出契约/格式/模板/按主题/值｜）

- **行149｜11:04:35（thinking 片段，±窗口摘录）**

  > d (other line running in parallel). I write my file: collection/01-disclosure.md.  Let me now carefully compile the collection file. Structure per output contract:  ``` # 采集文件：01-disclosure（full 模式） 头部：公司（代码/上市地）｜财年口径｜采集时间（YYYY-MM-DD HH:MM）｜本线范围一句话  ## 发现 按主题分区  ## 指标登记 YAML block  ## 冲突 table  ## 未获取到 table  ## 原文附录 逐字引用块 ```  Now the 指标登记 block. Collision-metrics for line 01-disclosure (full mode): - shares_outstanding (股) ✓ — 465,623,090 (as of 2026-07-31 monthly return; latest) - revenue (元) ✓ — FY2025: 724,334 千元 → unit 千元, value 724,334 - revenue_segment (repeatable, scope_required) ✓ — FY2025: 本地化部署 533,955 千元; 云端部署 190,379 千元. Should I also register product-line segments? The revenue_segments_sum crosscheck sums by scope — if I register both deployment segments AND product-line segments, the sum check would double-count. Better to register one classification only (deployment: the …[截断，共28288字符]

- **行153｜11:06:46（thinking 片段，±窗口摘录）**

  > The file is written. Now compose the final report (回报格式): - File path - Key findings ≤5 (one line each, Tier + date) - Number of conflict entries and the most important one; number of registered metric entries (separate columns) - Number of missing items and key gaps - Escalation items  Conflicts: 3 rows (greenshoe share count; capex definition; media net loss interpretation). Most important: greenshoe 5,612,900 vs 5,623,900 company announcement internal inconsistency. Ledger entries: 21. Not obtai

#### 3.x.4 Write 落盘的「## 发现」节首稿摘录

- **第1次 Write｜行151｜11:06:37｜内容 18508 字符**，「## 发现」节摘录：

```
### A. 公司与证券基本盘（均 Tier 1，披露易）

- 2019-06-11 成立为有限责任公司；2025-03-26 改制为股份有限公司；2026-01-08 H股于联交所主板上市（18C）。2026-01-08 起撤销监事会。核数师：毕马威（KPMG，项目合伙人温梓佑）；合规顾问迈时资本；H股登记处卓佳。
- 2026-06-01 董事会通过建议 A 股发行并在科创板上市 + 英文名变更；2026-06-22 年度股东会通过；2026-07-14 公告英文名由 Knowledge Atlas Technology Joint Stock Company Limited 变更为 Z.AI Co., Ltd.（中文不变）。
- 控股股东集团（一致行动人协议 2023-04-05）：北京鏈湃、刘德兵（董事长/执行董事）、唐傑（创始人/首席科学家）、李涓子、许斌、张鹏（CEO/执行董事）、慧惠、智登；配售完成后合共 133,044,230 股（未上市 123,042,373 + H股 10,001,857），约占 28.58%，禁售至 2027-01-07。基石投资者（禁售 6 个月，2026-07-07 届满）与领航资深独立投资者（君联资本、美团/天津三快）禁售亦已届满；全体现有股东按中国法律禁售至 2027-01-07。

### B. 股本与融资时间线（Tier 1）

- 总股本（已发行股份总数，截至2026-07-31月末）：465,623,090股＝H股241,094,605＋未上市股份224,528,485（来源：披露易月报表，呈交日 2026-08-04；本月底法定股本总额 RMB 46,562,309，面值每股 RMB 0.10）
- 股本路径：IPO 前拆细后普通股 402,810,690 股（1 拆 10，2025-06-13 决议、上市前生效；年报附注拆细后约数 402,810,000）→ 2026-01-08 全球发售 37,419,500 股 H股 @116.20 港元，上市后 440,230,190 股 → 2026-02-04 超额配股权悉数行使 5,612,900 股 @116.20 港元，至 445,843,090 股 → 2026-07-13 一般授权配售 19,780,000 股新 H股 @1,588.00 港元，至 465,623,090 股。
- IPO 认购：香港公开发售 1,159.46 倍（204,871 份申请，回拨至 20%）、国际发售 15.28 倍；基石合计 25,681,600 股（占发售 68.63%），最大基石 JSC International Investment Fund SPC（代表 Qizhi SP，现有股东紧密联系人，获 11,985,900 股/32.03%）；独家保荐人中金。IPO（未含绿鞋）所得款项总额 4,348.1 百万港元、净额 4,173.4 百万港元；含绿鞋合计发行 43,032,400 股，所得款项总额 5,000,365,000 港元（≈人民币 4,516,430,000 元）、净额约 4,896.2 百万港元。
- IPO 募资净额使用进度（Tier 1 三时点）：截至 2026-04-10 已用 1,828.11；截至 2026-05-29 已用 2,057.62；截至 2026-06-30 已用 4,588.15、未用 308.02（百万港元；用途 70% 研发 / 10% MaaS 平台 / 10% 生态与战投 / 10% 营运资金，预计 2027 年底前（配售公告表述）或招股书口径 2028-12-31 前动用完毕）。
- 2026-07 配售：19,780,000 股新 H股 @1,588.00 港元（不少于 6 名承配人，占扩大后 H股 4.25%），所得款项总额约 31,410.64 百万港元、净额约 31,374.95 百万港元；拟用途 55% 研发 / 15% 业务拓展·战略投资及并购 / 30% 资本结构与营运资金，预期 2027 年底前动用。
- 建议 A 股发行（科创板）：发行数量为发行后总股本的 2%–8%（不含绿鞋），即 9,098,838–38,768,964 股新股（以 445,843,090 股为基数）；绿鞋另计 15%。拟募投合计人民币 15 亿元：人工智能通用基座大模型 12 亿 + 大模型 MaaS 一站式服务平台 2 亿 + 补充流动资金 1 亿。保荐机构国泰海通、审计容诚、中国法律天元。2026-06-22 股东会批准；2026-07-07 澄清公告：辅导工作已完成（据证监会网站），媒体「撤回辅导备案」报道失实。发行后全部现有未上市股份将转换为 A 股并在科创板上市（受禁售限制）。

### C. FY2025 经审计财务（Tier 1：年度业绩公告 2026-03-31 + 2025 年报 2026-04-19，KPMG 审计）

四年财务概要（人民币千元，年报「财务概要」）：

| 项目 | 2025 | 2024 | 2023 | 2022 |
|---|---|---|---|---|
| 收入 | 724,334 | 312,414 | 124,538 | 57,409 |
| 销售成本 | (427,678) | (136,525) | (44,056) | (26,049) |
| 毛利 | 296,656 | 175,889 | 80,482 | 31,360 |
| 除税前亏损 | (4,718,167) | (2,958,007) | (787,957) | (143,650) |
| 年内亏损 | (4,718,167) | (2,958,007) | (787,957) | (143,650) |
| 经调整年内净亏损（非IFRS） | (3,181,972) | (2,465,569) | (620,984) | (97,417) |
| 资产总值 | 4,853,861 | 4,375,769 | 2,860,153 | 361,976 |
| 负债总额 | 12,964,843 | 8,330,914 | 3,842,746 | …[截断，共7733字符]
```

#### 3.x.6 最终回报（最后一条 text，逐字，截断 1800 字符）

（行154｜11:06:57）

```
W1 采集完成（full 模式 01-disclosure 线）。

**文件路径**：`C:\Users\zliu71\Documents\equity-research-workflow\research\Zhipu_02513HK_20260825\collection\01-disclosure.md`

**关键发现（≤5）**
1. FY2025 经审计（KPMG，业绩公告 2026-03-31/年报 2026-04-19，Tier 1）：收入 724,334 千元（+131.9%），年内亏损 -4,718,167 千元（归母 -4,698,203），经调整净亏损 -3,181,972 千元，毛利率 41.0%（2024：56.3%），研发开支为收入 4.4 倍。
2. 总股本 465,623,090 股（=H股 241,094,605 + 未上市 224,528,485；月报表 2026-08-04，Tier 1）：IPO 37,419,500 股 @116.20 港元（2026-01-08）→ 绿鞋 5,612,900 股（2026-02-04）→ 配售 19,780,000 股 @1,588.00 港元（2026-07-13，净筹 313.75 亿港元）——02 线算市值请用此股本。
3. 资产负债表深度亏绌 -8,110,982 千元，主因“向投资者发行的金融工具”10,072,827 千元列债；2026-01-08 上市后已转股权+募资总额 50.00 亿港元；现金及等价物 2,259,147 千元、未动用银行融资 5,235,909 千元（持续经营依据，Tier 1）。
4. 重大公司行动（Tier 1）：建议 A+H（科创板，发行后总股本 2%–8%，拟募 15 亿元，2026-06-22 股东会通过、辅导已完成）；收购北京红钻（钻石大厦，总代价 ≤3.605 亿元，期限 2026-08-31）；2026-08-31 董事会审议 2026 中期业绩（最近催化）。
5. 收入分部（FY2025）：本地化部署 533,955 / 云端部署 190,379 千元；产品线口径 API 190,379/智能体 165,687/通用大模型 365,724/其他 2,544 千元；五大客户占 26.51%、最大供应商占采购 20.92%。

**冲突**：3 条；最重要一条＝绿鞋行使股数 5,612,900（业绩公告/年报，与股本勾稽 440,230,190+5,612,900=445,843,090 吻合）vs 5,623,900（2026-06-01 及 07-13 公告两处），同一公司 Tier 1 公告内部矛盾，疑后两份笔误，已双值并列待裁决。
**指标登记块**：21 条（清单内：shares_outstanding/revenue×2/revenue_segment×4/gross_profit/operating_income/net_income×2/cfo/capex/fcf/eps/total_assets/total_liabilities/total_equity/receivables/deferred_revenue/employees）。

**未获取到**：4 条；关键缺口＝招股章程（2025-12-30）原文（servlet 12 月窗口两次失败；FY2022/2023 已由年报四年概要覆盖）、2026 中期业绩（2026-08-31 董事会审议，尚未发布）。

**升级项**：PARAMS 的 cn_adr=true 与实际不符——智谱为境内注册股份有限公司直接 H 股上市（无 VIE、无 ADR 迹象），后续章节按 H 股口径处理；A 股发行完成前属“H+未上市内资股”结构。
```

---


## 4. 观察与复现

### 4.1 thinking 全文格式字符串计数（验证 §0.5）

| line | thinking 块数/总字符 | '值｜' | 'URL 或文件名' | '按主题' | '输出契约' |
|---|---|---|---|---|---|
| 01-disclosure | 23 / 74,820 | 0 | 0 | 1（结构骨架复述，发现行被截为仅"按主题分区"） | 0 |
| 02-market | 15 / 72,205 | 0 | 0 | 0 | 0 |
| 03-consensus | 16 / 69,218 | 0 | 0 | 0 | 1（写文件权限论证，非格式） |
| 04-industry | 16 / 30,644 | 2（显式复述行内四段式） | 0 | 0 | 0 |

### 4.2 观察结论

1. 行内格式对落盘产物无任何强制点：body 输出契约 → collector 落笔（无读回自查）→ 编排者只读"回报小结"不读采集正文 → W2 打戳只要求 anchor 唯一（任意格式正文均可命中）→ W8 lint/checker 不校验行内来源格式。偏差因此在全链路静默通过。
2. 04 线证明该格式可被 agent 主动复述并（部分）执行——问题不在格式不可行，而在无执行压力时各线自由解释"按主题分区"前半句。
3. 采集文件的四节固定结构（指标登记 YAML/冲突/未获取到/原文附录）全部执行，说明"结构骨架"类指令可靠、"行内微格式"类指令无验收即失效。
4. 下游实际影响有限：W2 anchor 打戳、W3 质检、W4-W7 引用均以正文叙述行为锚点工作正常；但"每个关键数字自带 URL/日期"的可追溯性确实弱化为节级/条目级（04 线条目级、01 线节级+F 节清单级）。

### 4.3 复现方式

- transcript 源：`~/.claude/projects/C--Users-zliu71-Documents-equity-research-workflow/1448280e-ad28-4a61-a82f-b06c60a35c84/subagents/agent-<id>.jsonl`（collector id：01=a0a00fb6a14b85a33、02=ab1fa32c8dc66b838、03=aea096e0aa72f35a6、04=a1fb68d97f4f62d91）
- 契约版本：`git show 5870a00:.claude/agents/equity-data-collector.md`（2026-08-21 提交，运行时生效版；当前版本该节文字未变）
- 本文件 §3 由脚本逐字提取（thinking 取关键词±窗口、Write 取"## 发现"节至下一二级标题、截断处已标注字符数）

### 4.4 追加溯源：「Do NOT Write report/summary .md files」note 的来源（2026-09-13 补查）

collector thinking 中引用的通用 note 并非用户/项目配置，而是 **Claude Code CLI 编译内置的 subagent 系统提示模板**：

- 排除：用户全局 CLAUDE.md、项目 CLAUDE.md、settings、skill/agent 定义均无此句（全目录 grep）；subagent transcript 不落盘系统提示（JSONL 仅 user/assistant 条目）。
- 实证：`claude.exe` 偏移 195,831,722 处，subagent 系统提示组装函数 `Bfe(e,n)` 内的固定 `Notes:` 块，末条即 `Do NOT ${Pn} report/summary/findings/analysis .md files. Return findings directly as your final assistant message — the parent agent reads your text output, not files you create. (Files written as input to another tool are fine; this note is about report files.)`（${Pn} 运行时替换为 Write）。该块无条件追加给每个 Agent 工具派发的 subagent，与 agent 类型无关——故四条采集线全部收到，02/03/04 在 thinking 中复述并按"豁免条款＋角色契约优先"化解（见 §3.2/§3.3 行106/行126、§3.1 行98）。
- 指令栈结论：collector 实际运行在三层指令下——①CLI 编译 Notes（反报告文件）＋②agent body 输出契约（必须写 collection/<line>.md）＋③编排者 [PARAMS] 派发句。①②冲突由 agent 自行裁决放行写文件；而输出契约内部无验收机制的行内格式条款（值｜来源｜URL｜日期）仍被丢弃，与 §4.2 观察一致。
- 版本：0825 运行时 CLI 2.1.243；本机现装 2.1.270 模板仍在、文字未变。
