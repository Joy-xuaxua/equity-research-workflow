# 派生指标摘要（ledger §2 底稿）

> 由 `scripts/derive_metrics.py` 按 `references/derived-metrics.json` 生成，勿手改；
> 重跑：`PYTHONUTF8=1 python <skill_root>/scripts/derive_metrics.py <workdir>`。
> 值为「未获取」＝输入缺失（对应 ledger 列缺口/未转录项），不是计算失败；外部输入与锚见 `forensic/derived-inputs.json`。

| 指标 | 期间 | 值 | 单位 | 公式 |
|---|---|---:|---|---|
| 营收同比（yoy_revenue） | FY2022 | -19.3 | % | yoy(revenue) |
| 营收同比（yoy_revenue） | FY2023 | -3.9 | % | yoy(revenue) |
| 营收同比（yoy_revenue） | FY2024 | -10.1 | % | yoy(revenue) |
| 营收同比（yoy_revenue） | FY2025 | 1.5 | % | yoy(revenue) |
| 毛利率（gm_pct） | FY2021 | 73.0 | % | gross_profit/revenue*100 |
| 毛利率（gm_pct） | FY2022 | 75.0 | % | gross_profit/revenue*100 |
| 毛利率（gm_pct） | FY2023 | 74.6 | % | gross_profit/revenue*100 |
| 毛利率（gm_pct） | FY2024 | 73.6 | % | gross_profit/revenue*100 |
| 毛利率（gm_pct） | FY2025 | 70.0 | % | gross_profit/revenue*100 |
| 净利率（年内损益口径）（net_margin） | FY2021 | -1.7 | % | net_income/revenue*100 |
| 净利率（年内损益口径）（net_margin） | FY2022 | -3.8 | % | net_income/revenue*100 |
| 净利率（年内损益口径）（net_margin） | FY2023 | -5.6 | % | net_income/revenue*100 |
| 净利率（年内损益口径）（net_margin） | FY2024 | -32.4 | % | net_income/revenue*100 |
| 净利率（年内损益口径）（net_margin） | FY2025 | -21.6 | % | net_income/revenue*100 |
| 经营利润率（om_pct） | FY2021 | -0.4 | % | operating_income/revenue*100 |
| 经营利润率（om_pct） | FY2022 | -3.0 | % | operating_income/revenue*100 |
| 经营利润率（om_pct） | FY2023 | -5.7 | % | operating_income/revenue*100 |
| 经营利润率（om_pct） | FY2024 | -30.4 | % | operating_income/revenue*100 |
| 经营利润率（om_pct） | FY2025 | -21.2 | % | operating_income/revenue*100 |
| FCF 率（fcf_margin） | FY2021 | 9.7 | % | fcf/revenue*100 |
| FCF 率（fcf_margin） | FY2022 | 9.3 | % | fcf/revenue*100 |
| FCF 率（fcf_margin） | FY2023 | 0.8 | % | fcf/revenue*100 |
| FCF 率（fcf_margin） | FY2024 | -7.8 | % | fcf/revenue*100 |
| FCF 率（fcf_margin） | FY2025 | -3.2 | % | fcf/revenue*100 |
| SBC/收入（sbc_revenue） | FY2021 | 0.1 | % | sbc/revenue*100 |
| SBC/收入（sbc_revenue） | FY2022 | 0.1 | % | sbc/revenue*100 |
| SBC/收入（sbc_revenue） | FY2023 | 0.0 | % | sbc/revenue*100 |
| SBC/收入（sbc_revenue） | FY2024 | 0.0 | % | sbc/revenue*100 |
| SBC/收入（sbc_revenue） | FY2025 | 0.0 | % | sbc/revenue*100 |
| 研发费用/收入（rd_revenue） | FY2021 | 0.1 | % | rd_expense/revenue*100 |
| 研发费用/收入（rd_revenue） | FY2022 | 0.1 | % | rd_expense/revenue*100 |
| 研发费用/收入（rd_revenue） | FY2023 | 0.2 | % | rd_expense/revenue*100 |
| 研发费用/收入（rd_revenue） | FY2024 | 0.2 | % | rd_expense/revenue*100 |
| 研发费用/收入（rd_revenue） | FY2025 | 0.2 | % | rd_expense/revenue*100 |
| SGA/收入（sga_revenue） | FY2021 | 75.6 | % | sga/revenue*100 |
| SGA/收入（sga_revenue） | FY2022 | 77.6 | % | sga/revenue*100 |
| SGA/收入（sga_revenue） | FY2023 | 82.4 | % | sga/revenue*100 |
| SGA/收入（sga_revenue） | FY2024 | 84.5 | % | sga/revenue*100 |
| SGA/收入（sga_revenue） | FY2025 | 83.5 | % | sga/revenue*100 |
| 应收周转天数（净额）（dso_net） | FY2021 | 11.5 | 天 | receivables/revenue*365 |
| 应收周转天数（净额）（dso_net） | FY2022 | 13.0 | 天 | receivables/revenue*365 |
| 应收周转天数（净额）（dso_net） | FY2023 | 12.9 | 天 | receivables/revenue*365 |
| 应收周转天数（净额）（dso_net） | FY2024 | 12.0 | 天 | receivables/revenue*365 |
| 应收周转天数（净额）（dso_net） | FY2025 | 24.2 | 天 | receivables/revenue*365 |
| 应收增速−收入增速（recv_growth_gap_pp） | FY2022 | 10.6 | pp | yoy(receivables)-yoy(revenue) |
| 应收增速−收入增速（recv_growth_gap_pp） | FY2023 | -0.8 | pp | yoy(receivables)-yoy(revenue) |
| 应收增速−收入增速（recv_growth_gap_pp） | FY2024 | -5.8 | pp | yoy(receivables)-yoy(revenue) |
| 应收增速−收入增速（recv_growth_gap_pp） | FY2025 | 102.5 | pp | yoy(receivables)-yoy(revenue) |
| 合同负债同比（yoy_deferred） | FY2022 | -16.7 | % | yoy(deferred_revenue) |
| 合同负债同比（yoy_deferred） | FY2023 | -11.1 | % | yoy(deferred_revenue) |
| 合同负债同比（yoy_deferred） | FY2024 | 0.9 | % | yoy(deferred_revenue) |
| 合同负债同比（yoy_deferred） | FY2025 | 20.9 | % | yoy(deferred_revenue) |
| 应计比率（accruals_ratio） | FY2022 | -6.2 | % | (net_income-cfo)/avg2(total_assets)*100 |
| 应计比率（accruals_ratio） | FY2023 | -3.8 | % | (net_income-cfo)/avg2(total_assets)*100 |
| 应计比率（accruals_ratio） | FY2024 | -11.2 | % | (net_income-cfo)/avg2(total_assets)*100 |
| 应计比率（accruals_ratio） | FY2025 | -9.7 | % | (net_income-cfo)/avg2(total_assets)*100 |
| 人均创收（rev_per_capita） | FY2021 | 32.1 | 万元 | revenue/employees/10 |
| 人均创收（rev_per_capita） | FY2022 | 29.2 | 万元 | revenue/employees/10 |
| 人均创收（rev_per_capita） | FY2023 | 29.2 | 万元 | revenue/employees/10 |
| 人均创收（rev_per_capita） | FY2024 | 29.2 | 万元 | revenue/employees/10 |
| 人均创收（rev_per_capita） | FY2025 | 31.5 | 万元 | revenue/employees/10 |
| 收入全周期 CAGR（cagr_revenue_full） | FY2021→FY2025 | -8.3 | %/年 | cagr(revenue) |
| P/S（最新收盘×总股本/最新财年收入）（ps_fy） | 最新 | 0.1 | 倍 | price_close*shares_outstanding*fx_hkd_cny/1000/last(revenue) |
