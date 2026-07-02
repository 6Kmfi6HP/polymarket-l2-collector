# Backlog

| 功能 | 来源 | 状态 | 测试结论 |
|------|------|------|----------|
| 聚合导出管道：扫描所有窗口 Parquet，去重合并，输出统一 Parquet/CSV | poly_data `update_utils/process_live.py` | 待测 | |
| 缺失代币回填：扫描已收集数据发现未注册代币，从 Gamma API 批量抓取元数据并持久化 | poly_data `poly_utils/utils.py` `update_missing_tokens()` | 待测 | |
| CLOB 全量市场列表下载：从 CLOB API 分页并发抓取全部市场，写入 markets.csv，支持断点续传 | poly_data `update_utils/update_markets.py` | 待测 | |
