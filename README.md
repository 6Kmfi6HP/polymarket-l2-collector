# Polymarket L2 Collector

实时采集 Polymarket 上 BTC/ETH 的 L2 orderbook 和 trade 数据，按 5m/15m 时间窗口输出为 Parquet 文件。

## 当前能力

- ✅ **BTC/ETH + SOL/XRP** — 订单簿 (orderbook) + 成交 (trade) 实时数据
- ✅ **5m / 15m / 1h** — 三种时间窗口并行采集
- ✅ **Up/Down token 方向** — 可配 DIRECTIONS=up,down 采集完整盘口
- ✅ **WebSocket 实时订阅** — Polymarket CLOB WS channel
- ✅ **CLOB 全量市场列表** — `uv run polymarket-clob-markets` 从 CLOB API 分页并发下载全部市场（断点续传）
- ✅ **REST 快照补采** — `uv run polymarket-backfill` 自动检测数据断档并补采
- ✅ **Parquet 输出** — 按 `data/{interval}/{coin}/{orderbooks|trades}/{timestamp}{direction}.parquet` 结构
- ✅ **币安价格同步** — BTC/ETH/SOL/XRP midprice，供回测对齐
- ✅ **导出管道** — `uv run polymarket-export` 扫描所有窗口 → 去重合并 → 输出统一 Parquet/CSV
- ✅ **市场元数据富化** — `uv run polymarket-export --enrich` 导出时通过 Gamma API 附加 question/outcomes 字段
- ✅ **管道编排** — `uv run polymarket-pipeline` 串联 markets → export 全流程
- ✅ **数据留存清理** — `DATA_RETENTION_DAYS` 环境变量 + `uv run polymarket-data-retention` 自动删除过期窗口，24h 宽限期保护
- ✅ **配置输入验证** — Settings 启动时检查所有字段类型/范围/合法性
- ✅ **缺失代币回填** — `uv run polymarket-backfill --scan` 扫描数据文件发现未注册代币并自动查询 Gamma API
- ✅ **健康监控 + 自动重启** — 内存阈值守卫、WS 断线检测、每日定时重启、指数退避
- ✅ **原子 Parquet 写入** — 临时文件 + os.replace，避免写坏文件
- ✅ **窗口元数据追踪** — 每个 Parquet 窗口附带 .meta.json（消息数、时间范围、状态）
- ✅ **数据质量检查 CLI** — `uv run polymarket-check-quality`（含窗口断档检测）
- ✅ **Docker 部署** — Dockerfile + docker-compose.yml
- ✅ **CI** — GitHub Actions：ruff + pytest + 导入检查（Python 3.10-3.12）
- ✅ **结构化日志** — 支持 JSON 格式（LOG_FORMAT=json）
- ✅ **hftbacktest 事件转换** — `uv run polymarket-hbt-convert` 将 Parquet 导出数据转换为 hftbacktest 可消费的 numpy `.npy` 事件数组（支持 orderbook/trade/combined 三种模式）
- ✅ **盘口 + 成交合并** — `--data-type combined` 同时转换 orderbook 和 trade 事件，按时间戳合并为一个有序事件流
- ✅ **市场结算处理** — `--settlement` 自动追加二元结果结算快照（0.0 / 1.0）
- ✅ **币种过滤** — `--coin btc` 只转换指定币种
- ✅ **事件摘要与校验** — `--summary` 打印事件统计，`--validate` 校验数据结构完整性
- ✅ **回测统计** — `PolyAssetRecord` + `Stats` 类计算 Sharpe/Sortino/MaxDrawdown/Return 等指标，自动处理 Polymarket 结算价格修复
- ✅ **563 个测试** — 覆盖 hbt_converter（101 测试）、backtest_stats（39 测试）及原有全部模块
- ✅ **Deprecation warnings** — poly_ws_5min.py / poly_ws_15min.py 指向新 Collector

## 快速开始

```bash
# 1. 安装 uv（如果没有）
curl -LsSf https://astral.sh/uv/install.sh | sh

# 2. 安装依赖
uv sync

# 3. 复制配置（可选，有默认值）
cp .env.example .env

# 4. 运行采集
uv run polymarket-l2-collector

# 5. （可选）Docker 部署
docker compose up -d
```

## 项目结构

