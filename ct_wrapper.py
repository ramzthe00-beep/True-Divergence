"""
ct_wrapper.py
=============
Wrapper برای استراتژی CT-DTM (Ichimoku)

- اجرای ct_strategy.py با PyneCore ScriptRunner
- استخراج سیگنال‌های fire (Anni-L, Anni-S, Aati-L, Aati-S)
- خروجی: لیست سیگنال‌ها با زمان دقیق (UTC + ایران)
"""
import logging
from pathlib import Path
from datetime import time as dt_time, datetime, timezone, timedelta
import math

from pynecore.core.ohlcv import OHLCV
from pynecore.core.syminfo import SymInfo, SymInfoInterval, SymInfoSession
from pynecore.core.script_runner import ScriptRunner

logger = logging.getLogger("CT_WRAPPER")

CT_STRATEGY_PATH = Path(__file__).resolve().parent / "ct_strategy.py"

IRAN_TZ = timezone(timedelta(hours=3, minutes=30))
UTC_TZ = timezone.utc

# ═══════════════════════════════════════════════════════════════
# تنظیمات نمادها
# ═══════════════════════════════════════════════════════════════
# ═══════════════════════════════════════════════════════════════
# تنظیمات نمادها — همه‌ی ۶۳ market فعال TheTrueTrade
# منبع: GET https://apiv2.thetruetrade.io/futures/markets
# ═══════════════════════════════════════════════════════════════
SYMBOL_TICK_INFO = {
    "1000PEPEUSDT": {"mintick": 0.0000001, "pricescale": 10000000, "basecurrency": "1000PEPE"},
    "1000SHIBUSDT": {"mintick": 0.000001,  "pricescale": 1000000,  "basecurrency": "1000SHIB"},
    "AAVEUSDT":     {"mintick": 0.01,      "pricescale": 100,      "basecurrency": "AAVE"},
    "ADAUSDT":      {"mintick": 0.0001,    "pricescale": 10000,    "basecurrency": "ADA"},
    "ALGOUSDT":     {"mintick": 0.0001,    "pricescale": 10000,    "basecurrency": "ALGO"},
    "APEUSDT":      {"mintick": 0.0001,    "pricescale": 10000,    "basecurrency": "APE"},
    "APTUSDT":      {"mintick": 0.0001,    "pricescale": 10000,    "basecurrency": "APT"},
    "ARBUSDT":      {"mintick": 0.00001,   "pricescale": 100000,   "basecurrency": "ARB"},
    "ASTERUSDT":    {"mintick": 0.0001,    "pricescale": 10000,    "basecurrency": "ASTER"},
    "ATOMUSDT":     {"mintick": 0.001,     "pricescale": 1000,     "basecurrency": "ATOM"},
    "AVAXUSDT":     {"mintick": 0.001,     "pricescale": 1000,     "basecurrency": "AVAX"},
    "BANDUSDT":     {"mintick": 0.0001,    "pricescale": 10000,    "basecurrency": "BAND"},
    "BCHUSDT":      {"mintick": 0.01,      "pricescale": 100,      "basecurrency": "BCH"},
    "BMTUSDT":      {"mintick": 0.00001,   "pricescale": 100000,   "basecurrency": "BMT"},
    "BNBUSDT":      {"mintick": 0.01,      "pricescale": 100,      "basecurrency": "BNB"},
    "BTCUSDT":      {"mintick": 0.1,       "pricescale": 10,       "basecurrency": "BTC"},
    "BTWUSDT":      {"mintick": 0.00001,   "pricescale": 100000,   "basecurrency": "BTW"},
    "BZUSDT":       {"mintick": 0.01,      "pricescale": 100,      "basecurrency": "BZ"},
    "CAKEUSDT":     {"mintick": 0.0001,    "pricescale": 10000,    "basecurrency": "CAKE"},
    "CLUSDT":       {"mintick": 0.01,      "pricescale": 100,      "basecurrency": "CL"},
    "COPPERUSDT":   {"mintick": 0.001,     "pricescale": 1000,     "basecurrency": "COPPER"},
    "DASHUSDT":     {"mintick": 0.01,      "pricescale": 100,      "basecurrency": "DASH"},
    "DOGEUSDT":     {"mintick": 0.00001,   "pricescale": 100000,   "basecurrency": "DOGE"},
    "DOTUSDT":      {"mintick": 0.001,     "pricescale": 1000,     "basecurrency": "DOT"},
    "ENAUSDT":      {"mintick": 0.00001,   "pricescale": 100000,   "basecurrency": "ENA"},
    "ETCUSDT":      {"mintick": 0.001,     "pricescale": 1000,     "basecurrency": "ETC"},
    "ETHUSDT":      {"mintick": 0.01,      "pricescale": 100,      "basecurrency": "ETH"},
    "FETUSDT":      {"mintick": 0.0001,    "pricescale": 10000,    "basecurrency": "FET"},
    "FILUSDT":      {"mintick": 0.001,     "pricescale": 1000,     "basecurrency": "FIL"},
    "GRAMUSDT":     {"mintick": 0.001,     "pricescale": 1000,     "basecurrency": "GRAM"},
    "HBARUSDT":     {"mintick": 0.00001,   "pricescale": 100000,   "basecurrency": "HBAR"},
    "HYPEUSDT":     {"mintick": 0.001,     "pricescale": 1000,     "basecurrency": "HYPE"},
    "ICPUSDT":      {"mintick": 0.001,     "pricescale": 1000,     "basecurrency": "ICP"},
    "INJUSDT":      {"mintick": 0.001,     "pricescale": 1000,     "basecurrency": "INJ"},
    "KAITOUSDT":    {"mintick": 0.0001,    "pricescale": 10000,    "basecurrency": "KAITO"},
    "KSMUSDT":      {"mintick": 0.001,     "pricescale": 1000,     "basecurrency": "KSM"},
    "LINKUSDT":     {"mintick": 0.001,     "pricescale": 1000,     "basecurrency": "LINK"},
    "LTCUSDT":      {"mintick": 0.01,      "pricescale": 100,      "basecurrency": "LTC"},
    "MSTRUSDT":     {"mintick": 0.01,      "pricescale": 100,      "basecurrency": "MSTR"},
    "NEARUSDT":     {"mintick": 0.001,     "pricescale": 1000,     "basecurrency": "NEAR"},
    "NOTUSDT":      {"mintick": 0.0000001, "pricescale": 10000000, "basecurrency": "NOT"},
    "NVDAUSDT":     {"mintick": 0.01,      "pricescale": 100,      "basecurrency": "NVDA"},
    "ONDOUSDT":     {"mintick": 0.0001,    "pricescale": 10000,    "basecurrency": "ONDO"},
    "OPUSDT":       {"mintick": 0.0001,    "pricescale": 10000,    "basecurrency": "OP"},
    "PAXGUSDT":     {"mintick": 0.01,      "pricescale": 100,      "basecurrency": "PAXG"},
    "PUMPUSDT":     {"mintick": 0.000001,  "pricescale": 1000000,  "basecurrency": "PUMP"},
    "QNTUSDT":      {"mintick": 0.01,      "pricescale": 100,      "basecurrency": "QNT"},
    "SANDUSDT":     {"mintick": 0.00001,   "pricescale": 100000,   "basecurrency": "SAND"},
    "SOLUSDT":      {"mintick": 0.01,      "pricescale": 100,      "basecurrency": "SOL"},
    "SPCXUSDT":     {"mintick": 0.01,      "pricescale": 100,      "basecurrency": "SPCX"},
    "SUIUSDT":      {"mintick": 0.0001,    "pricescale": 10000,    "basecurrency": "SUI"},
    "TRUMPUSDT":    {"mintick": 0.001,     "pricescale": 1000,     "basecurrency": "TRUMP"},
    "TRXUSDT":      {"mintick": 0.00001,   "pricescale": 100000,   "basecurrency": "TRX"},
    "TSLAUSDT":     {"mintick": 0.01,      "pricescale": 100,      "basecurrency": "TSLA"},
    "TUTUSDT":      {"mintick": 0.00001,   "pricescale": 100000,   "basecurrency": "TUT"},
    "UNIUSDT":      {"mintick": 0.001,     "pricescale": 1000,     "basecurrency": "UNI"},
    "VETUSDT":      {"mintick": 0.000001,  "pricescale": 1000000,  "basecurrency": "VET"},
    "WLDUSDT":      {"mintick": 0.0001,    "pricescale": 10000,    "basecurrency": "WLD"},
    "XAGUSDT":      {"mintick": 0.01,      "pricescale": 100,      "basecurrency": "XAG"},
    "XAUUSDT":      {"mintick": 0.01,      "pricescale": 100,      "basecurrency": "XAU"},
    "XLMUSDT":      {"mintick": 0.00001,   "pricescale": 100000,   "basecurrency": "XLM"},
    "XRPUSDT":      {"mintick": 0.0001,    "pricescale": 10000,    "basecurrency": "XRP"},
    "ZECUSDT":      {"mintick": 0.01,      "pricescale": 100,      "basecurrency": "ZEC"},
}


