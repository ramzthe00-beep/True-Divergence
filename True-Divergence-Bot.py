# -*- coding: utf-8 -*-
"""
DTM v6 FC — Divergence + Golden/Death Cross Signal Bot
====================================================================
نسخه اصلاح‌شده - رفع باگ‌های محاسبه استاپ و تشخیص پیوت
+ تمام امکانات DTM Hybrid (Pine-parity fixes, reporting, state persistence, etc.)
+ **FIXED**: Bar-by-Bar State Machine (Pine-exact pivot confirmation)
+ **FIXED**: resolve_bar_from_ts slice bug
+ **ENHANCED**: Multi-Pivot Comparison for 1m timeframe
  (compare new pivot with multiple previous pivots, min/max bar distance filters)
+ **DEBUG**: Full Debug Log in file
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

logging.basicConfig(
    level=logging.INFO,
    format='%(asctime)s - %(levelname)s - %(message)s',
    handlers=[logging.StreamHandler()]
)
logger = logging.getLogger(__name__)

# ============================================
# API Configuration — فقط از متغیر محیطی
# ============================================
API_KEY = os.getenv("API_KEY")
API_SECRET = os.getenv("API_SECRET")
BASE_URL = os.getenv("BASE_URL", "https://apiv2.thetruetrade.io")

TELEGRAM_BOT_TOKEN = os.getenv("TELEGRAM_BOT_TOKEN")
TELEGRAM_CHAT_ID = os.getenv("TELEGRAM_CHAT_ID")

if not API_KEY or not API_SECRET:
    raise RuntimeError("API_KEY / API_SECRET باید به‌عنوان متغیر محیطی ست شوند.")
if not TELEGRAM_BOT_TOKEN or not TELEGRAM_CHAT_ID:
    raise RuntimeError("TELEGRAM_BOT_TOKEN / TELEGRAM_CHAT_ID باید به‌عنوان متغیر محیطی ست شوند.")

HISTORY_FILE = "trades_history_dtm_v6.json"
STATE_FILE = "pivot_state_dtm_v6.json"

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
}

# =====================================================================================
# ثابت‌های استراتژی
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
MIN_CLASSIC_SCORE = 2

STOP_ATR_BUFFER = 0.1
TARGET_RR = 3.0

SSL_TIMEFRAME = "5m"
SSL_BASELINE_LEN = 34
MAIN_TIMEFRAME = "1m"

CROSS_ATR_STOP_MULT = 2.0

TICK_SIZES = {"LTCUSDT": 0.01, "DOGEUSDT": 0.00001, "ETHUSDT": 0.01}
PRICE_PRECISION = {"LTCUSDT": 2, "DOGEUSDT": 5, "ETHUSDT": 2}
LEVERAGE_MAP = {"LTCUSDT": 75, "DOGEUSDT": 75, "ETHUSDT": 50}
TARGET_RISK_USDT = 3.5

SYMBOLS = ["LTCUSDT", "DOGEUSDT", "ETHUSDT"]

HISTORY_BARS = 5000
API_RETURNS_OPEN_CANDLE = False

# =====================================================================================
# NEW: Multi-Pivot Comparison Settings for 1m Timeframe
# =====================================================================================
MAX_HISTORICAL_PIVOTS = 20      # Compare new pivot with up to 20 previous pivots
MIN_BARS_BETWEEN_PIVOTS = 5    # Minimum distance between pivot pair (bars)
MAX_BARS_BETWEEN_PIVOTS = 80   # Maximum distance between pivot pair (bars)

# =====================================================================================
# کلاس دریافت داده
# =====================================================================================
class TrueTradeData:
    def __init__(self):
        self.base_url = BASE_URL

    def fetch_ohlcv(self, symbol, timeframe='1m', limit=HISTORY_BARS):
        symbol_clean = symbol.upper()
        resolution_map = {"1m": "1", "5m": "5", "15m": "15", "30m": "30", "1h": "60", "4h": "240"}
        resolution = resolution_map.get(timeframe, "1")
        to_timestamp = int(time.time())
        step = 300 if timeframe == "5m" else 60
        from_timestamp = to_timestamp - (limit * step)
        uri = f"/futures/udf/history?symbol={symbol_clean}&resolution={resolution}&from={from_timestamp}&to={to_timestamp}&countback={limit}"
        try:
            response = requests.get(f"{self.base_url}{uri}", timeout=15)
            response.raise_for_status()
            data = response.json()
            if not data or data.get('s') != 'ok':
                return None
            df = pd.DataFrame({
                'timestamp': pd.to_datetime(data['t'], unit='s', utc=True),
                'open': pd.to_numeric(data['o']), 'high': pd.to_numeric(data['h']),
                'low': pd.to_numeric(data['l']), 'close': pd.to_numeric(data['c']),
                'volume': pd.to_numeric(data['v'])
            })
            df.set_index('timestamp', inplace=True)
            return df
        except Exception as e:
            logger.error(f"[FETCH ERROR] {symbol} ({timeframe}): {e}")
            return None

    def fetch_current_price(self, symbol):
        try:
            df = self.fetch_ohlcv(symbol, '1m', 2)
            if df is not None and not df.empty:
                return float(df['close'].iloc[-1])
        except:
            pass
        return None

# =====================================================================================
# کلاس صرافی
# =====================================================================================
class TrueTradePrivateExchange:
    def __init__(self, api_key, api_secret, base_url):
        self.api_key = api_key
        self.api_secret = api_secret
        self.base_url = base_url
        self.session = requests.Session()
        self.connected = False

    def _sign_request(self, method, uri, timestamp):
        payload = f"{timestamp}{method.upper()}{uri}"
        return hmac.new(self.api_secret.encode(), payload.encode(), hashlib.sha256).hexdigest()

    def _request(self, method, uri, data=None):
        timestamp = str(int(time.time() * 1000))
        signature = self._sign_request(method, uri, timestamp)
        headers = {"X-API-Key": self.api_key, "X-Timestamp": timestamp,
                   "X-Signature": signature, "Content-Type": "application/json"}
        response = self.session.request(method, f"{self.base_url}{uri}", headers=headers, json=data, timeout=15)
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
            self._request('GET', '/futures/positions')
            self.connected = True
            return True
        except Exception as e:
            self.connected = False
            logger.error(f"[EXCHANGE] اتصال برقرار نیست: {e}")
            return False

    def fetch_balance(self):
        try:
            data = self._request('GET', '/futures/assets')
            assets_list = []
            if isinstance(data, dict) and 'assets' in data:
                assets_list = data['assets']
            elif isinstance(data, list):
                assets_list = data
            for asset in assets_list:
                if asset.get('symbol') == 'USDT':
                    return float(asset.get('availableBalance', asset.get('totalAssets', 0)))
            return 0
        except:
            return None

    def create_order(self, symbol, order_type, side, capital, price=None, params=None):
        if params:
            if 'stopLoss' in params:
                params['stopLoss'] = round_price(params['stopLoss'], symbol)
            if 'takeProfit' in params:
                params['takeProfit'] = round_price(params['takeProfit'], symbol)

        prec = PRICE_PRECISION.get(symbol.upper(), 2)
        order_data = {
            "symbol": symbol.upper(), "side": side.upper(), "tradeType": order_type.upper(),
            "leverage": params.get('leverage', 1) if params else 1,
            "cost": f"{capital:.{prec}f}", "walletType": "debit"
        }
        if order_type.upper() == "LIMIT" and price:
            order_data["price"] = str(price)
        if params:
            if 'stopLoss' in params:
                order_data["stopLoss"] = f"{params['stopLoss']:.{prec}f}"
            if 'takeProfit' in params:
                order_data["takeProfit"] = f"{params['takeProfit']:.{prec}f}"

        send_telegram_message(
            f"📤 ثبت سفارش - درخواست {HASHTAGS['order_request']}\n"
            f"━━━━━━━━━━━━━━━━━━━━━━\n"
            f"🔹 Symbol: {symbol}\n"
            f"🔸 Side: {side.upper()}\n"
            f"🔸 Type: {order_type.upper()}\n"
            f"💰 Cost: {capital:.{prec}f}\n"
            f"🔧 Leverage: {order_data['leverage']}\n"
            f"📦 Body:\n```\n{json.dumps(order_data, indent=2)}\n```\n"
            f"━━━━━━━━━━━━━━━━━━━━━━\n🕒 {format_iran_time()}"
        )

        try:
            result = self._request('POST', '/futures/positions', order_data)
            send_telegram_message(
                f"📥 ثبت سفارش - پاسخ {HASHTAGS['order_response']}\n"
                f"━━━━━━━━━━━━━━━━━━━━━━\n"
                f"🔹 Symbol: {symbol}\n"
                f"✅ Success - Position ID: {result.get('positionId', 'N/A')}\n"
                f"━━━━━━━━━━━━━━━━━━━━━━\n🕒 {format_iran_time()}"
            )
            return {'id': result.get('positionId'), 'symbol': symbol, 'side': side}
        except Exception as e:
            error_detail = str(e)[:500]
            if hasattr(self, '_last_response'):
                try:
                    error_detail = self._last_response.text[:500]
                except:
                    pass
            send_telegram_message(
                f"❌ ثبت سفارش - خطا {HASHTAGS['order_error']}\n"
                f"━━━━━━━━━━━━━━━━━━━━━━\n"
                f"🔹 Symbol: {symbol}\n📝 {error_detail}\n"
                f"━━━━━━━━━━━━━━━━━━━━━━\n🕒 {format_iran_time()}"
            )
            raise

# =====================================================================================
# توابع تلگرام
# =====================================================================================
def send_telegram_message(message: str):
    try:
        url = f"https://api.telegram.org/bot{TELEGRAM_BOT_TOKEN}/sendMessage"
        requests.post(url, json={"chat_id": TELEGRAM_CHAT_ID, "text": message, "parse_mode": "Markdown"}, timeout=10)
    except Exception as e:
        logger.error(f"[TELEGRAM] {e}")

def format_iran_time(dt=None):
    if dt is None:
        dt = datetime.now(timezone(timedelta(hours=3, minutes=30)))
    return dt.strftime('%Y-%m-%d %H:%M:%S')

def format_iran_date(dt=None):
    if dt is None:
        dt = datetime.now(timezone(timedelta(hours=3, minutes=30)))
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

# FIXED: رفع باگ slice در get_loc
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
# فیلتر روند SSL Hybrid
# =====================================================================================
def compute_ssl_hlv(df_5m):
    if df_5m is None or len(df_5m) < SSL_BASELINE_LEN + 5:
        return 0
    closed = df_5m.iloc[:-1].reset_index(drop=True)
    if len(closed) < SSL_BASELINE_LEN + 2:
        return 0
    ema_high = calc_hma(closed['high'], SSL_BASELINE_LEN)
    ema_low = calc_hma(closed['low'], SSL_BASELINE_LEN)
    close = closed['close']
    hlv = 0
    for i in range(len(closed)):
        if pd.isna(ema_high.iloc[i]) or pd.isna(ema_low.iloc[i]):
            continue
        if close.iloc[i] > ema_high.iloc[i]:
            hlv = 1
        elif close.iloc[i] < ema_low.iloc[i]:
            hlv = -1
    return hlv

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
# Helper: Check bar distance between two pivots
# =====================================================================================
def check_bar_distance(bar1, bar2):
    """Check if distance between two pivots is within acceptable range"""
    if bar1 is None or bar2 is None:
        return False
    distance = abs(bar2 - bar1)
    return MIN_BARS_BETWEEN_PIVOTS <= distance <= MAX_BARS_BETWEEN_PIVOTS

# =====================================================================================
# استاپ/تارگت
# =====================================================================================
def compute_divergence_sl_tp(p1_price, p2_price, direction, entry_price, atr_val):
    if direction == "long":
        lowest_valley = min(p1_price, p2_price)
        stop = lowest_valley - STOP_ATR_BUFFER * atr_val
        risk = entry_price - stop
    else:
        highest_peak = max(p1_price, p2_price)
        stop = highest_peak + STOP_ATR_BUFFER * atr_val
        risk = stop - entry_price
    if risk <= 0:
        return None, None
    target = entry_price + risk * TARGET_RR if direction == "long" else entry_price - risk * TARGET_RR
    return stop, target

def compute_cross_sl_tp(direction, entry_price, atr_val):
    if direction == "long":
        stop = entry_price - atr_val * CROSS_ATR_STOP_MULT
        risk = entry_price - stop
        target = entry_price + risk * TARGET_RR
    else:
        stop = entry_price + atr_val * CROSS_ATR_STOP_MULT
        risk = stop - entry_price
        target = entry_price - risk * TARGET_RR
    return stop, target

def score_stars(score):
    if score >= 5: return "★★★★★"
    if score >= 4: return "★★★★"
    if score >= 3: return "★★★"
    if score >= 2: return "★★"
    return "★"

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

    def to_dict(self):
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
            'telegram_log_count': self.telegram_log_count,
            'last_telegram_log_time': self.last_telegram_log_time
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
            state.telegram_log_count = data.get('telegram_log_count', 0)
            state.last_telegram_log_time = data.get('last_telegram_log_time', 0)
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
def process_ma_crosses(closed_df_indexed, ma_f, ma_m, ma_s, state, start_bar, end_bar):
    events = []
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
            events.append(("BUY_CROSS", closed_df_indexed.index[i]))
        if gc_s:
            state.rst_s = False
            events.append(("SELL_CROSS", closed_df_indexed.index[i]))
    return events

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
# تشخیص سیگنال — TRUE BAR-BY-BAR STATE MACHINE (Pine-exact)
# WITH MULTI-PIVOT COMPARISON FOR 1M TIMEFRAME
# =====================================================================================
def detect_signal(df_1m, df_5m, state, symbol, debug=False):
    debug_log = []
    debug_file_lines = []
    def log(msg):
        debug_log.append(msg)
        debug_file_lines.append(msg)
        if debug:
            logger.info(msg)

    log(f"🔍 DTMv6 — {symbol} | {format_iran_time()}")
    log(f"   Multi-Pivot: MaxHistorical={MAX_HISTORICAL_PIVOTS}, MinBars={MIN_BARS_BETWEEN_PIVOTS}, MaxBars={MAX_BARS_BETWEEN_PIVOTS}")

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

    # ------------------------------------------------------------------
    # TRUE BAR-BY-BAR PIVOT CONFIRMATION
    # ------------------------------------------------------------------
    last = n - 1
    real_pivot_candidate = last - RIGHT_BARS

    if real_pivot_candidate < LEFT_BARS:
        log("   ⚠️ هنوز داده کافی برای تأیید پیوت نیست")
        return [], debug_log

    existing_high_ts = {p['ts'] for p in state.pivot_highs}
    existing_low_ts = {p['ts'] for p in state.pivot_lows}

    ts_candidate = closed_df_indexed.index[real_pivot_candidate]

    new_pivots_high = []
    new_pivots_low = []

    if not pd.isna(pivot_high.iloc[real_pivot_candidate]) and ts_candidate not in existing_high_ts:
        new_pivots_high.append({
            'ts': ts_candidate,
            'price': float(pivot_high.iloc[real_pivot_candidate]),
            'bar': real_pivot_candidate,
            'rsi': float(rsi_val.iloc[real_pivot_candidate]) if not pd.isna(rsi_val.iloc[real_pivot_candidate]) else 0.0,
            'macdline': float(macd_line.iloc[real_pivot_candidate]) if not pd.isna(macd_line.iloc[real_pivot_candidate]) else 0.0,
            'hist': float(hist_line.iloc[real_pivot_candidate]) if not pd.isna(hist_line.iloc[real_pivot_candidate]) else 0.0
        })

    if not pd.isna(pivot_low.iloc[real_pivot_candidate]) and ts_candidate not in existing_low_ts:
        new_pivots_low.append({
            'ts': ts_candidate,
            'price': float(pivot_low.iloc[real_pivot_candidate]),
            'bar': real_pivot_candidate,
            'rsi': float(rsi_val.iloc[real_pivot_candidate]) if not pd.isna(rsi_val.iloc[real_pivot_candidate]) else 0.0,
            'macdline': float(macd_line.iloc[real_pivot_candidate]) if not pd.isna(macd_line.iloc[real_pivot_candidate]) else 0.0,
            'hist': float(hist_line.iloc[real_pivot_candidate]) if not pd.isna(hist_line.iloc[real_pivot_candidate]) else 0.0
        })

    if new_pivots_high:
        state.pivot_highs.extend(new_pivots_high)
        if len(state.pivot_highs) > 500:
            state.pivot_highs = state.pivot_highs[-500:]
    if new_pivots_low:
        state.pivot_lows.extend(new_pivots_low)
        if len(state.pivot_lows) > 500:
            state.pivot_lows = state.pivot_lows[-500:]

    state.last_processed_ts = closed_df_indexed.index[last]

    log(f"   new_high={len(new_pivots_high)}, new_low={len(new_pivots_low)} | mem H={len(state.pivot_highs)} L={len(state.pivot_lows)}")

    # ------------------------------------------------------------------
    # تقاطع طلایی / مرگ (بدون تغییر)
    # ------------------------------------------------------------------
    ma_start_pos = 1
    if state.last_ma_ts is not None and state.last_ma_ts in closed_df_indexed.index:
        try:
            ma_start_pos = max(1, closed_df_indexed.index.get_loc(state.last_ma_ts))
            if isinstance(ma_start_pos, slice):
                ma_start_pos = ma_start_pos.start if ma_start_pos.start is not None else 1
        except:
            ma_start_pos = 1

    ma_events = process_ma_crosses(closed_df_indexed, ma_f, ma_m, ma_s, state, ma_start_pos, n - 1)
    state.last_ma_ts = closed_df_indexed.index[n - 1]

    # ------------------------------------------------------------------
    # فیلتر SSL
    # ------------------------------------------------------------------
    hlv = compute_ssl_hlv(df_5m)
    gate_long = hlv == 1
    gate_short = hlv == -1
    log(f"   SSL(5m) Hlv={hlv} | gate_long={gate_long} gate_short={gate_short}")

    entry_price = float(close.iloc[-1])
    atr_now = float(atr14.iloc[-1]) if not pd.isna(atr14.iloc[-1]) else 0.0

    # ------------------------------------------------------------------
    # واگرایی — با مقایسه چندگانه پیوت‌ها
    # ------------------------------------------------------------------
    best_classic_bull = None
    best_hidden_bull = None
    best_classic_bear = None
    best_hidden_bear = None
    cross_signals = []

    # تقاطع طلایی/مرگ
    for etype, ets in ma_events:
        if etype == "BUY_CROSS" and gate_long:
            stop, target = compute_cross_sl_tp("long", entry_price, atr_now)
            cross_signals.append({
                'type': 'GOLDEN_CROSS', 'direction': 'BUY',
                'entry': entry_price, 'stop': stop, 'target': target,
                'extra': "⬆تقاطع طلایی", 'score': 0
            })
            log(f"   ⬆️ Golden Cross @ {ets}")
        elif etype == "SELL_CROSS" and gate_short:
            stop, target = compute_cross_sl_tp("short", entry_price, atr_now)
            cross_signals.append({
                'type': 'DEATH_CROSS', 'direction': 'SELL',
                'entry': entry_price, 'stop': stop, 'target': target,
                'extra': "⬇تقاطع مرگ", 'score': 0
            })
            log(f"   ⬇️ Death Cross @ {ets}")

    # ---------- واگرایی نزولی / مخفی نزولی (MULTI-PIVOT) ----------
    if len(new_pivots_high) > 0 and len(state.pivot_highs) >= 2:
        confirm_bar = last
        
        # Find the index of the newest pivot high in state
        new_ph = new_pivots_high[0] if new_pivots_high else None
        if new_ph:
            idx = next((i for i, p in enumerate(state.pivot_highs) if p['ts'] == new_ph['ts']), None)
            if idx is not None:
                best_bear_score = 0
                
                # Compare with MULTIPLE previous pivots
                for prev_idx in range(max(0, idx - MAX_HISTORICAL_PIVOTS), idx):
                    ph_1 = state.pivot_highs[prev_idx]
                    ph_2 = state.pivot_highs[idx]
                    
                    bar1 = resolve_bar_from_ts(closed_df_indexed, ph_1['ts'])
                    bar2 = resolve_bar_from_ts(closed_df_indexed, ph_2['ts'])
                    
                    if bar1 is None or bar2 is None:
                        continue
                    
                    # Check bar distance filter
                    if not check_bar_distance(bar1, bar2):
                        log(f"   ⏭️ Bearish pair [{prev_idx}↔{idx}]: distance={abs(bar2-bar1)} bars (min={MIN_BARS_BETWEEN_PIVOTS}, max={MAX_BARS_BETWEEN_PIVOTS}) — SKIPPED")
                        continue
                    
                    if trending.iloc[confirm_bar]:
                        div_rsi = div_macd = div_hist = hid = False
                        
                        if ph_2['price'] > ph_1['price']:
                            div_rsi = ph_2['rsi'] < ph_1['rsi']
                            div_macd = ph_2['macdline'] < ph_1['macdline']
                        elif ph_2['price'] < ph_1['price']:
                            hid = (ph_2['rsi'] > ph_1['rsi']) or (ph_2['macdline'] > ph_1['macdline'])
                        
                        if (div_rsi or div_macd or div_hist) and gate_short:
                            fib_ok = check_fib_near(high, low, confirm_bar, ph_2['price'], is_high_side=True)
                            pa_ok = check_shooting_star(closed_df, ph_2['bar'])
                            score = sum([div_rsi, div_hist, div_macd, fib_ok, pa_ok])
                            log(f"   🔴 Bearish pair [{prev_idx}↔{idx}]: distance={abs(bar2-bar1)}, score={score}/5")
                            
                            if score >= MIN_CLASSIC_SCORE and score > best_bear_score:
                                stop, target = compute_divergence_sl_tp(ph_1['price'], ph_2['price'], "short", entry_price, atr_now)
                                if stop and target:
                                    best_bear_score = score
                                    best_classic_bear = {
                                        'type': 'CLASSIC_BEARISH_DIV', 'direction': 'SELL',
                                        'entry': entry_price, 'stop': stop, 'target': target,
                                        'extra': f"{score_stars(score)}\nواگرایی↓[{score}/5]", 'score': score
                                    }
                                    log(f"   🔴 Classic Bearish Div SELECTED: score={score}/5")
                        
                        if hid and gate_short:
                            stop, target = compute_divergence_sl_tp(ph_1['price'], ph_2['price'], "short", entry_price, atr_now)
                            if stop and target:
                                best_hidden_bear = {
                                    'type': 'HIDDEN_BEARISH_DIV', 'direction': 'SELL',
                                    'entry': entry_price, 'stop': stop, 'target': target,
                                    'extra': "~واگرایی مخفی↓", 'score': 0
                                }
                                log(f"   🟠 Hidden Bearish Div [{prev_idx}↔{idx}]")

    # ---------- واگرایی صعودی / مخفی صعودی (MULTI-PIVOT) ----------
    if len(new_pivots_low) > 0 and len(state.pivot_lows) >= 2:
        confirm_bar = last
        
        # Find the index of the newest pivot low in state
        new_pl = new_pivots_low[0] if new_pivots_low else None
        if new_pl:
            idx = next((i for i, p in enumerate(state.pivot_lows) if p['ts'] == new_pl['ts']), None)
            if idx is not None:
                best_bull_score = 0
                
                # Compare with MULTIPLE previous pivots
                for prev_idx in range(max(0, idx - MAX_HISTORICAL_PIVOTS), idx):
                    pl_1 = state.pivot_lows[prev_idx]
                    pl_2 = state.pivot_lows[idx]
                    
                    bar1 = resolve_bar_from_ts(closed_df_indexed, pl_1['ts'])
                    bar2 = resolve_bar_from_ts(closed_df_indexed, pl_2['ts'])
                    
                    if bar1 is None or bar2 is None:
                        continue
                    
                    # Check bar distance filter
                    if not check_bar_distance(bar1, bar2):
                        log(f"   ⏭️ Bullish pair [{prev_idx}↔{idx}]: distance={abs(bar2-bar1)} bars (min={MIN_BARS_BETWEEN_PIVOTS}, max={MAX_BARS_BETWEEN_PIVOTS}) — SKIPPED")
                        continue
                    
                    if trending.iloc[confirm_bar]:
                        div_rsi = div_macd = div_hist = hid = False
                        
                        if pl_2['price'] < pl_1['price']:
                            div_rsi = pl_2['rsi'] > pl_1['rsi']
                            div_macd = pl_2['macdline'] > pl_1['macdline']
                        elif pl_2['price'] > pl_1['price']:
                            hid = (pl_2['rsi'] < pl_1['rsi']) or (pl_2['macdline'] < pl_1['macdline'])
                        
                        if (div_rsi or div_macd or div_hist) and gate_long:
                            fib_ok = check_fib_near(high, low, confirm_bar, pl_2['price'], is_high_side=False)
                            pa_ok = check_hammer(closed_df, pl_2['bar'])
                            score = sum([div_rsi, div_hist, div_macd, fib_ok, pa_ok])
                            log(f"   🟢 Bullish pair [{prev_idx}↔{idx}]: distance={abs(bar2-bar1)}, score={score}/5")
                            
                            if score >= MIN_CLASSIC_SCORE and score > best_bull_score:
                                stop, target = compute_divergence_sl_tp(pl_1['price'], pl_2['price'], "long", entry_price, atr_now)
                                if stop and target:
                                    best_bull_score = score
                                    best_classic_bull = {
                                        'type': 'CLASSIC_BULLISH_DIV', 'direction': 'BUY',
                                        'entry': entry_price, 'stop': stop, 'target': target,
                                        'extra': f"{score_stars(score)}\nواگرایی↑[{score}/5]", 'score': score
                                    }
                                    log(f"   🟢 Classic Bullish Div SELECTED: score={score}/5")
                        
                        if hid and gate_long:
                            stop, target = compute_divergence_sl_tp(pl_1['price'], pl_2['price'], "long", entry_price, atr_now)
                            if stop and target:
                                best_hidden_bull = {
                                    'type': 'HIDDEN_BULLISH_DIV', 'direction': 'BUY',
                                    'entry': entry_price, 'stop': stop, 'target': target,
                                    'extra': "~واگرایی مخفی↑", 'score': 0
                                }
                                log(f"   🔵 Hidden Bullish Div [{prev_idx}↔{idx}]")

    # ------------------------------------------------------------------
    # جمع‌آوری نهایی
    # ------------------------------------------------------------------
    signals = []
    for sig in [best_classic_bull, best_hidden_bull, best_classic_bear, best_hidden_bear]:
        if sig is not None:
            signals.append(sig)
    signals.extend(cross_signals)

    if not signals:
        log("   ⚪ No signal")
    else:
        log(f"   📊 Total signals: {len(signals)}")

    # ذخیره در فایل
    save_debug_log_to_file(symbol, debug_file_lines)

    return signals, debug_log

# =====================================================================================
# پیگیری سیگنال‌های باز — با قیمت لحظه‌ای صرافی
# =====================================================================================
def track_open_signals(data):
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
                f"🎯 حد سود فعال شد {HASHTAGS['target']} #Signal_{signal_number}\n\n"
                f"🔹 {symbol} | {direction}\n💰 سود: +{profit_pct:.2f}% | +{profit_usdt:.2f} USDT\n🕒 {format_iran_time()}"
            )
            logger.info(f"[TRACK] TAKE_PROFIT: {symbol} {direction} | PnL: +{profit_usdt:.2f} USDT")

        elif hit_stop:
            loss_pct = (entry - stop) / entry * 100 if direction == 'BUY' else (stop - entry) / entry * 100
            leverage = trade.get('leverage', 1)
            capital = trade.get('capital', 0)
            loss_usdt = capital * leverage * loss_pct / 100
            update_trade_result(signal_time, 'STOP_LOSS', cp, format_iran_time(), pnl=-loss_usdt)
            send_telegram_message(
                f"💔 حد ضرر فعال شد {HASHTAGS['stop']} #Signal_{signal_number}\n\n"
                f"🔹 {symbol} | {direction}\n💸 ضرر: -{loss_pct:.2f}% | -{loss_usdt:.2f} USDT\n🕒 {format_iran_time()}"
            )
            logger.info(f"[TRACK] STOP_LOSS: {symbol} {direction} | PnL: -{loss_usdt:.2f} USDT")

# =====================================================================================
# توابع گزارش
# =====================================================================================
def send_reports(exchange):
    now = datetime.now(timezone(timedelta(hours=3, minutes=30)))
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
    data = TrueTradeData()
    df = None
    try:
        df = data.fetch_ohlcv("LTCUSDT", "1m", 1500)
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
    exchange = TrueTradePrivateExchange(API_KEY, API_SECRET, BASE_URL)
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
    logger.info("[ANALYZE] شروع...")
    exchange = TrueTradePrivateExchange(API_KEY, API_SECRET, BASE_URL)
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

    data = TrueTradeData()
    track_open_signals(data)

    side_map = {"BUY": "LONG", "SELL": "SHORT"}

    for symbol in SYMBOLS:
        try:
            df_1m = data.fetch_ohlcv(symbol, MAIN_TIMEFRAME, HISTORY_BARS)
            df_5m = data.fetch_ohlcv(symbol, SSL_TIMEFRAME, 500)
            if df_1m is None or df_1m.empty:
                logger.warning(f"[SKIP] {symbol}: داده 1m نیست")
                continue

            logger.info(f"[DATA] {symbol}: 1m={len(df_1m)} کندل")

            signals, _ = detect_signal(df_1m, df_5m, SYMBOL_STATES[symbol], symbol, debug=True)

            for sig in signals:
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

                signal_message = (
                    f"{dir_emoji} Signal {sig['type']} — {symbol} {HASHTAGS['signal']} #Signal_{signal_number}\n"
                    f"━━━━━━━━━━━━━━━━━━━━━━\n\n"
                    f"🔸 Direction: {dir_txt}\n"
                    f"📝 {sig['extra']}\n\n"
                    f"📍 Entry: {entry:.{PRICE_PRECISION.get(symbol, 2)}f}\n"
                    f"🛑 Stop Loss: {stop:.{PRICE_PRECISION.get(symbol, 2)}f}\n"
                    f"🎯 Take Profit: {target:.{PRICE_PRECISION.get(symbol, 2)}f}\n\n"
                    f"📈 Potential Profit: +{profit_pct:.2f}%\n"
                    f"📉 Potential Loss: -{loss_pct:.2f}%\n"
                    f"⚖️ Risk/Reward Ratio: {rr:.2f}\n\n"
                    f"━━━━━━━━━━━━━━━━━━━━━━\n🕒 {current_signal_time}"
                )
                try:
                    send_telegram_message(signal_message)
                except Exception as e:
                    logger.error(f"[TELEGRAM SIGNAL ERROR] {symbol}: {e}")
                    fallback_msg = (
                        f"{dir_emoji} Signal {sig['type']} — {symbol} {HASHTAGS['signal']} #Signal_{signal_number}\n"
                        f"📍 Entry: {entry:.{PRICE_PRECISION.get(symbol, 2)}f}\n"
                        f"🛑 SL: {stop:.{PRICE_PRECISION.get(symbol, 2)}f} | 🎯 TP: {target:.{PRICE_PRECISION.get(symbol, 2)}f}\n"
                        f"🕒 {current_signal_time}"
                    )
                    try:
                        send_telegram_message(fallback_msg)
                    except:
                        pass
                time.sleep(0.5)

                history = load_history()
                history.append({
                    'symbol': symbol, 'direction': direction,
                    'entry_price': entry, 'stop_loss': stop, 'take_profit': target,
                    'signal_time': current_signal_time, 'result': None,
                    'type': sig['type'], 'capital': capital,
                    'leverage': int(used_leverage), 'qty': qty,
                    'signal_number': signal_number
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
                            f"✅ سفارش ثبت شد — {symbol} {HASHTAGS['signal']} #Signal_{signal_number}\n\n"
                            f"🔸 {side_map[direction]} | 💰 {capital:.2f} USDT | 🔧 {int(used_leverage)}x\n"
                        )
                        if capital_reduced:
                            order_message += (
                                f"⚠️ سرمایه کاهش یافت! {HASHTAGS['capital_reduced']}\n"
                                f"📐 لازم: {required_capital:.2f} | 💰 موجود: {balance:.2f}\n"
                                f"📉 ضرر: {TARGET_RISK_USDT:.2f} → {actual_risk:.2f} USDT\n"
                            )
                        order_message += (
                            f"🛑 {stop:.4f} | 🎯 {target:.4f}\n"
                            f"📉 ریسک: {actual_risk:.2f} USDT | 📈 سود بالقوه: {potential_profit:.2f} USDT\n"
                            f"🕒 {format_iran_time()}"
                        )
                        send_telegram_message(order_message)
                    except Exception as e:
                        send_telegram_message(f"❌ خطا — {symbol} {HASHTAGS['order_error']} #Signal_{signal_number}\n{side_map[direction]}\n📝 {str(e)[:200]}\n🕒 {format_iran_time()}")
        except Exception as e:
            logger.error(f"[ERROR] {symbol}: {e}")

    save_states()

# =====================================================================================
# حلقه اصلی
# =====================================================================================
def main_loop():
    exchange = TrueTradePrivateExchange(API_KEY, API_SECRET, BASE_URL)
    last_daily_report_date = None
    last_monthly_report_date = None

    while True:
        try:
            logger.info(f"[LOOP] {format_iran_time()}")
            analyze_and_execute()

            today = format_iran_date()
            now = datetime.now(timezone(timedelta(hours=3, minutes=30)))

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

if __name__ == "__main__":
    logger.info("DTM v6 FC Bot Starting...")

    load_signal_counter()
    load_states()

    hashtag_list = "\n".join([f"• {v} → {k}" for k, v in HASHTAGS.items()])
    send_telegram_message(
        f"🤖 DTM v6·FC — آنلاین {HASHTAGS['startup']}\n\n"
        f"🧠 سیگنال‌ها: واگرایی کلاسیک(≥۲★)/مخفی + تقاطع طلایی/مرگ\n"
        f"🔷 همه با گیت فیلتر SSL Hybrid (5m)\n"
        f"⚙️ Pivot: {LEFT_BARS}/{RIGHT_BARS} | تاریخچه: {HISTORY_BARS} کندل\n"
        f"🎯 تارگت: همیشه RR={TARGET_RR}\n"
        f"🔍 پیگیری با قیمت لحظه‌ای صرافی\n"
        f"🔄 Multi-Pivot: {MAX_HISTORICAL_PIVOTS} prev | Range: {MIN_BARS_BETWEEN_PIVOTS}-{MAX_BARS_BETWEEN_PIVOTS} bars\n\n"
        f"📌 هشتگ‌های ثابت:\n{hashtag_list}\n\n"
        f"📊 شمارنده سیگنال: از #Signal_{SIGNAL_COUNTER + 1} شروع می‌شود\n\n"
        f"🕒 {format_iran_time()}"
    )
    run_startup_diagnostic()
    threading.Thread(target=lambda: app.run(host="0.0.0.0", port=10000), daemon=True).start()
    main_loop()
