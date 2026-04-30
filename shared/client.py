"""
Binance 客户端封装 (增强版)
支持现货和合约交易，增加:
- LOT_SIZE / PRICE_FILTER 处理
- 实时资金费率获取
- 历史K线数据 (回测用)
- 订单簿快照
- 异步请求 (aiohttp)
"""
import time
import hmac
import hashlib
import asyncio
import aiohttp
import requests
from typing import Dict, Optional, List
from .config import Config


class BinanceClient:
    """Binance API 客户端 (增强版)"""

    def __init__(self, api_key: str, secret_key: str, testnet: bool = True):
        self.api_key = api_key
        self.secret_key = secret_key
        self.testnet = testnet
        self.spot_url = Config.BASE_URL
        self.futures_url = Config.FUTURES_URL
        self.session = requests.Session()
        self.session.headers.update({"X-MBX-APIKEY": api_key})

        # ── 缓存: Binance 交易对精度 (避免重复请求) ──
        self._symbol_info: Dict[str, Dict] = {}
        self._sync_initialized = False

    # ── 同步签名 ──
    def _sign(self, params: Dict) -> str:
        query = "&".join([f"{k}={v}" for k, v in params.items()])
        return hmac.new(
            self.secret_key.encode(),
            query.encode(),
            hashlib.sha256
        ).hexdigest()

    def _request(self, method: str, url: str, signed: bool = False,
                 params: Optional[Dict] = None) -> Dict:
        params = params or {}
        if signed:
            params = dict(params)  # 不修改原始
            params["timestamp"] = int(time.time() * 1000)
            params["signature"] = self._sign(params)

        try:
            if method == "GET":
                resp = self.session.get(url, params=params, timeout=10)
            else:
                resp = self.session.post(url, data=params, timeout=10)

            result = resp.json()
            if resp.status_code not in (200, 201):
                print(f"[API Error] {resp.status_code}: {result}")
            return result
        except Exception as e:
            print(f"[Request Error] {e}")
            return {}

    # ── 异步签名 ──
    def _sign_async(self, params: Dict) -> str:
        return self._sign(params)

    async def _arequest(self, session: aiohttp.ClientSession,
                        method: str, url: str, signed: bool = False,
                        params: Optional[Dict] = None) -> Dict:
        params = params or {}
        headers = {"X-MBX-APIKEY": self.api_key}
        if signed:
            params = dict(params)
            params["timestamp"] = int(time.time() * 1000)
            params["signature"] = self._sign_async(params)

        try:
            if method == "GET":
                async with session.get(url, params=params,
                                       headers=headers, timeout=10) as resp:
                    return await resp.json()
            else:
                async with session.post(url, data=params,
                                       headers=headers, timeout=10) as resp:
                    return await resp.json()
        except Exception as e:
            print(f"[Async Request Error] {e}")
            return {}

    # ══════════════════════════════════════════
    # 现货交易
    # ══════════════════════════════════════════

    def get_spot_balance(self) -> Dict:
        """获取现货账户余额"""
        url = f"{self.spot_url}/api/v3/account"
        return self._request("GET", url, signed=True)

    def get_spot_price(self, symbol: str) -> float:
        """获取当前价格"""
        url = f"{self.spot_url}/api/v3/ticker/price"
        result = self._request("GET", url, params={"symbol": symbol.upper()})
        return float(result.get("price", 0))

    def get_klines(self, symbol: str, interval: str = "1h",
                   limit: int = 100) -> List:
        """获取K线数据 (现货)"""
        url = f"{self.spot_url}/api/v3/klines"
        return self._request("GET", url, params={
            "symbol": symbol.upper(),
            "interval": interval,
            "limit": limit
        })

    def get_historical_klines(self, symbol: str, interval: str,
                              start_time: int, end_time: Optional[int] = None,
                              limit: int = 1000) -> List:
        """
        获取历史K线 (支持批量拉取大量数据，用于回测)
        start_time / end_time: millisecond timestamp
        """
        url = f"{self.spot_url}/api/v3/klines"
        params = {
            "symbol": symbol.upper(),
            "interval": interval,
            "startTime": start_time,
            "limit": limit,
        }
        if end_time:
            params["endTime"] = end_time
        return self._request("GET", url, params=params)

    def get_order_book(self, symbol: str, limit: int = 20) -> Dict:
        """获取订单簿"""
        url = f"{self.spot_url}/api/v3/depth"
        return self._request("GET", url, params={
            "symbol": symbol.upper(),
            "limit": limit
        })

    def get_exchange_info(self, symbol: str = "") -> Dict:
        """获取交易对精度信息 (现货)"""
        if symbol:
            # 单个交易对缓存
            if symbol.upper() in self._symbol_info:
                return self._symbol_info[symbol.upper()]

        url = f"{self.spot_url}/api/v3/exchangeInfo"
        result = self._request("GET", url)
        if symbol and result.get("symbols"):
            for s in result["symbols"]:
                if s["symbol"] == symbol.upper():
                    self._symbol_info[symbol.upper()] = s
                    break
        return result

    def spot_order(self, symbol: str, side: str, order_type: str,
                   quantity: float, price: Optional[float] = None) -> Dict:
        """现货下单 (自动处理精度)"""
        symbol = symbol.upper()
        quantity = self._round_step_size(quantity, symbol, side="spot")

        url = f"{self.spot_url}/api/v3/order"
        params = {
            "symbol": symbol,
            "side": side.upper(),
            "type": order_type.upper(),
            "quantity": quantity,
        }
        if price:
            params["price"] = self._round_price(price, symbol)
            params["timeInForce"] = "GTC"
        return self._request("POST", url, signed=True, params=params)

    def get_spot_orders(self, symbol: str) -> List:
        """获取当前挂单"""
        url = f"{self.spot_url}/api/v3/openOrders"
        return self._request("GET", url, signed=True,
                             params={"symbol": symbol.upper()})

    def cancel_order(self, symbol: str, order_id: int) -> Dict:
        """取消订单"""
        url = f"{self.spot_url}/api/v3/order"
        return self._request("DELETE", url, signed=True, params={
            "symbol": symbol.upper(),
            "orderId": order_id
        })

    # ══════════════════════════════════════════
    # 合约交易
    # ══════════════════════════════════════════

    def get_futures_balance(self) -> Dict:
        """获取合约账户余额(USDT)"""
        url = f"{self.futures_url}/fapi/v2/balance"
        return self._request("GET", url, signed=True)

    def get_funding_rate(self, symbol: str) -> Dict:
        """
        获取当前资金费率 (实时，从 Binance 获取)
        这是 L2 套利策略最关键的参数，之前是 hardcoded 0.0001
        """
        url = f"{self.futures_url}/fapi/v1/premiumIndex"
        result = self._request("GET", url, params={"symbol": symbol.upper()})
        return result

    def get_historical_funding_rate(self, symbol: str, limit: int = 100) -> List:
        """获取历史资金费率 (用于评估套利可行性)"""
        url = f"{self.futures_url}/fapi/v1/fundingRate"
        return self._request("GET", url, params={
            "symbol": symbol.upper(),
            "limit": limit
        })

    def futures_order(self, symbol: str, side: str, position_side: str,
                     order_type: str, quantity: float,
                     price: Optional[float] = None,
                     leverage: int = 1) -> Dict:
        """合约下单 (自动处理精度)"""
        symbol = symbol.upper()
        quantity = self._round_step_size(quantity, symbol, side="futures")

        url = f"{self.futures_url}/fapi/v1/order"
        params = {
            "symbol": symbol,
            "side": side.upper(),
            "positionSide": position_side.upper(),
            "type": order_type.upper(),
            "quantity": quantity,
            "leverage": leverage
        }
        if price:
            params["price"] = self._round_price(price, symbol)
        return self._request("POST", url, signed=True, params=params)

    def set_leverage(self, symbol: str, leverage: int) -> Dict:
        """设置杠杆倍数"""
        url = f"{self.futures_url}/fapi/v1/leverage"
        return self._request("POST", url, signed=True, params={
            "symbol": symbol.upper(),
            "leverage": leverage
        })

    def get_futures_position(self, symbol: str) -> List:
        """获取持仓信息"""
        url = f"{self.futures_url}/fapi/v2/positionRisk"
        return self._request("GET", url, signed=True,
                             params={"symbol": symbol.upper()})

    def get_futures_price(self, symbol: str) -> float:
        """获取合约当前价格"""
        url = f"{self.futures_url}/fapi/v1/ticker/price"
        result = self._request("GET", url, params={"symbol": symbol.upper()})
        return float(result.get("price", 0))

    def get_futures_klines(self, symbol: str, interval: str = "1h",
                            limit: int = 100) -> List:
        """获取合约K线数据"""
        url = f"{self.futures_url}/fapi/v1/klines"
        return self._request("GET", url, params={
            "symbol": symbol.upper(),
            "interval": interval,
            "limit": limit
        })

    # ══════════════════════════════════════════
    # 精度处理 (核心: 修复 LOT_SIZE 问题)
    # ══════════════════════════════════════════

    def _get_symbol_filters(self, symbol: str, side: str = "spot") -> Dict:
        """获取交易对精度过滤器"""
        try:
            info = self.get_exchange_info(symbol)
            filters = {}
            if side == "spot" and info.get("symbols"):
                for s in info["symbols"]:
                    if s["symbol"] == symbol.upper():
                        for f in s.get("filters", []):
                            if f["filterType"] == "LOT_SIZE":
                                filters["lot_size"] = {
                                    "minQty": float(f["minQty"]),
                                    "maxQty": float(f["maxQty"]),
                                    "stepSize": float(f["stepSize"]),
                                }
                            elif f["filterType"] == "PRICE_FILTER":
                                filters["price_filter"] = {
                                    "minPrice": float(f["minPrice"]),
                                    "maxPrice": float(f["maxPrice"]),
                                    "tickSize": float(f["tickSize"]),
                                }
                        break
            return filters
        except Exception:
            return {}

    def _round_step_size(self, quantity: float, symbol: str,
                         side: str = "spot") -> float:
        """按 LOT_SIZE 精度处理数量"""
        filters = self._get_symbol_filters(symbol, side)
        lot = filters.get("lot_size", {})
        if lot:
            step = lot["stepSize"]
            # 四舍五入到 stepSize 的整数倍
            q = round(quantity / step) * step
            # 确保不小于 minQty
            q = max(q, lot["minQty"])
            return q
        # 默认精度
        return round(quantity, 6)

    def _round_price(self, price: float, symbol: str) -> float:
        """按 PRICE_FILTER 精度处理价格"""
        filters = self._get_symbol_filters(symbol, "spot")
        pf = filters.get("price_filter", {})
        if pf:
            tick = pf["tickSize"]
            return round(price / tick) * tick
        return round(price, 2)

    # ══════════════════════════════════════════
    # 异步批量请求 (提升效率)
    # ══════════════════════════════════════════

    async def fetch_spot_prices_async(self, symbols: List[str]) -> Dict[str, float]:
        """并发获取多个现货价格"""
        async with aiohttp.ClientSession() as session:
            tasks = []
            for sym in symbols:
                url = f"{self.spot_url}/api/v3/ticker/price"
                tasks.append(self._arequest(session, "GET", url,
                                            params={"symbol": sym.upper()}))
            results = await asyncio.gather(*tasks)
            return {
                sym.upper(): float(r.get("price", 0))
                for sym, r in zip(symbols, results)
            }


def create_client(level: str = "L1") -> BinanceClient:
    """创建客户端"""
    from .config import get_config
    config = get_config(level)
    api_key, secret_key = config.get_api_keys()
    return BinanceClient(api_key, secret_key, testnet=config.TESTNET)
