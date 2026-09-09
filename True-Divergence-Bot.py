# -*- coding: utf-8 -*-
"""
DTM v6 FC — Divergence + Golden/Death Cross Signal Bot   (نسخه ۵ — Binance + TrueTrade SL/TP)
====================================================================
+ دریافت داده از **بایننس** (جایگزین دِتروترید)
+ تبدیل داده‌ها به فرمت OHLCV (مطابق strategy_wrapper)
+ محاسبه استاپ/تارگت با منطق دقیق strategy_wrapper (R:R >= 2)
+ ریسک‌فری روی سطح ساختاری (structural_level)
====================================================================
"""

import os
import time
import threading
import hashlib
import hmac
import requests
import numpy as np
import pandas as pd
from datetime import datetime, timezone, timedelta
from flask import Flask
import json
import logging
import traceback
import math as _math

logging.basicConfig(
    level=logging.INFO,
    format='%(asctime)s - %(levelname)s - %(message)s',
    handlers=[logging.StreamHandler()]
)
logger = logging.getLogger(__name__)

# ============================================
# ★★★ API Configuration — بایننس ★★★
# ============================================
API_KEY = os.getenv("BINANCE_API_KEY")
API_SECRET = os.getenv("BINANCE_API_SECRET")
BASE_URL = "https://fapi.binance.com"  # فیوچرز

TELEGRAM_BOT_TOKEN = os.getenv("TELEGRAM_BOT_TOKEN")
TELEGRAM_CHAT_ID = os.getenv("TELEGRAM_CHAT_ID")

if not API_KEY or not API_SECRET:
    raise RuntimeError("BINANCE_API_KEY / BINANCE_API_SECRET باید به‌عنوان متغیر محیطی ست شوند.")
if not TELEGRAM_BOT_TOKEN or not TELEGRAM_CHAT_ID:
    raise RuntimeError("TELEGRAM_BOT_TOKEN / TELEGRAM_CHAT_ID باید به‌عنوان متغیر محیطی ست شوند.")

HISTORY_FILE = "trades_history_dtm_v6.json"
STATE_FILE = "pivot_state_dtm_v6.json"

# ============================================
# ★ Import SSL Hybrid با مدیریت خطا
# ============================================
SSL_AVAILABLE = False
SSL_ERROR = None
SSL_ERROR_DETAIL = None

try:
    import ssl_hybrid
    from ssl_hybrid import main as ssl_hybrid_indicator
    SSL_AVAILABLE = True
    logger.info("[SSL] ✅ ssl_hybrid.py loaded successfully")
except ImportError as e:
    SSL_AVAILABLE = False
    SSL_ERROR = "ImportError"
    SSL_ERROR_DETAIL = str(e)
    logger.error(f"[SSL] ❌ Failed to import ssl_hybrid.py: {e}")
except Exception as e:
    SSL_AVAILABLE = False
    SSL_ERROR = type(e).__name__
    SSL_ERROR_DETAIL = str(e)
    logger.error(f"[SSL] ❌ Error loading ssl_hybrid.py: {e}")

# ═══════════════════════════════════════════════════════════════
# ★ LIVE MODE
# ═══════════════════════════════════════════════════════════════
LIVE_MODE = True
HISTORY_BARS = 300
LOOKBACK_HOURS = 2

FIRST_RUN = True

def reset_state_for_live_mode():
    global SYMBOL_STATES, SIGNAL_COUNTER, FIRST_RUN
    SYMBOL_STATES = {s: SymbolState() for s in SYMBOLS}
    for f in [STATE_FILE, HISTORY_FILE]:
        if os.path.exists(f):
            os.remove(f)
            logger.info(f"[LIVE] Removed old file: {f}")
    SIGNAL_COUNTER = 0
    FIRST_RUN = True
    logger.info("[LIVE] Mode activated - processing only new data from now on")

# =====================================================================================
# هشتگ‌ها
# =====================================================================================
HASHTAGS = {
    "startup": "#Online",
    "diagnostic": "#Diagnostic",
    "signal": "#Signal",
    "log": "#Log",
    "alert": "#Alert",
    "pivot": "#Pivot",
    "target": "#Target",
    "stop": "#Stop",
    "daily": "#Daily",
    "monthly": "#Monthly",
    "order_request": "#OrderReq",
    "order_response": "#OrderOK",
    "order_error": "#OrderErr",
    "connection": "#Connected",
    "connection_change": "#Reconnected",
    "capital_reduced": "#LowCapital",
    "ssl_status": "#SSL",
}

# =====================================================================================
# ★★★ TICK_SIZES / PRICE_PRECISION — از strategy_wrapper (22).py ★★★
# =====================================================================================
SYMBOL_TICK_INFO = {
    "LTCUSDT":  {"mintick": 0.01,    "pricescale": 100,    "basecurrency": "LTC"},
    "DOGEUSDT": {"mintick": 0.00001, "pricescale": 100000, "basecurrency": "DOGE"},
    "ETHUSDT":  {"mintick": 0.01,    "pricescale": 100,    "basecurrency": "ETH"},
    "BNBUSDT":  {"mintick": 0.01,    "pricescale": 100,    "basecurrency": "BNB"},
}

TICK_SIZES = {sym: info["mintick"] for sym, info in SYMBOL_TICK_INFO.items()}
PRICE_PRECISION = {
    "LTCUSDT": 2,
    "DOGEUSDT": 5,
    "ETHUSDT": 2,
    "BNBUSDT": 2,
}
LEVERAGE_MAP = {"LTCUSDT": 75, "DOGEUSDT": 75, "ETHUSDT": 50, "BNBUSDT": 50}
TARGET_RISK_USDT = 3.5
SYMBOLS = ["LTCUSDT", "DOGEUSDT", "ETHUSDT", "BNBUSDT"]

# =====================================================================================
# ★★★ بلوک ۱ — ثابت‌ها (Pine-Exact) ★★★
# =====================================================================================
LEFT_BARS = 5
RIGHT_BARS = 2

RSI_LEN = 14
MACD_FAST, MACD_SLOW, MACD_SIGNAL = 12, 26, 9
ADX_LEN = 14
ADX_THRESHOLD = 20
ATR_LEN = 14

MA_FAST_LEN, MA_MID_LEN, MA_SLOW_LEN = 7, 25, 99

FIB_TOLERANCE_PCT = 1.5
MIN_CLASSIC_SCORE = 1

REQUIRE_PA_CONFIRMATION = False
WAIT_BARS_PA_CONFIRM = 3

APPLY_SSL_GATE_ON_LABELS = True

# ★★★ استاپ/تارگت — عیناً از strategy_wrapper (22).py ★★★
STOP_ATR_BUFFER = 0.1
TARGET_RR = 2.0  # حداقل R:R = 2 (مطابق strategy_wrapper)

SSL_TIMEFRAME = "5m"
SSL_BASELINE_LEN = 34
MAIN_TIMEFRAME = "1m"

CROSS_ATR_STOP_MULT = 2.0

MAX_CROSS_EMIT_LOOKBACK_BARS = 2

HISTORY_BARS = 5000
API_RETURNS_OPEN_CANDLE = False

APPLY_SSL_GATE = True
SSL_SINGLE_TF = True

MAX_HISTORICAL_PIVOTS = 20
MIN_BARS_BETWEEN_PIVOTS = 5
MAX_BARS_BETWEEN_PIVOTS = 80

# =====================================================================================
# ★★★ کلاس OHLCV (برای تطبیق با strategy_wrapper) ★★★
# =====================================================================================
class OHLCV:
    def __init__(self, timestamp, open, high, low, close, volume=0, is_closed=True):
        self.timestamp = timestamp
        self.open = float(open)
        self.high = float(high)
        self.low = float(low)
        self.close = float(close)
        self.volume = float(volume)
        self.is_closed = is_closed

# =====================================================================================
# ★★★ تابع محاسبه استاپ/تارگت — عیناً از strategy_wrapper (22).py ★★★
# =====================================================================================
def _valid_num(x):
    return x is not None and not (isinstance(x, float) and x != x)

def _is_na(x):
    return x is None or (isinstance(x, float) and _math.isnan(x))

def compute_stop_target_from_wrapper(candles, signal, last_values, mintick, buffer_ticks=2):
    """
    ★★★ عیناً از strategy_wrapper (22).py کپی شده ★★★
    
    استاپ/تارگت سفارشی — کاملاً مستقل از منطق واگرایی strategy.py.
    
    LONG:  استاپ = پایین‌ترین دره از ۲ دره واگرایی - بافر
           تارگت خام = بالاترین قله بین آن دو دره
           اگر R:R < 2 → تارگت بالا برده می‌شود تا R:R = 2
    
    SHORT: استاپ = بالاترین قله از ۲ قله واگرایی + بافر
           تارگت خام = پایین‌ترین دره بین آن دو قله
           اگر R:R < 2 → تارگت پایین برده می‌شود تا R:R = 2

    خروجی چهارم (structural_level):
        LONG → بالاترین قلهٔ بین دو دره | SHORT → پایین‌ترین درهٔ بین دو قله
        (فقط برای محاسبهٔ نقطهٔ ریسک فری استفاده می‌شود)
    """
    def _valid(x):
        return x is not None and not (isinstance(x, float) and _math.isnan(x))

    entry = last_values.get("entry")
    if not _valid(entry):
        return None, None, None, None

    buffer_abs = buffer_ticks * mintick

    if signal == "LONG":
        low1 = last_values.get("previous_pivot_low_price")
        low2 = last_values.get("pivot_low_price")
        bar1 = last_values.get("previous_pivot_low_index")
        bar2 = last_values.get("pivot_low_index")
        
        if not (_valid(low1) and _valid(low2) and _valid(bar1) and _valid(bar2)):
            logger.warning(f"[SL/TP] LONG: missing pivot data low1={low1} low2={low2} bar1={bar1} bar2={bar2}")
            return None, None, None, None

        stop = min(low1, low2) - buffer_abs

        lo, hi = sorted((int(bar1), int(bar2)))
        lo, hi = max(lo, 0), min(hi, len(candles) - 1)
        if hi < lo:
            return None, None, None, None
        
        # پیدا کردن بالاترین قله بین دو دره
        mid_peak = max(c.high for c in candles[lo:hi + 1])

        risk = entry - stop
        if risk <= 0:
            return None, None, None, None

        rr = (mid_peak - entry) / risk
        target = mid_peak if rr >= 2 else entry + 2 * risk
        return stop, target, max(rr, 2.0), mid_peak

    elif signal == "SHORT":
        high1 = last_values.get("previous_pivot_high_price")
        high2 = last_values.get("pivot_high_price")
        bar1 = last_values.get("previous_pivot_high_index")
        bar2 = last_values.get("pivot_high_index")
        
        if not (_valid(high1) and _valid(high2) and _valid(bar1) and _valid(bar2)):
            logger.warning(f"[SL/TP] SHORT: missing pivot data high1={high1} high2={high2} bar1={bar1} bar2={bar2}")
            return None, None, None, None

        stop = max(high1, high2) + buffer_abs

        lo, hi = sorted((int(bar1), int(bar2)))
        lo, hi = max(lo, 0), min(hi, len(candles) - 1)
        if hi < lo:
            return None, None, None, None
        
        # پیدا کردن پایین‌ترین دره بین دو قله
        mid_trough = min(c.low for c in candles[lo:hi + 1])

        risk = stop - entry
        if risk <= 0:
            return None, None, None, None

        rr = (entry - mid_trough) / risk
        target = mid_trough if rr >= 2 else entry - 2 * risk
        return stop, target, max(rr, 2.0), mid_trough

    return None, None, None, None

def compute_risk_free_pct(entry, stop_price, structural_level, signal):
    """
    ★★★ محاسبه نقطه ریسک‌فری — عیناً از strategy_wrapper ★★★
    """
    if structural_level is None or stop_price is None or not _valid_num(entry) or entry <= 0:
        return None
    
    risk_abs = abs(entry - stop_price)
    risk_pct = risk_abs / entry
    
    if signal == "LONG":
        struct_pct = (structural_level - entry) / entry
        return max(struct_pct, risk_pct)
    else:  # SHORT
        struct_pct = (entry - structural_level) / entry
        return -max(struct_pct, risk_pct)