# ═══════════════════════════════════════════════════════════════
# Inputs — پیش‌فرض‌های CT v5
# ═══════════════════════════════════════════════════════════════
CT_INPUTS_DEFAULT = {
    "conversion_periods": 9,
    "base_periods": 26,
    "lagging_span2_periods": 52,
    "displacement": 26,
    "use_wicks_for_exit": True,
    "exit_consecutive_bars": 1,
    "max_anni_candles": 5,
    "aati_min_bars": 3,
    "distance_atr_mult": 1.5,
    "atr_len": 14,
    "enable_crescent_filter": False,
    "anni_stop_mode": "Far Edge (لبه دور ابر)",
    "aati_stop_mode": "Safe (امن)",
    "safe_buffer_atr_mult": 0.25,
    "rr_anni": 7.0,
    "rr_aati_risky": 10.0,
    "rr_aati_safe": 7.0,
    "enable_rf_second_touch": True,
    "enable_rf_reversal_candle": True,
    "enable_catalyst_filter": True,
    "enable_anni": True,
    "enable_aati": True,
    "trade_direction": "هر دو جهت",
    "enable_log": False,
}


# ═══════════════════════════════════════════════════════════════
# اجرای CT روی یه DataFrame
# ═══════════════════════════════════════════════════════════════
def run_ct_strategy(df, symbol, timeframe, inputs=None):
    """
    اجرای ct_strategy.py روی دیتای df و برگرداندن لیست سیگنال‌ها.
    """
    if df is None or df.empty:
        logger.warning(f"[CT] {symbol} {timeframe}: empty dataframe")
        return []

    if len(df) < 100:
        logger.warning(f"[CT] {symbol} {timeframe}: too few candles ({len(df)})")
        return []

    if inputs is None:
        inputs = CT_INPUTS_DEFAULT

    # ساخت candles
    candles = []
    for idx, row in df.iterrows():
        ts = int(idx.timestamp() * 1000)
        candles.append(OHLCV(
            timestamp=ts,
            open=float(row['open']),
            high=float(row['high']),
            low=float(row['low']),
            close=float(row['close']),
            volume=float(row.get('volume', 0)),
            is_closed=True,
        ))

    # SymInfo
    tick = SYMBOL_TICK_INFO.get(
        symbol.upper(),
        {"mintick": 0.01, "pricescale": 100, "basecurrency": symbol.replace("USDT", "")}
    )
    tf_min = int(timeframe) if str(timeframe).isdigit() else 60

    si = SymInfo(
        prefix="",
        description=f"{symbol} {tf_min}m",
        ticker=symbol,
        currency="USDT",
        basecurrency=tick["basecurrency"],
        period=str(tf_min),
        type="crypto",
        volumetype="base",
        mintick=tick["mintick"],
        pricescale=tick["pricescale"],
        minmove=1,
        pointvalue=1.0,
        mincontract=0.0,
        opening_hours=[SymInfoInterval(day=0, start=dt_time(0, 0), end=dt_time(23, 59, 59))],
        session_starts=[SymInfoSession(day=0, time=dt_time(0, 0))],
        session_ends=[SymInfoSession(day=0, time=dt_time(23, 59, 59))],
        timezone="UTC",
    )

    # اجرای ScriptRunner
    try:
        runner = ScriptRunner(
            CT_STRATEGY_PATH,
            iter(candles),
            si,
            last_bar_index=len(candles) - 1,
            inputs=inputs,
        )
    except Exception as e:
        logger.error(f"[CT] {symbol} {timeframe}: ScriptRunner init failed: {e}")
        return []

    # استخراج سیگنال‌ها
    signals = []
    bar_i = -1
    ms_list = [int(i.timestamp() * 1000) for i in df.index]

    try:
        for result in runner.run_iter():
            bar_i += 1
            if len(result) < 2 or not isinstance(result[1], dict):
                continue
            lv = result[1]
            if not lv:
                continue

            if lv.get("an_l_fire"):
                sig = _make_signal(bar_i, ms_list, lv, 'Anni-L', 'LONG',
                                   'an_l_entry', 'an_l_sl', 'an_l_tp')
                if sig: signals.append(sig)
            if lv.get("an_s_fire"):
                sig = _make_signal(bar_i, ms_list, lv, 'Anni-S', 'SHORT',
                                   'an_s_entry', 'an_s_sl', 'an_s_tp')
                if sig: signals.append(sig)
            if lv.get("at_l_fire"):
                sig = _make_signal(bar_i, ms_list, lv, 'Aati-L', 'LONG',
                                   'at_l_entry', 'at_l_sl', 'at_l_tp')
                if sig: signals.append(sig)
            if lv.get("at_s_fire"):
                sig = _make_signal(bar_i, ms_list, lv, 'Aati-S', 'SHORT',
                                   'at_s_entry', 'at_s_sl', 'at_s_tp')
                if sig: signals.append(sig)
    except Exception as e:
        logger.error(f"[CT] {symbol} {timeframe}: run_iter failed: {e}")
        return signals

    return signals


