"""
L2 策略: 现货+合约三角套利 (10万美金)
利用现货-合约价差进行套利
"""
import time
from typing import Dict, List
import statistics


class ArbitrageStrategy:
    """三角套利策略"""

    def __init__(self, config, client, risk_manager):
        self.config = config
        self.client = client
        self.risk = risk_manager
        self.position_history = []

    def get_spread_info(self, spot_symbol: str, futures_symbol: str) -> Dict:
        """获取价差信息"""
        spot_price = self.client.get_spot_price(spot_symbol)
        futures_price = self.client.get_futures_price(futures_symbol)

        spread = futures_price - spot_price
        spread_pct = spread / spot_price * 100
        funding_rate = 0.0001  # 合约资金费率(0.01%/日)

        return {
            "spot_price": spot_price,
            "futures_price": futures_price,
            "spread": spread,
            "spread_pct": spread_pct,
            "funding_rate": funding_rate,
            "annual_funding": funding_rate * 365 * 100,
            "theoretical_spread": spot_price * 0.001  # 合理价差约0.1%
        }

    def check_arbitrage_opportunity(self, spot_symbol: str, futures_symbol: str) -> Dict:
        """检查套利机会"""
        info = self.get_spread_info(spot_symbol, futures_symbol)

        # 判断条件
        if info["spread_pct"] > 0.1:  # 合约溢价过高
            return {
                "action": "SHORT_FUTURES_BUY_SPOT",
                "entry": {
                    "spot": {"symbol": spot_symbol, "side": "BUY"},
                    "futures": {"symbol": futures_symbol, "side": "SELL"}
                },
                "reason": f"合约溢价 {info['spread_pct']:.3f}% > 0.1%",
                "expected_return": info["spread_pct"] - 0.02  # 扣除手续费
            }
        elif info["spread_pct"] < -0.1:  # 合约折价过低
            return {
                "action": "BUY_FUTURES_SELL_SPOT",
                "entry": {
                    "spot": {"symbol": spot_symbol, "side": "SELL"},
                    "futures": {"symbol": futures_symbol, "side": "BUY"}
                },
                "reason": f"合约折价 {info['spread_pct']:.3f}% < -0.1%",
                "expected_return": abs(info["spread_pct"]) - 0.02
            }

        return {"action": "HOLD", "reason": "价差在正常范围"}

    def execute_arbitrage(self, opportunity: Dict, capital: float) -> bool:
        """执行套利"""
        if opportunity["action"] == "HOLD":
            return False

        print(f"\n[套利] 检测到机会: {opportunity['action']}")
        print(f"[套利] 原因: {opportunity['reason']}")
        print(f"[套利] 预期收益: {opportunity['expected_return']:.3f}%")

        entry = opportunity["entry"]

        # 计算仓位
        spot_amount = capital * 0.5  # 现货用50%资金
        futures_amount = capital * 0.5

        try:
            # 现货操作
            spot_result = self.client.spot_order(
                symbol=entry["spot"]["symbol"],
                side=entry["spot"]["side"],
                order_type="MARKET",
                quantity=spot_amount / self.client.get_spot_price(entry["spot"]["symbol"])
            )

            # 合约操作
            futures_result = self.client.futures_order(
                symbol=entry["futures"]["symbol"],
                side=entry["futures"]["side"],
                position_side="BOTH",
                order_type="MARKET",
                quantity=futures_amount / self.client.get_futures_price(entry["futures"]["symbol"]),
                leverage=1
            )

            print(f"[套利] 执行成功!")
            return True

        except Exception as e:
            print(f"[套利] 执行失败: {e}")
            return False

    def monitor_and_close(self, spot_symbol: str, futures_symbol: str) -> Dict:
        """监控并平仓"""
        info = self.get_spread_info(spot_symbol, futures_symbol)

        # 价差回归到合理范围就平仓
        if abs(info["spread_pct"]) < 0.02:
            return {"should_close": True, "reason": "价差回归"}

        return {"should_close": False}

    def run(self):
        """运行套利策略"""
        print(f"\n{'='*50}")
        print(f"L2 三角套利策略启动")
        print(f"资金: {self.config.CAPITAL} USDT")
        print(f"交易对: {self.config.PAIRS}")
        print(f"{'='*50}\n")

        while True:
            try:
                for spot_sym, fut_sym in zip(self.config.PAIRS, self.config.PAIRS_FUTURES):
                    # 检查套利机会
                    opp = self.check_arbitrage_opportunity(spot_sym, fut_sym)

                    if opp["action"] != "HOLD":
                        # 获取当前余额
                        balance = self.client.get_spot_balance()
                        capital = self.config.CAPITAL  # 简化处理

                        # 执行套利
                        self.execute_arbitrage(opp, capital)

                        # 记录持仓
                        self.position_history.append({
                            "time": time.time(),
                            "opportunity": opp
                        })

                    # 监控是否需要平仓
                    close_signal = self.monitor_and_close(spot_sym, fut_sym)
                    if close_signal["should_close"]:
                        print(f"[监控] {spot_sym}/{fut_sym} {close_signal['reason']}")

                    # 检查风险
                    can_trade, msg = self.risk.can_trade(self.config.CAPITAL)
                    if not can_trade:
                        print(f"[风险] {msg}")
                        return

                time.sleep(self.config.REBALANCE_INTERVAL)

            except KeyboardInterrupt:
                print("\n[退出] 停止套利策略")
                break
            except Exception as e:
                print(f"[错误] {e}")
                time.sleep(60)