# =====================================================================================
# ★★★ کلاس دریافت داده از بایننس ★★★
# =====================================================================================
class BinanceData:
    def __init__(self):
        self.base_url = BASE_URL

    def fetch_ohlcv(self, symbol, timeframe='1m', limit=HISTORY_BARS):
        """دریافت کندل از بایننس فیوچرز و تبدیل به لیست OHLCV (مطابق strategy_wrapper)"""
        symbol_clean = symbol.upper()
        resolution_map = {"1m": "1m", "5m": "5m", "15m": "15m", "30m": "30m", "1h": "1h", "4h": "4h"}
        interval = resolution_map.get(timeframe, "1m")
        
        uri = f"/futures/klines?symbol={symbol_clean}&interval={interval}&limit={limit}"
        
        try:
            response = requests.get(f"{self.base_url}{uri}", timeout=15)
            response.raise_for_status()
            data = response.json()
            
            if not data:
                return None
            
            # ★★★ تبدیل به لیست OHLCV (مطابق strategy_wrapper) ★★★
            candles = []
            for d in data:
                candles.append(
                    OHLCV(
                        timestamp=int(d[0]),  # میلی‌ثانیه
                        open=float(d[1]),
                        high=float(d[2]),
                        low=float(d[3]),
                        close=float(d[4]),
                        volume=float(d[5]),
                        is_closed=True,
                    )
                )
            
            # همچنین دیتافریم برای محاسبات اندیکاتورها
            df = pd.DataFrame({
                'timestamp': pd.to_datetime([d[0] for d in data], unit='ms', utc=True),
                'open': pd.to_numeric([d[1] for d in data]),
                'high': pd.to_numeric([d[2] for d in data]),
                'low': pd.to_numeric([d[3] for d in data]),
                'close': pd.to_numeric([d[4] for d in data]),
                'volume': pd.to_numeric([d[5] for d in data])
            })
            df.set_index('timestamp', inplace=True)
            
            return df, candles
        except Exception as e:
            logger.error(f"[FETCH ERROR] {symbol} ({timeframe}): {e}")
            return None, None

    def fetch_current_price(self, symbol):
        try:
            df, _ = self.fetch_ohlcv(symbol, '1m', 2)
            if df is not None and not df.empty:
                return float(df['close'].iloc[-1])
        except:
            pass
        return None

# =====================================================================================
# ★★★ کلاس صرافی بایننس ★★★
# =====================================================================================
class BinancePrivateExchange:
    def __init__(self, api_key, api_secret, base_url=BASE_URL):
        self.api_key = api_key
        self.api_secret = api_secret
        self.base_url = base_url
        self.session = requests.Session()
        self.connected = False
        self._last_response = None

    def _sign_request(self, method, uri, params=None, body=None):
        timestamp = int(time.time() * 1000)
        query_string = ""
        if params:
            query_string = "&".join([f"{k}={v}" for k, v in sorted(params.items())])
        if body:
            body_str = json.dumps(body)
            query_string = query_string + "&" + body_str if query_string else body_str
        
        signature_payload = f"{query_string}&timestamp={timestamp}" if query_string else f"timestamp={timestamp}"
        signature = hmac.new(self.api_secret.encode(), signature_payload.encode(), hashlib.sha256).hexdigest()
        
        if params is None:
            params = {}
        params['timestamp'] = timestamp
        params['signature'] = signature
        return params

    def _request(self, method, uri, params=None, body=None):
        params = self._sign_request(method, uri, params, body)
        headers = {
            "X-MBX-APIKEY": self.api_key,
            "Content-Type": "application/json"
        }
        
        url = f"{self.base_url}{uri}"
        response = self.session.request(method, url, headers=headers, params=params, json=body, timeout=15)
        self._last_response = response
        
        if not response.ok:
            if response.status_code in [401, 403]:
                self.connected = False
            logger.error(f"[EXCHANGE ERROR] {method} {uri} | {response.status_code} | {response.text[:300]}")
            response.raise_for_status()
        else:
            self.connected = True
        return response.json()

    def test_connection(self):
        try:
            self._request('GET', '/futures/v2/account')
            self.connected = True
            return True
        except Exception as e:
            self.connected = False
            logger.error(f"[EXCHANGE] اتصال برقرار نیست: {e}")
            return False

    def fetch_balance(self):
        try:
            data = self._request('GET', '/futures/v2/account')
            assets = data.get('assets', [])
            for asset in assets:
                if asset.get('asset') == 'USDT':
                    return float(asset.get('walletBalance', 0))
            return 0
        except:
            return None

    def _round_price(self, price, symbol):
        return round_price(price, symbol)

    def _round_quantity(self, quantity, symbol):
        """گرد کردن تعداد برای بایننس"""
        qty_prec = self._get_quantity_precision(symbol)
        return round(quantity, qty_prec)
    
    def _get_quantity_precision(self, symbol):
        """دریافت دقت تعداد از بایننس"""
        try:
            info = self._request('GET', '/futures/v1/exchangeInfo')
            for s in info.get('symbols', []):
                if s.get('symbol') == symbol.upper():
                    for f in s.get('filters', []):
                        if f.get('filterType') == 'LOT_SIZE':
                            step = float(f.get('stepSize'))
                            return int(round(-_math.log10(step)))
            return 3
        except:
            return 3

    def fetch_price(self, symbol):
        try:
            data = self._request('GET', f'/futures/v1/ticker/price', params={'symbol': symbol.upper()})
            return float(data.get('price', 0))
        except:
            return None

    def _set_sl_tp(self, symbol, order_id, side, quantity, stop_loss, take_profit):
        """تنظیم حد ضرر و حد سود برای بایننس"""
        symbol_u = symbol.upper()
        prec = PRICE_PRECISION.get(symbol_u, 2)
        qty_prec = self._get_quantity_precision(symbol_u)
        
        # حد ضرر
        sl_params = {
            'symbol': symbol_u,
            'side': 'SELL' if side.upper() == 'BUY' else 'BUY',
            'type': 'STOP_MARKET',
            'stopPrice': f"{round_price(stop_loss, symbol_u):.{prec}f}",
            'quantity': f"{round(quantity, qty_prec):.{qty_prec}f}",
            'workingType': 'MARK_PRICE'
        }
        try:
            self._request('POST', '/futures/v1/order', body=sl_params)
            logger.info(f"[SL] {symbol_u} Stop Loss set at {stop_loss}")
        except Exception as e:
            logger.error(f"[SL] Error setting stop loss: {e}")
        
        # حد سود
        tp_params = {
            'symbol': symbol_u,
            'side': 'SELL' if side.upper() == 'BUY' else 'BUY',
            'type': 'TAKE_PROFIT_MARKET',
            'stopPrice': f"{round_price(take_profit, symbol_u):.{prec}f}",
            'quantity': f"{round(quantity, qty_prec):.{qty_prec}f}",
            'workingType': 'MARK_PRICE'
        }
        try:
            self._request('POST', '/futures/v1/order', body=tp_params)
            logger.info(f"[TP] {symbol_u} Take Profit set at {take_profit}")
        except Exception as e:
            logger.error(f"[TP] Error setting take profit: {e}")

    def create_order(self, symbol, order_type, side, capital, price=None, params=None):
        """ثبت سفارش در بایننس فیوچرز"""
        symbol_u = symbol.upper()
        prec = PRICE_PRECISION.get(symbol_u, 2)
        qty_prec = self._get_quantity_precision(symbol_u)
        
        # تنظیم اهرم
        leverage = params.get('leverage', 1) if params else 1
        try:
            self._request('POST', f'/futures/v1/leverage', params={'symbol': symbol_u, 'leverage': leverage})
        except:
            pass
        
        # دریافت قیمت فعلی
        current_price = price or self.fetch_price(symbol_u)
        if not current_price:
            raise ValueError(f"نمی‌توان قیمت {symbol_u} را دریافت کرد")
        
        quantity = (capital * leverage) / current_price
        quantity = self._round_quantity(quantity, symbol_u)
        
        order_data = {
            'symbol': symbol_u,
            'side': side.upper(),
            'type': 'MARKET',
            'quantity': f"{round(quantity, qty_prec):.{qty_prec}f}"
        }
        
        # ثبت سفارش اصلی
        result = self._request('POST', '/futures/v1/order', body=order_data)
        position_id = result.get('orderId')
        
        # ثبت SL/TP
        stop_loss = params.get('stopLoss') if params else None
        take_profit = params.get('takeProfit') if params else None
        if stop_loss and take_profit:
            self._set_sl_tp(symbol_u, position_id, side, quantity, stop_loss, take_profit)
        
        logger.info(f"[ORDER SUCCESS] {symbol_u} {side} | OrderId: {position_id}")
        return {'id': position_id, 'symbol': symbol_u, 'side': side}

    def update_position_sl(self, position_id, symbol, stop_loss, take_profit=None):
        """
        🛡️ ریسک‌فری: جابه‌جایی حد ضرر یک پوزیشن باز روی صرافی
        """
        symbol_u = symbol.upper()
        prec = PRICE_PRECISION.get(symbol_u, 2)
        
        # بایننس برای بروزرسانی SL/TP باید سفارش جدید ثبت کند و قدیمی را کنسل کند
        try:
            # دریافت لیست سفارشات باز
            orders = self._request('GET', '/futures/v1/openOrders', params={'symbol': symbol_u})
            
            for order in orders:
                if order.get('type') in ['STOP_MARKET', 'TAKE_PROFIT_MARKET']:
                    self._request('DELETE', '/futures/v1/order', params={
                        'symbol': symbol_u,
                        'orderId': order.get('orderId')
                    })
            
            # ثبت استاپ جدید
            if take_profit:
                self._set_sl_tp(symbol_u, position_id, 'BUY', 0, stop_loss, take_profit)
            else:
                # فقط استاپ
                sl_params = {
                    'symbol': symbol_u,
                    'side': 'SELL',
                    'type': 'STOP_MARKET',
                    'stopPrice': f"{round_price(stop_loss, symbol_u):.{prec}f}",
                    'quantity': '0',  # مقدار از پوزیشن گرفته می‌شود
                    'workingType': 'MARK_PRICE'
                }
                self._request('POST', '/futures/v1/order', body=sl_params)
            
            logger.info(f"[RISK-FREE] {symbol_u}: Stop Loss moved to {stop_loss}")
            return {'status': 'success'}
        except Exception as e:
            logger.error(f"[RISK-FREE] Error updating SL: {e}")
            raise

# =====================================================================================
# توابع تلگرام
# =====================================================================================
def _send_telegram_single(text: str) -> bool:
    url = f"https://api.telegram.org/bot{TELEGRAM_BOT_TOKEN}/sendMessage"
    max_attempts = 3
    for attempt in range(max_attempts):
        try:
            r = requests.post(
                url,
                json={"chat_id": TELEGRAM_CHAT_ID, "text": str(text), "parse_mode": "Markdown"},
                timeout=30
            )
            if r.status_code == 429:
                try:
                    retry_after = r.json().get("parameters", {}).get("retry_after", 10)
                except Exception:
                    retry_after = 10
                if attempt == max_attempts - 1:
                    return False
                wait = min(retry_after + 2, 30)
                logger.warning(f"[TELEGRAM] Rate limit — retry در {wait}s")
                time.sleep(wait)
                continue
            if r.status_code == 200:
                return True
            if r.status_code == 400 and attempt == 0:
                try:
                    r2 = requests.post(url, json={"chat_id": TELEGRAM_CHAT_ID, "text": str(text)}, timeout=30)
                    if r2.status_code == 200:
                        return True
                except Exception:
                    pass
            return False
        except Exception as e:
            logger.error(f"[TELEGRAM] Exception: {e}")
            if attempt == max_attempts - 1:
                return False
            time.sleep(2 ** attempt)
    return False

def send_telegram_message(message: str) -> bool:
    text = str(message)
    if len(text) <= 4000:
        return _send_telegram_single(text)
    parts = [text[i:i + 4000] for i in range(0, len(text), 4000)]
    ok = True
    for part in parts:
        ok = _send_telegram_single(part) and ok
        time.sleep(1.0)
    return ok

send_telegram = send_telegram_message

IRAN_TZ = timezone(timedelta(hours=3, minutes=30))

def format_iran_time(dt=None):
    if dt is None:
        dt = datetime.now(IRAN_TZ)
    else:
        if isinstance(dt, pd.Timestamp):
            dt = dt.to_pydatetime()
        if dt.tzinfo is None:
            dt = dt.replace(tzinfo=timezone.utc)
        dt = dt.astimezone(IRAN_TZ)
    return dt.strftime('%Y-%m-%d %H:%M:%S')

def format_iran_date(dt=None):
    if dt is None:
        dt = datetime.now(IRAN_TZ)
    return dt.strftime('%Y-%m-%d')

def round_price(price, symbol):
    tick = TICK_SIZES.get(symbol.upper(), 0.01)
    precision = PRICE_PRECISION.get(symbol.upper(), 2)
    return round(round(price / tick) * tick, precision)

# =====================================================================================
# توابع محاسباتی پایه (Pine-Exact)
# =====================================================================================
def calc_rma(series, length):
    n = len(series)
    rma = pd.Series(np.nan, index=series.index)
    if n == 0:
        return rma
    alpha = 1.0 / length
    vals = series.to_numpy(dtype=float)
    leading_na = 0
    while leading_na < n and np.isnan(vals[leading_na]):
        leading_na += 1
    seed_idx = leading_na + length - 1
    if seed_idx >= n:
        return rma
    prev = vals[seed_idx - length + 1: seed_idx + 1].mean()
    rma.iloc[seed_idx] = prev
    for i in range(seed_idx + 1, n):
        prev = alpha * vals[i] + (1 - alpha) * prev
        rma.iloc[i] = prev
    return rma

