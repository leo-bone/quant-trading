"""
Binance 客户端封装
支持现货和合约交易
"""
import time
import hmac
import hashlib
import requests
from typing import Dict, Optional, List
from .config import Config


class BinanceClient:
    """Binance API 客户端"""

    def __init__(self, api_key: str, secret_key: str, testnet: bool = True):
        self.api_key = api_key
        self.secret_key = secret_key
        self.testnet = testnet
        self.spot_url = Config.BASE_URL
        self.futures_url = Config.FUTURES_URL
        self.session = requests.Session()
        self.session.headers.update({"X-MBX-APIKEY": api_key})

    def _sign(self, params: Dict) -> str:
        """生成签名"""
        query = "&".join([f"{k}={v}" for k, v in params.items()])
        signature = hmac.new(
            self.secret_key.encode(),
            query.encode(),
            hashlib.sha256
        ).hexdigest()
        return signature

    def _request(self, method: str, url: str, signed: bool = False,
                 params: Optional[Dict] = None) -> Dict:
        """发送请求"""
        params = params or {}
        if signed:
            params["timestamp"] = int(time.time() * 1000)
            params["signature"] = self._sign(params)

        try:
            if method == "GET":
                response = self.session.get(url, params=params)
            else:
                response = self.session.post(url, data=params)

            result = response.json()
            if response.status_code != 200:
                print(f"API Error: {result}")
            return result
        except Exception as e:
            print(f"Request Error: {e}")
            return {}

    # ===== 现货交易 =====

    def get_spot_balance(self) -> Dict:
        """获取现货账户余额"""
        url = f"{self.spot_url}/api/v3/account"
        return self._request("GET", url, signed=True)

    def get_spot_price(self, symbol: str) -> float:
        """获取当前价格"""
        url = f"{self.spot_url}/api/v3/ticker/price"
        result = self._request("GET", url, params={"symbol": symbol.upper()})
        return float(result.get("price", 0))

    def get_klines(self, symbol: str, interval: str = "1h", limit: int = 100) -> List:
        """获取K线数据"""
        url = f"{self.spot_url}/api/v3/klines"
        return self._request("GET", url, params={
            "symbol": symbol.upper(),
            "interval": interval,
            "limit": limit
        })

    def spot_order(self, symbol: str, side: str, order_type: str,
                   quantity: float, price: Optional[float] = None) -> Dict:
        """现货下单"""
        url = f"{self.spot_url}/api/v3/order"
        params = {
            "symbol": symbol.upper(),
            "side": side.upper(),
            "type": order_type.upper(),
            "quantity": quantity
        }
        if price:
            params["price"] = price
            params["timeInForce"] = "GTC"
        return self._request("POST", url, signed=True, params=params)

    def get_spot_orders(self, symbol: str) -> List:
        """获取当前挂单"""
        url = f"{self.spot_url}/api/v3/openOrders"
        return self._request("GET", url, signed=True, params={"symbol": symbol.upper()})

    def cancel_order(self, symbol: str, order_id: int) -> Dict:
        """取消订单"""
        url = f"{self.spot_url}/api/v3/order"
        return self._request("DELETE", url, signed=True, params={
            "symbol": symbol.upper(),
            "orderId": order_id
        })

    # ===== 合约交易 =====

    def get_futures_balance(self) -> Dict:
        """获取合约账户余额(USDT)"""
        url = f"{self.futures_url}/fapi/v2/balance"
        return self._request("GET", url, signed=True)

    def futures_order(self, symbol: str, side: str, position_side: str,
                      order_type: str, quantity: float,
                      price: Optional[float] = None,
                      leverage: int = 1) -> Dict:
        """合约下单"""
        url = f"{self.futures_url}/fapi/v1/order"
        params = {
            "symbol": symbol.upper(),
            "side": side.upper(),
            "positionSide": position_side.upper(),
            "type": order_type.upper(),
            "quantity": quantity,
            "leverage": leverage
        }
        if price:
            params["price"] = price
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
        return self._request("GET", url, signed=True, params={"symbol": symbol.upper()})

    def get_futures_price(self, symbol: str) -> float:
        """获取合约价格"""
        url = f"{self.futures_url}/fapi/v1/ticker/price"
        result = self._request("GET", url, params={"symbol": symbol.upper()})
        return float(result.get("price", 0))


def create_client(level: str = "L1") -> BinanceClient:
    """创建客户端"""
    from .config import get_config
    config = get_config(level)
    api_key, secret_key = config.get_api_keys()
    return BinanceClient(api_key, secret_key, testnet=config.TESTNET)
