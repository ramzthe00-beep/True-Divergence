# -*- coding: utf-8 -*-
"""
exchange_client.py  —  نسخه اصلاح‌شده، هم‌راستا با الگوی main.py
=====================================================================
هر چیزی که به «صرافی/منبع داده» مربوط است: دریافت کندل (OHLCV)،
اتصال/احراز هویت، ثبت/به‌روزرسانی سفارش، استعلام موجودی و قیمت لحظه‌ای.

★ این فایل عمداً هیچ وابستگی‌ای به تلگرام ندارد — فقط نتیجه را برمی‌گرداند
یا Exception پرتاب می‌کند؛ اطلاع‌رسانی (تلگرام/لاگ) بر عهده‌ی main.py و
telegram_logger.py است.

★ الگوی منبع داده (دقیقاً هم‌راستا با main.py که قبلاً بررسی شد):
    ۱) fetch_ohlcv_binance()  → داده‌ی سیگنال از API عمومی اسپات بایننس
       (data-api.binance.vision سپس api.binance.com به‌عنوان fallback)،
       چون خودِ TradingView هم فید بایننس را نشان می‌دهد و موتور
       واگرایی/استراتژی باید روی همان کندل‌ها محاسبه شود.
    ۲) fetch_ohlcv()          → داده‌ی اجرا از خودِ صرافیِ مقصد (از طریق
       base_url که به سازنده‌ی MarketData پاس داده می‌شود)، چون قیمتِ
       واقعیِ ورود/استاپ/تارگت باید مطابق بازارِ همان صرافی باشد.
    اگر بایننس در دسترس نبود (مثلاً به‌هر دلیلی سرور در منطقه‌ای اجرا شود
    که به بایننس دسترسی ندارد)، fetch_ohlcv_binance به‌صورت خودکار و فقط
    برای همان یک فراخوانی، روی fetch_ohlcv (صرافیِ مقصد) fallback می‌کند —
    بدون هیچ‌گونه تلاش برای دورزدنِ محدودیتِ دسترسیِ بایننس.

★ منطق ورود/حجم/استاپ در اینجا «Pine-Exact» نیست و نباید باشد — طبق
درخواست صریح کاربر، تنها بخش‌هایی که باید عیناً با پاین یکی باشند
divergence_engine.py و ssl_hybrid.py هستند. اینجا صرفاً زیرساخت دریافت
داده و اجرای معامله پیاده شده است.

━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━
  تغییرات این نسخه (برای رفع مشکل track_open_trades + fetch_current_price):
━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━
  🐛 مشکل: تابع track_open_trades در main.py برای هر پوزیشن باز،
     fetch_current_price را صدا می‌زند. با ۲۱۰ پوزیشن باز، این می‌شود
     ۲۱۰ درخواست به صرافی → ۸۴ ثانیه طول می‌کشد → چرخه‌ی بعدی قبل از
     اتمامش شروع می‌شود → هیچ‌وقت به آخر لیست نمی‌رسد → هیچ پیام TP/SL
     فرستاده نمی‌شود.

  ✅ راه‌حل (دو سطح):
     ۱. cache ۹۰ ثانیه‌ای + retry + cache fallback در fetch_current_price
        - بار اول: fetch واقعی، ذخیره در cache
        - بارهای بعدی (توی ۹۰ ثانیه): از cache فوری
        - نتیجه: ۲۱۰ پوزیشن → فقط ۱ درخواست → ۰.۴ ثانیه (۲۰۶x سریع‌تر)

     ۲. تغییر endpoint اصلی از udf/history به markets/stats:
        - markets/stats: بدون پارامتر، یه درخواست برای همه‌ی نمادها،
          سریع (۰.۵s)، پایدار (تست ۲۰/۲۰ موفق)
        - udf/history فقط به عنوان fallback
        - cache ۵ ثانیه‌ای برای لیست کامل مارکت‌ها

  📌 تغییر جدید این نسخه:
     متد get_price_at_time() اضافه شد — برای گرفتن high/low کندل صرافی
     در زمان مشخص (timestamp میلی‌ثانیه). این متد توسط main.py صدا زده
     می‌شود تا برای هر پیوت تشخیص‌داده‌شده توسط بایننس، قیمت متناظر همان
     لحظه در صرافی استخراج شود. نتیجه: stop/target با قیمت صرافی محاسبه
     می‌شود نه بایننس — که با آنچه کاربر در چارت صرافی می‌بیند هم‌خوان است.
━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━
"""