def calc_ema(series, length):
    alpha = 2.0 / (length + 1)
    ema = pd.Series(np.nan, index=series.index)
    if len(series) == 0:
        return ema
    first_valid = series.first_valid_index()
    if first_valid is None:
        return ema
    start_pos = series.index.get_loc(first_valid)
    ema.iloc[start_pos] = series.iloc[start_pos]
    prev = ema.iloc[start_pos]
    for i in range(start_pos + 1, len(series)):
        prev = alpha * series.iloc[i] + (1 - alpha) * prev
        ema.iloc[i] = prev
    return ema

def calc_rsi(close, length=14):
    delta = close.diff()
    gain = delta.clip(lower=0)
    loss = -delta.clip(upper=0)
    avg_gain = calc_rma(gain, length)
    avg_loss = calc_rma(loss, length)
    rsi = pd.Series(np.nan, index=close.index)
    for i in range(len(close)):
        ag = avg_gain.iloc[i]
        al = avg_loss.iloc[i]
        if pd.isna(ag) or pd.isna(al):
            continue
        if al == 0:
            rsi.iloc[i] = 100.0
        elif ag == 0:
            rsi.iloc[i] = 0.0
        else:
            rsi.iloc[i] = 100.0 - (100.0 / (1.0 + ag / al))
    return rsi

def calc_macd(close, fast=12, slow=26, signal=9):
    ema_fast = calc_ema(close, fast)
    ema_slow = calc_ema(close, slow)
    macd_line = ema_fast - ema_slow
    signal_line = calc_ema(macd_line, signal)
    return macd_line, signal_line, macd_line - signal_line

def calc_atr(high, low, close, length=14):
    prev_close = close.shift(1)
    tr = pd.concat([high-low, (high-prev_close).abs(), (low-prev_close).abs()], axis=1).max(axis=1)
    return calc_rma(tr, length)

def calc_adx(high, low, close, length=14):
    up_move = high.diff()
    down_move = -low.diff()
    plus_dm = pd.Series(np.where((up_move > down_move) & (up_move > 0), up_move, 0.0), index=high.index)
    minus_dm = pd.Series(np.where((down_move > up_move) & (down_move > 0), down_move, 0.0), index=high.index)
    prev_close = close.shift(1)
    tr = pd.concat([high-low, (high-prev_close).abs(), (low-prev_close).abs()], axis=1).max(axis=1)
    atr_ = calc_rma(tr, length)
    plus_di = 100 * (calc_rma(plus_dm, length) / atr_.replace(0, np.nan))
    minus_di = 100 * (calc_rma(minus_dm, length) / atr_.replace(0, np.nan))
    dx = 100 * (plus_di - minus_di).abs() / (plus_di + minus_di).replace(0, np.nan)
    adx = calc_rma(dx, length)
    return adx

def calc_wma(series, length):
    weights = np.arange(1, length + 1)
    return series.rolling(length).apply(lambda x: np.dot(x, weights) / weights.sum(), raw=True)

def calc_hma(series, length):
    half = max(1, int(length / 2))
    sqrt_len = max(1, int(round(np.sqrt(length))))
    diff = 2 * calc_wma(series, half) - calc_wma(series, length)
    return calc_wma(diff, sqrt_len)

def find_pivot_high(high, left=LEFT_BARS, right=RIGHT_BARS):
    n = len(high)
    result = pd.Series(np.nan, index=high.index)
    for i in range(left, n - right):
        if not (high.iloc[i-left:i] >= high.iloc[i]).any() and not (high.iloc[i+1:i+right+1] >= high.iloc[i]).any():
            result.iloc[i] = high.iloc[i]
    return result

def find_pivot_low(low, left=LEFT_BARS, right=RIGHT_BARS):
    n = len(low)
    result = pd.Series(np.nan, index=low.index)
    for i in range(left, n - right):
        if not (low.iloc[i-left:i] <= low.iloc[i]).any() and not (low.iloc[i+1:i+right+1] <= low.iloc[i]).any():
            result.iloc[i] = low.iloc[i]
    return result

def resolve_bar_from_ts(df_indexed, ts):
    if ts is None or df_indexed is None or df_indexed.empty:
        return None
    if not isinstance(ts, pd.Timestamp):
        ts = pd.Timestamp(ts)
    if hasattr(df_indexed.index, 'tz') and df_indexed.index.tz is not None:
        if ts.tzinfo is None:
            ts = ts.tz_localize(df_indexed.index.tz)
        else:
            ts = ts.tz_convert(df_indexed.index.tz)
    else:
        if ts.tzinfo is not None:
            ts = ts.tz_localize(None)
    if ts in df_indexed.index:
        loc = df_indexed.index.get_loc(ts)
        if isinstance(loc, slice):
            return loc.start
        elif isinstance(loc, np.ndarray):
            return int(np.where(loc)[0][0])
        return int(loc)
    time_diffs = (df_indexed.index - ts).abs()
    min_diff = time_diffs.min()
    if min_diff <= pd.Timedelta(minutes=3):
        return int(time_diffs.argmin())
    return None

# =====================================================================================
# ★ فیلتر روند SSL Hybrid
# =====================================================================================
def compute_ssl_hlv(df_5m):
    global SSL_AVAILABLE, SSL_ERROR, SSL_ERROR_DETAIL
    
    if df_5m is None or len(df_5m) < SSL_BASELINE_LEN + 5:
        return None
    
    if not SSL_AVAILABLE:
        error_msg = (
            f"❌ *SSL Hybrid غیرفعال است* {HASHTAGS['ssl_status']}\n"
            f"━━━━━━━━━━━━━━━━━━━━━━\n"
            f"📌 وضعیت: **غیرفعال**\n"
            f"🔴 خطا: `{SSL_ERROR}`\n"
            f"📝 جزئیات: `{SSL_ERROR_DETAIL}`\n"
            f"━━━━━━━━━━━━━━━━━━━━━━\n"
            f"⚠️ به دلیل این خطا، **هیچ سیگنالی** از ربات ارسال نمی‌شود.\n"
            f"🛠️ برای رفع مشکل، فایل `ssl_hybrid.py` را بررسی کنید.\n"
            f"🕒 {format_iran_time()}"
        )
        logger.error(f"[SSL] {error_msg}")
        send_telegram_message(error_msg)
        return None
    
    try:
        data = {
            'open': df_5m['open'].values,
            'high': df_5m['high'].values,
            'low': df_5m['low'].values,
            'close': df_5m['close'].values,
            'volume': df_5m['volume'].values if 'volume' in df_5m else None
        }
        result = ssl_hybrid_indicator(data)
        hlv = result.get('hlv')
        
        if hlv is not None and len(hlv) > 0:
            last_hlv = hlv[-1] if hasattr(hlv, '__getitem__') else hlv
            if last_hlv == 1:
                return 1
            elif last_hlv == -1:
                return -1
            else:
                return 0
        
        error_msg = (
            f"⚠️ *SSL Hybrid مقدار نامعتبر برگرداند* {HASHTAGS['ssl_status']}\n"
            f"━━━━━━━━━━━━━━━━━━━━━━\n"
            f"📌 وضعیت: **خطا در محاسبه**\n"
            f"🔴 hlv مقدار: `{hlv}`\n"
            f"━━━━━━━━━━━━━━━━━━━━━━\n"
            f"⚠️ به دلیل این خطا، **هیچ سیگنالی** از ربات ارسال نمی‌شود.\n"
            f"🕒 {format_iran_time()}"
        )
        logger.error(f"[SSL] {error_msg}")
        send_telegram_message(error_msg)
        return None
        
    except Exception as e:
        tb = traceback.format_exc()
        SSL_ERROR = type(e).__name__
        SSL_ERROR_DETAIL = str(e)
        SSL_AVAILABLE = False
        
        error_msg = (
            f"❌ *SSL Hybrid خطا داد* {HASHTAGS['ssl_status']}\n"
            f"━━━━━━━━━━━━━━━━━━━━━━\n"
            f"📌 وضعیت: **غیرفعال**\n"
            f"🔴 نوع خطا: `{type(e).__name__}`\n"
            f"📝 پیام خطا: `{str(e)}`\n"
            f"━━━━━━━━━━━━━━━━━━━━━━\n"
            f"📋 **Traceback:**\n"
            f"```\n{tb[:1500]}\n```\n"
            f"━━━━━━━━━━━━━━━━━━━━━━\n"
            f"⚠️ به دلیل این خطا، **هیچ سیگنالی** از ربات ارسال نمی‌شود.\n"
            f"🛠️ لطفاً فایل `ssl_hybrid.py` را بررسی و اصلاح کنید.\n"
            f"🕒 {format_iran_time()}"
        )
        logger.error(f"[SSL] {error_msg}")
        send_telegram_message(error_msg)
        return None

def compute_ssl_hlv_series(df_5m):
    global SSL_AVAILABLE
    if df_5m is None or len(df_5m) < SSL_BASELINE_LEN + 5 or not SSL_AVAILABLE:
        return None, None
    try:
        data = {
            'open': df_5m['open'].values,
            'high': df_5m['high'].values,
            'low': df_5m['low'].values,
            'close': df_5m['close'].values,
            'volume': df_5m['volume'].values if 'volume' in df_5m else None
        }
        result = ssl_hybrid_indicator(data)
        hlv = result.get('hlv')
        if hlv is None or not hasattr(hlv, '__len__'):
            return None, None
        return df_5m.index, np.asarray(hlv)
    except Exception as e:
        logger.error(f"[SSL-SERIES] Error: {e}")
        return None, None

def get_hlv_at_ts(hlv_index, hlv_array, event_ts):
    if hlv_index is None or hlv_array is None or event_ts is None:
        return None
    ts = pd.Timestamp(event_ts)
    if ts.tzinfo is None:
        ts = ts.tz_localize('UTC')
    else:
        ts = ts.tz_convert('UTC')
    pos = hlv_index.searchsorted(ts, side='right') - 1
    if pos < 0 or pos >= len(hlv_array):
        return None
    val = hlv_array[pos]
    if pd.isna(val):
        return None
    return int(val)

def compute_ssl_hybrid_status():
    if SSL_AVAILABLE:
        return (
            f"✅ *SSL Hybrid فعال است* {HASHTAGS['ssl_status']}\n"
            f"━━━━━━━━━━━━━━━━━━━━━━\n"
            f"📌 وضعیت: **فعال**\n"
            f"🟢 فایل `ssl_hybrid.py` با موفقیت بارگذاری شد.\n"
            f"🔄 سیگنال‌دهی با فیلتر SSL Hybrid انجام می‌شود.\n"
            f"━━━━━━━━━━━━━━━━━━━━━━\n"
            f"🕒 {format_iran_time()}"
        )
    else:
        return (
            f"❌ *SSL Hybrid غیرفعال است* {HASHTAGS['ssl_status']}\n"
            f"━━━━━━━━━━━━━━━━━━━━━━\n"
            f"📌 وضعیت: **غیرفعال**\n"
            f"🔴 خطا: `{SSL_ERROR}`\n"
            f"📝 جزئیات: `{SSL_ERROR_DETAIL}`\n"
            f"━━━━━━━━━━━━━━━━━━━━━━\n"
            f"⚠️ به دلیل این خطا، **هیچ سیگنالی** از ربات ارسال نمی‌شود.\n"
            f"🛠️ برای رفع مشکل، فایل `ssl_hybrid.py` را بررسی کنید.\n"
            f"🕒 {format_iran_time()}"
        )

# =====================================================================================
# فیبوناچی
# =====================================================================================
def check_fib_near(high_series, low_series, confirm_bar, target_price, is_high_side, tol_pct=FIB_TOLERANCE_PCT):
    if confirm_bar is None or confirm_bar < 0:
        return False
    lookback = RIGHT_BARS + 50
    start = max(0, confirm_bar - lookback + 1)
    window_high = high_series.iloc[start:confirm_bar + 1]
    window_low = low_series.iloc[start:confirm_bar + 1]
    if window_high.empty or window_low.empty:
        return False
    sw_hi = window_high.max()
    sw_lo = window_low.min()
    fib_rng = sw_hi - sw_lo
    tol = tol_pct / 100.0
    if is_high_side:
        fib618 = sw_lo + fib_rng * 0.618
        fib786 = sw_lo + fib_rng * 0.786
    else:
        fib618 = sw_hi - fib_rng * 0.618
        fib786 = sw_hi - fib_rng * 0.786
    near618 = fib618 > 0 and abs(target_price - fib618) / fib618 <= tol
    near786 = fib786 > 0 and abs(target_price - fib786) / fib786 <= tol
    return near618 or near786

def check_shooting_star(df, pivot_bar):
    if pivot_bar is None or pivot_bar < 0 or pivot_bar >= len(df):
        return False
    row = df.iloc[pivot_bar]
    body = abs(row['close'] - row['open'])
    w_top = row['high'] - max(row['close'], row['open'])
    w_bot = min(row['close'], row['open']) - row['low']
    rng = row['high'] - row['low']
    return rng > 0 and w_top >= body * 2.0 and w_top >= w_bot * 2.0 and body < rng * 0.4

