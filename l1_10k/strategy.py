"""
L1 策略: 网格策略 (1万美金)
在固定价格区间设置网格，低买高卖
"""
import time
from typing import Dict, List
from datetime import datetime


class GridStrategy:
    """网格策略"""

    def __init__(self, config, client, risk_manager):
        self.config = config
        self.client = client
        self.risk = risk_manager
        self.grid_orders = []  # 存储网格订单
        self.last_price = 0
        self.position = 0  # 持仓数量

    def initialize_grid(self, symbol: str, price_range: tuple, levels: int = None):
        """初始化网格"""
        levels = levels or self.config.GRID_LEVELS
        current_price = self.client.get_spot_price(symbol)
        self.last_price = current_price

        lower, upper = price_range
        grid_step = (upper - lower) / levels

        print(f"[Grid] 初始化 {symbol} 网格: {lower} - {upper}, {levels}层")

        # 计算每层下单数量
        balance = self.client.get_spot_balance()
        usdt_balance = self._get_balance(balance, "USDT")
        amount_per_grid = (usdt_balance * 0.8) / (levels / 2)  # 用80%资金

        # 创建网格
        for i in range(levels + 1):
            grid_price = lower + (grid_step * i)
            if i < levels / 2:
                # 下方网格: 买入
                side = "BUY"
                quantity = amount_per_grid / grid_price
            else:
                # 上方网格: 卖出
                side = "SELL"
                quantity = amount_per_grid / grid_price

            self.grid_orders.append({
                "price": grid_price,
                "side": side,
                "quantity": quantity,
                "filled": False,
                "order_id": None
            })

        return self.grid_orders

    def _get_balance(self, balance_data: Dict, asset: str) -> float:
        """获取余额"""
        if not balance_data:
            return 0
        for bal in balance_data.get("balances", []):
            if bal["asset"] == asset:
                return float(bal["free"])
        return 0

    def check_and_execute(self, symbol: str) -> List[Dict]:
        """检查价格并执行订单"""
        current_price = self.client.get_spot_price(symbol)
        executed = []

        for order in self.grid_orders:
            if order["filled"]:
                continue

            # 价格触及网格线
            should_fill = False
            if order["side"] == "BUY" and current_price <= order["price"]:
                should_fill = True
            elif order["side"] == "SELL" and current_price >= order["price"]:
                should_fill = True

            if should_fill:
                # 下单
                result = self.client.spot_order(
                    symbol=symbol,
                    side=order["side"],
                    order_type="LIMIT",
                    quantity=order["quantity"],
                    price=order["price"]
                )

                if result.get("orderId"):
                    order["filled"] = True
                    order["order_id"] = result["orderId"]
                    executed.append(order)
                    print(f"[Grid] 执行 {order['side']} {symbol} @ {order['price']}")

        self.last_price = current_price
        return executed

    def run(self, symbol: str, price_range: tuple):
        """运行网格策略"""
        print(f"\n{'='*50}")
        print(f"L1 网格策略启动")
        print(f"交易对: {symbol}")
        print(f"资金: {self.config.CAPITAL} USDT")
        print(f"{'='*50}\n")

        # 初始化网格
        self.initialize_grid(symbol, price_range)

        # 主循环
        while True:
            try:
                executed = self.check_and_execute(symbol)

                # 检查风险
                can_trade, msg = self.risk.can_trade(
                    self.client.get_spot_balance().get("totalPnl", self.config.CAPITAL)
                )
                if not can_trade:
                    print(f"[风险警告] {msg}")
                    break

                time.sleep(60)  # 每分钟检查

            except KeyboardInterrupt:
                print("\n[退出] 停止网格策略")
                break
            except Exception as e:
                print(f"[错误] {e}")
                time.sleep(60)


def create_l1_strategy(client, risk_manager):
    """创建L1策略"""
    return GridStrategy(
        config=__import__('shared.config', fromlist=['L1Config']).L1Config,
        client=client,
        risk_manager=risk_manager
    )
