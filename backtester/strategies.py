"""
回测策略实现
将三大实盘策略适配到回测引擎
"""
from typing import Dict, Optional
from collections import deque


# ══════════════════════════════════════════
# L1: 网格策略回测
# ══════════════════════════════════════════

def l1_grid_strategy(engine, idx: int) -> Optional[Dict]:
    """
    网格策略回测
    在价格触及网格线时执行
    """
    k = engine.data[idx]
    current_price = k["close"]

    # 初始化网格 (只在第一次调用时)
    if not hasattr(engine, "_grid_initialized"):
        engine._grid_initialized = True
        engine._grid_levels = []
        engine._grid_filled = set()

        lower = current_price * 0.92
        upper = current_price * 1.08
        levels = 8
        step = (upper - lower) / levels

        for i in range(levels + 1):
            engine._grid_levels.append(lower + step * i)

    # 检查是否触及网格
    for i, grid_price in enumerate(engine._grid_levels):
        if i in engine._grid_filled:
            continue

        # 买入: 价格从上方跌到网格价以下
        if i < len(engine._grid_levels) / 2:
            if idx > 0 and engine.data[idx-1]["close"] >= grid_price \
                    and current_price <= grid_price:
                engine._grid_filled.add(i)
                qty = (engine.capital * 0.1) / grid_price
                return {
                    "action": "BUY",
                    "quantity": qty,
                    "reason": f"网格{i}买入 @ {grid_price:.2f}"
                }
        else:
            # 卖出: 价格从下方涨到网格价以上
            if idx > 0 and engine.data[idx-1]["close"] <= grid_price \
                    and current_price >= grid_price:
                engine._grid_filled.add(i)
                qty = (engine.capital * 0.1) / grid_price
                return {
                    "action": "SELL",
                    "quantity": qty,
                    "reason": f"网格{i}卖出 @ {grid_price:.2f}"
                }

    return None


# ══════════════════════════════════════════
# L3: 多策略回测
# ══════════════════════════════════════════

def _calc_ema(prices, period):
    if len(prices) < period:
        return prices[-1] if prices else 0
    ema = prices[0]
    mult = 2 / (period + 1)
    for p in prices[1:]:
        ema = p * mult + ema * (1 - mult)
    return ema


def _calc_std(prices, period):
    if len(prices) < period:
        return 0
    recent = prices[-period:]
    mean = sum(recent) / len(recent)
    variance = sum((p - mean) ** 2 for p in recent) / len(recent)
    return variance ** 0.5


def l3_multi_strategy(engine, idx: int) -> Optional[Dict]:
    """
    多策略组合回测
    在 K 线收盘后生成信号
    """
    lookback = 100
    if idx < 60:
        return None

    closes = [engine.data[i]["close"] for i in range(max(0, idx - lookback), idx + 1)]
    current = closes[-1]

    signals = []

    # ─── 策略1: 趋势跟踪 (EMA 金叉/死叉) ───
    if len(closes) >= 21:
        ema5 = _calc_ema(closes, 5)
        ema20 = _calc_ema(closes, 20)

        if ema5 > ema20 * 1.005 and current > ema5:  # 0.5% 确认阈值
            signals.append(("BUY", 0.4))  # 权重 0.4
        elif ema5 < ema20 * 0.995 and current < ema5:
            signals.append(("SELL", 0.4))

    # ─── 策略2: 均值回归 (布林带) ───
    if len(closes) >= 31:
        sma30 = sum(closes[-30:]) / 30
        std30 = _calc_std(closes, 30)
        upper = sma30 + 2 * std30
        lower = sma30 - 2 * std30

        if current < lower:
            signals.append(("BUY", 0.3))
        elif current > upper:
            signals.append(("SELL", 0.3))

    # ─── 策略3: 突破策略 (修复 look-ahead) ───
    if len(closes) >= 51:
        hist = closes[:-1]  # 排除当根未完成K线
        channel_high = max(hist[-50:])
        channel_low = min(hist[-50:])

        # 价格必须超出通道 0.3% 才算有效突破
        if current > channel_high * 1.003:
            signals.append(("BUY", 0.3))
        elif current < channel_low * 0.997:
            signals.append(("SELL", 0.3))

    if not signals:
        return None

    # 权重投票: 累计 BUY/SELL 权重
    buy_score = sum(s[1] for s in signals if s[0] == "BUY")
    sell_score = sum(s[1] for s in signals if s[0] == "SELL")

    # 动态仓位: 基于当前可用资金，而非初始资金
    # 最大保证金使用 60% 资本 (留 40% 缓冲)
    max_position_value = engine.capital * 0.6
    current_position_value = abs(engine.position) * current
    position_pct = current_position_value / engine.capital if engine.capital > 0 else 0

    if buy_score >= 0.4 and buy_score > sell_score:
        if engine.position <= 0:
            # 开多仓 / 翻多
            target_value = min(max_position_value, engine.capital * 0.6)
            qty = target_value / current
        else:
            # 已有仓位: 不追加（防止无限累积）
            return None
        return {"action": "BUY", "quantity": qty,
                "reason": f"多策略BUY(权重{buy_score:.2f},仓位{position_pct:.0%})"}

    elif sell_score >= 0.4 and sell_score > buy_score:
        if engine.position >= 0:
            # 平多仓 / 开空
            target_value = min(max_position_value, engine.capital * 0.6)
            qty = target_value / current
        else:
            # 已有空仓: 不追加
            return None
        return {"action": "SELL", "quantity": qty,
                "reason": f"多策略SELL(权重{sell_score:.2f},仓位{position_pct:.0%})"}

    return None


# ══════════════════════════════════════════
# 对比基准: 买入持有
# ══════════════════════════════════════════

def benchmark_buy_hold(engine, idx: int) -> Optional[Dict]:
    """买入持有基准"""
    if idx == 0:
        qty = engine.initial_capital / engine.data[0]["close"]
        return {"action": "BUY", "quantity": qty, "reason": "买入持有基准建仓"}
    if idx == len(engine.data) - 1:
        # 最后K线: 强制平仓
        if engine.position != 0:
            return {"action": "SELL" if engine.position > 0 else "BUY",
                    "quantity": abs(engine.position), "reason": "期末平仓"}
    return None
