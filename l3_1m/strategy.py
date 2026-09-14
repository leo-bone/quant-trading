"""
L3 策略: 多策略组合 (100万美金) - 增强版
修复问题：
1. look-ahead bias: 突破策略用当前K线最高/最低，需排除当根K线
2. EMA 替代 SMA (指数加权，对价格变化更敏感)
3. 止损真正被监控 (之前只计算未真正执行)
4. 策略权重替代简单投票 (趋势:均值回归:突破 = 4:3:3)
5. ATR 动态止损 (真实反映波动率)
6. 持仓追踪与资金管理
7. 趋势强度过滤 (ADX)
"""
import time
from typing import Dict, List, Optional
from collections import deque
from datetime import datetime


class MultiStrategy:
    """多策略组合管理器 (增强版)"""

    # 策略权重 (趋势跟踪最重要)
    STRATEGY_WEIGHTS = {
        "TREND": 0.4,
        "MEAN_REVERSION": 0.3,
        "BREAKOUT": 0.3,
    }

    def __init__(self, config, client, risk_manager):
        self.config = config
        self.client = client
        self.risk = risk_manager

        self.strategies = {}
        self.active_positions: Dict[str, Dict] = {}  # {symbol: pos_info}
        self.price_history: Dict[str, deque] = {}

        # 止损追踪: 每K线检查一次
        self._stop_check_interval = 60  # 秒
        self._last_stop_check = 0

    # ─── 基础指标 ───

    def _calc_ema(self, prices: List[float], period: int) -> float:
        """指数移动平均 (替代SMA，对价格变化更敏感)"""
        if not prices:
            return 0.0
        if len(prices) < period:
            period = len(prices)

        ema = prices[0]
        multiplier = 2 / (period + 1)
        for p in prices[1:]:
            ema = p * multiplier + ema * (1 - multiplier)
        return ema

    def _calc_sma(self, prices: List[float], period: int) -> float:
        """简单移动平均 (保留备用)"""
        if len(prices) < period:
            return prices[-1] if prices else 0.0
        return sum(prices[-period:]) / period

    def _calc_std(self, prices: List[float], period: int) -> float:
        """标准差"""
        if len(prices) < period:
            return 0.0
        recent = prices[-period:]
        mean = sum(recent) / len(recent)
        variance = sum((p - mean) ** 2 for p in recent) / len(recent)
        return variance ** 0.5

    def _calc_atr(self, klines: List, period: int = 14) -> float:
        """ATR (Average True Range)"""
        if len(klines) < period + 1:
            return 0.0

        tr_list = []
        for i in range(1, len(klines)):
            high = float(klines[i][1])
            low = float(klines[i][2])
            prev_close = float(klines[i - 1][4])
            tr = max(high - low,
                     abs(high - prev_close),
                     abs(low - prev_close))
            tr_list.append(tr)

        return sum(tr_list[-period:]) / period if tr_list else 0.0

    def _calc_adx(self, klines: List, period: int = 14) -> float:
        """ADX (Average Directional Index) - 趋势强度指标"""
        if len(klines) < period + 1:
            return 0.0

        # 计算 +DM, -DM, TR
        tr_list, plus_dm, minus_dm = [], [], []
        for i in range(1, len(klines)):
            high = float(klines[i][1])
            low = float(klines[i][2])
            prev_high = float(klines[i - 1][1])
            prev_low = float(klines[i - 1][2])
            prev_close = float(klines[i - 1][4])

            tr = max(high - low, abs(high - prev_close), abs(low - prev_close))
            tr_list.append(tr)

            up_move = high - prev_high
            down_move = prev_low - low

            plus_dm.append(max(up_move, 0) if up_move > down_move else 0)
            minus_dm.append(max(down_move, 0) if down_move > up_move else 0)

        if not tr_list:
            return 0.0

        # 平滑 (使用 EMA)
        tr_smooth = sum(tr_list[-period:])
        plus_smooth = sum(plus_dm[-period:])
        minus_smooth = sum(minus_dm[-period:])

        if tr_smooth == 0:
            return 0.0

        plus_di = (plus_smooth / tr_smooth) * 100
        minus_di = (minus_smooth / tr_smooth) * 100

        di_sum = plus_di + minus_di
        if di_sum == 0:
            return 0.0

        dx = abs(plus_di - minus_di) / di_sum * 100
        # 简化 ADX (用 DX 近似，实际应用 Wilder 平滑)
        return dx

    def _get_klines_data(self, symbol: str) -> List:
        """获取K线数据用于指标计算"""
        return self.client.get_klines(symbol, interval="1h", limit=100)

    # ─── 策略1: 趋势跟踪 (EMA + ADX 过滤) ───

    def trend_strategy(self, symbol: str, prices: deque,
                       capital: float, klines: List = None) -> Dict:
        """
        趋势跟踪策略 (增强版)
        - 使用 EMA(5) vs EMA(20) 金叉/死叉
        - 加入 ADX 过滤: ADX > 25 才确认趋势
        - ATR 动态止损
        """
        if len(prices) < 21:
            return {"action": "HOLD", "reason": "数据不足"}

        ema5 = self._calc_ema(list(prices), 5)
        ema20 = self._calc_ema(list(prices), 20)
        current = prices[-1]

        # ADX 趋势强度
        adx = 0.0
        if klines:
            adx = self._calc_adx(klines)

        # ATR 动态止损
        stop_pct = 0.02  # 默认 2%
        if klines and len(klines) >= 14:
            atr = self._calc_atr(klines)
            if current > 0:
                stop_pct = min(atr / current, 0.05)  # 不超过 5%

        if adx > 25 and ema5 > ema20 and current > ema5:
            return {
                "strategy": "TREND",
                "action": "BUY",
                "position_size_pct": 0.2,
                "stop_loss": current * (1 - stop_pct),
                "reason": (f"上升趋势: EMA5={ema5:.2f} > EMA20={ema20:.2f}, "
                           f"ADX={adx:.1f} > 25")
            }
        elif adx > 25 and ema5 < ema20 and current < ema5:
            return {
                "strategy": "TREND",
                "action": "SELL",
                "position_size_pct": 0.2,
                "stop_loss": current * (1 + stop_pct),
                "reason": (f"下降趋势: EMA5={ema5:.2f} < EMA20={ema20:.2f}, "
                           f"ADX={adx:.1f} > 25")
            }

        return {"action": "HOLD",
                "reason": f"趋势不明确 (ADX={adx:.1f} <= 25 或无方向)"}  # 修复: 明确 HOLD 原因

    # ─── 策略2: 均值回归 (ATR 动态布林带) ───

    def mean_reversion_strategy(self, symbol: str, prices: deque,
                                 capital: float, klines: List = None) -> Dict:
        """
        均值回归策略 (增强版)
        - ATR 动态调整布林带宽度 (替代固定 2 STD)
        - 价格触及布林带边缘时入场，回归 SMA 止盈
        """
        if len(prices) < 31:
            return {"action": "HOLD", "reason": "数据不足"}

        current = prices[-1]
        sma = self._calc_sma(list(prices), 30)

        # ATR 动态波段宽度
        atr_mult = 2.0
        atr_val = 0.0
        if klines and len(klines) >= 14:
            atr_val = self._calc_atr(klines)
            atr_mult = atr_val * 2 / sma if sma > 0 else 0.04

        upper_band = sma * (1 + atr_mult)
        lower_band = sma * (1 - atr_mult)

        if current < lower_band:
            return {
                "strategy": "MEAN_REVERSION",
                "action": "BUY",
                "position_size_pct": 0.15,
                "target": sma,  # 目标价格 = SMA
                "reason": f"价格超卖: {current:.2f} < {lower_band:.2f}, ATR宽={atr_mult*100:.1f}%"
            }
        elif current > upper_band:
            return {
                "strategy": "MEAN_REVERSION",
                "action": "SELL",
                "position_size_pct": 0.15,
                "target": sma,
                "reason": f"价格超买: {current:.2f} > {upper_band:.2f}, ATR宽={atr_mult*100:.1f}%"
            }

        return {"action": "HOLD",
                "reason": f"价格在回归区间 [{lower_band:.2f}, {upper_band:.2f}]"}

    # ─── 策略3: 突破策略 (无 look-ahead bias) ───

    def breakout_strategy(self, symbol: str, prices: deque,
                          capital: float, klines: List = None) -> Dict:
        """
        突破策略 (增强版, 修复 look-ahead bias)
        关键: 使用已完成的K线数据，不包含当根未完成的K线
        """
        if len(prices) < 51:
            return {"action": "HOLD", "reason": "数据不足"}

        current = prices[-1]

        # ─── 修复 look-ahead bias ───
        # 严格使用已完成的历史K线 (排除当根未完成K线)
        hist_prices = list(prices)[:-1]  # 排除最后一根未完成K线

        # 使用过去 50 根已完成K线的最高/最低
        channel_high = max(hist_prices[-50:])
        channel_low = min(hist_prices[-50:])

        # ATR 动态止损
        stop_pct = 0.015
        if klines and len(klines) >= 14:
            atr = self._calc_atr(klines)
            if current > 0:
                stop_pct = min(atr / current, 0.04)

        # 额外过滤: 突破幅度至少超过通道的 0.5%
        threshold_pct = max((channel_high - channel_low) / channel_high * 0.1, 0.005)

        if current > channel_high * (1 + threshold_pct):
            return {
                "strategy": "BREAKOUT",
                "action": "BUY",
                "position_size_pct": 0.1,
                "stop_loss": channel_low,
                "reason": f"突破阻力: {current:.2f} > {channel_high:.2f} * {1+threshold_pct:.4f}"
            }
        elif current < channel_low * (1 - threshold_pct):
            return {
                "strategy": "BREAKOUT",
                "action": "SELL",
                "position_size_pct": 0.1,
                "stop_loss": channel_high,
                "reason": f"跌破支撑: {current:.2f} < {channel_low:.2f} * {1-threshold_pct:.4f}"
            }

        return {"action": "HOLD",
                "reason": f"无突破信号 [{channel_low:.2f}, {channel_high:.2f}]"}

    # ─── 持仓止损检查 (核心修复) ───

    def _check_and_apply_stops(self, symbol: str, current_price: float):
        """
        检查并执行止损 (真实监控，之前只算不执行)
        每隔 _stop_check_interval 秒调用一次
        """
        key = symbol
        if key not in self.active_positions:
            return

        pos = self.active_positions[key]
        stop = pos.get("stop_loss", 0)
        side = pos.get("side", "")
        entry = pos.get("entry_price", 0)

        if not stop or not side or not entry:
            return

        triggered = False
        if side == "BUY" and current_price <= stop:
            triggered = True
            reason = "止损触发"
        elif side == "SELL" and current_price >= stop:
            triggered = True
            reason = "止损触发"

        if triggered:
            print(f"\n[风控] {symbol} {reason}! 当前价={current_price:.2f}, "
                  f"止损={stop:.2f}, 持仓方向={side}")
            self._close_position(symbol, reason)

    def _close_position(self, symbol: str, reason: str):
        """平仓"""
        pos = self.active_positions.get(symbol, {})
        if not pos:
            return

        try:
            if pos.get("is_futures"):
                self.client.futures_order(
                    symbol=symbol,
                    side="SELL" if pos["side"] == "BUY" else "BUY",
                    position_side="BOTH",
                    order_type="MARKET",
                    quantity=pos.get("quantity", 0),
                    leverage=2
                )
            else:
                self.client.spot_order(
                    symbol=symbol, side="SELL" if pos["side"] == "BUY" else "BUY",
                    order_type="MARKET",
                    quantity=pos.get("quantity", 0)
                )

            # 记录PnL
            entry = pos.get("entry_price", 0)
            current = self.client.get_spot_price(symbol)
            if entry > 0:
                pnl_pct = (current - entry) / entry
                print(f"[平仓] {symbol}, PnL={pnl_pct*100:.2f}%, 原因: {reason}")
                self.risk.update_trade(pnl_pct * self.config.CAPITAL)

            del self.active_positions[symbol]

        except Exception as e:
            print(f"[平仓] 失败: {e}")

    # ─── 信号执行 ───

    def execute_signal(self, signal: Dict, symbol: str):
        """
        执行交易信号 (含真实持仓记录)
        修复: 记录 entry_price, stop_loss, 并监控止损
        """
        if signal["action"] == "HOLD":
            return None

        price = self.client.get_spot_price(symbol)

        # 仓位大小 = 资金占比 * 总资金
        position_value = signal["position_size_pct"] * self.config.CAPITAL
        quantity = self.client._round_step_size(position_value / price, symbol, "spot")

        if quantity <= 0:
            print(f"[{signal['strategy']}] 数量为0，跳过")
            return None

        can_trade, trade_msg = self.risk.can_trade(self.config.CAPITAL)
        if not can_trade:
            print(f"[风控] 禁止开仓: {trade_msg}，跳过 {symbol}")
            return None

        result = self.client.spot_order(
            symbol=symbol, side=signal["action"],
            order_type="MARKET", quantity=quantity, price=price
        )

        if result.get("orderId"):
            # 记录持仓
            self.active_positions[symbol] = {
                "strategy": signal["strategy"],
                "side": signal["action"],
                "entry_price": price,
                "quantity": quantity,
                "stop_loss": signal.get("stop_loss", 0),
                "target": signal.get("target", 0),
                "position_size_pct": signal["position_size_pct"],
                "is_futures": False,
                "entry_time": time.time(),
            }

            print(f"\n[{signal['strategy']}] {'买入' if signal['action']=='BUY' else '卖出'} "
                  f"{symbol} @ {price:.2f}")
            print(f"       止损: {signal.get('stop_loss', 'N/A')}, "
                  f"目标: {signal.get('target', 'N/A')}")
            return result

        return None

    # ─── 权重投票机制 ───

    def _weighted_vote(self, signals: List[Dict]) -> Optional[Dict]:
        """
        策略权重投票 (替代简单多数投票)
        - 每个策略根据自己的权重贡献 BUY/SELL 分数
        - 最终取加权分数最高的动作
        """
        scores = {"BUY": 0.0, "SELL": 0.0, "HOLD": 0.0}

        for sig in signals:
            action = sig["action"]
            strategy = sig.get("strategy", "UNKNOWN")
            weight = self.STRATEGY_WEIGHTS.get(strategy, 0.33)

            if action in scores:
                scores[action] += weight

        # 选出最高分
        best = max(scores.items(), key=lambda x: x[1])
        if best[1] > 0.4:  # 阈值: 权重超过 0.4 才执行
            return best[0]
        return "HOLD"

    # ─── 主循环 ───

    def run(self):
        """运行多策略"""
        print(f"\n{'='*50}")
        print(f"L3 多策略组合启动 (增强版)")
        print(f"资金: {self.config.CAPITAL} USDT")
        print(f"策略权重: 趋势={self.STRATEGY_WEIGHTS['TREND']}, "
              f"均值回归={self.STRATEGY_WEIGHTS['MEAN_REVERSION']}, "
              f"突破={self.STRATEGY_WEIGHTS['BREAKOUT']}")
        print(f"{'='*50}\n")

        # 初始化价格历史
        for symbol in self.config.PAIRS:
            self.price_history[symbol] = deque(maxlen=100)

        last_loop_time = 0

        while True:
            try:
                now = time.time()

                for symbol in self.config.PAIRS:
                    # 1. 获取 K 线数据
                    klines = self._get_klines_data(symbol)
                    price = self.client.get_spot_price(symbol)
                    self.price_history[symbol].append(price)

                    # 2. 收集三个策略信号
                    signals = [
                        self.trend_strategy(symbol, self.price_history[symbol],
                                            self.config.CAPITAL, klines),
                        self.mean_reversion_strategy(symbol, self.price_history[symbol],
                                                    self.config.CAPITAL, klines),
                        self.breakout_strategy(symbol, self.price_history[symbol],
                                              self.config.CAPITAL, klines),
                    ]

                    # 打印各策略信号 (调试用)
                    for sig in signals:
                        if sig["action"] != "HOLD":
                            print(f"[L3] {symbol} [{sig['strategy']}] {sig['action']}: "
                                  f"{sig.get('reason', '')}")

                    # 3. 权重投票
                    final_action = self._weighted_vote(signals)

                    if final_action != "HOLD":
                        # 找到权重最高的该方向信号
                        action_signals = [s for s in signals if s["action"] == final_action]
                        if action_signals:
                            best_signal = max(action_signals,
                                              key=lambda s: self.STRATEGY_WEIGHTS.get(
                                                  s.get("strategy", ""), 0))
                            self.execute_signal(best_signal, symbol)

                    # 4. 止损检查 (每分钟一次)
                    if now - self._last_stop_check >= self._stop_check_interval:
                        self._check_and_apply_stops(symbol, price)
                        self._last_stop_check = now

                    # 5. 止盈检查
                    pos = self.active_positions.get(symbol)
                    if pos and pos.get("target", 0) > 0:
                        if (pos["side"] == "BUY" and price >= pos["target"]) or \
                           (pos["side"] == "SELL" and price <= pos["target"]):
                            print(f"\n[L3] {symbol} 达到目标价 {price:.2f} >= {pos['target']:.2f}，止盈")
                            self._close_position(symbol, "止盈")

                    time.sleep(2)  # 每个交易对间隔 2 秒 (避免 API 限速)

                # 6. 风险检查 (接入实时权益，触发最大亏损/资金下限时停止)
                spot_bal = self.client.get_spot_balance()
                total_value = (
                    sum(float(b["free"]) for b in spot_bal.get("balances", [])
                        if b.get("asset") == "USDT")
                    if isinstance(spot_bal, dict) else 0.0
                )
                position_value = sum(
                    float(p.get("quantity", 0)) * self.client.get_spot_price(sym)
                    for sym, p in self.active_positions.items()
                )
                current_balance = total_value + position_value
                self.risk.update_balance(current_balance)
                can_trade, msg = self.risk.can_trade(current_balance)
                if not can_trade:
                    print(f"[风控] {msg}")
                    return

                time.sleep(3)

            except KeyboardInterrupt:
                print("\n[退出] 停止多策略")
                # 平所有持仓
                for sym in list(self.active_positions.keys()):
                    self._close_position(sym, "手动退出")
                break
            except Exception as e:
                print(f"[错误] {e}")
                time.sleep(60)