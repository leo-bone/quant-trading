#!/usr/bin/env python3
"""
L1 量化交易系统 (1万美金)
网格策略: 现货交易
"""
import sys
import os
sys.path.insert(0, os.path.join(os.path.dirname(__file__), '..'))

from shared.client import create_client
from shared.risk_manager import RiskManager
from l1_10k.strategy import GridStrategy


def main():
    print("""
    ╔══════════════════════════════════════╗
    ║   L1 量化交易系统 (1万美金)            ║
    ║   策略: 网格交易                      ║
    ║   模式: 现货交易                      ║
    ╚══════════════════════════════════════╝
    """)

    # 初始化
    client = create_client("L1")
    risk_manager = RiskManager(client.config)
    strategy = GridStrategy(client.config, client, risk_manager)

    # 配置
    symbol = "BTCUSDT"
    price_range = (60000, 75000)  # BTC 网格区间

    # 运行
    strategy.run(symbol, price_range)


if __name__ == "__main__":
    main()
