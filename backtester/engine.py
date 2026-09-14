"""
回测引擎 - 核心
支持三大策略的回测，模拟撮合引擎，计算完整绩效指标
"""
import os
import sys
import time
from datetime import datetime
from typing import Dict, List, Optional, Tuple
from dataclasses import dataclass, field
from collections import deque

sys.path.insert(0, os.path.join(os.path.dirname(__file__), ".."))

from backtester.data_fetcher import DataFetcher


@dataclass
class Trade:
    """交易记录"""
    time: int           # 毫秒时间戳
    symbol: str
    side: str           # BUY / SELL
    price: float
    quantity: float
    value: float        # 成交金额
    fee: float          # 手续费
    pnl: float = 0.0    # 平仓盈亏
    pnl_pct: float = 0.0


@dataclass
class EquityPoint:
    """权益曲线数据点"""
    time: int
    equity: float
    drawdown: float = 0.0


@dataclass
class BacktestResult:
    """回测结果"""
    strategy_name: str
    symbol: str
    total_return_pct: float
    annual_return_pct: float
    sharpe_ratio: float
    max_drawdown_pct: float
    win_rate: float
    total_trades: int
    total_wins: int
    total_loss: int
    avg_win_pct: float
    avg_loss_pct: float
    profit_factor: float
    equity_curve: List[EquityPoint]
    trades: List[Trade]
    trades_per_month: float


