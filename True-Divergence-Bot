# -*- coding: utf-8 -*-
"""
DTM v6 FC — Divergence + Golden/Death Cross Signal Bot
====================================================================
ترجمه‌ی مستقیم و وفادار از Pine Script "DTM — ثبت سوم"
فقط: واگرایی کلاسیک/مخفی + تقاطع طلایی/مرگ (CT, OC, H&S, DT/DB, Combo حذف شدند)

تنظیمات قطعی:
- Pivot: Left=5 (i_pl پیش‌فرض), Right=2 (i_pr)
- تایم‌فریم اصلی تحلیل: 1 دقیقه
- SSL Hybrid: i_rssl_mode="فقط تایم فریم ۱"، TF1=5 دقیقه
- i_lbl_gate=TRUE → همه‌ی ۶ نوع برچسب اول باید از فیلتر SSL هم‌جهت رد شوند
- واگرایی کلاسیک: فقط با امتیاز >= 2 ("۲ ستاره یا بیشتر")
- واگرایی مخفی: بدون آستانه امتیاز (در پاین ستاره ندارد)

⚠️ باگ عمدی حفظ‌شده از پاین (طبق دستور صریح "عیناً ترجمه کن"):
p_hi_bar/p_lo_bar هر کندل بدون شرط ریست می‌شوند (p_hi_bar := bar_index - i_pr)،
بنابراین شرط "bar_index > p_hi_bar + i_pr" هرگز true نمی‌شود و min_h_ph/max_h_pl
هیچ‌وقت واقعاً بین دو پیوت ردیابی نمی‌شوند — همیشه دقیقاً برابر c_hi_hst/c_lo_hst
باقی می‌مانند. این ریاضیاتاً غیرممکن می‌کند که c_hi_hst>0 و min_h_ph<0 همزمان
برقرار باشند. نتیجه: div_b_hist و div_u_hist همیشه False هستند و حداکثر امتیاز
عملی سیستم 4/5 است، نه 5/5.

استاپ واگرایی کلاسیک: فقط از پیوت تازه (c_hi/c_lo) ± 0.1×ATR — sl_b_ref/sl_u_ref پاین.
استاپ واگرایی مخفی: پاین SL مستقلی برایش ندارد (چون هرگز به‌تنهایی entry نمی‌داد)؛
همان فرمول پیوت‌تازه±0.1×ATR اعمال شده (طبق دستور قبلی: "مثل واگرایی کلاسیک").
استاپ تقاطع طلایی/مرگ: پاین هیچ SL برایش ندارد (هرگز به‌تنهایی entry نمی‌داد)؛
فرض مستقل من: 2×ATR — این از پاین نیامده.
تارگت: همیشه RR=3.0 برای همه (دستور صریح کاربر، جایگزین فرمول tp_div داخلی پاین).
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
# API Configuration
# ============================================
API_KEY = os.getenv("API_KEY", "J_MHpF-VbA59rq_oZIlSwIk76MBhYm3h_Ggn3lnS")
API_SECRET = os.getenv("API_SECRET", "eE9Ew_BHqC9x-u2TDvhhTyk8YCv5iKGP70vI6cf4")
BASE_URL = "https://apiv2.thetruetrade.io"



TELEGRAM_BOT_TOKEN = os.getenv("TELEGRAM_BOT_TOKEN","8942274184:AAFK2GbImsNiK57EyBTY702ha6GO291qPLw")
TELEGRAM_CHAT_ID = os.getenv("TELEGRAM_CHAT_ID", "7402770612")



HISTORY_FILE = "trades_history_dtm_v6.json"

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

MA_FAST_LEN, MA_MID_LEN, MA_SLOW_LEN = 7, 25, 99   # EMA — i_mat پیش‌فرض

FIB_TOLERANCE_PCT = 1.5
MIN_CLASSIC_SCORE = 2   # "۲ ستاره یا بیشتر"

STOP_ATR_BUFFER = 0.1
TARGET_RR = 3.0

SSL_TIMEFRAME = "5m"
SSL_BASELINE_LEN = 34
MAIN_TIMEFRAME = "1m"

CROSS_ATR_STOP_MULT = 2.0  # فرض مستقل من — پاین برای gc_l/gc_s تنها SL ندارد

TICK_SIZES = {"LTCUSDT": 0.01, "DOGEUSDT": 0.00001, "ETHUSDT": 0.01}
PRICE_PRECISION = {"LTCUSDT": 2, "DOGEUSDT": 5, "ETHUSDT": 2}
LEVERAGE_MAP = {"LTCUSDT": 75, "DOGEUSDT": 75, "ETHUSDT": 50}
TARGET_RISK_USDT = 3.5

SYMBOLS = ["LTCUSDT", "DOGEUSDT", "ETHUSDT"]

# =====================================================================================
# کلاس دریافت داده
# =====================================================================================
class TrueTradeData:
    def __init__(self):
        self.base_url = BASE_URL

    def fetch_ohlcv(self, symbol, timeframe='1m', limit=500):
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
                'timestamp': pd.to_datetime(data['t'], unit='s'),
                'open': pd.to_numeric(data['o']), 'high': pd.to_numeric(data['h']),
                'low': pd.to_numeric(data['l']), 'close': pd.to_numeric(data['c']),
                'volume': pd.to_numeric(data['v'])
            })
            df.set_index('timestamp', inplace=True)
            return df
        except Exception as e:
            logger.error(f"[FETCH ERROR] {symbol} ({timeframe}): {e}")
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
            data = self._request('GET', '/accounting/assets')
            if isinstance(data, list):
                for asset in data:
                    if asset.get('asset') == 'USDT' and asset.get('accountType') == 'futures':
                        return float(asset.get('balance', 0))
            return 0
        except:
            return None

    def create_order(self, symbol, order_type, side, amount, price=None, params=None):
        order_data = {
            "symbol": symbol.upper(), "side": side.upper(), "tradeType": order_type.upper(),
            "leverage": params.get('leverage', 1) if params else 1,
            "size": str(amount), "walletType": "debit"
        }
        if order_type.upper() == "LIMIT" and price:
            order_data["price"] = str(price)
        if params:
            if 'stopLoss' in params:
                order_data["stopLoss"] = str(params['stopLoss'])
            if 'takeProfit' in params:
                order_data["takeProfit"] = str(params['takeProfit'])
        result = self._request('POST', '/futures/positions', order_data)
        return {'id': result.get('positionId'), 'symbol': symbol, 'side': side}

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

def round_price(price, symbol):
    precision = PRICE_PRECISION.get(symbol.upper(), 2)
    tick = TICK_SIZES.get(symbol.upper(), 0.01)
    return round(round(price / tick) * tick, precision)

# =====================================================================================
# توابع محاسباتی پایه
# =====================================================================================
def calc_rsi(close, length=14):
    delta = close.diff()
    gain = delta.clip(lower=0)
    loss = -delta.clip(upper=0)
    avg_gain = gain.ewm(alpha=1.0/length, min_periods=length, adjust=False).mean()
    avg_loss = loss.ewm(alpha=1.0/length, min_periods=length, adjust=False).mean()
    rs = avg_gain / avg_loss.replace(0, np.nan)
    return (100 - (100 / (1 + rs))).fillna(50)

def calc_ema(series, length):
    return series.ewm(span=length, adjust=False).mean()

def calc_macd(close, fast=12, slow=26, signal=9):
    ema_fast = calc_ema(close, fast)
    ema_slow = calc_ema(close, slow)
    macd_line = ema_fast - ema_slow
    signal_line = calc_ema(macd_line, signal)
    return macd_line, signal_line, macd_line - signal_line

def calc_atr(high, low, close, length=14):
    prev_close = close.shift(1)
    tr = pd.concat([high-low, (high-prev_close).abs(), (low-prev_close).abs()], axis=1).max(axis=1)
    return tr.ewm(alpha=1.0/length, min_periods=length, adjust=False).mean()

def calc_adx(high, low, close, length=14):
    """معادل ta.dmi(14,14) — Wilder smoothing (RMA) از طریق ewm با alpha=1/length"""
    up_move = high.diff()
    down_move = -low.diff()
    plus_dm = pd.Series(np.where((up_move > down_move) & (up_move > 0), up_move, 0.0), index=high.index)
    minus_dm = pd.Series(np.where((down_move > up_move) & (down_move > 0), down_move, 0.0), index=high.index)
    prev_close = close.shift(1)
    tr = pd.concat([high-low, (high-prev_close).abs(), (low-prev_close).abs()], axis=1).max(axis=1)
    atr_ = tr.ewm(alpha=1.0/length, min_periods=length, adjust=False).mean()
    plus_di = 100 * (plus_dm.ewm(alpha=1.0/length, min_periods=length, adjust=False).mean() / atr_.replace(0, np.nan))
    minus_di = 100 * (minus_dm.ewm(alpha=1.0/length, min_periods=length, adjust=False).mean() / atr_.replace(0, np.nan))
    dx = 100 * (plus_di - minus_di).abs() / (plus_di + minus_di).replace(0, np.nan)
    adx = dx.ewm(alpha=1.0/length, min_periods=length, adjust=False).mean()
    return adx.fillna(0)

def calc_wma(series, length):
    weights = np.arange(1, length + 1)
    return series.rolling(length).apply(lambda x: np.dot(x, weights) / weights.sum(), raw=True)

def calc_hma(series, length):
    """Hull MA — برای Baseline فیلتر SSL Hybrid (i_rssl_matype='HMA')"""
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
    if ts not in df_indexed.index:
        return None
    return df_indexed.index.get_loc(ts)

# =====================================================================================
# فیلتر روند SSL Hybrid — فقط TF1=5m (i_rssl_mode="فقط تایم فریم ۱")
# Hlv: close > HMA(high,34) -> 1 ; close < HMA(low,34) -> -1 ; وگرنه sticky (مقدار قبلی)
# مقدار کندل بسته‌شده‌ی آخر برمی‌گردد (معادل استفاده‌ی Hlv[1] در پاین برای ضدـripaint)
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
# فیبوناچی (امتیاز ۴) — دقیقاً مطابق fib_lookback/fib618/fib786 پاین
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

# =====================================================================================
# پرایس‌اکشن (Shooting Star / Hammer) — دقیقاً روی خودِ کندل پیوت (high[i_pr] و ...)
# =====================================================================================
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
# استاپ/تارگت
# =====================================================================================
def compute_divergence_sl_tp(fresh_pivot_price, direction, entry_price, atr_val):
    """فقط از پیوت تازه ± 0.1×ATR — دقیقاً sl_b_ref/sl_u_ref پاین"""
    if direction == "long":
        stop = fresh_pivot_price - STOP_ATR_BUFFER * atr_val
        risk = entry_price - stop
    else:
        stop = fresh_pivot_price + STOP_ATR_BUFFER * atr_val
        risk = stop - entry_price
    if risk <= 0:
        return None, None
    target = entry_price + risk * TARGET_RR if direction == "long" else entry_price - risk * TARGET_RR
    return stop, target

def compute_cross_sl_tp(direction, entry_price, atr_val):
    """فرض مستقل من — پاین برای gc_l/gc_s تنها SL تعریف نکرده"""
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
    """دقیقاً همان نردبان ستاره‌ی پاین (5 عملاً غیرقابل‌دستیابی است، اما نردبان حفظ شده)"""
    if score >= 5: return "★★★★★"
    if score >= 4: return "★★★★"
    if score >= 3: return "★★★"
    if score >= 2: return "★★"
    return "★"

# =====================================================================================
# کلاس وضعیت
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

SYMBOL_STATES = {s: SymbolState() for s in SYMBOLS}

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

def update_trade_result(symbol, stime, result, price):
    h = load_history()
    for t in h:
        if t['symbol'] == symbol and t['signal_time'] == stime:
            t['result'] = result
            t['close_price'] = price
            t['close_time'] = format_iran_time()
    save_history(h)

# =====================================================================================
# تقاطع طلایی/مرگ — دقیقاً مطابق rst_l/rst_s/xup/xdn/gc_l/gc_s پاین
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
# تشخیص سیگنال — دقیقاً منطبق با لحظه‌ی ظاهر شدن برچسب در پاین + گیت SSL روی هر ۶ نوع
# =====================================================================================
def detect_signal(df_1m, df_5m, state, symbol, debug=False):
    debug_log = []
    def log(msg):
        debug_log.append(msg)
        if debug:
            logger.info(msg)

    log(f"🔍 DTMv6 — {symbol} | {format_iran_time()}")

    closed_df_indexed = df_1m.iloc[:-1].copy()
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
    last_valid_pivot_index = n - RIGHT_BARS - 1

    existing_high_ts = {p['ts'] for p in state.pivot_highs}
    existing_low_ts = {p['ts'] for p in state.pivot_lows}

    if state.last_processed_ts is None:
        start_bar = 0
    else:
        if state.last_processed_ts in closed_df_indexed.index:
            last_pos = closed_df_indexed.index.get_loc(state.last_processed_ts)
            start_bar = max(0, last_pos - 5)
        else:
            start_bar = max(0, n - 10)
    start_bar = min(start_bar, last_valid_pivot_index)

    log(f"   n={n}, last_valid={last_valid_pivot_index}, start={start_bar}")

    new_pivots_high, new_pivots_low = [], []
    for i in range(start_bar, last_valid_pivot_index + 1):
        ts = closed_df_indexed.index[i]
        if not pd.isna(pivot_high.iloc[i]) and ts not in existing_high_ts:
            new_pivots_high.append({'ts': ts, 'price': pivot_high.iloc[i], 'bar': i,
                                     'rsi': rsi_val.iloc[i], 'macdline': macd_line.iloc[i], 'hist': hist_line.iloc[i]})
        if not pd.isna(pivot_low.iloc[i]) and ts not in existing_low_ts:
            new_pivots_low.append({'ts': ts, 'price': pivot_low.iloc[i], 'bar': i,
                                    'rsi': rsi_val.iloc[i], 'macdline': macd_line.iloc[i], 'hist': hist_line.iloc[i]})

    if n > 0:
        state.last_processed_ts = closed_df_indexed.index[min(last_valid_pivot_index, n-1)]

    state.pivot_highs.extend(new_pivots_high)
    state.pivot_lows.extend(new_pivots_low)
    if len(state.pivot_highs) > 100:
        state.pivot_highs = state.pivot_highs[-100:]
    if len(state.pivot_lows) > 100:
        state.pivot_lows = state.pivot_lows[-100:]

    log(f"   new_high={len(new_pivots_high)}, new_low={len(new_pivots_low)} | mem: H={len(state.pivot_highs)} L={len(state.pivot_lows)}")

    # ── تقاطع طلایی/مرگ ─────────────────────────────────────────────────
    ma_start_pos = 1
    if state.last_ma_ts is not None and state.last_ma_ts in closed_df_indexed.index:
        ma_start_pos = max(1, closed_df_indexed.index.get_loc(state.last_ma_ts))
    ma_events = process_ma_crosses(closed_df_indexed, ma_f, ma_m, ma_s, state, ma_start_pos, n - 1)
    state.last_ma_ts = closed_df_indexed.index[n - 1]

    # ── فیلتر SSL Hybrid (5m، فقط TF1) — i_lbl_gate=true: گیت روی همه‌ی ۶ برچسب ──
    hlv = compute_ssl_hlv(df_5m)
    gate_long = hlv == 1
    gate_short = hlv == -1
    log(f"   SSL(5m) Hlv={hlv} | gate_long={gate_long} gate_short={gate_short}")

    entry_price = close.iloc[-1]
    signals = []

    # ── تقاطع طلایی/مرگ → سیگنال (فقط هم‌جهت با گیت) ───────────────────
    for etype, ets in ma_events:
        if etype == "BUY_CROSS" and gate_long:
            stop, target = compute_cross_sl_tp("long", entry_price, atr14.iloc[-1])
            signals.append({'type': 'GOLDEN_CROSS', 'direction': 'BUY', 'entry': entry_price,
                             'stop': stop, 'target': target, 'extra': "⬆تقاطع طلایی"})
            log(f"   ⬆️ Golden Cross @ {ets} (gate_long=True)")
        elif etype == "SELL_CROSS" and gate_short:
            stop, target = compute_cross_sl_tp("short", entry_price, atr14.iloc[-1])
            signals.append({'type': 'DEATH_CROSS', 'direction': 'SELL', 'entry': entry_price,
                             'stop': stop, 'target': target, 'extra': "⬇تقاطع مرگ"})
            log(f"   ⬇️ Death Cross @ {ets} (gate_short=True)")

    # ── واگرایی نزولی/مخفی‌نزولی (پیوت‌های های تازه) ────────────────────
    for new_ph in new_pivots_high:
        if len(state.pivot_highs) < 2:
            continue
        idx = next((i for i, p in enumerate(state.pivot_highs) if p['ts'] == new_ph['ts']), None)
        if idx is None or idx == 0:
            continue
        p1, p2 = state.pivot_highs[idx - 1], state.pivot_highs[idx]
        bar1 = resolve_bar_from_ts(closed_df_indexed, p1['ts'])
        bar2 = resolve_bar_from_ts(closed_df_indexed, p2['ts'])
        if bar1 is None or bar2 is None:
            continue
        confirm_bar2 = min(bar2 + RIGHT_BARS, n - 1)
        if not trending.iloc[confirm_bar2]:
            continue

        div_rsi = div_macd = hid = False
        div_hist = False  # ⚠️ همیشه False — باگ پاین عیناً حفظ شده (توضیح بالای فایل)

        if p2['price'] > p1['price']:  # priceHigherHigh → واگرایی کلاسیک نزولی
            div_rsi = p2['rsi'] < p1['rsi']
            div_macd = p2['macdline'] < p1['macdline']
        elif p2['price'] < p1['price']:  # priceLowerHigh → واگرایی مخفی نزولی
            hid = p2['rsi'] > p1['rsi'] or p2['macdline'] > p1['macdline']

        if div_rsi or div_macd or div_hist:  # برچسب کلاسیک ظاهر می‌شود
            fib_ok = check_fib_near(high, low, confirm_bar2, p2['price'], is_high_side=True)
            pa_ok = check_shooting_star(closed_df, bar2)
            score = sum([div_rsi, div_hist, div_macd, fib_ok, pa_ok])
            if score >= MIN_CLASSIC_SCORE and gate_short:   # ✅ "۲ ستاره یا بیشتر" + گیت SSL
                stop, target = compute_divergence_sl_tp(p2['price'], "short", entry_price, atr14.iloc[-1])
                if stop and target:
                    signals.append({'type': 'CLASSIC_BEARISH_DIV', 'direction': 'SELL', 'entry': entry_price,
                                     'stop': stop, 'target': target,
                                     'extra': f"{score_stars(score)}\nواگرایی↓[{score}/5]"})
                    log(f"   🔴 Classic Bearish Div score={score}/5 (gate_short=True)")
            else:
                log(f"   🔴 Classic Bearish Div score={score}/5 — رد شد (score<2 یا gate_short=False)")

        if hid and gate_short:   # ✅ واگرایی مخفی — بدون آستانه امتیاز، فقط گیت SSL
            stop, target = compute_divergence_sl_tp(p2['price'], "short", entry_price, atr14.iloc[-1])
            if stop and target:
                signals.append({'type': 'HIDDEN_BEARISH_DIV', 'direction': 'SELL', 'entry': entry_price,
                                 'stop': stop, 'target': target, 'extra': "~واگرایی مخفی↓"})
                log(f"   🟠 Hidden Bearish Div (gate_short=True)")

    # ── واگرایی صعودی/مخفی‌صعودی (پیوت‌های لو تازه) ─────────────────────
    for new_pl in new_pivots_low:
        if len(state.pivot_lows) < 2:
            continue
        idx = next((i for i, p in enumerate(state.pivot_lows) if p['ts'] == new_pl['ts']), None)
        if idx is None or idx == 0:
            continue
        p1, p2 = state.pivot_lows[idx - 1], state.pivot_lows[idx]
        bar1 = resolve_bar_from_ts(closed_df_indexed, p1['ts'])
        bar2 = resolve_bar_from_ts(closed_df_indexed, p2['ts'])
        if bar1 is None or bar2 is None:
            continue
        confirm_bar2 = min(bar2 + RIGHT_BARS, n - 1)
        if not trending.iloc[confirm_bar2]:
            continue

        div_rsi = div_macd = hid = False
        div_hist = False  # ⚠️ همیشه False — باگ پاین عیناً حفظ شده

        if p2['price'] < p1['price']:  # priceLowerLow → واگرایی کلاسیک صعودی
            div_rsi = p2['rsi'] > p1['rsi']
            div_macd = p2['macdline'] > p1['macdline']
        elif p2['price'] > p1['price']:  # priceHigherLow → واگرایی مخفی صعودی
            hid = p2['rsi'] < p1['rsi'] or p2['macdline'] < p1['macdline']

        if div_rsi or div_macd or div_hist:
            fib_ok = check_fib_near(high, low, confirm_bar2, p2['price'], is_high_side=False)
            pa_ok = check_hammer(closed_df, bar2)
            score = sum([div_rsi, div_hist, div_macd, fib_ok, pa_ok])
            if score >= MIN_CLASSIC_SCORE and gate_long:
                stop, target = compute_divergence_sl_tp(p2['price'], "long", entry_price, atr14.iloc[-1])
                if stop and target:
                    signals.append({'type': 'CLASSIC_BULLISH_DIV', 'direction': 'BUY', 'entry': entry_price,
                                     'stop': stop, 'target': target,
                                     'extra': f"{score_stars(score)}\nواگرایی↑[{score}/5]"})
                    log(f"   🟢 Classic Bullish Div score={score}/5 (gate_long=True)")
            else:
                log(f"   🟢 Classic Bullish Div score={score}/5 — رد شد (score<2 یا gate_long=False)")

        if hid and gate_long:
            stop, target = compute_divergence_sl_tp(p2['price'], "long", entry_price, atr14.iloc[-1])
            if stop and target:
                signals.append({'type': 'HIDDEN_BULLISH_DIV', 'direction': 'BUY', 'entry': entry_price,
                                 'stop': stop, 'target': target, 'extra': "~واگرایی مخفی↑"})
                log(f"   🔵 Hidden Bullish Div (gate_long=True)")

    if not signals:
        log("   ⚪ No signal")

    # ⚡ لاگ تلگرام
    current_time = time.time()
    should_send = False
    if state.telegram_log_count < 10:
        if state.last_telegram_log_time == 0 or (current_time - state.last_telegram_log_time) >= 300:
            should_send = True
    else:
        if current_time - state.last_telegram_log_time >= 21600:
            should_send = True
    if should_send:
        state.last_telegram_log_time = current_time
        state.telegram_log_count += 1
        try:
            telegram_debug = "\n".join(debug_log)
            send_telegram_message(f"ℹ️ لاگ #{state.telegram_log_count} — {symbol}\n```\n{telegram_debug[:3000]}\n```")
        except Exception as e:
            logger.error(f"[TELEGRAM] {e}")

    return signals, debug_log

# =====================================================================================
# پیگیری سیگنال‌های باز
# =====================================================================================
def track_open_signals():
    history = load_history()
    data = TrueTradeData()
    for trade in history:
        if trade.get('result') is None:
            df = data.fetch_ohlcv(trade['symbol'], '1m', 10)
            if df is None or df.empty:
                continue
            cp = df['close'].iloc[-1]
            entry, stop, target = trade['entry_price'], trade['stop_loss'], trade['take_profit']
            direction = trade['direction']
            if direction == 'BUY':
                if cp >= target:
                    update_trade_result(trade['symbol'], trade['signal_time'], 'TAKE_PROFIT', cp)
                    send_telegram_message(f"🎯 تارگت خورد | {trade['symbol']} LONG | سود: +{(cp-entry)/entry*100:.2f}%")
                elif cp <= stop:
                    update_trade_result(trade['symbol'], trade['signal_time'], 'STOP_LOSS', cp)
                    send_telegram_message(f"💔 استاپ خورد | {trade['symbol']} LONG | ضرر: {(cp-entry)/entry*100:.2f}%")
            else:
                if cp <= target:
                    update_trade_result(trade['symbol'], trade['signal_time'], 'TAKE_PROFIT', cp)
                    send_telegram_message(f"🎯 تارگت خورد | {trade['symbol']} SHORT | سود: +{(entry-cp)/entry*100:.2f}%")
                elif cp >= stop:
                    update_trade_result(trade['symbol'], trade['signal_time'], 'STOP_LOSS', cp)
                    send_telegram_message(f"💔 استاپ خورد | {trade['symbol']} SHORT | ضرر: {(entry-cp)/entry*100:.2f}%")

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

    data = TrueTradeData()
    track_open_signals()

    side_map = {"BUY": "LONG", "SELL": "SHORT"}

    for symbol in SYMBOLS:
        try:
            df_1m = data.fetch_ohlcv(symbol, MAIN_TIMEFRAME, 500)
            df_5m = data.fetch_ohlcv(symbol, SSL_TIMEFRAME, 200)
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
                dir_txt = "🟢 LONG (خرید)" if direction == "BUY" else "🔴 SHORT (فروش)"

                send_telegram_message(
                    f"🚨 سیگنال {sig['type']} — {symbol}\n"
                    f"━━━━━━━━━━━━━━━━━━━━━━\n"
                    f"🔸 {dir_txt}\n"
                    f"📝 {sig['extra']}\n\n"
                    f"📍 ورود: {entry}\n🛑 استاپ: {stop}\n🎯 تارگت (RR=3): {target}\n\n"
                    f"📈 سود: +{profit_pct:.2f}% | 📉 ضرر: -{loss_pct:.2f}%\n"
                    f"━━━━━━━━━━━━━━━━━━━━━━\n🕒 {format_iran_time()}"
                )

                history = load_history()
                history.append({
                    'symbol': symbol, 'direction': direction, 'type': sig['type'],
                    'entry_price': entry, 'stop_loss': stop, 'take_profit': target,
                    'signal_time': format_iran_time(), 'result': None
                })
                save_history(history)

                if exchange.connected:
                    try:
                        leverage = LEVERAGE_MAP.get(symbol, 50)
                        stop_pct = abs(entry - stop) / entry
                        old_leverage = 1.0 / stop_pct if stop_pct > 0 else 999999
                        if old_leverage <= leverage:
                            required_capital = TARGET_RISK_USDT
                            used_leverage = old_leverage
                        else:
                            required_capital = TARGET_RISK_USDT * (old_leverage / leverage)
                            used_leverage = leverage
                        capital = min(required_capital, balance) if balance > 0 else required_capital
                        qty = (capital * used_leverage) / entry

                        exchange.create_order(symbol, "market", side_map[direction], qty, None,
                                               {'leverage': int(used_leverage), 'stopLoss': stop, 'takeProfit': target})
                        send_telegram_message(f"✅ سفارش ثبت شد | {symbol} | حجم: {qty:.6f} | لوریج: {int(used_leverage)}x")
                    except Exception as e:
                        send_telegram_message(f"❌ خطای ثبت سفارش | {symbol}: {str(e)[:200]}")

        except Exception as e:
            logger.error(f"[ERROR] {symbol}: {e}")

# =====================================================================================
# حلقه اصلی
# =====================================================================================
def main_loop():
    while True:
        try:
            logger.info(f"[LOOP] {format_iran_time()}")
            analyze_and_execute()
            time.sleep(60)
        except Exception as e:
            logger.error(f"[LOOP] {e}")
            time.sleep(60)

app = Flask(__name__)
@app.route("/")
def health():
    return "DTM v6 FC Bot running.", 200

if __name__ == "__main__":
    logger.info("DTM v6 FC Bot Starting...")
    send_telegram_message(
        "🤖 DTM v6·FC — آنلاین\n\n"
        "🧠 سیگنال‌ها: واگرایی کلاسیک(≥۲★)/مخفی + تقاطع طلایی/مرگ\n"
        "🔷 همه با گیت فیلتر SSL Hybrid (5m، فقط TF1)\n"
        "⚙️ Pivot: Left=5, Right=2 | تایم‌فریم اصلی: 1m\n"
        "🎯 تارگت: همیشه RR=3.0\n"
        f"🕒 {format_iran_time()}"
    )
    threading.Thread(target=lambda: app.run(host="0.0.0.0", port=10000), daemon=True).start()
    main_loop()