```
polymarket-l2-collector/
├── pyproject.toml              # 项目元数据和依赖
├── uv.lock                     # 锁定依赖版本
├── .env.example                # 配置模板
├── README.md
├── polymarket_l2_collector/    # 主 Python 包
│   ├── __init__.py / __main__.py
│   ├── main.py                 # 入口编排（健康监控 + 内存守卫 + 每日重启）
│   ├── config.py               # 配置加载（.env + 默认值 + 输入验证）
│   ├── collector.py            # 参数化采集核心
│   ├── market_discovery.py     # Gamma API 市场发现
│   ├── ws_client.py            # WebSocket 连接、订阅、消息接收
│   ├── data_formatter.py       # 消息格式化（orderbook / trade）
│   ├── file_cache.py           # Parquet 写入缓存（原子写入 + 追加刷新）
│   ├── binance_price.py        # 币安 bookTicker 中间价
│   ├── get_asset_id.py         # Gamma API HTTP 客户端（async + sync）
│   ├── window_metadata.py      # 窗口质量元数据 + 数据质量扫描
│   ├── check_quality.py        # 数据质量检查 CLI
│   ├── logger_config.py        # 日志配置（plain / JSON）
│   ├── rest_snapshot.py        # REST 快照补采
│   ├── clob_markets.py         # CLOB 全量市场列表下载（断点续传）
│   ├── missing_markets.py      # 缺失代币回填
│   ├── export_pipeline.py      # 导出管道（扫描 → 去重 → 合并 → 输出 + 元数据富化）
│   ├── pipeline.py             # 管道编排（markets → export）
│   ├── data_retention.py       # 数据留存策略（过期窗口自动清除）
│   ├── extract_asset_id.py     # Gamma API 响应解析工具
│   ├── asset_utils.py          # 兼容性 re-export
│   ├── backtest_stats.py       # 回测统计模块（Sharpe/Sortino/MDD + PolyAssetRecord）
│   ├── hbt_converter.py        # hftbacktest 事件格式转换器（orderbook/trade/combined + 结算 + 时间戳 + 校验）
│   └── utils.py                # 共享工具函数（read_last_line 等）
├── tests/                      # 377 个测试（24 个测试文件）
│   ├── test_collector.py
│   ├── test_config.py
│   ├── test_data_formatter.py
│   ├── test_file_cache.py
│   ├── test_market_discovery.py
│   ├── test_ws_client.py
│   ├── test_window_metadata.py
│   ├── test_check_quality.py
│   ├── test_binance_price.py
│   ├── test_clob_markets.py
│   ├── test_missing_markets.py
│   ├── test_export_pipeline.py
│   ├── test_pipeline.py
│   ├── test_data_retention.py
│   ├── test_get_asset_id.py
│   ├── test_extract_asset_id.py
│   ├── test_logger_config.py
│   ├── test_main.py
│   ├── test_utils.py
│   ├── test_smoke.py
│   ├── test_hbt_converter.py   # hftbacktest 事件转换（101 测试）
│   ├── test_backtest_stats.py  # 回测统计指标（39 测试）
│   └── test_ws_wallet/         # Dual-WS 验证模块
├── data/                       # Parquet 输出目录（自动创建）
├── Dockerfile + docker-compose.yml
└── .github/workflows/ci.yml
```

## 未来计划

> hftbacktest 转换器 + 回测统计模块在 0.3.0 版本中已实现。

> 以下暂无实现计划，PR 欢迎

- ❌ 策略回测可视化（图表化 equity curve 和 position）

## CLI 命令

| 命令 | 说明 |
|------|------|
| `uv run polymarket-l2-collector` | 启动实时采集（连续会话，自动重启） |
| `uv run polymarket-export` | 导出所有采集数据为统一 Parquet/CSV |
| `uv run polymarket-export --enrich` | 导出时附加市场元数据（question/outcomes/closed） |
| `uv run polymarket-pipeline` | 运行全管道（markets → export） |
| `uv run polymarket-backfill` | REST 快照补采（自动检测窗口断档） |
| `uv run polymarket-backfill --scan` | 扫描数据发现缺失代币并回填 |
| `uv run polymarket-check-quality` | 数据质量检查（含窗口断档检测） |
| `uv run polymarket-data-retention` | 清理过期数据窗口 |
| `uv run polymarket-data-retention --retention-days 30 --dry-run` | 预览 30 天以上的数据会删除哪些 |
| `uv run polymarket-data-retention --retention-days 7 --force` | 强制清理（跳过 24h 宽限期） |
│ `uv run polymarket-hbt-convert --data-dir data --output exports/books.npy --data-type orderbooks` | 转换 orderbook 数据为 hftbacktest .npy 事件数组
│ `uv run polymarket-hbt-convert --data-dir data --output exports/combined.npy --data-type combined --settlement` | 转换合并事件流（orderbook + trade）并附加结算
│ `uv run polymarket-hbt-convert --data-dir data --output exports/btc_books.npy --coin btc --summary --validate` | 转换 BTC orderbook 并打印摘要 + 校验

## 环境变量

关键配置项（完整列表见 `.env.example`）：

| 变量 | 默认值 | 说明 |
|------|--------|------|
| `COINS` | `btc,eth` | 追踪币种 |
| `INTERVALS` | `5m,15m` | 时间窗口 |
| `DIRECTIONS` | `up` | 方向（`up` 或 `up,down`） |
| `LOG_FORMAT` | `plain` | 日志格式（`plain` 或 `json`） |
| `DATA_RETENTION_DAYS` | `0` | 数据留存天数（`0`=仅保留最近 24h） |
| `CHAIN_VERIFY_ENABLED` | `false` | 链上验证开关 |
| `MEMORY_SOFT_LIMIT_MB` | `300` | 内存软上限（触发 flush） |
| `MEMORY_HARD_LIMIT_MB` | `400` | 内存硬上限（触发重启） |

