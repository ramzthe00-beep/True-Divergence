"""
ct_signal_filter.py
===================
فیلتر CT برای DTM

قاعده: وقتی DTM روی تایم‌فریم X سیگنال می‌ده، CT باید روی تایم‌فریم بالاتر تأیید کنه.

Mapping:
    1m  → 5m
    3m  → 15m
    5m  → 15m
    15m → 1h
    30m → 1h
    1h  → 4h

منطق (طبق تصمیمات کاربر):
    - CT باید در ۱۰ کندل آخر، حداقل یک سیگنال هم‌جهت داشته باشه
    - اگه CT هیچ سیگنالی نداشت → reject (احتیاط)
    - اگه CT سیگنال مخالف داشت → reject
    - اگه CT سیگنال هم‌جهت داشت → allow
"""
import logging

logger = logging.getLogger("CT_FILTER")


# ═══════════════════════════════════════════════════════════════
# Mapping تایم‌فریم DTM → تایم‌فریم فیلتر CT
# ═══════════════════════════════════════════════════════════════
TF_MAP = {
    "1":   "5",
    "3":   "15",
    "5":   "15",
    "15":  "60",
    "30":  "60",
    "60":  "240",
    "240": "1440",   # 4h → 1D
}

# تعداد کندل آخر CT برای بررسی سیگنال
CT_LOOKBACK_BARS = 10


def get_ct_filter_timeframe(dtm_timeframe):
    """تبدیل تایم‌فریم DTM به تایم‌فریم فیلتر CT"""
    tf = str(dtm_timeframe).strip()
    return TF_MAP.get(tf, "15")  # پیش‌فرض 15m


def check_ct_filter(public_data, symbol, dtm_direction, dtm_timeframe,
                     lookback_bars=None):
    """
    بررسی تأیید CT برای سیگنال DTM.

    Args:
        public_data: instance از PublicData (در bot.py)
        symbol: "ETHUSDT" یا مشابه
        dtm_direction: "LONG" یا "SHORT"
        dtm_timeframe: تایم‌فریم DTM ("1" یا "5" یا ...)
        lookback_bars: تعداد کندل آخر CT برای بررسی (پیش‌فرض ۱۰)

    Returns:
        dict: {
            'allowed': bool,
            'reason': str,
            'ct_timeframe': str,
            'ct_signal': dict or None,
            'ct_signals_count': int,
        }
    """
    if lookback_bars is None:
        lookback_bars = CT_LOOKBACK_BARS

    ct_tf = get_ct_filter_timeframe(dtm_timeframe)

    result = {
        'allowed': False,
        'reason': 'unknown',
        'ct_timeframe': ct_tf,
        'ct_signal': None,
        'ct_signals_count': 0,
    }

    # ۱. دریافت دیتا
    try:
        df = public_data.fetch_ohlcv(symbol, ct_tf)
    except Exception as e:
        logger.error(f"[CT-FILTER] {symbol} @ {ct_tf}m: fetch failed: {e}")
        result['reason'] = 'fetch_error'
        return result

    if df is None or df.empty:
        logger.warning(f"[CT-FILTER] {symbol} @ {ct_tf}m: empty data")
        result['reason'] = 'no_data'
        return result

    # ۲. اجرای CT
    try:
        from ct_wrapper import run_ct_strategy
        signals = run_ct_strategy(df, symbol, ct_tf)
        signals = [s for s in signals if s is not None]
        result['ct_signals_count'] = len(signals)
    except Exception as e:
        logger.error(f"[CT-FILTER] {symbol} @ {ct_tf}m: CT run failed: {e}")
        result['reason'] = 'ct_run_error'
        return result

    # ۳. اگه CT هیچ سیگنالی نداره → reject
    if not signals:
        result['reason'] = 'no_ct_signals'
        return result

    # ۴. بررسی داده کافی
    if len(df) < lookback_bars:
        result['reason'] = 'not_enough_candles'
        return result

    # ۵. سیگنال‌های ۱۰ کندل آخر
    cutoff_ms = int(df.index[-lookback_bars].timestamp() * 1000)
    recent = [s for s in signals if (s['time_ms'] or 0) >= cutoff_ms]

    if not recent:
        result['reason'] = 'no_recent_ct_signal'
        return result

    # ۶. هم‌جهتی
    matching = [s for s in recent if s['direction'] == dtm_direction]

    if matching:
        latest = max(matching, key=lambda x: x['time_ms'] or 0)
        result['allowed'] = True
        result['reason'] = 'confirmed'
        result['ct_signal'] = latest
        return result

    # ۷. CT سیگنال داره ولی مخالف
    latest_recent = max(recent, key=lambda x: x['time_ms'] or 0)
    result['reason'] = f"ct_wrong_direction({latest_recent['kind']})"
    result['ct_signal'] = latest_recent
    return result


def format_ct_filter_log(symbol, dtm_direction, dtm_timeframe, result):
    """فرمت لاگ برای CT filter"""
    ct_tf = result.get('ct_timeframe', '?')
    allowed = result.get('allowed', False)
    reason = result.get('reason', '?')
    signal = result.get('ct_signal')

    status = "✅ ALLOW" if allowed else "❌ REJECT"
    line = (f"[CT-FILTER] {symbol} DTM@{dtm_timeframe}m {dtm_direction} "
            f"→ CT@{ct_tf}m: {status} ({reason})")
    if signal and signal.get('time_iran'):
        try:
            t_str = signal['time_iran'].strftime('%m-%d %H:%M')
            line += f" | CT: {signal['kind']} @ {t_str}"
        except Exception:
            pass
    return line