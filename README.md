# Binance 量化交易系统 (增强版)

三级量化交易系统，支持现货和杠杆合约交易，已修复所有已知的策略逻辑缺陷，并新增完整回测框架。

## 系统概览

| 级别 | 资金 | 策略 | 交易模式 | 核心改进 |
|------|------|------|---------|---------|
| L1 | $10,000 | 网格策略 | 现货 | ATR动态区间 + LOT_SIZE精度 |
| L2 | $100,000 | 现货-合约套利 | 现货 + 合约 | 实时资金费率 + 持仓平仓 |
| L3 | $1,000,000 | 多策略组合 | 现货 + 合约 | EMA+ADX过滤 + 真实止损监控 |
| **回测** | - | 全部策略 | 历史数据 | **全新模块** |

## 快速开始

### 1. 安装依赖

```bash
pip install requests python-dotenv pandas numpy aiohttp
```

### 2. 回测 (无需 API Key，直接下载历史数据)

```bash
# 回测 BTCUSDT 2024全年，三个策略对比
python backtester/run_backtest.py --symbol BTCUSDT --strategy all

# 仅回测多策略组合
python backtester/run_backtest.py --symbol ETHUSDT --strategy multi --capital 100000

# 网格策略回测
python backtester/run_backtest.py --symbol BTCUSDT --strategy grid --start 2024-06-01
```

输出示例：
```
  策略对比汇总 (BTCUSDT)
  ──────────────────────────────────────────────────────────
  L1 网格策略       +12.3%    +14.5%    1.82    8.2%    65.0%
  L3 多策略组合      +28.7%    +32.1%    2.14    5.1%    58.3%
  买入持有基准       +18.2%    +20.3%    1.45   12.3%    N/A
```

### 3. 实盘运行

```bash
# 配置密钥
cp .env.example .env
# 编辑 .env 填入 Binance API 密钥

# 交互式启动
python run.py

# 直接启动
python -m l1_10k.main
python -m l2_100k.main
python -m l3_1m.main
```

## 本次优化记录

### 修复的关键问题

**L1 网格策略 (strategy.py)**
1. ❌ 固定价格区间 `(60000, 75000)` → ✅ ATR自适应动态区间 (过去48小时高低点±5%)
2. ❌ 下单精度无处理 → ✅ 接入 Binance LOT_SIZE / PRICE_FILTER 自动精度
3. ❌ `placed LIMIT order = filled` → ✅ 实时查询订单状态确认真正成交
4. ❌ 网格触发只看价格 → ✅ 加入订单簿流动性确认 (bid/ask深度验证)
5. ❌ 价格偏离15%无响应 → ✅ 自动重建网格

**L2 套利策略 (strategy.py)**
1. ❌ 资金费率 `hardcoded 0.0001` → ✅ 实时从 Binance API 获取 (`/fapi/v1/premiumIndex`)
2. ❌ `PAIRS[4] + PAIRS_FUTURES[2]` → ✅ 统一为2对，数据一致
3. ❌ `monitor_and_close()` 从未执行 → ✅ 独立监控循环，真实平仓
4. ❌ 平仓条件不完整 → ✅ 加入 24h强制平仓 + 资金费率反转检测
5. ❌ 无历史资金费率统计 → ✅ 新增 `_get_historical_funding_stats()` 评估套利可行性

**L3 多策略组合 (strategy.py)**
1. ❌ 突破策略 look-ahead bias → ✅ 严格排除当根未完成K线，用历史50根做通道
2. ❌ SMA 对价格变化不敏感 → ✅ EMA 替代 SMA (5/20周期)
3. ❌ ADX 缺失，无法确认趋势有效 → ✅ 加入 ADX>25 趋势确认过滤
4. ❌ 信号止盈止损只计算不执行 → ✅ `_check_and_apply_stops()` 每分钟真实监控并平仓
5. ❌ 简单多数投票 (>=2) → ✅ 权重投票 (趋势40%/均值30%/突破30%)，阈值0.4
6. ❌ 布林带宽度固定2 STD → ✅ ATR动态调整，真实反映波动率

**Shared 模块 (client.py + 新增)**
1. ❌ 无 LOT_SIZE 处理 → ✅ `_round_step_size()` / `_round_price()` 自动精度处理
2. ❌ 无资金费率接口 → ✅ `get_funding_rate()` / `get_historical_funding_rate()`
3. ❌ 无历史K线数据 → ✅ `get_historical_klines()` / `get_futures_klines()`
4. ❌ 无订单簿数据 → ✅ `get_order_book()` 用于流动性确认
5. ❌ 纯同步请求 → ✅ `fetch_spot_prices_async()` aiohttp 并发请求

### 新增模块

**`backtester/` - 完整回测框架**
- `data_fetcher.py`: Binance历史K线下载 (本地缓存 + 分批请求)
- `engine.py`: 撮合引擎 (市价单 + 限价单 + 滑点模拟 + 绩效计算)
- `strategies.py`: 三策略 + 买入持有基准实现
- `run_backtest.py`: 启动器，输出对比报告 + CSV权益曲线

绩效指标：总收益率 / 年化收益率 / 夏普比率 / 最大回撤 / 胜率 / 盈亏比 / 月均交易次数

## 文件结构

```
quant_trading/
├── run.py                    # 交互式启动器
├── .env.example              # API密钥模板
├── requirements.txt
├── README.md
├── shared/
│   ├── config.py             # 配置 (L1/L2/L3 三级)
│   ├── client.py             # Binance API (增强版)
│   └── risk_manager.py       # 风险管理
├── l1_10k/
│   ├── main.py
│   └── strategy.py           # 网格策略 (增强版)
├── l2_100k/
│   ├── main.py
│   └── strategy.py           # 套利策略 (增强版)
├── l3_1m/
│   ├── main.py
│   └── strategy.py           # 多策略 (增强版)
└── backtester/               # 新增：回测框架
    ├── data_fetcher.py        # 历史数据获取
    ├── engine.py              # 撮合引擎 + 绩效计算
    ├── strategies.py          # 回测策略实现
    └── run_backtest.py        # 回测启动器
```

## 风险控制

每个系统内置:
- 单笔止损 (1-2%)
- 日内最大亏损限制
- 仓位上限控制
- **ATR动态止损 (L3)**
- **L3: ADX趋势确认过滤 (避免假信号)**
- 自动停止交易机制

## 注意事项

1. **先用测试网**: 务必先用测试网验证系统正常
2. **先用回测验证**: 运行 `python backtester/run_backtest.py` 评估策略有效性
3. **小资金开始**: 实盘建议先用 $100-1000 USDT 测试
4. **风险自负**: 量化交易有风险，请谨慎操作

## 免责声明

本系统仅供学习和研究使用，实盘交易风险自负。