def check_hammer(df, pivot_bar):
    if pivot_bar is None or pivot_bar < 0 or pivot_bar >= len(df):
        return False
    row = df.iloc[pivot_bar]
    body = abs(row['close'] - row['open'])
    w_top = row['high'] - max(row['close'], row['open'])
    w_bot = min(row['close'], row['open']) - row['low']
    rng = row['high'] - row['low']
    return rng > 0 and w_bot >= body * 2.0 and w_bot >= w_top * 2.0 and body < rng * 0.4

# =====================================================================================
# کلاس وضعیت (با state persistence)
# =====================================================================================
class SymbolState:
    def __init__(self):
        self.pivot_highs = []
        self.pivot_lows = []
        self.last_processed_ts = None
        self.rst_l = False
        self.rst_s = False
        self.last_ma_ts = None
        self.telegram_log_count = 0
        self.last_telegram_log_time = 0
        self.pending_bull_divs = []
        self.pending_bear_divs = []

    def to_dict(self):
        def _pending_to_dict(lst):
            out = []
            for c in lst:
                cc = dict(c)
                cc['confirm_start_ts'] = str(c['confirm_start_ts'])
                cc['deadline_ts'] = str(c['deadline_ts'])
                out.append(cc)
            return out

        return {
            'pivot_highs': [{'ts': str(p['ts']), 'price': p['price'],
                           'rsi': p.get('rsi', 0), 'macdline': p.get('macdline', 0),
                           'hist': p.get('hist', 0), 'bar': p.get('bar', 0)}
                          for p in self.pivot_highs[-200:]],
            'pivot_lows': [{'ts': str(p['ts']), 'price': p['price'],
                          'rsi': p.get('rsi', 0), 'macdline': p.get('macdline', 0),
                          'hist': p.get('hist', 0), 'bar': p.get('bar', 0)}
                         for p in self.pivot_lows[-200:]],
            'last_processed_ts': str(self.last_processed_ts) if self.last_processed_ts else None,
            'rst_l': self.rst_l,
            'rst_s': self.rst_s,
            'last_ma_ts': str(self.last_ma_ts) if self.last_ma_ts else None,
            'telegram_log_count': self.telegram_log_count,
            'last_telegram_log_time': self.last_telegram_log_time,
            'pending_bull_divs': _pending_to_dict(self.pending_bull_divs),
            'pending_bear_divs': _pending_to_dict(self.pending_bear_divs),
        }

    @classmethod
    def from_dict(cls, data):
        state = cls()
        if data:
            state.pivot_highs = [{'ts': pd.Timestamp(p['ts']), 'price': p['price'],
                                 'rsi': p.get('rsi', 0), 'macdline': p.get('macdline', 0),
                                 'hist': p.get('hist', 0), 'bar': p.get('bar', 0)}
                                for p in data.get('pivot_highs', [])]
            state.pivot_lows = [{'ts': pd.Timestamp(p['ts']), 'price': p['price'],
                                'rsi': p.get('rsi', 0), 'macdline': p.get('macdline', 0),
                                'hist': p.get('hist', 0), 'bar': p.get('bar', 0)}
                               for p in data.get('pivot_lows', [])]
            state.last_processed_ts = pd.Timestamp(data['last_processed_ts']) if data.get('last_processed_ts') else None
            state.rst_l = data.get('rst_l', False)
            state.rst_s = data.get('rst_s', False)
            state.last_ma_ts = pd.Timestamp(data['last_ma_ts']) if data.get('last_ma_ts') else None
            state.telegram_log_count = data.get('telegram_log_count', 0)
            state.last_telegram_log_time = data.get('last_telegram_log_time', 0)

            def _pending_from_dict(lst):
                out = []
                for c in lst:
                    cc = dict(c)
                    cc['confirm_start_ts'] = pd.Timestamp(c['confirm_start_ts'])
                    cc['deadline_ts'] = pd.Timestamp(c['deadline_ts'])
                    out.append(cc)
                return out

            state.pending_bull_divs = _pending_from_dict(data.get('pending_bull_divs', []))
            state.pending_bear_divs = _pending_from_dict(data.get('pending_bear_divs', []))
        return state

SYMBOL_STATES = {s: SymbolState() for s in SYMBOLS}

def save_states():
    data = {s: SYMBOL_STATES[s].to_dict() for s in SYMBOLS}
    with open(STATE_FILE, 'w') as f:
        json.dump(data, f, indent=2)

def load_states():
    global SYMBOL_STATES
    if os.path.exists(STATE_FILE):
        try:
            with open(STATE_FILE) as f:
                data = json.load(f)
            for s in SYMBOLS:
                if s in data:
                    SYMBOL_STATES[s] = SymbolState.from_dict(data[s])
            logger.info(f"[STATE] Loaded pivot states from {STATE_FILE}")
        except Exception as e:
            logger.error(f"[STATE] Error loading states: {e}")

# =====================================================================================
# مدیریت تاریخچه
# =====================================================================================
def load_history():
    if os.path.exists(HISTORY_FILE):
        try:
            with open(HISTORY_FILE) as f:
                return json.load(f)
        except:
            return []
    return []

def save_history(h):
    with open(HISTORY_FILE, 'w') as f:
        json.dump(h, f, indent=2)

def update_trade_result(signal_time, result, close_price, close_time, pnl=None):
    h = load_history()
    for t in h:
        if t.get('signal_time') == signal_time:
            t['result'] = result
            t['close_price'] = close_price
            t['close_time'] = close_time
            if pnl is not None:
                t['realized_pnl'] = pnl
            break
    save_history(h)

# =====================================================================================
# شمارنده سیگنال
# =====================================================================================
SIGNAL_COUNTER = 0

def get_next_signal_number():
    global SIGNAL_COUNTER
    SIGNAL_COUNTER += 1
    return SIGNAL_COUNTER

def load_signal_counter():
    global SIGNAL_COUNTER
    history = load_history()
    if history:
        SIGNAL_COUNTER = len(history)
    else:
        SIGNAL_COUNTER = 0

# =====================================================================================
# تقاطع طلایی/مرگ
# =====================================================================================
def process_ma_crosses(closed_df_indexed, ma_f, ma_m, ma_s, state, start_bar, end_bar, emit_from_bar=None):
    events = []
    skipped_old = 0
    for i in range(max(1, start_bar), end_bar + 1):
        f_now, f_prev = ma_f.iloc[i], ma_f.iloc[i-1]
        m_now, m_prev = ma_m.iloc[i], ma_m.iloc[i-1]
        s_now = ma_s.iloc[i]
        if pd.isna(f_now) or pd.isna(m_now) or pd.isna(s_now) or pd.isna(f_prev) or pd.isna(m_prev):
            continue
        if f_now < s_now and m_now < s_now:
            state.rst_l = True
        if f_now > s_now and m_now > s_now:
            state.rst_s = True
        xup = f_prev <= m_prev and f_now > m_now
        xdn = f_prev >= m_prev and f_now < m_now
        gc_l = xup and f_now > s_now and state.rst_l
        gc_s = xdn and f_now < s_now and state.rst_s
        if gc_l:
            state.rst_l = False
            if emit_from_bar is None or i >= emit_from_bar:
                events.append(("BUY_CROSS", closed_df_indexed.index[i]))
            else:
                skipped_old += 1
        if gc_s:
            state.rst_s = False
            if emit_from_bar is None or i >= emit_from_bar:
                events.append(("SELL_CROSS", closed_df_indexed.index[i]))
            else:
                skipped_old += 1
    return events, skipped_old

# =====================================================================================
# تابع ذخیره لاگ در فایل
# =====================================================================================
def save_debug_log_to_file(symbol, debug_log_lines):
    try:
        today = format_iran_date()
        log_file = "full_debug_log_v6.txt"
        with open(log_file, "a", encoding="utf-8") as f:
            f.write(f"\n{'═' * 80}\n")
            f.write(f"📅 DATE: {today} | SYMBOL: {symbol}\n")
            f.write(f"{'═' * 80}\n\n")
            for line in debug_log_lines:
                f.write(line + "\n")
            f.write("-" * 70 + "\n\n")
    except Exception as e:
        logger.error(f"[DEBUG FILE] Error writing log: {e}")