## 数据输出

### 单个窗口 Parquet（原始格式）

| 字段 | 类型 | 说明 |
|------|------|------|
| `bids/asks` | `list[{p, s}]` | 订单簿买方/卖方 depth，p=price×100, s=size×100 (int) |
| `price/size` | `int` | trade 的 price 和 size（×100 存储） |
| `timestamp` | `string` | Polymarket 消息时间戳 (ms) |
| `local_timestamp` | `string` | 本地接收时间戳 (ms) |
| `asset_price` | `float` | 币安该币种 midprice |
| `window_open_ts` | `int` | 对应时间窗口起始 Unix 秒 |
| `side` | `string` | trade 方向 ("buy" / "sell") |

> Parquet 中 price/size 字段压缩为 `p`/`s` 整数以节省空间。读取后需除以 100 恢复浮点值。

### 导出合并数据（uv run polymarket-export）

导出时自动添加 `interval`、`coin`、`direction`、`window_ts` 字段。使用 `--enrich` 标志时额外包含：

| 字段 | 说明 |
|------|------|
| `market_question` | 市场问题（如 "BTC > $100k?"） |
| `market_slug` | 事件 URL slug |
| `market_outcomes` | 逗号分隔的 outcomes |
| `market_closed` | 市场是否已关闭 |

## hftbacktest 回测集成

`polymarket-hbt-convert` 将收集的 Parquet 数据转换为 hftbacktest 兼容的事件数组（.npy），可直接用于 pm-hftbacktest 回测引擎。

### 基本用法

```bash
# 转换 orderbook 数据
uv run polymarket-hbt-convert --data-dir data --output exports/orderbooks.npy --data-type orderbooks

# 转换 trade 数据
uv run polymarket-hbt-convert --data-dir data --output exports/trades.npy --data-type trades

# 合并转换（orderbook + trade 事件合并为一个流）
uv run polymarket-hbt-convert --data-dir data --output exports/combined.npy --data-type combined

# 带市场结算处理 + 摘要 + 校验
uv run polymarket-hbt-convert --data-dir data --output exports/combined.npy --data-type combined --settlement --summary --validate
```

### 回测结果分析（Python API）

```python
import numpy as np
from polymarket_l2_collector.backtest_stats import PolyAssetRecord

# 从 hftbacktest 拿到 record 数组后
record = np.load("backtest_result.npy")

# 计算性能指标
stats = PolyAssetRecord(record).resample("1s").stats(book_size=100_000)
print(stats.summary())
print(f"Earn: {stats.earn}")

# 月度分区统计
monthly = PolyAssetRecord(record).monthly().stats(book_size=100_000)
print(monthly.summary())
```

### 高级选项

| 选项 | 说明 |
|------|------|
| `--data-type orderbooks | trades | combined` | 数据类型 |
| `--coin btc` | 只转换指定币种 |
| `--settlement` | 附加 Polymarket 结算快照 |
| `--constant-latency 10000000` | 固定延迟（ns） |
| `--no-correct-ts` | 跳过负延迟校正 |
| `--summary` | 打印事件数组摘要 |
| `--validate` | 校验事件数组 |

### Python API（不经过 CLI）

```python
from polymarket_l2_collector.hbt_converter import convert_from_data_dir, load_event_array, event_array_summary

# 直接将收集的 Parquet 数据转换为 .npy
convert_from_data_dir(
    data_dir="data",
    output="exports/btc_combined.npy",
    data_type="combined",
    settlement=True,
    coin="btc",
)

# 加载并查看统计
events = load_event_array("exports/btc_combined.npy")
print(event_array_summary(events))
```


## 测试

```bash
uv run pytest tests/       # 运行全部 563+ 个测试
uv run ruff check .        # 代码风格检查
```

## 版本历史

| 版本 | 亮点 |
|------|------|
| 0.3.0 | hftbacktest 事件格式转换器（orderbook/trade/combined/—summary/—validate/—settlement/--coin）+ 回测统计模块（Sharpe/Sortino/MDD/PolyAssetRecord）+ 563+ 测试 |
| 0.2.0 | 导出管道 + 市场元数据富化 + 配置验证 + 数据留存 + 563+ 测试 |
| 0.1.0 | 初始版本 — 实时 WS 采集 + REST 补采 + 数据质量检查 |

## 参考文档

- [Polymarket CLOB WebSocket 文档](https://docs.polymarket.com/developers/CLOB/websocket/market-channel)
- [Polymarket API 文档](https://docs.polymarket.com/)