def _make_signal(bar_i, ms_list, lv, kind, direction, entry_key, stop_key, target_key):
    """ساخت یه سیگنال استاندارد"""
    ms = ms_list[bar_i] if 0 <= bar_i < len(ms_list) else None

    entry = lv.get(entry_key)
    stop = lv.get(stop_key)
    target = lv.get(target_key)

    def is_valid(x):
        if x is None:
            return False
        if isinstance(x, float) and (math.isnan(x) or math.isinf(x)):
            return False
        return True

    if not (is_valid(entry) and is_valid(stop) and is_valid(target)):
        return None

    t_utc = datetime.fromtimestamp(ms / 1000, tz=UTC_TZ) if ms else None
    t_iran = t_utc.astimezone(IRAN_TZ) if t_utc else None

    return {
        'time_ms': ms,
        'time_utc': t_utc,
        'time_iran': t_iran,
        'kind': kind,
        'direction': direction,
        'entry': float(entry),
        'stop': float(stop),
        'target': float(target),
        'bar_index': bar_i,
    }


# ═══════════════════════════════════════════════════════════════
# آخرین N سیگنال
# ═══════════════════════════════════════════════════════════════
def get_last_n_signals(df, symbol, timeframe, n=5, inputs=None):
    """برگرداندن آخرین n سیگنال"""
    all_signals = run_ct_strategy(df, symbol, timeframe, inputs)
    all_signals = [s for s in all_signals if s is not None]
    return sorted(all_signals, key=lambda x: x['time_ms'] or 0)[-n:]


# ═══════════════════════════════════════════════════════════════
# فرمت گزارش برای تلگرام
# ═══════════════════════════════════════════════════════════════
def format_signals_report(symbol, timeframe, signals):
    """فرمت کردن لیست سیگنال‌ها برای نمایش در تلگرام."""
    if not signals:
        return f"📊 {symbol} {timeframe}m — بدون سیگنال"

    lines = [f"📊 {symbol} {timeframe}m — {len(signals)} سیگنال آخر:"]
    lines.append("━━━━━━━━━━━━━━━━━━━━━━━━━━")

    for i, s in enumerate(signals, 1):
        if s['time_iran'] is None:
            time_str = "?"
        else:
            time_str = s['time_iran'].strftime("%Y-%m-%d %H:%M")

        emoji = "🟢" if s['direction'] == 'LONG' else "🔴"
        risk = abs(s['entry'] - s['stop']) if s['stop'] else 0
        rr = (abs(s['target'] - s['entry']) / risk) if risk > 0 else 0

        lines.append(f"{i}. {emoji} {s['kind']} | {time_str}")
        lines.append(
            f"   entry={s['entry']:.4f} SL={s['stop']:.4f} TP={s['target']:.4f} R:R={rr:.2f}"
        )

    return "\n".join(lines)