# =====================================================================================
# ★★★ تابع detect_signal — با استاپ/تارگت از strategy_wrapper ★★★
# =====================================================================================
def detect_signal(df_1m, df_5m, state, symbol, debug=False, allow_realtime_cross_trade=True):
    """
    ★★★ نسخه اصلاح‌شده با استاپ/تارگت از strategy_wrapper ★★★
    """
    debug_log = []
    debug_file_lines = []
    def log(msg):
        debug_log.append(msg)
        debug_file_lines.append(msg)
        if debug:
            logger.info(msg)

    log(f"🔍 Pine-Exact DTM — {symbol} | {format_iran_time()}")
    log(f"   Pivot {LEFT_BARS}/{RIGHT_BARS} | دو پیوت متوالی | SSL={SSL_TIMEFRAME} تک‌تایم‌فریمی gate={APPLY_SSL_GATE}")

    if API_RETURNS_OPEN_CANDLE:
        closed_df_indexed = df_1m.iloc[:-1].copy()
    else:
        closed_df_indexed = df_1m.copy()

    if len(closed_df_indexed) > HISTORY_BARS:
        closed_df_indexed = closed_df_indexed.tail(HISTORY_BARS).copy()
        log(f"   ✂️ Sliced to last {HISTORY_BARS} bars")

    closed_df = closed_df_indexed.reset_index(drop=True)
    n = len(closed_df)

    if n < 120:
        log(f"❌ داده ناکافی: {n}")
        return [], debug_log

    close = closed_df["close"]; high = closed_df["high"]; low = closed_df["low"]

    rsi_val = calc_rsi(close, RSI_LEN)
    macd_line, signal_line, hist_line = calc_macd(close, MACD_FAST, MACD_SLOW, MACD_SIGNAL)
    atr14 = calc_atr(high, low, close, ATR_LEN)
    adx_val = calc_adx(high, low, close, ADX_LEN)
    trending = adx_val > ADX_THRESHOLD

    ma_f = calc_ema(close, MA_FAST_LEN)
    ma_m = calc_ema(close, MA_MID_LEN)
    ma_s = calc_ema(close, MA_SLOW_LEN)

    pivot_high = find_pivot_high(high, LEFT_BARS, RIGHT_BARS)
    pivot_low = find_pivot_low(low, LEFT_BARS, RIGHT_BARS)

    last = n - 1
    end_scan_pos = last - RIGHT_BARS

    if end_scan_pos < LEFT_BARS:
        log("   ⚠️ هنوز داده کافی برای تأیید پیوت نیست")
        return [], debug_log

    if state.last_processed_ts is not None and state.last_processed_ts in closed_df_indexed.index:
        try:
            _loc = closed_df_indexed.index.get_loc(state.last_processed_ts)
            if isinstance(_loc, slice):
                _loc = _loc.start if _loc.start is not None else (LEFT_BARS - 1)
            start_scan_pos = int(_loc) + 1
        except Exception:
            start_scan_pos = LEFT_BARS
    else:
        start_scan_pos = LEFT_BARS

    start_scan_pos = max(start_scan_pos, LEFT_BARS)

    existing_high_ts = {p['ts'] for p in state.pivot_highs}
    existing_low_ts = {p['ts'] for p in state.pivot_lows}

    new_pivots_high = []
    new_pivots_low = []

    if start_scan_pos <= end_scan_pos:
        for pos in range(start_scan_pos, end_scan_pos + 1):
            ts_pos = closed_df_indexed.index[pos]

            if not pd.isna(pivot_high.iloc[pos]) and ts_pos not in existing_high_ts:
                ph_entry = {
                    'ts': ts_pos,
                    'price': float(pivot_high.iloc[pos]),
                    'bar': pos,
                    'rsi': float(rsi_val.iloc[pos]) if not pd.isna(rsi_val.iloc[pos]) else 0.0,
                    'macdline': float(macd_line.iloc[pos]) if not pd.isna(macd_line.iloc[pos]) else 0.0,
                    'hist': float(hist_line.iloc[pos]) if not pd.isna(hist_line.iloc[pos]) else 0.0
                }
                new_pivots_high.append(ph_entry)
                state.pivot_highs.append(ph_entry)
                existing_high_ts.add(ts_pos)

            if not pd.isna(pivot_low.iloc[pos]) and ts_pos not in existing_low_ts:
                pl_entry = {
                    'ts': ts_pos,
                    'price': float(pivot_low.iloc[pos]),
                    'bar': pos,
                    'rsi': float(rsi_val.iloc[pos]) if not pd.isna(rsi_val.iloc[pos]) else 0.0,
                    'macdline': float(macd_line.iloc[pos]) if not pd.isna(macd_line.iloc[pos]) else 0.0,
                    'hist': float(hist_line.iloc[pos]) if not pd.isna(hist_line.iloc[pos]) else 0.0
                }
                new_pivots_low.append(pl_entry)
                state.pivot_lows.append(pl_entry)
                existing_low_ts.add(ts_pos)

    if len(state.pivot_highs) > 500:
        state.pivot_highs = state.pivot_highs[-500:]
    if len(state.pivot_lows) > 500:
        state.pivot_lows = state.pivot_lows[-500:]

    state.last_processed_ts = closed_df_indexed.index[last]
    log(f"   new_high={len(new_pivots_high)}, new_low={len(new_pivots_low)} | mem H={len(state.pivot_highs)} L={len(state.pivot_lows)} | scan=[{start_scan_pos}..{end_scan_pos}]")

    # تقاطع طلایی / مرگ
    ma_start_pos = 1
    ma_fallback_used = False
    if state.last_ma_ts is not None and state.last_ma_ts in closed_df_indexed.index:
        try:
            ma_start_pos = max(1, closed_df_indexed.index.get_loc(state.last_ma_ts))
            if isinstance(ma_start_pos, slice):
                ma_start_pos = ma_start_pos.start if ma_start_pos.start is not None else 1
        except:
            ma_start_pos = 1
            ma_fallback_used = True
    else:
        ma_fallback_used = True

    emit_from_bar = None
    if allow_realtime_cross_trade:
        emit_from_bar = max(1, (n - 1) - MAX_CROSS_EMIT_LOOKBACK_BARS)
        if ma_fallback_used:
            log(f"   ⚠️ last_ma_ts نامعتبر/خالی بود — Catch-up انجام می‌شود اما فقط تقاطع‌های {MAX_CROSS_EMIT_LOOKBACK_BARS} کندل اخیر سیگنال/معامله می‌شوند")
        elif ma_start_pos < emit_from_bar - 1:
            log(f"   ⚠️ فاصله‌ی زیاد بین last_ma_ts و اکنون — تقاطع‌های قدیمی‌تر از کندل {emit_from_bar} فقط برای rst_l/rst_s پردازش می‌شوند")

    ma_events, ma_skipped_old = process_ma_crosses(
        closed_df_indexed, ma_f, ma_m, ma_s, state, ma_start_pos, n - 1, emit_from_bar=emit_from_bar
    )
    if ma_skipped_old:
        log(f"   ⏮️ {ma_skipped_old} تقاطع طلایی/مرگ قدیمی (Catch-up) نادیده گرفته شد")
    state.last_ma_ts = closed_df_indexed.index[n - 1]

    # ✅ فیلتر SSL Hybrid
    hlv = compute_ssl_hlv(df_5m)
    if hlv is None:
        log("   ❌ SSL Hybrid Error - SIGNALS DISABLED")
        return [], debug_log
    
    gate_long = hlv == 1
    gate_short = hlv == -1
    log(f"   SSL(5m) Hlv={hlv} | gate_long={gate_long} gate_short={gate_short}")

    entry_price = float(close.iloc[-1])
    atr_now = float(atr14.iloc[-1]) if not pd.isna(atr14.iloc[-1]) else 0.0

    hidden_signals = []
    new_classic_bull_candidates = []
    new_classic_bear_candidates = []
    cross_signals = []

    hlv_index, hlv_array = compute_ssl_hlv_series(df_5m)

    # ★★★ دریافت tick info برای محاسبه استاپ/تارگت ★★★
    tick_info = SYMBOL_TICK_INFO.get(symbol.upper(), {"mintick": 0.01})
    mintick = tick_info["mintick"]
    
    # ★★★ تعیین buffer_ticks بر اساس نماد (مطابق strategy_wrapper) ★★★
    if symbol in ["BNBUSDT", "ETHUSDT"]:
        buffer_ticks = 9
    elif symbol in ["LTCUSDT", "DOGEUSDT"]:
        buffer_ticks = 3
    else:
        buffer_ticks = 5

    # تقاطع طلایی/مرگ (با استاپ/تارگت ATR — قدیمی)
    for etype, ets in ma_events:
        hlv_evt = get_hlv_at_ts(hlv_index, hlv_array, ets)
        if hlv_evt is None:
            hlv_evt = hlv
        gate_long_evt = hlv_evt == 1
        gate_short_evt = hlv_evt == -1

        if etype == "BUY_CROSS" and gate_long_evt:
            stop, target = compute_cross_sl_tp("long", entry_price, atr_now)
            cross_signals.append({
                'type': 'GOLDEN_CROSS', 'direction': 'BUY',
                'entry': entry_price, 'stop': stop, 'target': target,
                'extra': "⬆تقاطع طلایی", 'score': 0, 'time': format_iran_time(ets)
            })
            log(f"   ⬆️ Golden Cross @ {ets} | Hlv(event)={hlv_evt}")
        elif etype == "SELL_CROSS" and gate_short_evt:
            stop, target = compute_cross_sl_tp("short", entry_price, atr_now)
            cross_signals.append({
                'type': 'DEATH_CROSS', 'direction': 'SELL',
                'entry': entry_price, 'stop': stop, 'target': target,
                'extra': "⬇تقاطع مرگ", 'score': 0, 'time': format_iran_time(ets)
            })
            log(f"   ⬇️ Death Cross @ {ets} | Hlv(event)={hlv_evt}")

    # ★★★ واگرایی نزولی — با استاپ/تارگت از strategy_wrapper ★★★
    for new_ph in new_pivots_high:
        idx = next((i for i, p in enumerate(state.pivot_highs) if p['ts'] == new_ph['ts']), None)
        if idx is None or idx < 1:
            continue
        ph_1 = state.pivot_highs[idx - 1]
        ph_2 = state.pivot_highs[idx]
        bar1 = resolve_bar_from_ts(closed_df_indexed, ph_1['ts'])
        bar2 = resolve_bar_from_ts(closed_df_indexed, ph_2['ts'])
        if bar1 is None or bar2 is None:
            continue
        confirm_bar = min(bar2 + RIGHT_BARS, last)

        if not (trending.iloc[confirm_bar] and gate_short):
            continue

        if ph_2['price'] > ph_1['price']:
            div_rsi = ph_2['rsi'] < ph_1['rsi']
            div_macd = ph_2['macdline'] < ph_1['macdline']
            div_hist = False

            if div_rsi or div_macd or div_hist:
                fib_ok = check_fib_near(high, low, bar2, ph_2['price'], is_high_side=True, tol_pct=FIB_TOLERANCE_PCT)
                pa_ok = check_shooting_star(closed_df, ph_2['bar'])
                score = int(div_rsi) + int(div_hist) + int(div_macd) + int(fib_ok) + int(pa_ok)
                log(f"   🔴 Classic Bearish [{bar1}↔{bar2}]: score={score}/5")

                if score >= MIN_CLASSIC_SCORE:
                    # ★★★ ساخت last_values برای تابع compute_stop_target_from_wrapper ★★★
                    last_values = {
                        "entry": entry_price,
                        "previous_pivot_high_price": ph_1['price'],
                        "pivot_high_price": ph_2['price'],
                        "previous_pivot_high_index": bar1,
                        "pivot_high_index": bar2,
                    }
                    
                    # ★★★ محاسبه استاپ/تارگت با تابع strategy_wrapper ★★★
                    stop, target, rr_value, structural_level = compute_stop_target_from_wrapper(
                        [], "SHORT", last_values, mintick, buffer_ticks
                    )
                    
                    # ★★★ اگر محاسبه استاپ/تارگت با شکست مواجه شد، از روش قدیمی استفاده کن ★★★
                    if stop is None or target is None:
                        stop, target = compute_divergence_sl_tp(ph_1['price'], ph_2['price'], "short", entry_price, symbol)
                    
                    if stop and target:
                        sig = {
                            'type': 'CLASSIC_BEARISH_DIV', 'direction': 'SELL',
                            'entry': entry_price, 'stop': stop, 'target': target,
                            'extra': f"{score_stars(score)}\nواگرایی↓[{score}/5]", 'score': score,
                            'time': format_iran_time(ph_2['ts']), 'pivot_ts': str(ph_2['ts']),
                            'structural_level': structural_level  # برای ریسک‌فری
                        }
                        if REQUIRE_PA_CONFIRMATION:
                            confirm_start_ts = closed_df_indexed.index[confirm_bar]
                            deadline_ts = confirm_start_ts + pd.Timedelta(minutes=WAIT_BARS_PA_CONFIRM)
                            new_classic_bear_candidates.append({
                                'signal': sig, 'direction': 'short',
                                'confirm_start_ts': confirm_start_ts, 'deadline_ts': deadline_ts
                            })
                            log(f"   ⏳ Classic Bearish Div در انتظار کندل تأییدیه تا {format_iran_time(deadline_ts)}")
                        else:
                            hidden_signals.append(sig)
                            log(f"   🔴 Classic Bearish Div SELECTED: score={score}/5")

        # مخفی نزولی
        elif ph_2['price'] < ph_1['price']:
            hid = (ph_2['rsi'] > ph_1['rsi']) or (ph_2['macdline'] > ph_1['macdline'])
            if hid:
                last_values = {
                    "entry": entry_price,
                    "previous_pivot_high_price": ph_1['price'],
                    "pivot_high_price": ph_2['price'],
                    "previous_pivot_high_index": bar1,
                    "pivot_high_index": bar2,
                }
                stop, target, rr_value, structural_level = compute_stop_target_from_wrapper(
                    [], "SHORT", last_values, mintick, buffer_ticks
                )
                if stop is None or target is None:
                    stop, target = compute_divergence_sl_tp(ph_1['price'], ph_2['price'], "short", entry_price, symbol)
                
                if stop and target:
                    hidden_signals.append({
                        'type': 'HIDDEN_BEARISH_DIV', 'direction': 'SELL',
                        'entry': entry_price, 'stop': stop, 'target': target,
                        'extra': "~واگرایی مخفی↓", 'score': 0,
                        'time': format_iran_time(ph_2['ts']), 'pivot_ts': str(ph_2['ts']),
                        'structural_level': structural_level
                    })
                    log(f"   🟠 Hidden Bearish Div [{bar1}↔{bar2}]")

    # ★★★ واگرایی صعودی — با استاپ/تارگت از strategy_wrapper ★★★
    for new_pl in new_pivots_low:
        idx = next((i for i, p in enumerate(state.pivot_lows) if p['ts'] == new_pl['ts']), None)
        if idx is None or idx < 1:
            continue
        pl_1 = state.pivot_lows[idx - 1]
        pl_2 = state.pivot_lows[idx]
        bar1 = resolve_bar_from_ts(closed_df_indexed, pl_1['ts'])
        bar2 = resolve_bar_from_ts(closed_df_indexed, pl_2['ts'])
        if bar1 is None or bar2 is None:
            continue
        confirm_bar = min(bar2 + RIGHT_BARS, last)

        if not (trending.iloc[confirm_bar] and gate_long):
            continue

        if pl_2['price'] < pl_1['price']:
            div_rsi = pl_2['rsi'] > pl_1['rsi']
            div_macd = pl_2['macdline'] > pl_1['macdline']
            div_hist = False

            if div_rsi or div_macd or div_hist:
                fib_ok = check_fib_near(high, low, bar2, pl_2['price'], is_high_side=False, tol_pct=FIB_TOLERANCE_PCT)
                pa_ok = check_hammer(closed_df, pl_2['bar'])
                score = int(div_rsi) + int(div_hist) + int(div_macd) + int(fib_ok) + int(pa_ok)
                log(f"   🟢 Classic Bullish [{bar1}↔{bar2}]: score={score}/5")

                if score >= MIN_CLASSIC_SCORE:
                    last_values = {
                        "entry": entry_price,
                        "previous_pivot_low_price": pl_1['price'],
                        "pivot_low_price": pl_2['price'],
                        "previous_pivot_low_index": bar1,
                        "pivot_low_index": bar2,
                    }
                    stop, target, rr_value, structural_level = compute_stop_target_from_wrapper(
                        [], "LONG", last_values, mintick, buffer_ticks
                    )
                    if stop is None or target is None:
                        stop, target = compute_divergence_sl_tp(pl_1['price'], pl_2['price'], "long", entry_price, symbol)
                    
                    if stop and target:
                        sig = {
                            'type': 'CLASSIC_BULLISH_DIV', 'direction': 'BUY',
                            'entry': entry_price, 'stop': stop, 'target': target,
                            'extra': f"{score_stars(score)}\nواگرایی↑[{score}/5]", 'score': score,
                            'time': format_iran_time(pl_2['ts']), 'pivot_ts': str(pl_2['ts']),
                            'structural_level': structural_level
                        }
                        if REQUIRE_PA_CONFIRMATION:
                            confirm_start_ts = closed_df_indexed.index[confirm_bar]
                            deadline_ts = confirm_start_ts + pd.Timedelta(minutes=WAIT_BARS_PA_CONFIRM)
                            new_classic_bull_candidates.append({
                                'signal': sig, 'direction': 'long',
                                'confirm_start_ts': confirm_start_ts, 'deadline_ts': deadline_ts
                            })
                            log(f"   ⏳ Classic Bullish Div در انتظار کندل تأییدیه تا {format_iran_time(deadline_ts)}")
                        else:
                            hidden_signals.append(sig)
                            log(f"   🟢 Classic Bullish Div SELECTED: score={score}/5")

        # مخفی صعودی
        elif pl_2['price'] > pl_1['price']:
            hid = (pl_2['rsi'] < pl_1['rsi']) or (pl_2['macdline'] < pl_1['macdline'])
            if hid:
                last_values = {
                    "entry": entry_price,
                    "previous_pivot_low_price": pl_1['price'],
                    "pivot_low_price": pl_2['price'],
                    "previous_pivot_low_index": bar1,
                    "pivot_low_index": bar2,
                }
                stop, target, rr_value, structural_level = compute_stop_target_from_wrapper(
                    [], "LONG", last_values, mintick, buffer_ticks
                )
                if stop is None or target is None:
                    stop, target = compute_divergence_sl_tp(pl_1['price'], pl_2['price'], "long", entry_price, symbol)
                
                if stop and target:
                    hidden_signals.append({
                        'type': 'HIDDEN_BULLISH_DIV', 'direction': 'BUY',
                        'entry': entry_price, 'stop': stop, 'target': target,
                        'extra': "~واگرایی مخفی↑", 'score': 0,
                        'time': format_iran_time(pl_2['ts']), 'pivot_ts': str(pl_2['ts']),
                        'structural_level': structural_level
                    })
                    log(f"   🔵 Hidden Bullish Div [{bar1}↔{bar2}]")

    # پردازش صف تأییدیه
    confirmed_bull_signals = []
    confirmed_bear_signals = []
    if REQUIRE_PA_CONFIRMATION:
        bull_queue = state.pending_bull_divs + new_classic_bull_candidates
        bear_queue = state.pending_bear_divs + new_classic_bear_candidates
        confirmed_bull_signals, state.pending_bull_divs = process_pending_confirmations(
            closed_df_indexed, closed_df, bull_queue, log)
        confirmed_bear_signals, state.pending_bear_divs = process_pending_confirmations(
            closed_df_indexed, closed_df, bear_queue, log)

    # جمع‌آوری نهایی
    signals = []
    signals.extend(confirmed_bull_signals)
    signals.extend(confirmed_bear_signals)
    signals.extend(hidden_signals)
    signals.extend(cross_signals)

    if not signals:
        log("   ⚪ No signal")
    else:
        log(f"   📊 Total signals: {len(signals)}")

    save_debug_log_to_file(symbol, debug_file_lines)
    return signals, debug_log