class BacktestEngine:
    """
    回测引擎 (支持三大策略)
    核心功能:
    1. 历史数据加载 (DataFetcher)
    2. 订单撮合 (限价单/市价单)
    3. 资金管理
    4. 绩效计算
    """

    MAKER_FEE = 0.001    # 0.1%
    TAKER_FEE = 0.001    # 0.1%
    SLIPPAGE_PCT = 0.0005  # 0.05% 滑点

    def __init__(self, symbol: str, initial_capital: float = 10000,
                 data_fetcher: DataFetcher = None):
        self.symbol = symbol
        self.initial_capital = initial_capital
        self.data_fetcher = data_fetcher or DataFetcher()

        self.data: List[Dict] = []
        self.current_idx = 0

        self.capital = initial_capital
        self.position = 0.0         # 持仓数量
        self.position_value = 0.0    # 持仓价值
        self.entry_price = 0.0       # 入场价

        self.trades: List[Trade] = []
        self.equity_curve: List[EquityPoint] = []

        # 订单簿模拟
        self.pending_limit_orders: List[Dict] = []

        # 统计
        self.peak_equity = initial_capital
        self.wins = 0
        self.losses = 0
        self.win_sum = 0.0
        self.loss_sum = 0.0

    # ─── 数据加载 ───

    def load_data(self, interval: str = "1h",
                   start_date: str = "2024-01-01",
                   end_date: str = "2025-04-01") -> int:
        """加载历史数据"""
        self.data = self.data_fetcher.fetch_spot_klines(
            self.symbol, interval, start_date, end_date
        )
        print(f"[回测] {self.symbol} 加载 {len(self.data)} 根K线")
        print(f"       {datetime.fromtimestamp(self.data[0]['time']/1000).date()} "
              f"-> {datetime.fromtimestamp(self.data[-1]['time']/1000).date()}")
        return len(self.data)

    # ─── 撮合引擎 ───

    def _execute_market_order(self, side: str, quantity: float,
                               timestamp: int, price: float) -> Optional[Trade]:
        """执行市价单 (含滑点)"""
        if quantity <= 0:
            return None

        exec_price = price * (1 + self.SLIPPAGE_PCT) if side == "BUY" \
            else price * (1 - self.SLIPPAGE_PCT)
        value = exec_price * quantity
        fee = value * self.TAKER_FEE

        if side == "BUY":
            cost = value + fee
            # 资金不足时自动按比例缩减数量（而非直接拒绝）
            if cost > self.capital and self.capital > 0:
                ratio = self.capital / (cost + 1e-9)
                quantity = max(quantity * ratio, 1e-8)
                exec_price = price * (1 + self.SLIPPAGE_PCT)
                value = exec_price * quantity
                fee = value * self.TAKER_FEE
                cost = value + fee
            if cost > self.capital:
                return None
            self.capital -= cost
            self.position += quantity
            self.position_value = self.position * exec_price
            # 计算新的平均入场价（避免除零）
            if self.position == quantity:
                self.entry_price = exec_price
            elif self.position > 0:
                self.entry_price = (
                    self.entry_price * (self.position - quantity)
                    + exec_price * quantity
                ) / self.position
        else:
            # SELL: 可能平仓（多），也可能开空
            self.capital += value - fee
            if quantity >= self.position:
                # 全部平多仓（或翻空）
                if self.position > 0:
                    pnl = (exec_price - self.entry_price) * self.position
                    pnl_pct = pnl / (self.entry_price * self.position) if self.entry_price > 0 else 0.0
                    trade = Trade(
                        time=timestamp, symbol=self.symbol,
                        side="SELL", price=exec_price,
                        quantity=self.position, value=value, fee=fee,
                        pnl=pnl, pnl_pct=pnl_pct
                    )
                    self.trades.append(trade)
                    self._record_pnl(pnl, pnl_pct)

                # 剩余 → 开空仓
                remaining = quantity - self.position
                self.position = -remaining if remaining > 0 else 0
                self.entry_price = exec_price if self.position < 0 else 0.0
            else:
                # 部分平多仓
                if self.position > 0:
                    pnl = (exec_price - self.entry_price) * quantity
                    pnl_pct = pnl / (self.entry_price * quantity) if self.entry_price > 0 else 0.0
                    trade = Trade(
                        time=timestamp, symbol=self.symbol,
                        side="SELL", price=exec_price,
                        quantity=quantity, value=value, fee=fee,
                        pnl=pnl, pnl_pct=pnl_pct
                    )
                    self.trades.append(trade)
                    self._record_pnl(pnl, pnl_pct)
                self.position -= quantity
                self.position_value = abs(self.position) * exec_price

        return None

    def _record_pnl(self, pnl: float, pnl_pct: float):
        """记录盈亏统计"""
        if pnl > 0:
            self.wins += 1
            self.win_sum += pnl_pct
        else:
            self.losses += 1
            self.loss_sum += pnl_pct

    def market_order(self, side: str, quantity: float):
        """在当前K线收盘时执行市价单"""
        if self.current_idx >= len(self.data):
            return
        k = self.data[self.current_idx]
        self._execute_market_order(side, quantity, k["time"], k["close"])

    def limit_order(self, side: str, price: float, quantity: float):
        """挂限价单 (在后续K线价格触及限价时成交)"""
        self.pending_limit_orders.append({
            "side": side, "price": price, "quantity": quantity
        })

    def _process_limit_orders(self, kline: Dict):
        """处理限价单撮合"""
        new_pending = []
        for order in self.pending_limit_orders:
            filled = False
            if order["side"] == "BUY" and kline["low"] <= order["price"]:
                filled = True
            elif order["side"] == "SELL" and kline["high"] >= order["price"]:
                filled = True

            if filled:
                self._execute_market_order(
                    order["side"], order["quantity"],
                    kline["time"], order["price"]
                )
            else:
                new_pending.append(order)

        self.pending_limit_orders = new_pending

    # ─── 主回测循环 ───

    def run(self, strategy_fn, verbose: bool = True) -> BacktestResult:
        """
        运行回测
        strategy_fn: 策略函数，签名 (engine, current_idx) -> 信号或 None
                    信号格式: {"action": "BUY"/"SELL"/"HOLD",
                               "quantity": ..., "reason": "..."}
        """
        self.capital = self.initial_capital
        self.position = 0.0
        self.peak_equity = self.initial_capital
        self.trades = []
        self.equity_curve = []
        self.pending_limit_orders = []
        self.wins = 0
        self.losses = 0
        self.win_sum = 0.0
        self.loss_sum = 0.0

        signals_count = 0

        for idx in range(len(self.data)):
            self.current_idx = idx
            k = self.data[idx]

            # 处理限价单
            self._process_limit_orders(k)

            # 调用策略函数
            signal = strategy_fn(self, idx)

            if signal and signal.get("action") in ("BUY", "SELL"):
                qty = signal.get("quantity", 0)
                if qty > 0:
                    self.market_order(signal["action"], qty)
                    signals_count += 1
                    if verbose:
                        print(f"  {datetime.fromtimestamp(k['time']/1000)} | "
                              f"{signal['action']:4s} {self.symbol} @ {k['close']:.2f} | "
                              f"{signal.get('reason', '')}")

            # 更新权益曲线
            # 多头: position>0 加市值; 空头: position<0 减市值 (空头盈利=(entry-close)*qty)
            equity = self.capital + self.position * k["close"]
            self.peak_equity = max(self.peak_equity, equity)
            drawdown = (self.peak_equity - equity) / self.peak_equity
            self.equity_curve.append(
                EquityPoint(time=k["time"], equity=equity, drawdown=drawdown)
            )

        # 强制平仓
        if self.position != 0:
            last_k = self.data[-1]
            self.market_order("SELL" if self.position > 0 else "BUY",
                             abs(self.position))
            if verbose:
                print(f"  [强制平仓] {datetime.fromtimestamp(last_k['time']/1000)} | "
                      f"Equity: {self.capital:.2f}")

        return self._generate_report(signals_count)

    def _generate_report(self, signals_count: int) -> BacktestResult:
        """生成回测报告"""
        final_equity = self.equity_curve[-1].equity if self.equity_curve \
            else self.capital

        total_return = (final_equity - self.initial_capital) / self.initial_capital

        # 年化收益
        if self.equity_curve:
            total_days = (self.equity_curve[-1].time - self.equity_curve[0].time) / 86400000
            if total_days > 0:
                annual = (1 + total_return) ** (365 / total_days) - 1
            else:
                annual = 0.0
        else:
            annual = 0.0

        # 最大回撤
        max_dd = max((e.drawdown for e in self.equity_curve), default=0.0)

        # 夏普比率
        if len(self.equity_curve) > 1:
            returns = [self.equity_curve[i].equity / self.equity_curve[i-1].equity - 1
                      for i in range(1, len(self.equity_curve))]
            if returns:
                import statistics
                mean_ret = statistics.mean(returns)
                std_ret = statistics.stdev(returns) if len(returns) > 1 else 0.001
                sharpe = (mean_ret / std_ret * (252 * 24) ** 0.5) if std_ret > 0 else 0.0
            else:
                sharpe = 0.0
        else:
            sharpe = 0.0

        # 胜率
        total_trades = self.wins + self.losses
        win_rate = self.wins / total_trades if total_trades > 0 else 0.0
        avg_win = self.win_sum / self.wins if self.wins > 0 else 0.0
        avg_loss = self.loss_sum / self.losses if self.losses > 0 else 0.0
        profit_factor = abs(self.win_sum / self.loss_sum) if self.loss_sum != 0 else float("inf")

        # 每月交易次数
        if self.equity_curve:
            months = max((self.equity_curve[-1].time - self.equity_curve[0].time) / 2592000000, 1)
            trades_per_month = signals_count / months
        else:
            trades_per_month = 0.0

        return BacktestResult(
            strategy_name="Grid/Arbitrage/Multi",
            symbol=self.symbol,
            total_return_pct=total_return * 100,
            annual_return_pct=annual * 100,
            sharpe_ratio=sharpe,
            max_drawdown_pct=max_dd * 100,
            win_rate=win_rate,
            total_trades=total_trades,
            total_wins=self.wins,
            total_loss=self.losses,
            avg_win_pct=avg_win * 100,
            avg_loss_pct=avg_loss * 100,
            profit_factor=profit_factor,
            equity_curve=self.equity_curve,
            trades=self.trades,
            trades_per_month=trades_per_month,
        )


def print_report(result: BacktestResult):
    """打印回测报告"""
    print(f"\n{'='*55}")
    print(f"  回测报告: {result.strategy_name} | {result.symbol}")
    print(f"{'='*55}")
    print(f"  总收益率:      {result.total_return_pct:+.2f}%")
    print(f"  年化收益率:   {result.annual_return_pct:+.2f}%")
    print(f"  夏普比率:      {result.sharpe_ratio:.2f}")
    print(f"  最大回撤:      {result.max_drawdown_pct:.2f}%")
    print(f"  ─────────────")
    print(f"  总交易次数:    {result.total_trades}")
    print(f"  胜率:          {result.win_rate:.1%}")
    print(f"  平均盈利:      {result.avg_win_pct:.2f}%")
    print(f"  平均亏损:      {result.avg_loss_pct:.2f}%")
    print(f"  盈亏比:        {result.profit_factor:.2f}")
    print(f"  月均交易次数:  {result.trades_per_month:.1f}")
    print(f"{'='*55}")