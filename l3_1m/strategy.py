"""
L3 策略: 多策略组合 (100万美金)
趋势策略 + 均值回归 + 套利 三策略并行
"""
import time
from typing import Dict, List
from collections import deque


class MultiStrategy:
    """多策略组合管理器"""

    def __init__(self, config, client, risk_manager):
        self.config = config
        self.client = client
        self.risk = risk_manager
        self.strategies = {}
        self.active_positions = {}
        self.price_history = {}  # 价格历史

    def _calculate_sma(self, prices: List[float], period: int) -> float:
        """简单移动平均"""
        if len(prices) < period:
            return prices[-1] if prices else 0
        return sum(prices[-period:]) / period

    def _calculate_std(self, prices: List[float], period: int) -> float:
        """标准差"""
        if len(prices) < period:
            return 0
        recent = prices[-period:]
        mean = sum(recent) / len(recent)
        variance = sum((p - mean) ** 2 for p in recent) / len(recent)
        return variance ** 0.5

    # ===== 策略1: 趋势跟踪 =====
    def trend_strategy(self, symbol: str, prices: deque, capital: float) -> Dict:
        """趋势跟踪策略"""
        if len(prices) < 20:
            return {"action": "HOLD", "reason": "数据不足"}

        sma_short = self._calculate_sma(list(prices), 5)
        sma_long = self._calculate_sma(list(prices), 20)
        current = prices[-1]

        if sma_short > sma_long and current > sma_short:
            return {
                "strategy": "TREND",
                "action": "BUY",
                "position_size": capital * 0.2,
                "stop_loss": current * 0.98,
                "reason": f"上升趋势: SMA5={sma_short:.2f} > SMA20={sma_long:.2f}"
            }
        elif sma_short < sma_long and current < sma_short:
            return {
                "strategy": "TREND",
                "action": "SELL",
                "position_size": capital * 0.2,
                "stop_loss": current * 1.02,
                "reason": f"下降趋势: SMA5={sma_short:.2f} < SMA20={sma_long:.2f}"
            }

        return {"action": "HOLD", "reason": "无明显趋势"}

    # ===== 策略2: 均值回归 =====
    def mean_reversion_strategy(self, symbol: str, prices: deque, capital: float) -> Dict:
        """均值回归策略"""
        if len(prices) < 30:
            return {"action": "HOLD", "reason": "数据不足"}

        current = prices[-1]
        sma = self._calculate_sma(list(prices), 30)
        std = self._calculate_std(list(prices), 30)

        # 价格偏离2个标准差时回归
        upper_band = sma + 2 * std
        lower_band = sma - 2 * std

        if current < lower_band:
            return {
                "strategy": "MEAN_REVERSION",
                "action": "BUY",
                "position_size": capital * 0.15,
                "target": sma,
                "reason": f"价格超卖: {current:.2f} < {lower_band:.2f}"
            }
        elif current > upper_band:
            return {
                "strategy": "MEAN_REVERSION",
                "action": "SELL",
                "position_size": capital * 0.15,
                "target": sma,
                "reason": f"价格超买: {current:.2f} > {upper_band:.2f}"
            }

        return {"action": "HOLD", "reason": "价格在正常范围"}

    # ===== 策略3: 突破策略 =====
    def breakout_strategy(self, symbol: str, prices: deque, capital: float) -> Dict:
        """突破策略"""
        if len(prices) < 50:
            return {"action": "HOLD", "reason": "数据不足"}

        current = prices[-1]
        highs = max(list(prices)[-50:-1])
        lows = min(list(prices)[-50:-1])

        if current > highs:
            return {
                "strategy": "BREAKOUT",
                "action": "BUY",
                "position_size": capital * 0.1,
                "stop_loss": lows,
                "reason": f"突破阻力: {current:.2f} > {highs:.2f}"
            }
        elif current < lows:
            return {
                "strategy": "BREAKOUT",
                "action": "SELL",
                "position_size": capital * 0.1,
                "stop_loss": highs,
                "reason": f"跌破支撑: {current:.2f} < {lows:.2f}"
            }

        return {"action": "HOLD", "reason": "无突破信号"}

    def execute_signal(self, signal: Dict, symbol: str, is_futures: bool = False):
        """执行交易信号"""
        if signal["action"] == "HOLD":
            return None

        price = self.client.get_futures_price(symbol) if is_futures else self.client.get_spot_price(symbol)
        quantity = signal["position_size"] / price

        if is_futures:
            result = self.client.futures_order(
                symbol=symbol,
                side=signal["action"],
                position_side="BOTH",
                order_type="MARKET",
                quantity=quantity,
                leverage=2
            )
        else:
            result = self.client.spot_order(
                symbol=symbol,
                side=signal["action"],
                order_type="MARKET",
                quantity=quantity,
                price=price
            )

        print(f"[{signal['strategy']}] {signal['action']} {symbol} @ {price}")
        return result

    def run(self):
        """运行多策略"""
        print(f"\n{'='*50}")
        print(f"L3 多策略组合启动")
        print(f"资金: {self.config.CAPITAL} USDT")
        print(f"策略: 趋势 + 均值回归 + 突破")
        print(f"{'='*50}\n")

        # 初始化价格历史
        for symbol in self.config.PAIRS:
            self.price_history[symbol] = deque(maxlen=100)

        while True:
            try:
                for symbol in self.config.PAIRS:
                    # 获取价格
                    price = self.client.get_spot_price(symbol)
                    self.price_history[symbol].append(price)

                    # 三个策略各自判断
                    signals = [
                        self.trend_strategy(symbol, self.price_history[symbol], self.config.CAPITAL),
                        self.mean_reversion_strategy(symbol, self.price_history[symbol], self.config.CAPITAL),
                        self.breakout_strategy(symbol, self.price_history[symbol], self.config.CAPITAL)
                    ]

                    # 投票机制: 多数策略一致时执行
                    votes = {"BUY": 0, "SELL": 0}
                    for sig in signals:
                        if sig["action"] in votes:
                            votes[sig["action"]] += 1

                    # 至少2个策略同意才执行
                    final_action = None
                    for action, count in votes.items():
                        if count >= 2:
                            final_action = action
                            break

                    if final_action:
                        # 找到多数策略的信号
                        final_signal = next(s for s in signals if s["action"] == final_action)
                        self.execute_signal(final_signal, symbol)

                    # 检查风险
                    can_trade, msg = self.risk.can_trade(self.config.CAPITAL)
                    if not can_trade:
                        print(f"[风控] {msg}")
                        return

                    time.sleep(5)  # 每个交易对间隔

            except KeyboardInterrupt:
                print("\n[退出] 停止多策略")
                break
            except Exception as e:
                print(f"[错误] {e}")
                time.sleep(60)
