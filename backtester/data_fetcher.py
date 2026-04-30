"""
回测引擎 - 数据层
负责从 Binance 下载历史K线数据并缓存到本地
"""
import os
import time
import json
from datetime import datetime, timedelta
from typing import Dict, List, Optional
from collections import defaultdict


# 缓存目录
CACHE_DIR = os.path.join(os.path.dirname(__file__), ".cache")
os.makedirs(CACHE_DIR, exist_ok=True)


class DataFetcher:
    """历史数据获取器 (带本地缓存)"""

    # Binance API 端点 (不需要签名)
    SPOT_BASE = "https://api.binance.com/api/v3"
    FUTURES_BASE = "https://testnet.binancefuture.com/fapi/v1"

    def __init__(self, cache_dir: str = CACHE_DIR):
        self.cache_dir = cache_dir
        self._session = None

    def _get_session(self):
        if self._session is None:
            import requests
            self._session = requests.Session()
        return self._session

    def _cache_path(self, symbol: str, interval: str) -> str:
        return os.path.join(
            self.cache_dir,
            f"{symbol}_{interval}.json"
        )

    def _load_cache(self, symbol: str, interval: str) -> List:
        """加载本地缓存"""
        path = self._cache_path(symbol, interval)
        if os.path.exists(path):
            try:
                with open(path, "r") as f:
                    data = json.load(f)
                return data
            except Exception:
                pass
        return []

    def _save_cache(self, symbol: str, interval: str, data: List):
        """保存到本地缓存"""
        path = self._cache_path(symbol, interval)
        try:
            with open(path, "w") as f:
                json.dump(data, f)
        except Exception as e:
            print(f"[DataFetcher] 缓存写入失败: {e}")

    def _http_get(self, url: str, params: Dict) -> List:
        """发送 HTTP GET 请求"""
        try:
            session = self._get_session()
            resp = session.get(url, params=params, timeout=30)
            if resp.status_code == 200:
                return resp.json()
            else:
                print(f"[DataFetcher] HTTP {resp.status_code}: {resp.text[:100]}")
        except Exception as e:
            print(f"[DataFetcher] 请求失败: {e}")
        return []

    # ─── 现货 K 线数据 ───

    def fetch_spot_klines(self, symbol: str, interval: str = "1h",
                          start_time: Optional[int] = None,
                          end_time: Optional[int] = None,
                          limit: int = 1000) -> List:
        """
        获取现货K线数据 (自动分批，支持大量历史数据)
        返回: List[Dict] 每条记录 = {time, open, high, low, close, volume}
        """
        cache = self._load_cache(symbol, interval)

        # 如果没有指定时间范围，尝试加载缓存
        if start_time is None and end_time is None and cache:
            return cache

        # 转换时间
        if isinstance(start_time, str):
            start_time = int(
                datetime.strptime(start_time, "%Y-%m-%d").timestamp() * 1000
            )
        if isinstance(end_time, str):
            end_time = int(
                datetime.strptime(end_time, "%Y-%m-%d").timestamp() * 1000
            )

        all_klines = list(cache)
        existing_times = {k["time"] for k in all_klines}

        current_ts = start_time or (int(time.time() * 1000) - 365 * 24 * 3600 * 1000)
        end_ts = end_time or int(time.time() * 1000)

        while current_ts < end_ts:
            params = {
                "symbol": symbol.upper(),
                "interval": interval,
                "startTime": current_ts,
                "limit": limit,
            }
            if end_ts:
                params["endTime"] = end_ts

            klines = self._http_get(f"{self.SPOT_BASE}/klines", params)

            if not klines:
                break

            # 转换格式
            new_klines = []
            for k in klines:
                ts = int(k[0])
                if ts not in existing_times:
                    new_klines.append({
                        "time": ts,
                        "open": float(k[1]),
                        "high": float(k[2]),
                        "low": float(k[3]),
                        "close": float(k[4]),
                        "volume": float(k[5]),
                        "close_time": int(k[6]),
                    })
                    existing_times.add(ts)

            all_klines.extend(new_klines)
            current_ts = klines[-1][0] + 1

            if len(klines) < limit:
                break

            time.sleep(0.2)  # 避免限速

        # 去重并按时间排序
        all_klines.sort(key=lambda x: x["time"])

        # 保存缓存
        self._save_cache(symbol, interval, all_klines)

        return all_klines

    def fetch_futures_klines(self, symbol: str, interval: str = "1h",
                              start_time: Optional[int] = None,
                              end_time: Optional[int] = None,
                              limit: int = 1000) -> List:
        """获取合约K线数据"""
        cache_key = f"FUT_{symbol}_{interval}"
        cache = self._load_cache_from_path(
            os.path.join(self.cache_dir, f"{cache_key}.json")
        )

        if start_time is None and end_time is None and cache:
            return cache

        if isinstance(start_time, str):
            start_time = int(datetime.strptime(start_time, "%Y-%m-%d").timestamp() * 1000)
        if isinstance(end_time, str):
            end_time = int(datetime.strptime(end_time, "%Y-%m-%d").timestamp() * 1000)

        all_klines = list(cache)
        existing_times = {k["time"] for k in all_klines}

        current_ts = start_time or (int(time.time() * 1000) - 365 * 24 * 3600 * 1000)
        end_ts = end_time or int(time.time() * 1000)

        while current_ts < end_ts:
            params = {
                "symbol": symbol.upper(),
                "interval": interval,
                "startTime": current_ts,
                "limit": limit,
            }
            if end_ts:
                params["endTime"] = end_ts

            klines = self._http_get(f"{self.FUTURES_BASE}/klines", params)

            if not klines:
                break

            new_klines = []
            for k in klines:
                ts = int(k[0])
                if ts not in existing_times:
                    new_klines.append({
                        "time": ts,
                        "open": float(k[1]),
                        "high": float(k[2]),
                        "low": float(k[3]),
                        "close": float(k[4]),
                        "volume": float(k[5]),
                        "close_time": int(k[6]),
                    })
                    existing_times.add(ts)

            all_klines.extend(new_klines)
            current_ts = klines[-1][0] + 1

            if len(klines) < limit:
                break

            time.sleep(0.2)

        all_klines.sort(key=lambda x: x["time"])
        self._save_cache_to_path(
            os.path.join(self.cache_dir, f"{cache_key}.json"),
            all_klines
        )

        return all_klines

    def _load_cache_from_path(self, path: str) -> List:
        if os.path.exists(path):
            try:
                with open(path, "r") as f:
                    return json.load(f)
            except Exception:
                pass
        return []

    def _save_cache_to_path(self, path: str, data: List):
        try:
            with open(path, "w") as f:
                json.dump(data, f)
        except Exception as e:
            print(f"[DataFetcher] 缓存写入失败: {e}")


    # ─── 模拟数据生成 (网络不可用时的备选) ───

    @staticmethod
    def generate_synthetic_klines(symbol: str, interval: str = "1h",
                                  start_time: int = None,
                                  end_time: int = None,
                                  base_price: float = None,
                                  volatility: float = 0.02,
                                  trend: float = 0.0001) -> List:
        """
        生成模拟K线数据 (几何布朗运动)
        用于网络不可用时验证回测逻辑
        """
        import math
        import random

        price_map = {
            "BTCUSDT": 67000, "ETHUSDT": 3500,
            "BNBUSDT": 580, "SOLUSDT": 145,
        }
        base = base_price or price_map.get(symbol.upper(), 1000)

        interval_ms = {
            "1m": 60000, "5m": 300000, "15m": 900000,
            "30m": 1800000, "1h": 3600000, "4h": 14400000, "1d": 86400000,
        }.get(interval, 3600000)

        # 默认: 最近6个月
        end_ts = end_time or int(time.time() * 1000)
        start_ts = start_time or (end_ts - 180 * 24 * 3600 * 1000)

        klines = []
        price = base
        sigma = volatility

        ts = start_ts
        while ts <= end_ts:
            drift = (trend - 0.5 * sigma**2) * (interval_ms / 3600000)
            shock = sigma * math.sqrt(interval_ms / 3600000) * random.gauss(0, 1)
            price *= math.exp(drift + shock)

            rng = price * sigma * abs(random.gauss(0, 1))
            high_p = price + rng * random.random()
            low_p = price - rng * random.random()
            close_p = low_p + (high_p - low_p) * random.random()

            klines.append({
                "time": int(ts), "open": round(price, 2),
                "high": round(high_p, 2), "low": round(low_p, 2),
                "close": round(close_p, 2),
                "volume": round(random.uniform(100, 10000), 2),
                "close_time": int(ts + interval_ms - 1),
            })
            ts += interval_ms

        return klines


# ─── 快速数据预览 ───
if __name__ == "__main__":
    fetcher = DataFetcher()

    # 下载 BTCUSDT 最近 3 个月 1h 数据
    print("正在下载 BTCUSDT 1小时K线数据...")
    data = fetcher.fetch_spot_klines("BTCUSDT", "1h",
                                      start_time="2024-01-01",
                                      end_time="2025-04-01")
    print(f"数据量: {len(data)} 根K线")
    if data:
        print(f"时间范围: {datetime.fromtimestamp(data[0]['time']/1000)} -> "
              f"{datetime.fromtimestamp(data[-1]['time']/1000)}")
        print(f"示例数据: {data[-1]}")