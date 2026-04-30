"""
量化交易回测模块
=====================
提供完整的策略回测框架，支持:
- 数据获取 (DataFetcher)
- 撮合引擎 (BacktestEngine)
- 策略实现 (strategies)
- 命令行工具 (run_backtest.py)
"""
from .engine import BacktestEngine, print_report, Trade, BacktestResult, EquityPoint
from .data_fetcher import DataFetcher
from .strategies import l1_grid_strategy, l3_multi_strategy, benchmark_buy_hold

__all__ = [
    "BacktestEngine",
    "print_report",
    "Trade",
    "BacktestResult",
    "EquityPoint",
    "DataFetcher",
    "l1_grid_strategy",
    "l3_multi_strategy",
    "benchmark_buy_hold",
]
