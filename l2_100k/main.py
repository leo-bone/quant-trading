#!/usr/bin/env python3
"""
L2 量化交易系统 (10万美金)
策略: 现货+合约三角套利
"""
import sys
import os
sys.path.insert(0, os.path.join(os.path.dirname(__file__), '..'))

from shared.client import create_client
from shared.risk_manager import RiskManager
from l2_100k.strategy import ArbitrageStrategy


def main():
    print("""
    ╔══════════════════════════════════════╗
    ║   L2 量化交易系统 (10万美金)          ║
    ║   策略: 现货+合约三角套利            ║
    ║   模式: 现货 + 杠杆合约              ║
    ╚══════════════════════════════════════╝
    """)

    # 初始化
    client = create_client("L2")
    risk_manager = RiskManager(client.config)
    strategy = ArbitrageStrategy(client.config, client, risk_manager)

    # 运行
    strategy.run()


if __name__ == "__main__":
    main()
