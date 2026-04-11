"""
风险管理模块
"""
import time
from typing import Dict, Optional
from dataclasses import dataclass
from datetime import datetime


@dataclass
class RiskState:
    """风险状态"""
    daily_pnl: float = 0
    daily_trades: int = 0
    max_drawdown: float = 0
    current_drawdown: float = 0
    peak_balance: float = 0
    last_reset: str = ""


class RiskManager:
    """风险管理器"""

    def __init__(self, config):
        self.config = config
        self.state = RiskState()
        self.state.peak_balance = config.CAPITAL
        self.state.last_reset = datetime.now().strftime("%Y-%m-%d")

    def check_position_size(self, price: float, capital: float,
                           symbol: str, is_futures: bool = False) -> float:
        """计算安全仓位大小"""
        max_position_value = capital * self.config.MAX_POSITION

        if is_futures:
            return max_position_value / price
        return min(max_position_value, capital)

    def check_stop_loss(self, entry_price: float, current_price: float,
                       side: str, leverage: int = 1) -> bool:
        """检查是否触发止损"""
        if side == "BUY":
            loss_pct = (entry_price - current_price) / entry_price
        else:
            loss_pct = (current_price - entry_price) / entry_price
        effective_loss = loss_pct * leverage
        return effective_loss >= self.config.STOP_LOSS

    def check_take_profit(self, entry_price: float, current_price: float,
                         side: str, leverage: int = 1) -> bool:
        """检查是否触发止盈"""
        if side == "BUY":
            profit_pct = (current_price - entry_price) / entry_price
        else:
            profit_pct = (entry_price - current_price) / entry_price
        effective_profit = profit_pct * leverage
        return effective_profit >= self.config.TAKE_PROFIT

    def check_daily_loss(self, current_balance: float) -> bool:
        """检查日内亏损限制"""
        today = datetime.now().strftime("%Y-%m-%d")
        if self.state.last_reset != today:
            self.state.daily_pnl = 0
            self.state.daily_trades = 0
            self.state.last_reset = today
        self.state.current_drawdown = (self.state.peak_balance - current_balance) / self.state.peak_balance
        self.state.max_drawdown = max(self.state.max_drawdown, self.state.current_drawdown)
        return abs(self.state.daily_pnl) >= self.config.MAX_DAILY_LOSS * self.state.peak_balance

    def update_trade(self, pnl: float):
        """更新交易统计"""
        self.state.daily_pnl += pnl
        self.state.daily_trades += 1

    def update_balance(self, balance: float):
        """更新余额并更新峰值"""
        if balance > self.state.peak_balance:
            self.state.peak_balance = balance

    def can_trade(self, current_balance: float) -> tuple:
        """检查是否可以交易"""
        if self.check_daily_loss(current_balance):
            return False, "日内亏损已达上限"
        if current_balance < self.config.CAPITAL * 0.5:
            return False, "资金低于50%"
        return True, "可以交易"

    def get_report(self) -> str:
        """获取风险报告"""
        return f"""=== 风险状态 ===
日内盈亏: {self.state.daily_pnl:.2f} USDT
日内交易: {self.state.daily_trades} 笔
当前回撤: {self.state.current_drawdown*100:.2f}%
最大回撤: {self.state.max_drawdown*100:.2f}%
峰值余额: {self.state.peak_balance:.2f} USDT"""
