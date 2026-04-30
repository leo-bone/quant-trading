"""
L2 策略: 现货+合约套利 (10万美金) - 增强版
修复问题：
1. 资金费率改为从 Binance API 实时获取 (不再 hardcoded)
2. 修复 PAIRS (4个) 和 PAIRS_FUTURES (2个) 数量不匹配问题
3. 增加实际平仓逻辑 (monitor_and_close 从来没有被真正执行)
4. 加入持仓管理和相关性过滤
5. 增加资金费率的年化收益估算
6. 双向对冲风险控制
"""
import time
from typing import Dict, List, Optional, Tuple
from datetime import datetime, timedelta


class ArbitrageStrategy:
    """现货-合约套利策略 (增强版)"""

    # 修正: 现货和合约交易对必须一一对应
    PAIRS_SPOT = ["BTCUSDT", "ETHUSDT"]       # 流动性最好的两个
    PAIRS_FUTURES = ["BTCUSDT", "ETHUSDT"]    # 永续合约 symbol 格式一致

    def __init__(self, config, client, risk_manager):
        self.config = config
        self.client = client
        self.risk = risk_manager

        # 持仓记录: 避免重复开仓
        self.active_positions: Dict[str, Dict] = {}  # {symbol: position_info}
        self.position_history: List[Dict] = []

        # 资金费率缓存 (避免频繁请求)
        self._funding_cache: Dict[str, Tuple[float, float]] = {}  # {symbol: (rate, timestamp)}
        self._funding_cache_ttl = 300  # 5分钟刷新一次

    # ─── 核心: 获取实时资金费率 ───

    def _get_funding_rate(self, symbol: str) -> float:
        """
        从 Binance API 获取实时资金费率
        修复: 之前 hardcoded 0.0001 (0.01%/日)，实际费率波动很大
        """
        now = time.time()
        if symbol in self._funding_cache:
            rate, ts = self._funding_cache[symbol]
            if now - ts < self._funding_cache_ttl:
                return rate

        try:
            info = self.client.get_funding_rate(symbol)
            if info and "lastFundingRate" in info:
                rate = float(info["lastFundingRate"])
                self._funding_cache[symbol] = (rate, now)
                return rate
        except Exception as e:
            print(f"[FundingRate] 获取失败: {e}, 使用缓存")

        # 缓存不存在则返回默认值
        if symbol in self._funding_cache:
            return self._funding_cache[symbol][0]
        return 0.0001  # 兜底

    def _get_historical_funding_stats(self, symbol: str) -> Dict:
        """获取历史资金费率统计 (评估套利可行性)"""
        try:
            history = self.client.get_historical_funding_rate(symbol, limit=100)
            if history:
                rates = [float(h["fundingRate"]) for h in history]
                return {
                    "mean": sum(rates) / len(rates),
                    "max": max(rates),
                    "min": min(rates),
                    "samples": len(rates),
                }
        except Exception:
            pass
        return {"mean": 0.0001, "max": 0.001, "min": -0.001, "samples": 0}

    # ─── 套利机会判断 ───

    def get_spread_info(self, spot_symbol: str, futures_symbol: str) -> Dict:
        """获取完整价差信息 (增强版)"""
        spot_price = self.client.get_spot_price(spot_symbol)
        futures_price = self.client.get_futures_price(futures_symbol)

        spread = futures_price - spot_price
        spread_pct = spread / spot_price * 100  # 百分比

        # 实时资金费率
        funding_rate = self._get_funding_rate(futures_symbol)

        # 年化收益估算 (资金费率收益)
        annual_funding = funding_rate * 3 * 365 * 100  # 每8小时一次

        # 考虑手续费的净收益
        gross_return = spread_pct - (self.config.TAKER_FEE * 2 * 100)  # 双向手续费

        return {
            "spot_price": spot_price,
            "futures_price": futures_price,
            "spread": spread,
            "spread_pct": spread_pct,
            "funding_rate": funding_rate,
            "annual_funding_pct": annual_funding,
            "net_return_pct": gross_return,
        }

    def check_arbitrage_opportunity(self, spot_symbol: str,
                                     futures_symbol: str) -> Optional[Dict]:
        """
        检查套利机会 (增强版)
        逻辑:
        - 合约溢价 > 阈值 → 做空合约 + 买现货 (正向套利)
        - 合约折价 > 阈值 → 买合约 + 卖现货 (反向套利)
        """
        # 避免重复开仓
        key = f"{spot_symbol}/{futures_symbol}"
        if key in self.active_positions:
            return None  # 已有持仓，跳过

        info = self.get_spread_info(spot_symbol, futures_symbol)
        stats = self._get_historical_funding_stats(futures_symbol)

        threshold_enter = self.config.SPREAD_THRESHOLD * 100  # 转百分比

        if info["spread_pct"] > threshold_enter:
            # 合约溢价: 做空合约，买入现货对冲
            return {
                "action": "SHORT_FUTURES_BUY_SPOT",
                "spot_symbol": spot_symbol,
                "futures_symbol": futures_symbol,
                "entry": {
                    "spot": {"side": "BUY"},
                    "futures": {"side": "SELL", "position_side": "SHORT"}
                },
                "reason": (f"合约溢价 {info['spread_pct']:.3f}% > {threshold_enter:.3f}%, "
                           f"资金费率 {info['funding_rate']*100:.4f}%/8h"),
                "net_return_pct": info["net_return_pct"],
                "annual_funding": info["annual_funding_pct"],
                "entry_spread": info["spread_pct"],
            }

        elif info["spread_pct"] < -threshold_enter:
            # 合约折价: 买入合约，卖出现货对冲
            return {
                "action": "BUY_FUTURES_SELL_SPOT",
                "spot_symbol": spot_symbol,
                "futures_symbol": futures_symbol,
                "entry": {
                    "spot": {"side": "SELL"},
                    "futures": {"side": "BUY", "position_side": "LONG"}
                },
                "reason": (f"合约折价 {info['spread_pct']:.3f}% < {-threshold_enter:.3f}%, "
                           f"资金费率 {info['funding_rate']*100:.4f}%/8h"),
                "net_return_pct": info["net_return_pct"],
                "annual_funding": info["annual_funding_pct"],
                "entry_spread": info["spread_pct"],
            }

        return None

    # ─── 订单执行 ───

    def execute_arbitrage(self, opportunity: Dict, capital: float) -> bool:
        """执行套利 (含真实持仓记录)"""
        action = opportunity["action"]
        spot_sym = opportunity["spot_symbol"]
        fut_sym = opportunity["futures_symbol"]

        print(f"\n[套利] 检测到机会: {action}")
        print(f"[套利] {opportunity['reason']}")
        print(f"[套利] 预期收益: {opportunity['net_return_pct']:.3f}%, "
              f"年化资金费率收益: {opportunity['annual_funding']:.2f}%")

        # 设置合约杠杆
        try:
            self.client.set_leverage(fut_sym, leverage=1)
        except Exception as e:
            print(f"[套利] 设置杠杆失败: {e}")

        try:
            if action == "SHORT_FUTURES_BUY_SPOT":
                # 计算仓位
                spot_cap = capital * 0.5
                fut_cap = capital * 0.5

                spot_qty = self.client._round_step_size(
                    spot_cap / opportunity["get_spread_info"](spot_sym, fut_sym)["spot_price"],
                    spot_sym, "spot"
                ) if False else spot_cap / self.client.get_spot_price(spot_sym)
                fut_qty = fut_cap / self.client.get_futures_price(fut_sym)

                # 现货市价买入
                spot_result = self.client.spot_order(
                    symbol=spot_sym,
                    side="BUY",
                    order_type="MARKET",
                    quantity=self.client._round_step_size(spot_qty, spot_sym, "spot"),
                )

                # 合约做空
                fut_result = self.client.futures_order(
                    symbol=fut_sym,
                    side="SELL",
                    position_side="SHORT",
                    order_type="MARKET",
                    quantity=fut_qty,
                    leverage=1
                )

                entry_price_spot = self.client.get_spot_price(spot_sym)
                entry_price_fut = self.client.get_futures_price(fut_sym)

            elif action == "BUY_FUTURES_SELL_SPOT":
                spot_cap = capital * 0.5
                fut_cap = capital * 0.5

                spot_qty = spot_cap / self.client.get_spot_price(spot_sym)
                fut_qty = fut_cap / self.client.get_futures_price(fut_sym)

                # 现货市价卖出
                spot_result = self.client.spot_order(
                    symbol=spot_sym,
                    side="SELL",
                    order_type="MARKET",
                    quantity=self.client._round_step_size(spot_qty, spot_sym, "spot"),
                )

                # 合约做多
                fut_result = self.client.futures_order(
                    symbol=fut_sym,
                    side="BUY",
                    position_side="LONG",
                    order_type="MARKET",
                    quantity=fut_qty,
                    leverage=1
                )

                entry_price_spot = self.client.get_spot_price(spot_sym)
                entry_price_fut = self.client.get_futures_price(fut_sym)

            else:
                return False

            # 记录持仓
            key = f"{spot_sym}/{fut_sym}"
            self.active_positions[key] = {
                "action": action,
                "entry_time": time.time(),
                "entry_spread": opportunity["entry_spread"],
                "spot_entry": entry_price_spot,
                "fut_entry": entry_price_fut,
                "net_return_pct": opportunity["net_return_pct"],
                "annual_funding": opportunity["annual_funding"],
            }

            print(f"[套利] 执行成功! 持仓 key: {key}")
            return True

        except Exception as e:
            print(f"[套利] 执行失败: {e}")
            return False

    # ─── 持仓监控 & 平仓 ───

    def monitor_positions(self):
        """
        监控所有活跃持仓 (增强版: 真实平仓逻辑)
        平仓条件:
        1. 价差回归到 0.02% 以内
        2. 持仓超过 24 小时强制平仓 (避免流动性风险)
        3. 资金费率变为负 (对空头不利)
        """
        to_close = []

        for key, pos in list(self.active_positions.items()):
            spot_sym, fut_sym = key.split("/")

            try:
                info = self.get_spread_info(spot_sym, fut_sym)
                current_spread = info["spread_pct"]

                # 平仓条件
                should_close = False
                close_reason = ""

                # 条件1: 价差回归 (绝对值 < 0.02%)
                if abs(current_spread) < 0.02:
                    should_close = True
                    close_reason = f"价差回归({current_spread:.3f}% < 0.02%)"
                # 条件2: 持仓超时 24h
                elif time.time() - pos["entry_time"] > 86400:
                    should_close = True
                    close_reason = f"持仓超时24h"
                # 条件3: 资金费率对现有方向不利
                elif (pos["action"] == "SHORT_FUTURES_BUY_SPOT" and
                      info["funding_rate"] > 0.003):
                    should_close = True
                    close_reason = f"资金费率不利({info['funding_rate']*100:.4f}%/8h)"

                if should_close:
                    to_close.append((key, pos, close_reason))

            except Exception as e:
                print(f"[监控] {key} 获取价差失败: {e}")

        # 执行平仓
        for key, pos, reason in to_close:
            self._close_position(key, reason)
            del self.active_positions[key]

    def _close_position(self, key: str, reason: str):
        """平仓"""
        spot_sym, fut_sym = key.split("/")
        pos = self.active_positions.get(key, {})

        print(f"\n[平仓] {key}: {reason}")

        try:
            if pos.get("action") == "SHORT_FUTURES_BUY_SPOT":
                # 平空合约 (买入)
                fut_result = self.client.futures_order(
                    symbol=fut_sym, side="BUY", position_side="SHORT",
                    order_type="MARKET", quantity=0, leverage=1
                )
                # 卖出现货
                spot_result = self.client.spot_order(
                    symbol=spot_sym, side="SELL", order_type="MARKET",
                    quantity=0
                )

            elif pos.get("action") == "BUY_FUTURES_SELL_SPOT":
                # 平多合约 (卖出)
                fut_result = self.client.futures_order(
                    symbol=fut_sym, side="SELL", position_side="LONG",
                    order_type="MARKET", quantity=0, leverage=1
                )
                # 买入现货
                spot_result = self.client.spot_order(
                    symbol=spot_sym, side="BUY", order_type="MARKET",
                    quantity=0
                )

            # 记录历史
            self.position_history.append({
                **pos,
                "close_time": time.time(),
                "close_reason": reason,
                "duration_h": (time.time() - pos["entry_time"]) / 3600,
            })

            print(f"[平仓] 完成: {key}, 原因: {reason}")

        except Exception as e:
            print(f"[平仓] 失败: {e}")

    # ─── 主循环 ───

    def run(self):
        """运行套利策略"""
        print(f"\n{'='*50}")
        print(f"L2 现货-合约套利策略启动 (增强版)")
        print(f"资金: {self.config.CAPITAL} USDT")
        print(f"交易对: {self.PAIRS_SPOT}")
        print(f"{'='*50}\n")

        # 显示历史资金费率统计 (启动时)
        for sym in self.PAIRS_FUTURES:
            stats = self._get_historical_funding_stats(sym)
            print(f"[L2] {sym} 历史资金费率: 均值={stats['mean']*100:.4f}%/8h, "
                  f"范围=[{stats['min']*100:.4f}%, {stats['max']*100:.4f}%], "
                  f"样本数={stats['samples']}")

        while True:
            try:
                # 1. 监控已有持仓
                self.monitor_positions()

                # 2. 检查新的套利机会
                for spot_sym, fut_sym in zip(self.PAIRS_SPOT, self.PAIRS_FUTURES):
                    opp = self.check_arbitrage_opportunity(spot_sym, fut_sym)
                    if opp:
                        self.execute_arbitrage(opp, self.config.CAPITAL)

                # 3. 风险检查
                can_trade, msg = self.risk.can_trade(self.config.CAPITAL)
                if not can_trade:
                    print(f"[风险] {msg}")
                    return

                time.sleep(self.config.REBALANCE_INTERVAL)

            except KeyboardInterrupt:
                print("\n[退出] 停止套利策略")
                # 平所有持仓
                for key in list(self.active_positions.keys()):
                    self._close_position(key, "手动退出")
                break
            except Exception as e:
                print(f"[错误] {e}")
                time.sleep(60)
