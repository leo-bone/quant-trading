# 回测模块 (Backtester)

## 概述

完整的量化策略回测框架，支持真实 Binance K 线数据和模拟数据（几何布朗运动）两种模式。

## 目录结构

```
backtester/
├── __init__.py          # 模块入口，导出核心类
├── data_fetcher.py      # 数据层：K 线获取 + 本地缓存 + 模拟数据
├── engine.py             # 撮合引擎：订单执行 + 资金管理 + 绩效计算
├── strategies.py          # 策略实现：网格 / 多策略 / 基准
└── run_backtest.py       # 命令行入口
```

## 快速开始

```bash
# 默认: BTCUSDT, 2024全年, 三策略对比
python backtester/run_backtest.py

# 指定币种
python backtester/run_backtest.py --symbol ETHUSDT

# 指定策略（打印详细交易日志）
python backtester/run_backtest.py --symbol BTCUSDT --strategy multi --verbose

# 指定资金和区间
python backtester/run_backtest.py --symbol BTCUSDT --capital 50000 --start 2023-01-01 --end 2024-12-31
```

## Python API

```python
from backtester import BacktestEngine, DataFetcher, l3_multi_strategy, benchmark_buy_hold

# 方式1: 自动下载真实数据（需网络）
fetcher = DataFetcher()
data = fetcher.fetch_spot_klines("BTCUSDT", "1h", "2024-01-01", "2024-12-31")

# 方式2: 使用模拟数据（无需网络）
data = DataFetcher.generate_synthetic_klines(
    symbol="BTCUSDT",
    volatility=0.02,   # 波动率 (2%)
    trend=0.0001,     # 每小时漂移趋势
)

# 运行回测
engine = BacktestEngine("BTCUSDT", initial_capital=10000, data_fetcher=fetcher)
engine.data = data

r = engine.run(l3_multi_strategy, verbose=True)
print(f"总收益: {r.total_return_pct:.2f}%")
print(f"夏普比率: {r.sharpe_ratio:.2f}")
print(f"最大回撤: {r.max_drawdown_pct:.2f}%")
```

## 策略说明

| 策略 | 文件 | 核心逻辑 | 适用场景 |
|------|------|---------|---------|
| L1 网格 | `l1_grid_strategy` | 8层等距网格，价格触及网格线触发买卖 | 震荡市场，$10K 级别 |
| L3 多策略 | `l3_multi_strategy` | 趋势(EMA) + 均值回归(布林带) + 突破，三信号权重投票 | 趋势市场，$100K+ 级别 |
| 买入持有 | `benchmark_buy_hold` | 期初全仓买入，期末卖出 | 收益基准 |

## 绩效指标

- **总收益率**: 期末权益 vs 期初权益
- **年化收益率**: 按复利年化
- **夏普比率**: (年化收益 - 无风险利率) / 年化波动率（年化系数 √252×24）
- **最大回撤**: 从峰值最大跌幅
- **胜率**: 盈利交易 / 总交易数
- **盈亏比**: 平均盈利 / |平均亏损|
- **月均交易次数**: 总信号数 / 交易月数

## 撮合规则

- **市价单**: 以当前 K 线收盘价 × (1 ± 0.05%) 执行（模拟 0.05% 滑点）
- **限价单**: 在后续 K 线价格触及限价时成交（高/低价判定）
- **手续费**: Taker 0.1%（双向收取）
- **资金不足**: 自动按比例缩减下单量（不会拒绝订单）

## 数据缓存

真实 Binance 数据会自动缓存到 `backtester/.cache/` 目录，
重启后优先读取本地缓存，无网络时自动 fallback 到 GBM 模拟数据。
