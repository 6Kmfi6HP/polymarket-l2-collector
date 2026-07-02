# Backlog

| 功能 | 来源 | 状态 | 测试结论 |
|------|------|------|----------|
| hftbacktest 事件格式转换器：将 Parquet 导出数据转换为 hftbacktest 兼容的 numpy event_dtype 数组（orderbook/trade/combined 转换、时间戳处理、事件顺序修正 `correct_event_order`、负延迟修正 `correct_local_timestamp`、事件验证 `validate_event_order`、市场结算 `--settlement`、CLI 入口 `polymarket-hbt-convert`；88 条测试覆盖） | pm-hftbacktest `polymarket_to_hbt()` + `correct_event_order()` + `correct_local_timestamp()` + `validate_event_order()` | 待测 | |
| 合并回测事件流：`--data-type combined` 同时读取 orderbook 和 trade 数据，自动分类转换并合并为一个有序事件数组 | 项目自身需求（hbt_converter 增强；pm-hftbacktest 回测引擎需要合并的 orderbook+trade 事件流） | 待测 | |
| 回测统计模块：回测 record_dtype → Pandas DataFrame → 结算价格修复 → 核心指标计算（Shapre、Sortino、MaxDrawdown、Return、NumTrades、MaxPositionValue）；PolyAssetRecord 类支持 resample/partition/stats 链式调用；39 条测试覆盖 | pm-hftbacktest `hftbacktest.stats`（`metrics.py` + `stats.py`，`PolyAssetRecord`） | 待测 | |
| 聚合导出管道：扫描所有窗口 Parquet，去重合并，输出统一 Parquet/CSV | poly_data `update_utils/process_live.py` | 待测 | |
| 缺失代币回填：扫描已收集数据发现未注册代币，从 Gamma API 批量抓取元数据并持久化 | poly_data `poly_utils/utils.py` `update_missing_tokens()` | 待测 | |
| CLOB 全量市场列表下载：从 CLOB API 分页并发抓取全部市场，写入 markets.csv，支持断点续传 | poly_data `update_utils/update_markets.py` | 待测 | |
| 管道编排：串联 markets → export 等阶段，CLI 入口 `polymarket-pipeline` | poly_data `update_utils/pipeline.py` | 待测 | |
| 市场元数据富化：导出时通过 slug 从 Gamma API 获取 question/outcomes/closed 并附加到每行 | 受 poly_data `process_live._processed_df()` 启发（JOIN 市场元数据模式） | 待测 | |
| 配置输入验证：Settings 启动时检查所有字段类型、范围、合法性；42 条测试覆盖默认值/环境变量/validation 成功失败/load_settings 缓存 | poly_data 无对应模块（项目自身质量需求）；参考 poly_data `process_live` 的输入校验模式 | 待测 | |
| data_formatter 单元测试：25 条测试覆盖 format_orderbook/format_trade 的格式化逻辑、资产过滤、缺失字段、Binance 价格查询 | 参考 poly_data `test_utils.py` 的测试模式（测试数据管线的第一道入口） | 待测 | |
| logger_config 单元测试：25 条测试覆盖 get_logger 缓存、plain/json 格式、log_context 上下文注入、_JsonFormatter | 项目自身质量需求（poly_data 无对应模块，但该模块被所有其他模块依赖） | 待测 | |
| get_asset_id 单元测试：22 条测试覆盖同步/异步 Gamma API 调用、JSON 解析、HTTP 错误、会话生命周期、search_markets、CLI 入口 | poly_data `test_utils.py` 测试模式（HTTP 客户端独立测试） | 待测 | |
| extract_asset_id 单元测试：11 条测试覆盖 CLI 工具的输出格式化、空数据、JSON 字符串字段、文件/标准输入读取 | poly_data `test_utils.py` 测试模式 | 待测 | |
| check_quality 测试补全：3 条测试覆盖 zero_message_meta 和 duplicate_ts（scan_data_quality 全部 7 个维度 100% 覆盖） | poly_data `test_update_markets.py` 测试模式（全面性） | 待测 | |
| main 模块提取 + 单元测试：提取 compute_restart_delay 纯函数，10 条测试覆盖退避算法（3s/60s/120s 阶梯）和 GracefulKiller 信号处理 | 项目自身质量需求 | 待测 | |
| file_cache 测试补全：14 条新测试覆盖原子写入、缓存保存/flush、空缓存窗口清理、None/未知字段容错 | 项目自身质量需求（数据持久化的关键路径） | 待测 | |
| read_last_line 共享工具函数：从 poly_data 移植，高效读取大文件末行（seek backward），9 条测试覆盖 UTF-8/大行/空行/缺失文件 | poly_data `process_live.py` `_read_last_line()` | 待测 | |
| clob_markets / market_discovery 测试补全：_save_state / _load_state / _build_event_url 覆盖 + 大文件尾读取边界测试 | poly_data `test_update_markets.py` 测试模式 | 待测 | |
| 数据留存策略：可配置 DATA_RETENTION_DAYS，purge_old_data 删除过期窗口 Parquet+meta，24h 宽限期保护，--dry-run / --force CLI | 参照 poly_data 的 `process_live` 增量处理模式（不积累过期数据） | 待测 | |
| README 文档重写：完整 CLI 命令表、环境变量表、模块结构图、v0.3.0 版本历史 | 项目自身文档需求 | 完成 | |
| collector.py 内部函数单元测试：_build_asset_to_coin 的 asset_id→coin_tag 映射逻辑（多币种/方向/None）和 _should_save 开关 | 项目自身质量需求（最后的大型代码缺口） | 待测 | |
| .env.example 同步：新增 Wallet/Dual-WS/Chain Verify/Data Retention/Health Check 等 9 个缺失的配置项 | 项目运维质量 | 待测 | |
