#!/usr/bin/env python3
"""
量化交易系统启动器
"""
import sys


def main():
    print("""
    ╔══════════════════════════════════════════════════════╗
    ║           三级量化交易系统                          ║
    ║           Python + Binance API                      ║
    ╚══════════════════════════════════════════════════════╝

    请选择要运行的系统级别:
    """)

    print("""
    [1] L1 系统 - 1万美金 (网格策略)
    [2] L2 系统 - 10万美金 (套利策略)
    [3] L3 系统 - 100万美金 (多策略组合)
    [4] 查看系统架构
    [0] 退出
    """)

    choice = input("请输入选项 (0-4): ").strip()

    if choice == "1":
        print("\n启动 L1 系统 (1万美金 - 网格策略)...")
        from l1_10k.main import main as l1_main
        l1_main()
    elif choice == "2":
        print("\n启动 L2 系统 (10万美金 - 套利策略)...")
        from l2_100k.main import main as l2_main
        l2_main()
    elif choice == "3":
        print("\n启动 L3 系统 (100万美金 - 多策略组合)...")
        from l3_1m.main import main as l3_main
        l3_main()
    elif choice == "4":
        print("""
        ═══════════════════════════════════════════════════
        系统架构

        shared/           - 共享模块
        ├── config.py     - 配置文件 (API、参数)
        ├── client.py     - Binance 客户端
        └── risk_manager.py - 风险管理器

        l1_10k/           - L1 系统 (1万美金)
        ├── strategy.py   - 网格策略
        └── main.py       - 入口

        l2_100k/          - L2 系统 (10万美金)
        ├── strategy.py   - 三角套利策略
        └── main.py       - 入口

        l3_1m/            - L3 系统 (100万美金)
        ├── strategy.py   - 多策略组合
        └── main.py       - 入口

        requirements.txt   - 依赖包
        ═══════════════════════════════════════════════════
        """)
        main()
    elif choice == "0":
        print("\n退出系统")
        sys.exit(0)
    else:
        print("\n无效选项，请重新选择")
        main()


if __name__ == "__main__":
    main()
