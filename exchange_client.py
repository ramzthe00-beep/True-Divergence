# -*- coding: utf-8 -*-
"""
exchange_client.py
=====================================================================
هر چیزی که به «صرافی» مربوط است: دریافت کندل (OHLCV)، اتصال/احراز هویت،
ثبت/به‌روزرسانی سفارش، استعلام موجودی و قیمت لحظه‌ای.

★ این فایل عمداً هیچ وابستگی‌ای به تلگرام ندارد — فقط نتیجه را برمی‌گرداند
یا Exception پرتاب می‌کند؛ اطلاع‌رسانی (تلگرام/لاگ) بر عهده‌ی main.py و
telegram_logger.py است. این جداسازی باعث می‌شود منطق صرافی مستقل و
قابل تست باشد.

★ منطق ورود/حجم/استاپ در اینجا «Pine-Exact» نیست و نباید باشد — طبق
درخواست صریح کاربر، تنها بخش‌هایی که باید عیناً با پاین یکی باشند
divergence_engine.py و ssl_hybrid.py هستند. اینجا صرفاً زیرساخت اجرای
معامله (که خودِ کاربر منطقش را جدا مدیریت می‌کند) پیاده شده است.
"""

import hashlib
import hmac
import time
import logging

import requests
import pandas as pd

logger = logging.getLogger("exchange")

# ─────────────────────────────────────────────────────────────────
# تنظیمات نمادها
# ─────────────────────────────────────────────────────────────────
TICK_SIZES = {"LTCUSDT": 0.01, "DOGEUSDT": 0.00001, "ETHUSDT": 0.01}
PRICE_PRECISION = {"LTCUSDT": 2, "DOGEUSDT": 5, "ETHUSDT": 2}
LEVERAGE_MAP = {"LTCUSDT": 75, "DOGEUSDT": 75, "ETHUSDT": 50}
SYMBOLS = ["LTCUSDT", "DOGEUSDT", "ETHUSDT"]


def round_price(price: float, symbol: str) -> float:
    tick = TICK_SIZES.get(symbol.upper(), 0.01)
    prec = PRICE_PRECISION.get(symbol.upper(), 2)
    return round(round(price / tick) * tick, prec)


# ═══════════════════════════════════════════════════════════════════
# دریافت داده
# ═══════════════════════════════════════════════════════════════════
class MarketData:
    def __init__(self, base_url: str):
        self.base_url = base_url

    def fetch_ohlcv(self, symbol: str, timeframe: str = "1m", limit: int = 5000):
        resolution_map = {"1m": "1", "5m": "5", "15m": "15", "30m": "30", "1h": "60", "4h": "240"}
        resolution = resolution_map.get(timeframe, "1")
        step_sec = {"1m": 60, "5m": 300, "15m": 900, "30m": 1800, "1h": 3600, "4h": 14400}.get(timeframe, 60)
        to_ts = int(time.time())
        from_ts = to_ts - limit * step_sec
        uri = (f"/futures/udf/history?symbol={symbol.upper()}&resolution={resolution}"
               f"&from={from_ts}&to={to_ts}&countback={limit}")
        try:
            r = requests.get(f"{self.base_url}{uri}", timeout=15)
            r.raise_for_status()
            data = r.json()
            if not data or data.get("s") != "ok":
                return None
            df = pd.DataFrame({
                "timestamp": pd.to_datetime(data["t"], unit="s", utc=True),
                "open": pd.to_numeric(data["o"]),
                "high": pd.to_numeric(data["h"]),
                "low": pd.to_numeric(data["l"]),
                "close": pd.to_numeric(data["c"]),
                "volume": pd.to_numeric(data["v"]),
            })
            df.set_index("timestamp", inplace=True)
            return df
        except Exception as e:
            logger.error(f"[FETCH] {symbol} ({timeframe}): {e}")
            return None

    def fetch_current_price(self, symbol: str):
        df = self.fetch_ohlcv(symbol, "1m", 2)
        if df is not None and not df.empty:
            return float(df["close"].iloc[-1])
        return None