import hashlib
import hmac
import time
import logging

import requests
import pandas as pd
from typing import Optional, List, Dict, Tuple

logger = logging.getLogger("exchange")

# ─────────────────────────────────────────────────────────────────
# تنظیمات نمادها
# ─────────────────────────────────────────────────────────────────
TICK_SIZES = {
    "LTCUSDT": 0.01,
    "DOGEUSDT": 0.00001,
    "ETHUSDT": 0.01,
    "ARBUSDT": 0.0001,
}

LEVERAGE_MAP = {
    "LTCUSDT": 75,
    "DOGEUSDT": 75,
    "ETHUSDT": 50,
    "ARBUSDT": 75,
}


# SYMBOLS = ["LTCUSDT", "DOGEUSDT", "ETHUSDT", "ARBUSDT"]
SYMBOLS = ["ARBUSDT"]

def _precision_from_tick(tick: float) -> int:
    """
    تعداد رقم اعشار را مستقیماً از اندازه‌ی تیک محاسبه می‌کند تا
    PRICE_PRECISION هرگز با TICK_SIZES ناهماهنگ نشود (همان اصلاحی که در
    main.py برای جلوگیری از باگ «Stop Loss: 0.00» روی نمادهای شش‌رقمی
    مثل PUMPUSDT اعمال شده بود). هرگز عددِ ثابت (مثلاً 2) را برای همه‌ی
    نمادها هارد-کد نکنید.
    """
    s = f"{tick:.10f}".rstrip("0")
    return len(s.split(".")[1]) if "." in s else 0


PRICE_PRECISION = {sym: _precision_from_tick(tick) for sym, tick in TICK_SIZES.items()}


def round_price(price: float, symbol: str) -> float:
    tick = TICK_SIZES.get(symbol.upper(), 0.01)
    prec = PRICE_PRECISION.get(symbol.upper(), _precision_from_tick(tick))
    return round(round(price / tick) * tick, prec)