# =====================================================================================
# توابع کمکی برای استاپ/تارگت
# =====================================================================================
def compute_divergence_sl_tp(p1_price, p2_price, direction, entry_price, symbol):
    """روش قدیمی استاپ/تارگت — به‌عنوان fallback"""
    tick = TICK_SIZES.get(symbol.upper(), 0.01)
    buffer_ = tick * 5  # استفاده از بافر ثابت 5 تیک

    if direction == "long":
        lowest_valley = min(p1_price, p2_price)
        stop = lowest_valley - buffer_
        risk = entry_price - stop
    else:
        highest_peak = max(p1_price, p2_price)
        stop = highest_peak + buffer_
        risk = stop - entry_price

    if risk <= 0:
        return None, None

    target = entry_price + risk * 2.0 if direction == "long" else entry_price - risk * 2.0
    return stop, target

def compute_cross_sl_tp(direction, entry_price, atr_val):
    if direction == "long":
        stop = entry_price - atr_val * CROSS_ATR_STOP_MULT
        risk = entry_price - stop
        target = entry_price + risk * 2.0
    else:
        stop = entry_price + atr_val * CROSS_ATR_STOP_MULT
        risk = stop - entry_price
        target = entry_price - risk * 2.0
    return stop, target

def score_stars(score):
    if score >= 5: return "★★★★★"
    if score >= 4: return "★★★★"
    if score >= 3: return "★★★"
    if score >= 2: return "★★"
    return "★"

def process_pending_confirmations(closed_df_indexed, closed_df, pending_list, log_fn):
    finalized = []
    still_pending = []
    idx = closed_df_indexed.index
    for cand in pending_list:
        start_ts = cand['confirm_start_ts']
        deadline_ts = cand['deadline_ts']
        mask = (idx >= start_ts) & (idx <= deadline_ts)
        positions = np.where(mask)[0]
        found = False
        for wpos in positions:
            ok = check_hammer(closed_df, wpos) if cand['direction'] == 'long' else check_shooting_star(closed_df, wpos)
            if ok:
                sig = dict(cand['signal'])
                confirm_ts = idx[wpos]
                sig['confirm_time'] = format_iran_time(confirm_ts)
                finalized.append(sig)
                log_fn(f"   ✅ کندل تأییدیه دریافت شد برای {sig['type']} @ {format_iran_time(confirm_ts)}")
                found = True
                break
        if found:
            continue
        if len(idx) > 0 and idx[-1] >= deadline_ts:
            log_fn(f"   ⌛ مهلت به پایان رسید — {cand['signal']['type']} حذف شد")
            continue
        still_pending.append(cand)
    return finalized, still_pending

# =====================================================================================
# پیگیری سیگنال‌های باز
# =====================================================================================
def track_open_signals(data, exchange=None):
    history = load_history()
    open_trades = [t for t in history if t.get('result') is None]
    if not open_trades:
        return

    for trade in open_trades:
        symbol = trade['symbol']
        direction = trade['direction']
        entry = trade['entry_price']
        stop = trade['stop_loss']
        target = trade['take_profit']
        signal_time = trade['signal_time']
        signal_number = trade.get('signal_number', '?')

        cp = data.fetch_current_price(symbol)
        if cp is None:
            continue

        hit_target = False
        hit_stop = False

        if direction == 'BUY':
            if cp >= target:
                hit_target = True
            elif cp <= stop:
                hit_stop = True
        else:
            if cp <= target:
                hit_target = True
            elif cp >= stop:
                hit_stop = True

        if hit_target:
            profit_pct = (target - entry) / entry * 100 if direction == 'BUY' else (entry - target) / entry * 100
            leverage = trade.get('leverage', 1)
            capital = trade.get('capital', 0)
            profit_usdt = capital * leverage * profit_pct / 100
            update_trade_result(signal_time, 'TAKE_PROFIT', cp, format_iran_time(), pnl=profit_usdt)
            send_telegram_message(
                f"🎯 *حد سود فعال شد* {HASHTAGS['target']} #Signal_{signal_number}\n"
                f"━━━━━━━━━━━━━━━━━━━━━━\n"
                f"🔹 نماد: `{symbol}`  |  جهت: *{direction}*\n"
                f"💰 سود: +{profit_pct:.2f}%  |  +{profit_usdt:.2f} USDT\n"
                f"━━━━━━━━━━━━━━━━━━━━━━\n🕒 {format_iran_time()}"
            )
            continue

        elif hit_stop:
            loss_pct = (entry - stop) / entry * 100 if direction == 'BUY' else (stop - entry) / entry * 100
            leverage = trade.get('leverage', 1)
            capital = trade.get('capital', 0)
            loss_usdt = capital * leverage * loss_pct / 100
            update_trade_result(signal_time, 'STOP_LOSS', cp, format_iran_time(), pnl=-loss_usdt)
            send_telegram_message(
                f"💔 *حد ضرر فعال شد* {HASHTAGS['stop']} #Signal_{signal_number}\n"
                f"━━━━━━━━━━━━━━━━━━━━━━\n"
                f"🔹 نماد: `{symbol}`  |  جهت: *{direction}*\n"
                f"💸 ضرر: -{loss_pct:.2f}%  |  -{loss_usdt:.2f} USDT\n"
                f"━━━━━━━━━━━━━━━━━━━━━━\n🕒 {format_iran_time()}"
            )
            continue

        # 🛡️ ریسک‌فری
        if (exchange is not None and exchange.connected and not trade.get('risk_free_done')
                and trade.get('position_id') and trade.get('position_id') != 'N/A'):
            # ★★★ استفاده از structural_level برای ریسک‌فری ★★★
            structural_level = trade.get('structural_level')
            if structural_level is not None:
                risk_dist = abs(entry - stop)
                if risk_dist > 0:
                    if direction == 'BUY':
                        one_r_hit = cp >= entry + risk_dist
                        # نقطه ریسک‌فری روی structural_level یا 1R
                        risk_free_price = max(structural_level, entry + risk_dist)
                    else:
                        one_r_hit = cp <= entry - risk_dist
                        risk_free_price = min(structural_level, entry - risk_dist)
                    
                    if one_r_hit:
                        try:
                            exchange.update_position_sl(trade['position_id'], symbol, risk_free_price, take_profit=target)
                            trade['risk_free_done'] = True
                            trade['stop_loss'] = risk_free_price
                            save_history(history)
                            logger.info(f"[RISK-FREE] {symbol} #{signal_number}: استاپ به {risk_free_price} منتقل شد")
                        except Exception as e:
                            logger.error(f"[RISK-FREE] {symbol} #{signal_number}: خطا — {e}")

# =====================================================================================
# توابع گزارش
# =====================================================================================
def send_reports(exchange):
    now = datetime.now(IRAN_TZ)
    today_str = format_iran_date()

    try:
        history = load_history()
        today_trades = [t for t in history if t.get('signal_time', '').startswith(today_str)]
        if today_trades:
            total = len(today_trades)
            wins = len([t for t in today_trades if t.get('result') == 'TAKE_PROFIT'])
            losses = len([t for t in today_trades if t.get('result') == 'STOP_LOSS'])
            open_count = len([t for t in today_trades if t.get('result') is None])
            closed = wins + losses
            win_rate = (wins / closed * 100) if closed > 0 else 0
            local_daily_msg = f"""📊 گزارش روزانه — {today_str} {HASHTAGS['daily']}
━━━━━━━━━━━━━━━━━━━━━━
📈 کل معاملات: {total} عدد
✅ موفق: {wins} ({win_rate:.1f}%)
❌ ناموفق: {losses}
⏳ باز: {open_count}
📊 نرخ موفقیت: {win_rate:.1f}%
━━━━━━━━━━━━━━━━━━━━━━
🕒 {format_iran_time()}"""
            send_telegram_message(local_daily_msg)
    except Exception as e:
        logger.error(f"[REPORT ERROR] Local daily: {e}")

    try:
        history = load_history()
        month_ago = (now - timedelta(days=30)).strftime('%Y-%m-%d')
        month_trades = [t for t in history if t.get('signal_time', '') >= month_ago]
        if month_trades:
            total = len(month_trades)
            wins = len([t for t in month_trades if t.get('result') == 'TAKE_PROFIT'])
            losses = len([t for t in month_trades if t.get('result') == 'STOP_LOSS'])
            total_pnl = sum(t.get('realized_pnl', 0) for t in month_trades if t.get('realized_pnl'))
            win_rate = (wins / (wins + losses) * 100) if (wins + losses) > 0 else 0
            monthly_msg = f"""📈 گزارش ۳۰ روز گذشته {HASHTAGS['monthly']}
━━━━━━━━━━━━━━━━━━━━━━
📊 کل معاملات: {total} عدد
✅ موفق: {wins} ({win_rate:.1f}%)
❌ ناموفق: {losses}
💰 سود/زیان خالص: {total_pnl:.2f} USDT
📈 نرخ موفقیت: {win_rate:.1f}%
━━━━━━━━━━━━━━━━━━━━━━
🕒 {format_iran_time()}"""
            send_telegram_message(monthly_msg)
    except Exception as e:
        logger.error(f"[REPORT ERROR] Monthly: {e}")

    try:
        current_balance = exchange.fetch_balance()
        exchange_report_msg = f"""📈 وضعیت حساب — {today_str} {HASHTAGS['daily']}
━━━━━━━━━━━━━━━━━━━━━━
💰 موجودی حساب: {current_balance:.2f} USDT
🕒 {format_iran_time()}"""
        send_telegram_message(exchange_report_msg)
    except Exception as e:
        logger.error(f"[REPORT ERROR] Exchange: {e}")