# ═══════════════════════════════════════════════════════════════════
# اتصال خصوصی صرافی (سفارش/موجودی)
# ═══════════════════════════════════════════════════════════════════
class ExchangeError(Exception):
    def __init__(self, message, response=None):
        super().__init__(message)
        self.response = response


class PrivateExchange:
    def __init__(self, api_key: str, api_secret: str, base_url: str):
        self.api_key = api_key
        self.api_secret = api_secret
        self.base_url = base_url
        self.session = requests.Session()
        self.connected = False
        self._last_response = None

    def _sign(self, method, uri, ts):
        payload = f"{ts}{method.upper()}{uri}"
        return hmac.new(self.api_secret.encode(), payload.encode(), hashlib.sha256).hexdigest()

    def _request(self, method, uri, data=None):
        ts = str(int(time.time() * 1000))
        sig = self._sign(method, uri, ts)
        headers = {"X-API-Key": self.api_key, "X-Timestamp": ts,
                   "X-Signature": sig, "Content-Type": "application/json"}
        r = self.session.request(method, f"{self.base_url}{uri}", headers=headers, json=data, timeout=15)
        self._last_response = r
        if not r.ok:
            if r.status_code in (401, 403):
                self.connected = False
            raise ExchangeError(f"{method} {uri} -> {r.status_code}: {r.text[:300]}", response=r)
        self.connected = True
        return r.json()

    def test_connection(self) -> bool:
        try:
            self._request("GET", "/futures/positions")
            self.connected = True
            return True
        except Exception as e:
            self.connected = False
            logger.error(f"[CONN] {e}")
            return False

    def fetch_balance(self):
        try:
            data = self._request("GET", "/futures/assets")
            assets = data.get("assets", []) if isinstance(data, dict) else (data if isinstance(data, list) else [])
            for a in assets:
                if a.get("symbol") == "USDT":
                    return float(a.get("availableBalance", a.get("totalAssets", 0)))
            return 0.0
        except Exception as e:
            logger.error(f"[BALANCE] {e}")
            return None

    def create_order(self, symbol, side, capital, leverage, stop_loss=None, take_profit=None):
        """
        ثبت سفارش مارکت با SL/TP اختیاری. مقادیر SL/TP قبل از ارسال به تیکِ
        نماد رند می‌شوند؛ اگر بعد از رند صفر/نامعتبر شد، از بدنه حذف می‌شود
        تا خطای صرافی نگیریم.
        برمی‌گرداند: dict نتیجه صرافی، یا ExchangeError پرتاب می‌کند.
        """
        prec = PRICE_PRECISION.get(symbol.upper(), 2)
        order_data = {
            "symbol": symbol.upper(), "side": side.upper(), "tradeType": "MARKET",
            "leverage": int(leverage), "cost": f"{capital:.{prec}f}", "walletType": "debit",
        }
        if stop_loss is not None:
            rsl = round_price(stop_loss, symbol)
            if rsl and rsl > 0:
                order_data["stopLoss"] = f"{rsl:.{prec}f}"
        if take_profit is not None:
            rtp = round_price(take_profit, symbol)
            if rtp and rtp > 0:
                order_data["takeProfit"] = f"{rtp:.{prec}f}"

        try:
            result = self._request("POST", "/futures/positions", order_data)
            return {"order_data": order_data, "result": result,
                    "position_id": result.get("positionId") if isinstance(result, dict) else None}
        except ExchangeError:
            raise
        except Exception as e:
            raise ExchangeError(str(e))

    def update_position_sl(self, position_id, symbol, stop_loss, take_profit=None):
        """ریسک‌فری: جابه‌جایی حد ضرر یک پوزیشن باز به نقطه‌ی سر‌به‌سر."""
        prec = PRICE_PRECISION.get(symbol.upper(), 2)
        body = {
            "stopLoss": f"{round_price(stop_loss, symbol):.{prec}f}",
            "stopLossStrategy": "LATEST_PRICE",
            "stopLossOrderType": "STOP_MARKET",
        }
        if take_profit is not None:
            body["takeProfit"] = f"{round_price(take_profit, symbol):.{prec}f}"
        return self._request("PATCH", f"/futures/positions/{position_id}/tpsl", body)