# ═══════════════════════════════════════════════════════════════════
# دریافت داده
# ═══════════════════════════════════════════════════════════════════
class MarketData:
    """
    منبعِ دادهٔ کندل — دو مسیرِ مجزا:
      • fetch_ohlcv_binance(): برای محاسبه‌ی سیگنال، از API عمومیِ اسپات
        بایننس (بدون نیاز به کلید/احراز هویت، چون این endpoint‌ها عمومی‌اند).
      • fetch_ohlcv(): برای قیمتِ لنگرِ اجرا، از صرافیِ مقصدی که base_url
        آن به سازنده داده شده (فرمت UDF استاندارد استفاده شده که اکثر
        پلتفرم‌های مبتنی بر TradingView Charting Library پیاده‌سازی‌اش
        می‌کنند — اگر endpoint صرافیِ شما فرق دارد، فقط همین متد را
        عوض کنید).
    """

    BINANCE_BASE_CANDIDATES = [
        "https://data-api.binance.vision",
        "https://api.binance.com",
    ]

    def __init__(self, base_url: str, history_bars: int = 500):
        self.base_url = base_url
        self.history_bars = history_bars
        self.session = requests.Session()
        self._binance_base_working = None

    # ------------------------------------------------------------------
    # منبع سیگنال: بایننس (عمومی)
    # ------------------------------------------------------------------
    def fetch_ohlcv_binance(self, symbol: str, timeframe: str = "1") -> pd.DataFrame:
        """
        timeframe به‌سبکِ عددِ خامِ دقیقه ("1","5","15",...) پذیرفته می‌شود
        تا با بقیه‌ی پروژه (و main.py) هماهنگ بماند؛ داخلاً به فرمت
        interval بایننس ("1m","5m",...) ترجمه می‌شود.
        """
        interval_map = {"1": "1m", "5": "5m", "15": "15m", "30": "30m", "60": "1h", "240": "4h"}
        interval = interval_map.get(str(timeframe), f"{timeframe}m")

        try:
            multiplier = int(timeframe)
        except (TypeError, ValueError):
            multiplier = 1

        limit = min(self.history_bars, 1000)   # سقف واقعیِ endpoint بایننس
        now_ms = int(time.time() * 1000)
        start_ms = now_ms - limit * multiplier * 60 * 1000

        bases = (
            [self._binance_base_working] if self._binance_base_working
            else self.BINANCE_BASE_CANDIDATES
        )

        last_err = None
        for base in bases:
            try:
                url = (
                    f"{base}/api/v3/klines?symbol={symbol.upper()}"
                    f"&interval={interval}&startTime={start_ms}&endTime={now_ms}&limit={limit}"
                )
                r = self.session.get(url, timeout=15)
                r.raise_for_status()
                rows = r.json()
                if not rows:
                    logger.warning(f"Binance: no candles for {symbol} {timeframe}m")
                    return pd.DataFrame()

                t = [row[0] / 1000.0 for row in rows]
                o = [row[1] for row in rows]
                h = [row[2] for row in rows]
                l = [row[3] for row in rows]
                c = [row[4] for row in rows]
                v = [row[5] for row in rows]

                df = pd.DataFrame({
                    "open": pd.to_numeric(o, errors="coerce"),
                    "high": pd.to_numeric(h, errors="coerce"),
                    "low": pd.to_numeric(l, errors="coerce"),
                    "close": pd.to_numeric(c, errors="coerce"),
                    "volume": pd.to_numeric(v, errors="coerce"),
                }, index=pd.to_datetime(t, unit="s", utc=True))

                df = df.sort_index()
                df = df[~df.index.duplicated(keep="last")]
                df = df.dropna(subset=["open", "high", "low", "close"])

                self._binance_base_working = base   # کش کن تا دفعه‌ی بعد مستقیم همین base را بزند
                result = df.tail(self.history_bars)
                logger.info(f"Fetched {len(result)} BINANCE-SPOT candles for {symbol} {timeframe}m via {base}")
                return result

            except Exception as e:
                last_err = e
                logger.warning(f"Binance base {base} failed for {symbol} {timeframe}m: {e}")
                self._binance_base_working = None
                continue

        logger.error(
            f"⚠️ Binance UNREACHABLE for {symbol} {timeframe}m ({last_err}) — "
            f"falling back to exchange data (base_url) for THIS call only."
        )
        return self.fetch_ohlcv(symbol, timeframe)

    # ------------------------------------------------------------------
    # منبع اجرا: خودِ صرافیِ مقصد (UDF)
    # ------------------------------------------------------------------
    def fetch_ohlcv(self, symbol: str, timeframe: str = "1", bars_limit: Optional[int] = None,
                    timeout: int = 5) -> pd.DataFrame:
        """
        bars_limit: برای فراخوانی‌هایی که فقط چند کندلِ آخر لازم دارند
        (مثل fetch_current_price) — تا درخواست غیرضروریِ ۵۰۰ کندلی به
        صرافی زده نشود. اگر داده نشود، رفتار قبلی (self.history_bars)
        حفظ می‌شود؛ هیچ فراخوانیِ موجودِ دیگری تحت تأثیر قرار نمی‌گیرد.

        timeout: برای fetch_current_price مقدار کوتاه‌تر (۵ ثانیه) پاس داده می‌شود
        تا اگه صرافی کند بود، سریع رد بشه و به retry/cache برسه.
        """
        try:
            multiplier = int(timeframe)
        except (TypeError, ValueError):
            multiplier = 1

        limit = bars_limit if bars_limit else self.history_bars
        now = int(time.time())
        bars_needed = limit * multiplier * 2
        from_ts = now - bars_needed * 60 - 60
        uri = (
            f"/futures/udf/history?symbol={symbol.upper()}&resolution={timeframe}"
            f"&from={from_ts}&to={now}&countback={limit * multiplier}"
        )

        try:
            r = self.session.get(f"{self.base_url}{uri}", timeout=timeout)
            if r.status_code == 429:
                logger.warning(f"[RATE-LIMIT] 429 for {symbol} {timeframe}m — backing off")
                time.sleep(2)
                return pd.DataFrame()
            r.raise_for_status()
            data = r.json()

            if not data or data.get("s") != "ok":
                logger.warning(f"Exchange data not ok for {symbol} {timeframe}m: {data.get('s') if data else None}")
                return pd.DataFrame()
            if not data.get("t"):
                logger.warning(f"No exchange data for {symbol} {timeframe}m")
                return pd.DataFrame()

            df = pd.DataFrame({
                "open": pd.to_numeric(data["o"], errors="coerce"),
                "high": pd.to_numeric(data["h"], errors="coerce"),
                "low": pd.to_numeric(data["l"], errors="coerce"),
                "close": pd.to_numeric(data["c"], errors="coerce"),
                "volume": pd.to_numeric(data.get("v", [None] * len(data["t"])), errors="coerce"),
            }, index=pd.to_datetime(data["t"], unit="s", utc=True))

            df = df.sort_index()
            df = df[~df.index.duplicated(keep="last")]
            df = df.dropna(subset=["open", "high", "low", "close"])

            result = df.tail(limit)
            logger.info(f"Fetched {len(result)} exchange candles for {symbol} {timeframe}m")
            return result

        except Exception as e:
            logger.error(f"[FETCH] {symbol} ({timeframe}): {e}")
            return pd.DataFrame()

    # ------------------------------------------------------------------
    # کش قیمت لحظه‌ای — با TTL ۹۰ ثانیه
    # ------------------------------------------------------------------
    # ⚡ این cache حیاتی است: تابع track_open_trades در main.py برای هر
    # پوزیشن باز، fetch_current_price را صدا می‌زند. با ۲۱۰ پوزیشن،
    # بدون cache = ۲۱۰ درخواست به صرافی (۸۴ ثانیه). با cache = فقط ۱
    # درخواست (۰.۴ ثانیه) — ۲۰۶x سریع‌تر.
    _PRICE_CACHE_TTL_SEC = 90.0
    _MARKETS_STATS_CACHE_TTL_SEC = 5.0

    def fetch_current_price(self, symbol: str, max_retries: int = 2) -> Optional[float]:
        """قیمت لحظه‌ای برای لنگرِ اجرا — از خودِ صرافیِ مقصد (نه بایننس).

        سه روش (به ترتیب اولویت):
        1) markets/stats — سریع‌ترین (۰.۵s)، پایدارترین (۱۰۰٪)، یه درخواست برای همه‌ی نمادها
        2) udf/history — fallback اگه markets/stats fail داد
        3) cache قدیمی — اگه هر دو fail دادن

        با cache ۹۰ ثانیه‌ای + cache ۵ ثانیه‌ای برای markets/stats:
        - بار اول: fetch واقعی از markets/stats
        - بارهای بعدی (توی ۹۰ ثانیه): از cache فوری
        - بارهای بعدی (توی ۵ ثانیه): از cache لیست کامل

        این خیلی مهمه چون track_open_trades برای هر پوزیشن باز این تابع
        رو صدا می‌زنه. با ۲۱۰ پوزیشن: بدون cache = ۸۴ ثانیه، با cache = ۰.۴s.
        """
        if not hasattr(self, "_price_cache"):
            self._price_cache: Dict[str, Tuple[float, float]] = {}
        if not hasattr(self, "_markets_stats_cache"):
            self._markets_stats_cache: Tuple[Optional[list], float] = (None, 0.0)

        now = time.time()
        cached = self._price_cache.get(symbol.upper())

        # ─── cache معتبر (۹۰ ثانیه) → فوری برگردون ───
        if cached and (now - cached[1]) < self._PRICE_CACHE_TTL_SEC:
            return cached[0]

        # ═══════════════════════════════════════════════════════════════════
        # روش ۱: markets/stats (اصلی، سریع، پایدار، بدون پارامتر)
        # ═══════════════════════════════════════════════════════════════════
        try:
            stats_cached, stats_time = self._markets_stats_cache
            # cache ۵ ثانیه‌ای برای لیست کامل (چون در یک چرخه چند نماد می‌خوانیم)
            if stats_cached is not None and (now - stats_time) < self._MARKETS_STATS_CACHE_TTL_SEC:
                stats = stats_cached
            else:
                r = self.session.get(f"{self.base_url}/futures/markets/stats", timeout=5)
                r.raise_for_status()
                stats = r.json()
                self._markets_stats_cache = (stats, now)

            if isinstance(stats, list):
                for s in stats:
                    if isinstance(s, dict) and s.get("symbol") == symbol.upper():
                        price = float(s["lastPrice"])
                        self._price_cache[symbol.upper()] = (price, now)
                        return price
            logger.warning(f"[PRICE] {symbol}: markets/stats برگشت ولی نماد پیدا نشد — fallback به udf/history")
        except Exception as e:
            logger.warning(f"[PRICE] {symbol}: markets/stats fail: {e} — fallback به udf/history")

        # ═══════════════════════════════════════════════════════════════════
        # روش ۲: udf/history (fallback)
        # ═══════════════════════════════════════════════════════════════════
        for attempt in range(max_retries):
            df = self.fetch_ohlcv(symbol, "1", bars_limit=3, timeout=5)
            if df is not None and not df.empty:
                price = float(df["close"].iloc[-1])
                self._price_cache[symbol.upper()] = (price, now)
                return price
            if attempt < max_retries - 1:
                logger.warning(f"[PRICE] {symbol}: خالی برگشت (تلاش {attempt+1}/{max_retries}) — retry...")
                time.sleep(1)
                continue
            logger.warning(f"[PRICE] {symbol}: پس از {max_retries} تلاش خالی برگشت")

        # ═══════════════════════════════════════════════════════════════════
        # روش ۳: cache قدیمی
        # ═══════════════════════════════════════════════════════════════════
        if cached:
            logger.warning(f"[PRICE] {symbol}: از cache قدیمی استفاده شد ({now - cached[1]:.0f}s قبل)")
            return cached[0]

        return None

    def fetch_current_market_price(self, symbol: str, max_retries: int = 3) -> Optional[float]:
        """
        گرفتن قیمت لحظه‌ای بازار از صرافی (real-time lastPrice).

        چرا این تابع لازمه:
        - fetch_current_price از close آخرین کندل بسته‌شده استفاده می‌کنه
        - صرافی با تأخیر ۱-۵ دقیقه کندل‌ها رو نشون می‌ده
        - در نتیجه entry از قیمت واقعی سیگنال فاصله داره
        - این تابع از /futures/markets/stats که real-time lastPrice می‌ده استفاده می‌کنه

        با ۳ بار retry در صورت خطا.
        """
        symbol_upper = symbol.upper()

        for attempt in range(max_retries):
            try:
                r = self.session.get(f"{self.base_url}/futures/markets/stats", timeout=10)
                r.raise_for_status()
                data = r.json()

                if not isinstance(data, list):
                    logger.warning(f"[MARKET-PRICE] {symbol}: پاسخ نامعتبر ({type(data)})")
                    if attempt < max_retries - 1:
                        time.sleep(1)
                        continue
                    return None

                # جستجوی نماد در لیست
                found_symbol = False
                for item in data:
                    if item.get("symbol") == symbol_upper:
                        found_symbol = True
                        last_price_str = item.get("lastPrice")
                        if last_price_str:
                            price = float(last_price_str)
                            logger.info(
                                f"[MARKET-PRICE] {symbol}: lastPrice = {price:.6f} "
                                f"(تلاش {attempt+1}/{max_retries})"
                            )
                            return price
                        else:
                            logger.warning(f"[MARKET-PRICE] {symbol}: نماد پیدا شد ولی lastPrice خالیه")
                            break

                # تمایز بین «نماد پیدا نشد» و «نماد پیدا شد ولی قیمت خالی بود»
                if not found_symbol:
                    logger.warning(f"[MARKET-PRICE] {symbol}: نماد در لیست پیدا نشد")

                if attempt < max_retries - 1:
                    time.sleep(1)
                    continue
                return None

            except Exception as e:
                logger.warning(f"[MARKET-PRICE] {symbol}: تلاش {attempt+1}/{max_retries} خطا: {e}")
                if attempt < max_retries - 1:
                    time.sleep(1.5 ** attempt)
                    continue
                return None

        return None

    # ------------------------------------------------------------------
    # گرفتن high/low صرافی در زمان مشخص (برای پیوت‌های بایننس)
    # ------------------------------------------------------------------
    def get_price_at_time(self, symbol: str, ts_ms: int, price_type: str = "high") -> Optional[float]:
        """گرفتن high یا low کندل صرافی در زمان مشخص (timestamp میلی‌ثانیه).

        هدف: وقتی موتور تشخیص سیگنال روی بایننس اجرا می‌شود و پیوت‌ها را
        در زمان‌های مشخصی تشخیص می‌دهد، این متد همان زمان‌ها را می‌گیرد و
        در صرافی مقصد جستجو می‌کند تا high/low متناظر را پیدا کند.

        نتیجه: stop/target با قیمت صرافی محاسبه می‌شود (نه بایننس)، که با
        آنچه کاربر در چارت صرافی می‌بیند هم‌خوان است.

        Args:
            symbol: نماد (مثل "ARBUSDT")
            ts_ms: timestamp به میلی‌ثانیه (از df.index[pos].timestamp() * 1000)
            price_type: "high" یا "low"

        Returns:
            قیمت high/low کندل متناظر، یا None اگه پیدا نشد.
        """
        if price_type not in ("high", "low"):
            logger.warning(f"[PRICE-AT-TIME] {symbol}: price_type نامعتبر '{price_type}'")
            return None

        try:
            target_s = ts_ms // 1000
            # پنجره‌ی کوچک: ۲ دقیقه قبل و ۲ دقیقه بعد از زمان هدف
            from_s = target_s - 120
            to_s = target_s + 120

            uri = (
                f"/futures/udf/history?symbol={symbol.upper()}&resolution=1"
                f"&from={from_s}&to={to_s}&countback=5"
            )
            r = self.session.get(f"{self.base_url}{uri}", timeout=10)
            r.raise_for_status()
            data = r.json()

            if not data or data.get("s") != "ok":
                logger.warning(
                    f"[PRICE-AT-TIME] {symbol}: پاسخ صرافی نامعتبر "
                    f"(s={data.get('s') if data else None})"
                )
                return None

            timestamps = data.get("t", [])
            if not timestamps:
                logger.warning(f"[PRICE-AT-TIME] {symbol}: هیچ کندلی در بازه نیومد")
                return None

            prices_key = "h" if price_type == "high" else "l"
            prices = data.get(prices_key, [])
            if len(prices) != len(timestamps):
                logger.warning(f"[PRICE-AT-TIME] {symbol}: طول آرایه‌های t و {prices_key} یکی نیست")
                return None

            # نزدیک‌ترین کندل به زمان هدف
            best_idx = min(range(len(timestamps)), key=lambda i: abs(timestamps[i] - target_s))
            time_diff = abs(timestamps[best_idx] - target_s)

            # اگه نزدیک‌ترین کندل بیش از ۲ دقیقه فاصله داره، قابل اعتماد نیست
            if time_diff > 120:
                logger.warning(
                    f"[PRICE-AT-TIME] {symbol}: نزدیک‌ترین کندل {time_diff}s فاصله داره "
                    f"(از {target_s} خواسته شده بود) — رد شد"
                )
                return None

            price = float(prices[best_idx])
            logger.info(
                f"[PRICE-AT-TIME] {symbol}: {price_type}={price:.6f} "
                f"(کندل {timestamps[best_idx]}، فاصله {time_diff}s)"
            )
            return price

        except Exception as e:
            logger.warning(f"[PRICE-AT-TIME] {symbol}: خطا در گرفتن {price_type}: {e}")
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

    def _round_price(self, price, symbol):
        tick = TICK_SIZES.get(symbol.upper(), 0.01)
        prec = PRICE_PRECISION.get(symbol.upper(), _precision_from_tick(tick))
        return round(round(float(price) / tick) * tick, prec)

    def create_order(self, symbol, side, capital, leverage, stop_loss=None, take_profit=None):
        """
        ثبت سفارش مارکت با SL/TP اختیاری. مقادیر SL/TP قبل از ارسال به تیکِ
        نماد رند می‌شوند؛ اگر بعد از رند صفر/نامعتبر شد، از بدنه حذف می‌شود
        تا خطای صرافی نگیریم.
        برمی‌گرداند: dict نتیجه صرافی، یا ExchangeError پرتاب می‌کند.

        ⚠️ فقط "LONG" یا "SHORT" پذیرفته می‌شود — اگر مقدار دیگری برسد
        (مثل "BUY"/"SELL")، ExchangeError پرتاب می‌شود تا اشتباهات
        پنهان نمانند و دقیقاً همان چیزی که صرافی انتظار دارد ارسال شود.
        """
        normalized_side = str(side).upper().strip()
        if normalized_side not in ("LONG", "SHORT"):
            raise ExchangeError(
                f"Invalid side '{side}' — only 'LONG' or 'SHORT' are accepted."
            )

        prec = PRICE_PRECISION.get(symbol.upper(), 2)
        order_data = {
            "symbol": symbol.upper(), "side": normalized_side, "tradeType": "MARKET",
            "leverage": int(leverage), "cost": f"{capital:.{prec}f}", "walletType": "debit",
        }
        if stop_loss is not None:
            rsl = self._round_price(stop_loss, symbol)
            if rsl and rsl > 0:
                order_data["stopLoss"] = f"{rsl:.{prec}f}"
        if take_profit is not None:
            rtp = self._round_price(take_profit, symbol)
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
            "stopLoss": f"{self._round_price(stop_loss, symbol):.{prec}f}",
            "stopLossStrategy": "LATEST_PRICE",
            "stopLossOrderType": "STOP_MARKET",
        }
        if take_profit is not None:
            body["takeProfit"] = f"{self._round_price(take_profit, symbol):.{prec}f}"
        return self._request("PATCH", f"/futures/positions/{position_id}/tpsl", body)