# =====================================================================================
# Startup Diagnostic
# =====================================================================================
def run_startup_diagnostic():
    logger.info("Running Startup Diagnostic...")
    diagnostic_log = []
    diagnostic_log.append(f"🔍 بررسی سلامت سیستم {HASHTAGS['diagnostic']}")
    diagnostic_log.append("━━━━━━━━━━━━━━━━━━━━━━")
    try:
        requests.get("https://www.google.com", timeout=5)
        diagnostic_log.append("🟢 اتصال اینترنت")
    except:
        diagnostic_log.append("🔴 اتصال اینترنت")
    data = BinanceData()
    df, candles = None, None
    try:
        df, candles = data.fetch_ohlcv("LTCUSDT", "1m", 1500)
        if df is not None and not df.empty:
            diagnostic_log.append(f"🟢 دریافت داده: {len(df)} کندل")
        else:
            diagnostic_log.append("🔴 دریافت داده")
    except Exception as e:
        diagnostic_log.append(f"🔴 دریافت داده: {str(e)[:50]}")
    try:
        if df is not None and not df.empty:
            rsi = calc_rsi(df['close'], 14)
            diagnostic_log.append(f"🟢 RSI(14): {rsi.iloc[-1]:.2f}")
            diagnostic_log.append("🟢 MACD(12,26,9): فعال")
            atr = calc_atr(df['high'], df['low'], df['close'], 14)
            diagnostic_log.append(f"🟢 ATR(14): {atr.iloc[-1]:.4f}")
            adx = calc_adx(df['high'], df['low'], df['close'], 14)
            diagnostic_log.append(f"🟢 ADX(14): {adx.iloc[-1]:.2f}")
    except Exception as e:
        diagnostic_log.append(f"🔴 خطا: {str(e)[:50]}")
    diagnostic_log.append("🟢 موتور سیگنال: آماده")
    diagnostic_log.append("🟢 اتصال به تلگرام")
    exchange = BinancePrivateExchange(API_KEY, API_SECRET, BASE_URL)
    conn = exchange.test_connection()
    if conn:
        diagnostic_log.append("🟢 اتصال به صرافی: برقرار")
        balance = exchange.fetch_balance()
        if balance:
            diagnostic_log.append(f"🟢 موجودی: {balance:.2f} USDT")
    else:
        diagnostic_log.append("🔴 اتصال به صرافی: قطع")
    diagnostic_log.append("\n━━━━━━━━━━━━━━━━━━━━━━")
    diagnostic_log.append("✅ تمام بخش‌ها فعال هستند" if conn else "⚠️ برخی بخش‌ها غیرفعال هستند")
    diagnostic_log.append(f"🕒 {format_iran_time()}")
    send_telegram_message("\n".join(diagnostic_log))
    logger.info("Startup Diagnostic Complete")

# =====================================================================================
# تابع اصلی تحلیل + اجرا
# =====================================================================================
def analyze_and_execute():
    global FIRST_RUN
    
    logger.info("[ANALYZE] شروع...")
    exchange = BinancePrivateExchange(API_KEY, API_SECRET, BASE_URL)
    conn = exchange.test_connection()
    balance = exchange.fetch_balance() if conn else 0
    if balance is None:
        balance = 0

    if not hasattr(analyze_and_execute, "_last_status"):
        analyze_and_execute._last_status = conn
        status_text = "✅ متصل — ترید خودکار فعال است" if conn else "⚠️ قطع — ترید خودکار غیرفعال است"
        balance_text = f"\n💰 موجودی حساب فیوچرز: {balance:.2f} USDT" if balance else "\n💰 موجودی: نامشخص"
        send_telegram_message(f"📡 وضعیت اتصال به صرافی {HASHTAGS['connection']}\n\n{status_text}{balance_text}\n🕒 {format_iran_time()}")
    elif analyze_and_execute._last_status != conn:
        analyze_and_execute._last_status = conn
        status_text = "✅ متصل — ترید خودکار فعال شد" if conn else "⚠️ قطع — ترید خودکار متوقف شد"
        balance_text = f"\n💰 موجودی حساب فیوچرز: {balance:.2f} USDT" if balance else ""
        send_telegram_message(f"🔄 تغییر وضعیت صرافی {HASHTAGS['connection_change']}\n\n{status_text}{balance_text}\n🕒 {format_iran_time()}")

    data = BinanceData()
    track_open_signals(data, exchange)

    side_map = {"BUY": "LONG", "SELL": "SHORT"}

    for symbol in SYMBOLS:
        try:
            df_1m, candles_1m = data.fetch_ohlcv(symbol, MAIN_TIMEFRAME, HISTORY_BARS)
            df_5m, _ = data.fetch_ohlcv(symbol, SSL_TIMEFRAME, 500)
            if df_1m is None or df_1m.empty:
                logger.warning(f"[SKIP] {symbol}: داده 1m نیست")
                continue

            logger.info(f"[DATA] {symbol}: 1m={len(df_1m)} کندل")

            signals, _ = detect_signal(df_1m, df_5m, SYMBOL_STATES[symbol], symbol, debug=True,
                                        allow_realtime_cross_trade=True)

            if FIRST_RUN and len(signals) > 2:
                logger.info(f"[FIRST_RUN] {symbol}: {len(signals)} سیگنال یافت شد، فقط ۲ تای آخر ارسال می‌شوند")
                signals = signals[-2:]

            for sig in signals:
                if FIRST_RUN:
                    direction = sig['direction']
                    dir_emoji = "🟢" if direction == "BUY" else "🔴"
                    dir_txt = "LONG" if direction == "BUY" else "SHORT"
                    
                    entry = round_price(sig['entry'], symbol)
                    stop = round_price(sig['stop'], symbol)
                    target = round_price(sig['target'], symbol)
                    
                    profit_pct = (target-entry)/entry*100 if direction=="BUY" else (entry-target)/entry*100
                    loss_pct = (entry-stop)/entry*100 if direction=="BUY" else (stop-entry)/entry*100
                    rr = abs(profit_pct/loss_pct) if loss_pct != 0 else 0
                    
                    signal_message = (
                        f"{dir_emoji} *سیگنال جدید* — {sig['type']} — `{symbol}` {HASHTAGS['signal']}\n"
                        f"━━━━━━━━━━━━━━━━━━━━━━\n"
                        f"🔸 جهت: *{dir_txt}*\n"
                        f"📝 {sig['extra']}\n"
                        f"🕐 زمان سیگنال (پیوت): `{sig.get('time', '—')}`\n"
                        f"━━━━━━━━━━━━━━━━━━━━━━\n"
                        f"📍 ورود: `{entry:.{PRICE_PRECISION.get(symbol, 2)}f}`\n"
                        f"🛑 حد ضرر: `{stop:.{PRICE_PRECISION.get(symbol, 2)}f}`\n"
                        f"🎯 حد سود: `{target:.{PRICE_PRECISION.get(symbol, 2)}f}`\n"
                        f"━━━━━━━━━━━━━━━━━━━━━━\n"
                        f"📈 سود احتمالی: +{profit_pct:.2f}%\n"
                        f"📉 ضرر احتمالی: -{loss_pct:.2f}%\n"
                        f"⚖️ نسبت ریسک به ریوارد: *1:{rr:.2f}*\n"
                        f"━━━━━━━━━━━━━━━━━━━━━━\n"
                        f"⚠️ *حالت اولین اجرا - فقط نمایشی، بدون معامله*\n"
                        f"🕒 {format_iran_time()}"
                    )
                    send_telegram_message(signal_message)
                    continue

                entry = round_price(sig['entry'], symbol)
                stop = round_price(sig['stop'], symbol)
                target = round_price(sig['target'], symbol)
                direction = sig['direction']

                profit_pct = (target-entry)/entry*100 if direction=="BUY" else (entry-target)/entry*100
                loss_pct = (entry-stop)/entry*100 if direction=="BUY" else (stop-entry)/entry*100
                rr = abs(profit_pct/loss_pct) if loss_pct != 0 else 0
                dir_txt = "LONG" if direction == "BUY" else "SHORT"
                dir_emoji = "🟢" if direction == "BUY" else "🔴"

                signal_number = get_next_signal_number()
                current_signal_time = format_iran_time()

                leverage = LEVERAGE_MAP.get(symbol, 50)
                stop_pct = abs(entry - stop) / entry
                old_leverage = 1.0 / stop_pct if stop_pct > 0 else 999999
                if old_leverage <= leverage:
                    required_capital = TARGET_RISK_USDT
                    used_leverage = old_leverage
                else:
                    required_capital = TARGET_RISK_USDT * (old_leverage / leverage)
                    used_leverage = leverage

                capital_reduced = False
                if balance >= required_capital:
                    capital = required_capital
                    actual_risk = TARGET_RISK_USDT
                else:
                    capital = balance * 0.98
                    actual_risk = capital * used_leverage * stop_pct
                    capital_reduced = True

                qty = (capital * used_leverage) / entry
                potential_profit = capital * used_leverage * (profit_pct / 100)

                # ★★★ ذخیره structural_level برای ریسک‌فری ★★★
                structural_level = sig.get('structural_level')

                signal_message = (
                    f"{dir_emoji} *سیگنال جدید* — {sig['type']} — `{symbol}` {HASHTAGS['signal']} #Signal_{signal_number}\n"
                    f"━━━━━━━━━━━━━━━━━━━━━━\n"
                    f"🔸 جهت: *{dir_txt}*\n"
                    f"📝 {sig['extra']}\n"
                    f"🕐 زمان سیگنال (پیوت): `{sig.get('time', '—')}`\n"
                    f"━━━━━━━━━━━━━━━━━━━━━━\n"
                    f"📍 ورود: `{entry:.{PRICE_PRECISION.get(symbol, 2)}f}`\n"
                    f"🛑 حد ضرر: `{stop:.{PRICE_PRECISION.get(symbol, 2)}f}`\n"
                    f"🎯 حد سود: `{target:.{PRICE_PRECISION.get(symbol, 2)}f}`\n"
                    f"━━━━━━━━━━━━━━━━━━━━━━\n"
                    f"📈 سود احتمالی: +{profit_pct:.2f}%\n"
                    f"📉 ضرر احتمالی: -{loss_pct:.2f}%\n"
                    f"⚖️ نسبت ریسک به ریوارد: *1:{rr:.2f}*\n"
                    f"━━━━━━━━━━━━━━━━━━━━━━\n🕒 {current_signal_time}"
                )
                try:
                    send_telegram_message(signal_message)
                except Exception as e:
                    logger.error(f"[TELEGRAM SIGNAL ERROR] {symbol}: {e}")

                time.sleep(0.5)

                history = load_history()
                history.append({
                    'symbol': symbol, 'direction': direction,
                    'entry_price': entry, 'stop_loss': stop, 'take_profit': target,
                    'signal_time': current_signal_time, 'result': None,
                    'type': sig['type'], 'capital': capital,
                    'leverage': int(used_leverage), 'qty': qty,
                    'signal_number': signal_number,
                    'position_id': None, 'risk_free_done': False,
                    'structural_level': structural_level  # ★★★ برای ریسک‌فری
                })
                save_history(history)

                if exchange.connected:
                    try:
                        order_result = exchange.create_order(symbol, "market", side_map[direction], capital, None,
                                               {'leverage': int(used_leverage), 'stopLoss': stop, 'takeProfit': target})
                        position_id = order_result.get('id', 'N/A')

                        history = load_history()
                        for t in history:
                            if t.get('signal_time') == current_signal_time:
                                t['position_id'] = position_id
                                break
                        save_history(history)

                        order_message = (
                            f"✅ *سفارش با موفقیت ثبت شد* — `{symbol}` {HASHTAGS['signal']} #Signal_{signal_number}\n"
                            f"━━━━━━━━━━━━━━━━━━━━━━\n"
                            f"🔸 جهت: *{side_map[direction]}*  |  💰 {capital:.2f} USDT  |  🔧 {int(used_leverage)}x\n"
                        )
                        if capital_reduced:
                            order_message += (
                                f"⚠️ سرمایه به‌دلیل کمبود موجودی کاهش یافت {HASHTAGS['capital_reduced']}\n"
                                f"📐 لازم: {required_capital:.2f} USDT  |  💰 موجود: {balance:.2f} USDT\n"
                                f"📉 ریسک واقعی: {TARGET_RISK_USDT:.2f} → {actual_risk:.2f} USDT\n"
                            )
                        order_message += (
                            f"🛑 حد ضرر: {stop:.{PRICE_PRECISION.get(symbol, 2)}f}\n"
                            f"🎯 حد سود: {target:.{PRICE_PRECISION.get(symbol, 2)}f}\n"
                            f"📉 ریسک: {actual_risk:.2f} USDT  |  📈 سود بالقوه: {potential_profit:.2f} USDT\n"
                            f"━━━━━━━━━━━━━━━━━━━━━━\n🕒 {format_iran_time()}"
                        )
                        send_telegram_message(order_message)
                    except Exception as e:
                        send_telegram_message(
                            f"❌ *خطا در ثبت سفارش* — `{symbol}` {HASHTAGS['order_error']} #Signal_{signal_number}\n"
                            f"🔸 {side_map[direction]}\n📝 {str(e)[:200]}\n🕒 {format_iran_time()}"
                        )
        except Exception as e:
            logger.error(f"[ERROR] {symbol}: {e}")

    if FIRST_RUN:
        FIRST_RUN = False
        logger.info("[FIRST_RUN] حالت اولین اجرا به پایان رسید - ربات وارد حالت عادی می‌شود")

    save_states()

