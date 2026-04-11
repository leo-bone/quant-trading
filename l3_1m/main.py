#!/usr/bin/env python3
"""
L3 量化交易系统 (100万美金)
策略: 多策略组合 (趋势 + 均值回归 + 突破)
"""
import sys
import os
sys.path.insert(0, os.path.join(os.path.dirname(__file__), '..'))

from shared.client import create_client
from shared.risk_manager import RiskManager
from l3_1m.strategy import MultiStrategy


def main():
    print("""
    ╔══════════════════════════════════════╗
    ║   L3 量化交易系统 (100万美金)         ║
    ║   策略: 多策略组合                    ║
    ║   模式: 现货 + 杠杆合约               ║
    ╚══════════════════════════════════════╝
    """)

    # 初始化
    client = create_client("L3")
    risk_manager = RiskManager(client.config)
    strategy = MultiStrategy(client.config, client, risk_manager)

    # 运行
    strategy.run()


if __name__ == "__main__":
    main()
