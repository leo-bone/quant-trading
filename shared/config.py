"""
Binance API 配置
仅使用测试网密钥，实盘需替换为真实API Key
"""
import os

# ===== API 配置 =====
# 测试网API (默认使用，模拟交易)
TESTNET_API_KEY = os.getenv("BINANCE_TEST_API_KEY", "your_testnet_api_key")
TESTNET_SECRET_KEY = os.getenv("BINANCE_TEST_SECRET_KEY", "your_testnet_secret_key")

# 实盘API (替换为你的真实密钥)
LIVE_API_KEY = os.getenv("BINANCE_LIVE_API_KEY", "your_live_api_key")
LIVE_SECRET_KEY = os.getenv("BINANCE_LIVE_SECRET_KEY", "your_live_secret_key")

# ===== 运行环境 =====
class Config:
    """通用配置"""
    # 交易所设置
    EXCHANGE = "binance"
    TESTNET = True  # True=测试网, False=实盘

    # API端点
    BASE_URL = "https://testnet.binance.vision" if TESTNET else "https://api.binance.com"
    FUTURES_URL = "https://testnet.binancefuture.com" if TESTNET else "https://fapi.binance.com"

    # 交易手续费率 (Maker/Taker)
    MAKER_FEE = 0.001  # 0.1%
    TAKER_FEE = 0.001  # 0.1%

    # 日志配置
    LOG_LEVEL = "INFO"
    LOG_FILE = "trading.log"

    @classmethod
    def get_api_keys(cls):
        """获取当前环境的API密钥"""
        if cls.TESTNET:
            return TESTNET_API_KEY, TESTNET_SECRET_KEY
        return LIVE_API_KEY, LIVE_SECRET_KEY


# ===== 级别配置 =====
class L1Config(Config):
    """L1: 1万美金配置"""
    CAPITAL = 10000  # 初始资金 USDT
    RISK_PER_TRADE = 0.02  # 单笔风险 2%
    MAX_POSITION = 0.3  # 最大仓位 30%
    STOP_LOSS = 0.02  # 止损 2%
    TAKE_PROFIT = 0.04  # 止盈 4%
    MAX_DAILY_LOSS = 0.05  # 日内最大亏损 5%

    # 策略参数
    STRATEGY_TYPE = "grid"  # 网格策略
    GRID_LEVELS = 5  # 网格层数
    GRID_SPACING = 0.01  # 网格间距 1%

    # 交易对
    PAIRS = ["BTCUSDT", "ETHUSDT"]


class L2Config(Config):
    """L2: 10万美金配置"""
    CAPITAL = 100000
    RISK_PER_TRADE = 0.015  # 单笔风险 1.5%
    MAX_POSITION = 0.4  # 最大仓位 40%
    STOP_LOSS = 0.015  # 止损 1.5%
    TAKE_PROFIT = 0.03  # 止盈 3%
    MAX_DAILY_LOSS = 0.08  # 日内最大亏损 8%

    # 策略参数
    STRATEGY_TYPE = "arbitrage"  # 套利策略
    SPREAD_THRESHOLD = 0.001  # 价差阈值
    REBALANCE_INTERVAL = 300  # 调仓间隔(秒)

    # 交易对
    PAIRS = ["BTCUSDT", "ETHUSDT", "BNBUSDT", "SOLUSDT"]
    PAIRS_FUTURES = ["BTCPERP", "ETHPERP"]  # 合约交易对


class L3Config(Config):
    """L3: 100万美金配置"""
    CAPITAL = 1000000
    RISK_PER_TRADE = 0.01  # 单笔风险 1%
    MAX_POSITION = 0.5  # 最大仓位 50%
    STOP_LOSS = 0.01  # 止损 1%
    TAKE_PROFIT = 0.02  # 止盈 2%
    MAX_DAILY_LOSS = 0.1  # 日内最大亏损 10%

    # 策略参数
    STRATEGY_TYPE = "multi_strategy"  # 多策略组合
    STRATEGIES = ["trend", "mean_reversion", "arbitrage"]

    # 交易对
    PAIRS = ["BTCUSDT", "ETHUSDT", "BNBUSDT", "SOLUSDT", "ADAUSDT"]
    PAIRS_FUTURES = ["BTCPERP", "ETHPERP", "BNBPERP"]


def get_config(level: str):
    """获取指定级别的配置"""
    configs = {
        "L1": L1Config,
        "L2": L2Config,
        "L3": L3Config,
        "l1": L1Config,
        "l2": L2Config,
        "l3": L3Config,
    }
    return configs.get(level, L1Config)