# =====================================================================================
# حلقه اصلی
# =====================================================================================
def main_loop():
    global FIRST_RUN
    
    exchange = BinancePrivateExchange(API_KEY, API_SECRET, BASE_URL)
    last_daily_report_date = None
    last_monthly_report_date = None

    if FIRST_RUN:
        logger.info("[MAIN_LOOP] اولین اجرا - پردازش فقط داده‌های جدید")
        analyze_and_execute()
        FIRST_RUN = False
        logger.info("[MAIN_LOOP] اولین اجرا کامل شد - وارد حلقه عادی می‌شویم")

    while True:
        try:
            logger.info(f"[LOOP] {format_iran_time()}")
            analyze_and_execute()

            today = format_iran_date()
            now = datetime.now(IRAN_TZ)

            if last_daily_report_date != today:
                try:
                    send_reports(exchange)
                    last_daily_report_date = today
                    last_monthly_report_date = now
                except Exception as e:
                    logger.error(f"[REPORT ERROR] {e}")

            if last_monthly_report_date is None or (now - last_monthly_report_date).days >= 30:
                try:
                    send_reports(exchange)
                    last_monthly_report_date = now
                except Exception as e:
                    logger.error(f"[REPORT ERROR] {e}")

            time.sleep(60)
        except Exception as e:
            logger.error(f"[LOOP] {e}")
            time.sleep(60)

app = Flask(__name__)
@app.route("/")
def health():
    return "OK", 200

# =====================================================================================
# تحلیل ۲۴ ساعت اخیر
# =====================================================================================
def analyze_last_24h_and_send_report():
    logger.info("[ANALYZE_24H] شروع تحلیل ۲۴ ساعت اخیر...")
    
    now = datetime.now(IRAN_TZ)
    now_str = now.strftime('%Y-%m-%d %H:%M:%S')
    cutoff_time = now - timedelta(hours=24)
    cutoff_str = cutoff_time.strftime('%Y-%m-%d %H:%M:%S')
    
    send_telegram_message(
        f"📊 *تحلیل ۲۴ ساعت اخیر* {HASHTAGS['diagnostic']}\n"
        f"━━━━━━━━━━━━━━━━━━━━━━\n"
        f"🕐 از: `{cutoff_str}`\n"
        f"🕐 تا: `{now_str}`\n"
        f"📌 حالت: *فقط تحلیل — بدون معامله*\n"
        f"━━━━━━━━━━━━━━━━━━━━━━"
    )
    
    data = BinanceData()
    all_signals = {}
    signal_count = 0
    
    for symbol in SYMBOLS:
        try:
            logger.info(f"[ANALYZE_24H] بررسی {symbol}...")
            
            df_1m, _ = data.fetch_ohlcv(symbol, MAIN_TIMEFRAME, 1500)
            df_5m, _ = data.fetch_ohlcv(symbol, SSL_TIMEFRAME, 300)
            
            if df_1m is None or df_1m.empty:
                logger.warning(f"[ANALYZE_24H] {symbol}: داده 1m نیست")
                continue
            
            df_1m = df_1m[df_1m.index >= cutoff_time].copy()
            
            if len(df_1m) < 120:
                logger.warning(f"[ANALYZE_24H] {symbol}: داده ناکافی ({len(df_1m)} کندل)")
                continue
            
            temp_state = SymbolState()
            signals, _ = detect_signal(df_1m, df_5m, temp_state, symbol, debug=False,
                                        allow_realtime_cross_trade=False)
            
            if signals:
                all_signals[symbol] = signals
                signal_count += len(signals)
                logger.info(f"[ANALYZE_24H] {symbol}: {len(signals)} سیگنال یافت شد")
            else:
                logger.info(f"[ANALYZE_24H] {symbol}: هیچ سیگنالی یافت نشد")
                
        except Exception as e:
            logger.error(f"[ANALYZE_24H] خطا در {symbol}: {e}")
    
    # ذخیره در فایل TXT
    report_file = f"signals_24h_{now.strftime('%Y%m%d_%H%M%S')}.txt"
    try:
        with open(report_file, 'w', encoding='utf-8') as f:
            f.write("=" * 80 + "\n")
            f.write(f"📊 REPORT: 24-HOUR SIGNAL ANALYSIS\n")
            f.write("=" * 80 + "\n\n")
            f.write(f"📅 Analysis Time : {now_str}\n")
            f.write(f"🕐 From          : {cutoff_str}\n")
            f.write(f"🕐 To            : {now_str}\n")
            f.write(f"📊 Total Signals : {signal_count}\n")
            f.write("-" * 80 + "\n\n")
            
            if signal_count == 0:
                f.write("⚠️ هیچ سیگنالی در ۲۴ ساعت اخیر یافت نشد.\n")
            else:
                for symbol, signals in all_signals.items():
                    f.write(f"\n{'=' * 80}\n")
                    f.write(f"🔹 SYMBOL: {symbol}\n")
                    f.write(f"{'=' * 80}\n")
                    f.write(f"📊 تعداد سیگنال‌ها: {len(signals)}\n\n")
                    
                    for idx, sig in enumerate(signals, 1):
                        direction = sig['direction']
                        dir_txt = "LONG" if direction == "BUY" else "SHORT"
                        dir_emoji = "🟢" if direction == "BUY" else "🔴"
                        
                        entry = sig['entry']
                        stop = sig['stop']
                        target = sig['target']
                        if direction == "BUY":
                            profit_pct = (target - entry) / entry * 100
                            loss_pct = (entry - stop) / entry * 100
                        else:
                            profit_pct = (entry - target) / entry * 100
                            loss_pct = (stop - entry) / entry * 100
                        rr = profit_pct / loss_pct if loss_pct != 0 else 0
                        
                        f.write(f"┌─ سیگنال #{idx} ─────────────────────────────\n")
                        f.write(f"│ {dir_emoji} نوع: {sig['type']}\n")
                        f.write(f"│ 📊 جهت: {dir_txt}\n")
                        f.write(f"│ 📝 توضیحات: {sig['extra']}\n")
                        f.write(f"│ 🕐 تاریخ و ساعت دقیق سیگنال: {sig.get('time', '—')}\n")
                        if sig.get('confirm_time'):
                            f.write(f"│ ✅ زمان تأییدیه پرایس‌اکشن: {sig['confirm_time']}\n")
                        f.write(f"│ ──────────────────────────────────────────\n")
                        f.write(f"│ 📍 ورود     : {entry:.{PRICE_PRECISION.get(symbol, 2)}f}\n")
                        f.write(f"│ 🛑 حد ضرر   : {stop:.{PRICE_PRECISION.get(symbol, 2)}f}\n")
                        f.write(f"│ 🎯 حد سود   : {target:.{PRICE_PRECISION.get(symbol, 2)}f}\n")
                        f.write(f"│ ──────────────────────────────────────────\n")
                        f.write(f"│ 📈 سود احتمالی : +{profit_pct:.2f}%\n")
                        f.write(f"│ 📉 ضرر احتمالی : -{loss_pct:.2f}%\n")
                        f.write(f"│ ⚖️ نسبت RR     : 1:{rr:.2f}\n")
                        f.write(f"└──────────────────────────────────────────\n\n")
            
            f.write("-" * 80 + "\n")
            f.write(f"⚠️ این گزارش صرفاً جهت تحلیل است و هیچ معامله‌ای انجام نشده است.\n")
            f.write(f"🕒 {now_str}\n")
            f.write("=" * 80 + "\n")
            
        logger.info(f"[ANALYZE_24H] فایل گزارش ذخیره شد: {report_file}")
    except Exception as e:
        logger.error(f"[ANALYZE_24H] خطا در ذخیره فایل: {e}")
        report_file = None

    # ارسال فایل به تلگرام
    if report_file and os.path.exists(report_file):
        try:
            url = f"https://api.telegram.org/bot{TELEGRAM_BOT_TOKEN}/sendDocument"
            with open(report_file, 'rb') as f:
                files = {'document': (report_file, f, 'text/plain')}
                data_payload = {
                    'chat_id': TELEGRAM_CHAT_ID,
                    'caption': f"📊 گزارش تحلیل ۲۴ ساعت اخیر\n📅 {now_str}\n📊 {signal_count} سیگنال یافت شد"
                }
                response = requests.post(url, files=files, data=data_payload, timeout=60)
                
            if response.status_code == 200:
                logger.info(f"[ANALYZE_24H] فایل گزارش به تلگرام ارسال شد")
            else:
                logger.error(f"[ANALYZE_24H] خطا در ارسال فایل: {response.text[:200]}")
                try:
                    with open(report_file, 'r', encoding='utf-8') as f:
                        content = f.read()
                    if len(content) > 4000:
                        parts = [content[i:i+4000] for i in range(0, len(content), 4000)]
                        for i, part in enumerate(parts):
                            send_telegram_message(
                                f"📄 *گزارش تحلیل (بخش {i+1}/{len(parts)})*\n"
                                f"━━━━━━━━━━━━━━━━━━━━━━\n"
                                f"```\n{part}\n```"
                            )
                    else:
                        send_telegram_message(
                            f"📄 *گزارش تحلیل ۲۴ ساعت اخیر*\n"
                            f"━━━━━━━━━━━━━━━━━━━━━━\n"
                            f"```\n{content}\n```"
                        )
                except Exception as e2:
                    logger.error(f"[ANALYZE_24H] خطا در ارسال متن: {e2}")
                    
        except Exception as e:
            logger.error(f"[ANALYZE_24H] خطا در ارسال فایل به تلگرام: {e}")
    
    summary_msg = (
        f"✅ *تحلیل ۲۴ ساعت اخیر کامل شد* {HASHTAGS['diagnostic']}\n"
        f"━━━━━━━━━━━━━━━━━━━━━━\n"
        f"📊 کل سیگنال‌های یافته شده: *{signal_count}*\n"
        f"📁 فایل گزارش: `{report_file}`\n"
        f"━━━━━━━━━━━━━━━━━━━━━━\n"
        f"⚠️ *هیچ معامله‌ای انجام نشد*\n"
        f"🕒 {now_str}"
    )
    send_telegram_message(summary_msg)
    
    logger.info(f"[ANALYZE_24H] تحلیل کامل شد. {signal_count} سیگنال یافت شد.")
    return all_signals, signal_count

# =====================================================================================
# اجرای اصلی
# =====================================================================================
if __name__ == "__main__":
    logger.info("DTM v6 FC Bot Starting... (نسخه ۵ — Binance + TrueTrade SL/TP)")
    
    ssl_status_msg = compute_ssl_hybrid_status()
    send_telegram_message(ssl_status_msg)
    
    if os.getenv("FORCE_RESET_STATE") == "1":
        logger.info("[STARTUP] FORCE_RESET_STATE=1 → ریست دستی state")
        reset_state_for_live_mode()

    load_signal_counter()
    load_states()

    hashtag_list = "\n".join([f"• {v} → {k}" for k, v in HASHTAGS.items()])

    try:
        logger.info("[STARTUP] شروع تحلیل ۲۴ ساعت اخیر...")
        analyze_last_24h_and_send_report()
        logger.info("[STARTUP] تحلیل ۲۴ ساعت اخیر کامل شد")
    except Exception as e:
        logger.error(f"[STARTUP] خطا در تحلیل ۲۴ ساعت: {e}")
        send_telegram_message(
            f"⚠️ *خطا در تحلیل ۲۴ ساعت اخیر* {HASHTAGS['diagnostic']}\n"
            f"━━━━━━━━━━━━━━━━━━━━━━\n"
            f"📝 {str(e)[:200]}\n"
            f"🕒 {format_iran_time()}"
        )

    send_telegram_message(
        f"🤖 *DTM v6·FC — آنلاین* {HASHTAGS['startup']}\n"
        f"━━━━━━━━━━━━━━━━━━━━━━\n"
        f"🧠 سیگنال‌ها: واگرایی کلاسیک(★)/مخفی + تقاطع طلایی/مرگ\n"
        f"🔷 فیلتر SSL: {SSL_TIMEFRAME} تک‌تایم‌فریمی — فعال روی همه‌ی سیگنال‌ها\n"
        f"⚙️ Pivot: {LEFT_BARS}/{RIGHT_BARS} | دو پیوت متوالی (Pine-exact)\n"
        f"🛡️ استاپ/تارگت: **دقیقاً مطابق strategy_wrapper (R:R >= 2)**\n"
        f"🛡️ ریسک‌فری خودکار: روی سطح ساختاری (structural_level)\n"
        f"📡 دریافت داده: **بایننس** → تطبیق با دِتروترید\n"
        f"━━━━━━━━━━━━━━━━━━━━━━\n"
        f"📌 هشتگ‌های ثابت:\n{hashtag_list}\n"
        f"━━━━━━━━━━━━━━━━━━━━━━\n"
        f"📊 شمارنده سیگنال از #Signal_{SIGNAL_COUNTER + 1} شروع می‌شود\n"
        f"🕒 {format_iran_time()}"
    )

    FIRST_RUN = True
    run_startup_diagnostic()
    
    threading.Thread(target=lambda: app.run(host="0.0.0.0", port=10000), daemon=True).start()
    main_loop()
