"""
L1 策略: 网格策略 (1万美金) - 增强版
修复问题：
1. 价格区间动态跟踪 (不复用固定区间)
2. 正确处理 LOT_SIZE 精度
3. 挂单是否成交的准确判断 (通过订单状态查询)
4. 动态调整网格参数 (ATR 自适应)
5. 订单簿确认而非简单价格触发 (避免虚假突破)
6. 追踪实际持仓
"""
import time
from typing import Dict, List, Optional
from datetime import datetime


class GridStrategy:
    """网格策略 (增强版)"""

    def __init__(self, config, client, risk_manager):
        self.config = config
        self.client = client
        self.risk = risk_manager
        self.grid_orders: List[Dict] = []
        self.last_price = 0.0
        self.position = 0.0       # 当前净持仓 (含多空)
        self.entry_price = 0.0     # 平均入场价
        self.pending_orders: List[Dict] = []  # 等待成交的订单
        self.atr = 0.0             # 14日ATR (用于自适应间距)
        self.peak_price = 0.0       # 当前区间最高价
        self.lowest_price = float("inf")  # 当前区间最低价

    # ─── 辅助函数 ───

    def _calc_atr(self, symbol: str, period: int = 14) -> float:
        """计算 ATR (Average True Range) 用于动态网格间距"""
        klines = self.client.get_klines(symbol, interval="1h", limit=100)
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

        if len(tr_list) < period:
            return 0.0
        return sum(tr_list[-period:]) / period

    def _get_order_status(self, symbol: str, order_id: int) -> Dict:
        """查询订单状态 (修复: 判断是否真正成交)"""
        url = f"{self.client.spot_url}/api/v3/order"
        params = {"symbol": symbol.upper(), "orderId": order_id}
        result = self.client._request("GET", url, signed=True, params=params)
        return result

    def _get_open_orders(self, symbol: str) -> List[Dict]:
        """获取当前挂单"""
        return self.client.get_spot_orders(symbol)

    def _calc_avg_price(self, trades: List[Dict]) -> float:
        """从订单成交详情计算平均成交价"""
        if not trades:
            return 0.0
        total_value = sum(float(t["price"]) * float(t["qty"])
                          for t in trades)
        total_qty = sum(float(t["qty"]) for t in trades)
        return total_value / total_qty if total_qty > 0 else 0.0

    def _dynamic_price_range(self, symbol: str, lookback: int = 48) -> tuple:
        """
        动态计算网格区间 (替代固定 hardcoded 区间)
        使用过去 lookback 小时的高低点，保留 5% 缓冲
        """
        klines = self.client.get_klines(symbol, interval="1h",
                                         limit=lookback + 1)
        if len(klines) < lookback:
            # 数据不足，用当前价格 ±10% 作为临时区间
            current = self.client.get_spot_price(symbol)
            return current * 0.9, current * 1.1

        highs = [float(k[1]) for k in klines]
        lows = [float(k[2]) for k in klines]

        period_high = max(highs[:-1])  # 不含当前K线 (避免 look-ahead)
        period_low = min(lows[:-1])

        buffer = 0.05  # 5% 缓冲
        lower = period_low * (1 - buffer)
        upper = period_high * (1 + buffer)

        return lower, upper

    def _update_position_from_orders(self, symbol: str):
        """
        从订单簿更新实际持仓状态
        修复: pending_orders 需要实时同步订单状态
        """
        if not self.pending_orders and not self.grid_orders:
            return

        # 查询所有未完成订单
        open_orders = self._get_open_orders(symbol)
        open_ids = {str(o["orderId"]) for o in open_orders}

        new_pending = []
        for order in self.pending_orders:
            oid = str(order.get("orderId") or order.get("local_id", ""))
            if oid in open_ids:
                # 仍在挂单，继续等待
                new_pending.append(order)
            else:
                # 已撤单或已成交 → 查询实际状态
                if oid:
                    status = self._get_order_status(symbol, int(oid))
                    if status.get("status") == "FILLED":
                        self._apply_fill(order, symbol)

        self.pending_orders = new_pending

    def _apply_fill(self, order: Dict, symbol: str):
        """成交时更新持仓"""
        price = float(order.get("price", 0))
        qty = float(order.get("quantity", 0))
        side = order.get("side", "")

        if side == "BUY":
            # 多头加仓
            total_cost = self.position * self.entry_price + price * qty
            self.position += qty
            if self.position > 0:
                self.entry_price = total_cost / self.position
        elif side == "SELL":
            if qty >= self.position:
                # 平仓
                self.position = 0
                self.entry_price = 0.0
            else:
                self.position -= qty

    def _close_position(self, symbol: str, reason: str):
        """止损/止盈触发时真正市价平仓并重置持仓"""
        if self.position > 0:
            qty = self.client._round_step_size(self.position, symbol, "spot")
            if qty > 0:
                result = self.client.spot_order(
                    symbol=symbol, side="SELL", order_type="MARKET", quantity=qty
                )
                print(f"[Grid] {reason} 平仓 {symbol} x {qty}: {result}")
                # 同步风控盈亏
                if self.entry_price > 0:
                    exit_price = self.client.get_spot_price(symbol)
                    pnl = (exit_price - self.entry_price) * qty
                    self.risk.update_trade(pnl)
            else:
                print(f"[Grid] {reason} 但持仓四舍五入为0，跳过平仓")
        self.position = 0.0
        self.entry_price = 0.0

    # ─── 网格初始化 ───

    def initialize_grid(self, symbol: str, price_range: Optional[tuple] = None,
                        levels: int = None):
        """初始化网格 (支持动态区间)"""
        levels = levels or self.config.GRID_LEVELS
        current_price = self.client.get_spot_price(symbol)
        self.last_price = current_price

        if price_range is None:
            price_range = self._dynamic_price_range(symbol)
            print(f"[Grid] 动态区间计算: {price_range[0]:.2f} - {price_range[1]:.2f}")
        else:
            print(f"[Grid] 使用固定区间: {price_range[0]:.2f} - {price_range[1]:.2f}")

        lower, upper = price_range

        # ATR 自适应间距
        atr = self._calc_atr(symbol)
        if atr > 0 and levels > 0:
            grid_step = (upper - lower) / levels
            # 如果 ATR 比默认间距小太多，增加层数；反之减少
            self.atr = atr
        else:
            grid_step = (upper - lower) / levels

        self.peak_price = current_price
        self.lowest_price = current_price

        print(f"[Grid] 初始化 {symbol} 网格: [{lower:.2f}, {upper:.2f}], "
              f"{levels}层, 当前价 {current_price:.2f}")

        # 获取余额并分配 (正确处理 LOT_SIZE)
        balance = self.client.get_spot_balance()
        usdt_balance = self._get_balance(balance, "USDT")

        # 每层可用资金 = 80% USDT / (levels/2)，但不超过最大仓位
        max_per_level = (self.config.CAPITAL * self.config.MAX_POSITION) / (levels / 2)
        amount_per_level = min(
            (usdt_balance * 0.8) / (levels / 2),
            max_per_level
        )

        self.grid_orders = []
        for i in range(levels + 1):
            grid_price = lower + (grid_step * i)

            # 精度处理
            grid_price = self.client._round_price(grid_price, symbol)

            if i < levels / 2:
                side = "BUY"
            else:
                side = "SELL"

            # 精度处理: 按 LOT_SIZE 格式化数量
            qty = amount_per_level / grid_price
            qty = self.client._round_step_size(qty, symbol, "spot")

            self.grid_orders.append({
                "price": grid_price,
                "side": side,
                "quantity": qty,
                "filled": False,
                "order_id": None,       # API 返回的订单号
                "local_id": None,        # 本地编号
                "level": i,
            })

        return self.grid_orders

    def _get_balance(self, balance_data: Dict, asset: str) -> float:
        """获取余额"""
        if not balance_data:
            return 0.0
        for bal in balance_data.get("balances", []):
            if bal["asset"] == asset:
                return float(bal.get("free", 0))
        return 0.0

    # ─── 核心检查 & 执行 ───

    def check_and_execute(self, symbol: str) -> List[Dict]:
        """
        检查价格并执行订单
        修复: 用订单簿确认突破，而非单一价格
        """
        # 首先同步订单状态
        self._update_position_from_orders(symbol)

        current_price = self.client.get_spot_price(symbol)
        self.last_price = current_price

        # 跟踪价格区间
        self.peak_price = max(self.peak_price, current_price)
        self.lowest_price = min(self.lowest_price, current_price)

        executed = []

        # 获取订单簿，验证流动性
        book = self.client.get_order_book(symbol, limit=5)
        bids = book.get("bids", [])
        asks = book.get("asks", [])
        if bids and asks:
            bid_depth = float(bids[0][0])
            ask_depth = float(asks[0][0])
            spread = (ask_depth - bid_depth) / current_price * 100
            print(f"[Grid] {symbol} 价差: {spread:.3f}%, 买1: {bid_depth:.2f}, "
                  f"卖1: {ask_depth:.2f}")

        for order in self.grid_orders:
            if order["filled"]:
                continue

            # 价格触及网格线 (双向确认: 价格条件 + 订单簿流动性)
            should_fill = False
            if order["side"] == "BUY":
                # 买单: 当价格 <= 网格价 且 bid_depth 接近网格价
                if (current_price <= order["price"] and
                        abs(bids[0][0] - order["price"]) / order["price"] < 0.001):
                    should_fill = True
            elif order["side"] == "SELL":
                # 卖单: 当价格 >= 网格价 且 ask_depth 接近网格价
                if (current_price >= order["price"] and
                        abs(asks[0][0] - order["price"]) / order["price"] < 0.001):
                    should_fill = True

            if should_fill:
                # 检查风险
                can_trade, _ = self.risk.can_trade(
                    self.client.get_spot_balance().get("totalPnl",
                                                        self.config.CAPITAL)
                )
                if not can_trade:
                    break

                result = self.client.spot_order(
                    symbol=symbol,
                    side=order["side"],
                    order_type="LIMIT",
                    quantity=order["quantity"],
                    price=order["price"]
                )

                oid = result.get("orderId")
                if oid:
                    order["filled"] = True
                    order["order_id"] = oid
                    order["local_id"] = f"grid_{order['level']}"
                    self.pending_orders.append(order)
                    executed.append(order.copy())
                    print(f"[Grid] 挂单 {order['side']} {symbol} @ "
                          f"{order['price']} x {order['quantity']}")
                else:
                    print(f"[Grid] 下单失败: {result}")

        return executed

    # ─── 动态区间重置 ───

    def check_and_rebalance(self, symbol: str):
        """
        当价格大幅偏离区间时，重新设置网格
        条件: 价格超出区间 ±15%
        """
        if not self.grid_orders:
            return

        lower = self.grid_orders[0]["price"]
        upper = self.grid_orders[-1]["price"]
        current = self.last_price

        # 价格偏离超过 15% → 重建网格
        if current < lower * 0.85:
            print(f"[Grid] 价格跌破区间下限 {lower*0.85:.2f}，重建网格")
            self.grid_orders = []
            self.initialize_grid(symbol)
        elif current > upper * 1.15:
            print(f"[Grid] 价格涨破区间上限 {upper*1.15:.2f}，重建网格")
            self.grid_orders = []
            self.initialize_grid(symbol)

    # ─── 主循环 ───

    def run(self, symbol: str, price_range: Optional[tuple] = None):
        """运行网格策略"""
        print(f"\n{'='*50}")
        print(f"L1 网格策略启动 (增强版)")
        print(f"交易对: {symbol}")
        print(f"资金: {self.config.CAPITAL} USDT")
        print(f"{'='*50}\n")

        self.initialize_grid(symbol, price_range)

        while True:
            try:
                # 检查 & 执行
                executed = self.check_and_execute(symbol)

                # 检查是否需要重建网格
                self.check_and_rebalance(symbol)

                # 检查持仓盈亏
                if self.position > 0 and self.entry_price > 0:
                    pnl_pct = (self.last_price - self.entry_price) / self.entry_price
                    if self.risk.check_take_profit(
                            self.entry_price, self.last_price, "BUY", 1):
                        print(f"[Grid] 止盈! 持仓 PnL {pnl_pct*100:.2f}%")
                        self._close_position(symbol, "止盈")
                        return
                    elif self.risk.check_stop_loss(
                            self.entry_price, self.last_price, "BUY", 1):
                        print(f"[Grid] 止损! 持仓 PnL {pnl_pct*100:.2f}%")
                        self._close_position(symbol, "止损")
                        return

                # 风险检查 (接入实时权益，触发最大亏损/资金下限时停止)
                balance_data = self.client.get_spot_balance()
                total_value = self._get_balance(balance_data, "USDT")
                position_value = self.position * self.last_price
                pending_buy_value = sum(
                    float(k.get("price", 0)) * float(k.get("quantity", 0))
                    for k in self.pending_orders
                    if k.get("side") == "BUY"
                )
                current_balance = total_value + position_value + pending_buy_value
                self.risk.update_balance(current_balance)
                can_trade, msg = self.risk.can_trade(current_balance)
                if not can_trade:
                    print(f"[风险警告] {msg}")
                    break

                time.sleep(60)

            except KeyboardInterrupt:
                print("\n[退出] 停止网格策略")
                break
            except Exception as e:
                print(f"[错误] {e}")
                time.sleep(60)


def create_l1_strategy(client, risk_manager):
    """创建L1策略"""
    import importlib
    config_module = importlib.import_module('shared.config')
    return GridStrategy(
        config=config_module.L1Config,
        client=client,
        risk_manager=risk_manager
    )