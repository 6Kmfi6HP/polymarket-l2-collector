# Backlog

| 功能 | 来源 | 状态 | 测试结论 |
|------|------|------|----------|
| 聚合导出管道：扫描所有窗口 Parquet，去重合并，输出统一 Parquet/CSV | poly_data `update_utils/process_live.py` | 待测 | |
| 缺失代币回填：扫描已收集数据发现未注册代币，从 Gamma API 批量抓取元数据并持久化 | poly_data `poly_utils/utils.py` `update_missing_tokens()` | 待测 | |
| CLOB 全量市场列表下载：从 CLOB API 分页并发抓取全部市场，写入 markets.csv，支持断点续传 | poly_data `update_utils/update_markets.py` | 待测 | |
| 管道编排：串联 markets → export 等阶段，CLI 入口 `polymarket-pipeline` | poly_data `update_utils/pipeline.py` | 待测 | |
| 市场元数据富化：导出时通过 slug 从 Gamma API 获取 question/outcomes/closed 并附加到每行 | 受 poly_data `process_live._processed_df()` 启发（JOIN 市场元数据模式） | 待测 | |
| 配置输入验证：Settings 启动时检查所有字段类型、范围、合法性；42 条测试覆盖默认值/环境变量/validation 成功失败/load_settings 缓存 | poly_data 无对应模块（项目自身质量需求）；参考 poly_data `process_live` 的输入校验模式 | 待测 | |
| data_formatter 单元测试：25 条测试覆盖 format_orderbook/format_trade 的格式化逻辑、资产过滤、缺失字段、Binance 价格查询 | 参考 poly_data `test_utils.py` 的测试模式（测试数据管线的第一道入口） | 待测 | |
| logger_config 单元测试：25 条测试覆盖 get_logger 缓存、plain/json 格式、log_context 上下文注入、_JsonFormatter | 项目自身质量需求（poly_data 无对应模块，但该模块被所有其他模块依赖） | 待测 | |
