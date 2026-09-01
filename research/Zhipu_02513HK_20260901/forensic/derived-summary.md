# 派生指标摘要（ledger §2 底稿）

> 由 `scripts/derive_metrics.py` 按 `references/derived-metrics.json` 生成，勿手改；
> 重跑：`PYTHONUTF8=1 python <skill_root>/scripts/derive_metrics.py <workdir>`。
> 值为「未获取」＝输入缺失（对应 ledger 列缺口/未转录项），不是计算失败；外部输入与锚见 `forensic/derived-inputs.json`。

| 指标 | 期间 | 值 | 单位 | 公式 |
|---|---|---:|---|---|
| 营收同比（yoy_revenue） | FY2023 | 116.9 | % | yoy(revenue) |
| 营收同比（yoy_revenue） | FY2024 | 150.9 | % | yoy(revenue) |
| 营收同比（yoy_revenue） | FY2025 | 131.9 | % | yoy(revenue) |
| 营收同比（yoy_revenue） | 2025H1 | -73.6 | % | yoy(revenue) |
| 营收同比（yoy_revenue） | 2026H1 | 399.7 | % | yoy(revenue) |
| 毛利率（gm_pct） | FY2022 | 54.6 | % | gross_profit/revenue*100 |
| 毛利率（gm_pct） | FY2023 | 64.6 | % | gross_profit/revenue*100 |
| 毛利率（gm_pct） | FY2024 | 56.3 | % | gross_profit/revenue*100 |
| 毛利率（gm_pct） | FY2025 | 41.0 | % | gross_profit/revenue*100 |
| 毛利率（gm_pct） | 2025H1 | 50.0 | % | gross_profit/revenue*100 |
| 毛利率（gm_pct） | 2026H1 | 26.4 | % | gross_profit/revenue*100 |
| 净利率（年内损益口径）（net_margin） | FY2022 | -250.2 | % | net_income/revenue*100 |
| 净利率（年内损益口径）（net_margin） | FY2023 | -632.7 | % | net_income/revenue*100 |
| 净利率（年内损益口径）（net_margin） | FY2024 | -946.8 | % | net_income/revenue*100 |
| 净利率（年内损益口径）（net_margin） | FY2025 | -651.4 | % | net_income/revenue*100 |
| 净利率（年内损益口径）（net_margin） | 2025H1 | -1235.3 | % | net_income/revenue*100 |
| 净利率（年内损益口径）（net_margin） | 2026H1 | -217.2 | % | net_income/revenue*100 |
| 经营利润率（om_pct） | FY2025 | -522.8 | % | operating_income/revenue*100 |
| 经营利润率（om_pct） | 2025H1 | -995.0 | % | operating_income/revenue*100 |
| 经营利润率（om_pct） | 2026H1 | -225.0 | % | operating_income/revenue*100 |
| FCF 率（fcf_margin） | FY2024 | -761.1 | % | fcf/revenue*100 |
| FCF 率（fcf_margin） | FY2025 | -313.3 | % | fcf/revenue*100 |
| SBC/收入（sbc_revenue） | FY2025 | 77.1 | % | sbc/revenue*100 |
| SBC/收入（sbc_revenue） | 2025H1 | 83.2 | % | sbc/revenue*100 |
| SBC/收入（sbc_revenue） | 2026H1 | 9.0 | % | sbc/revenue*100 |
| 研发费用/收入（rd_revenue） | FY2025 | 439.1 | % | rd_expense/revenue*100 |
| 研发费用/收入（rd_revenue） | 2025H1 | 835.4 | % | rd_expense/revenue*100 |
| 研发费用/收入（rd_revenue） | 2026H1 | 223.4 | % | rd_expense/revenue*100 |
| SGA/收入（sga_revenue） | FY2025 | 123.7 | % | sga/revenue*100 |
| SGA/收入（sga_revenue） | 2025H1 | 206.3 | % | sga/revenue*100 |
| SGA/收入（sga_revenue） | 2026H1 | 29.5 | % | sga/revenue*100 |
| 应收周转天数（净额）（dso_net） | FY2024 | 106.5 | 天 | receivables/revenue*365 |
| 应收周转天数（净额）（dso_net） | FY2025 | 152.8 | 天 | receivables/revenue*365 |
| 应收周转天数（净额）（dso_net） | 2026H1 | 299.6 | 天 | receivables/revenue*365 |
| 应收增速−收入增速（recv_growth_gap_pp） | FY2025 | 100.9 | pp | yoy(receivables)-yoy(revenue) |
| 合同负债同比（yoy_deferred） | 2026H1 | 未获取 | % | yoy(deferred_revenue) |
| 应计比率（accruals_ratio） | FY2024 | -19.7 | % | (net_income-cfo)/avg2(total_assets)*100 |
| 应计比率（accruals_ratio） | FY2025 | -53.6 | % | (net_income-cfo)/avg2(total_assets)*100 |
| 人均创收（rev_per_capita） | FY2025 | 66.2 | 万元 | revenue/employees/10 |
| 人均创收（rev_per_capita） | 2025H1 | 21.6 | 万元 | revenue/employees/10 |
| 人均创收（rev_per_capita） | 2026H1 | 97.2 | 万元 | revenue/employees/10 |
| 收入全周期 CAGR（cagr_revenue_full） | FY2022→2026H1 | 75.4 | %/年 | cagr(revenue) |
| P/S（最新收盘×总股本/最新财年收入）（ps_fy） | 最新 | 499.9 | 倍 | price_close*shares_outstanding*fx_hkd_cny/1000/last(revenue) |
| Rule of 40（rule_of_40） | FY2024 | -610.2 | % | yoy_revenue+fcf_margin |
| Rule of 40（rule_of_40） | FY2025 | -181.4 | % | yoy_revenue+fcf_margin |
| ARR（年化经常性收入）（arr） | 2026-08 | 约16亿美元（月度收入×12年化，2026-08；另有单周×52口径超20亿美元——双口径并存见ledger C21，Tier 5业绩会转述未经审计） | 美元/年（年化，MaaS平台口径） | 转录（derived-inputs.json） |
| NRR / gross retention（nrr） | 最新 | 未获取 | 按转录 | 转录（derived-inputs.json） |
| RPO / cRPO（rpo） | 最新 | 未获取 | 按转录 | 转录（derived-inputs.json） |
| CAC payback / S&M efficiency（cac_payback） | 最新 | 未获取 | 按转录 | 转录（derived-inputs.json） |
