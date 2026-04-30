#!/usr/bin/env python3
"""
回测启动器
用法:
  python backtester/run_backtest.py                    # 默认: BTCUSDT 2024全年
  python backtester/run_backtest.py --symbol ETHUSDT   # 指定币种
  python backtester/run_backtest.py --capital 100000  # 指定初始资金
"""
import sys
import os
import time
import argparse
import traceback
from datetime import datetime

sys.path.insert(0, os.path.join(os.path.dirname(__file__), ".."))

from backtester.engine import BacktestEngine, print_report
from backtester.data_fetcher import DataFetcher
from backtester.strategies import l1_grid_strategy, l3_multi_strategy, benchmark_buy_hold


STRATEGIES_MAP = {
    "grid": ("L1 网格策略", l1_grid_strategy),
    "multi": ("L3 多策略组合", l3_multi_strategy),
    "benchmark": ("买入持有基准", benchmark_buy_hold),
}


def run_backtest(symbol: str = "BTCUSDT",
                 start_date: str = "2024-01-01",
                 end_date: str = "2025-01-01",
                 capital: float = 10000,
                 strategy: str = "all"):
    """运行回测"""
    print(f"\n{'#'*60}")
    print(f"# 量化策略回测系统")
    print(f"# 交易对: {symbol}")
    print(f"# 资金: ${capital:,.0f}")
    print(f"# 回测区间: {start_date} -> {end_date}")
    print(f"{'#'*60}\n")

    fetcher = DataFetcher()

    # ── 尝试加载真实数据，网络不可用时自动切换模拟数据 ──
    raw_data = fetcher.fetch_spot_klines(symbol, "1h", start_date, end_date)
    if not raw_data:
        print("[回测] Binance API 不可达，使用 GBM 模拟数据")
        end_ts = int(time.time() * 1000)
        start_ts = int(datetime.strptime(start_date, "%Y-%m-%d").timestamp() * 1000)
        raw_data = DataFetcher.generate_synthetic_klines(
            symbol, "1h", start_ts, end_ts, volatility=0.02, trend=0.00005
        )
        print(f"[回测] 生成了 {len(raw_data)} 根模拟K线")

    if strategy == "all":
        results = {}
        for strat_key, (name, strat_fn) in STRATEGIES_MAP.items():
            print(f"\n{'='*55}")
            print(f"正在回测: {name}")
            print(f"{'='*55}")

            # 策略签名统一为 fn(engine, idx)
            strat_fn_wrapped = strat_fn

            try:
                engine = BacktestEngine(symbol, capital, fetcher)
                engine.data = raw_data  # 直接注入数据，跳过API
                result = engine.run(strat_fn_wrapped, verbose=False)
                print_report(result)
                results[strat_key] = result
            except Exception as e:
                print(f"  [回测失败] {e}")
                traceback.print_exc()

        if results:
            print(f"\n{'#'*60}")
            print(f"  策略对比汇总 ({symbol})")
            print(f"{'#'*60}")
            print(f"  {'策略':<20} {'总收益':>10} {'年化':>10} {'夏普':>8} {'最大回撤':>10} {'胜率':>8}")
            print(f"  {'-'*66}")
            for key, r in results.items():
                name = STRATEGIES_MAP[key][0]
                print(f"  {name:<20} {r.total_return_pct:>+9.1f}% "
                      f"{r.annual_return_pct:>+9.1f}% {r.sharpe_ratio:>8.2f} "
                      f"{r.max_drawdown_pct:>9.1f}% {r.win_rate:>7.1%}")

    else:
        name, strat_fn = STRATEGIES_MAP.get(strategy, STRATEGIES_MAP["grid"])
        engine = BacktestEngine(symbol, capital, fetcher)
        engine.data = raw_data
        result = engine.run(strat_fn, verbose=True)
        print_report(result)
        _save_equity_csv(result, symbol, strategy)

    print()


def _save_equity_csv(result, symbol: str, strategy: str):
    """保存权益曲线到 CSV"""
    import csv
    csv_path = os.path.join(os.path.dirname(__file__), f"equity_{symbol}_{strategy}.csv")
    try:
        with open(csv_path, "w", newline="") as f:
            w = csv.writer(f)
            w.writerow(["timestamp", "datetime", "equity", "drawdown_pct"])
            for pt in result.equity_curve:
                dt = datetime.fromtimestamp(pt.time / 1000).strftime("%Y-%m-%d %H:%M")
                w.writerow([pt.time, dt, f"{pt.equity:.2f}", f"{pt.drawdown*100:.2f}"])
        print(f"\n[保存] 权益曲线已保存: {csv_path}")
    except Exception as e:
        print(f"[保存失败] {e}")


if __name__ == "__main__":
    parser = argparse.ArgumentParser(description="量化策略回测")
    parser.add_argument("--symbol", default="BTCUSDT", help="交易对")
    parser.add_argument("--start", default="2024-01-01", help="开始日期")
    parser.add_argument("--end", default="2025-01-01", help="结束日期")
    parser.add_argument("--capital", type=float, default=10000, help="初始资金")
    parser.add_argument("--strategy", default="all",
                       choices=["all", "grid", "multi", "benchmark"],
                       help="策略: all/grid/multi/benchmark")
    args = parser.parse_args()

    run_backtest(
        symbol=args.symbol,
        start_date=args.start,
        end_date=args.end,
        capital=args.capital,
        strategy=args.strategy,
    )