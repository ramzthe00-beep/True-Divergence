# -*- coding: utf-8 -*-
"""
راهنمای دقیق پچ‌کردن detect_signal در بات شما (dtm.py اصلی)
================================================================
⚠️ یک نکته‌ی مهم قبل از هر چیز:
فایلی که در این چت آپلود کردید (dtm.py) در واقع همان *اسکریپت
کامپایل‌شده‌ی PyneCore* بود (یک @script.strategy با plotshape های
CD-/CD+/HD+/HD-)، نه فایل ارکستریتور بات (کلاس‌های TrueTradePublicData/
TrueTradePrivateExchange، تلگرام، detect_signal و غیره) که شما به‌صورت
متن در پیام پیست کرده بودید. من فایل کامپایل‌شده را بدون تغییر با نام
`dtm_pyne_strategy.py` ذخیره کردم تا با فایل بات تداخل نکند.

چون بازنویسی کامل فایل ۹۰۰+ خطی بات از روی متن پیام ریسک اشتباه تایپی
دارد، به‌جای آن، این فایل دقیقاً همان چند تکه‌ای را نشان می‌دهد که باید
در فایل بات واقعی خودتان (dtm.py) اضافه/جایگزین کنید. هرکدام از این
پچ‌ها را در بخش مربوطه از فایل خودتان کپی کنید — بقیه‌ی بات (تلگرام،
سفارش‌گذاری، state persistence، حلقه‌ی اصلی و ...) کاملاً دست‌نخورده
می‌ماند، دقیقاً طبق درخواست شما.

فایل‌های همراه:
  - pyne_bridge.py            → ماژول پل (این را کنار dtm.py قرار دهید)
  - dtm_pyne_strategy.py      → همان اسکریپت کامپایل‌شده‌ی PyneCore شما
"""

# ======================================================================
# پچ ۱ — ایمپورت‌ها (بالای فایل dtm.py، کنار سایر import ها)
# ======================================================================
"""
# --- AFTER (اضافه کنید) ---
from pathlib import Path
from pyne_bridge import run_pyne_indicator, extract_final_signal
"""

# ======================================================================
# پچ ۲ — یک ثابت پیکربندی (کنار سایر ثابت‌ها، مثل HISTORY_BARS)
# ======================================================================
"""
# --- AFTER (اضافه کنید) ---
# مسیر اسکریپت کامپایل‌شده‌ی PyneCore — کنار همین فایل بات قرار دهید
PYNE_SCRIPT_PATH = Path(
    os.getenv("PYNE_SCRIPT_PATH", str(Path(__file__).parent / "dtm_pyne_strategy.py"))
)
# مطابق مقدار پیش‌فرض ورودی mtfTimeframe در خود اسکریپت PyneCore
PYNE_MTF_TIMEFRAME = "240"
"""

# ======================================================================
# پچ ۳ — فراخوانی پل PyneCore داخل detect_signal
# محل دقیق: بلافاصله بعد از این خط موجود در کد شما:
#     closed_df_reset = closed_df.reset_index(drop=True)
#     n = len(closed_df_reset)
#     if n < 33:
#         log(f"❌ داده ناکافی: {n}")
#         return None, None, None, None, False, None, None, 0, [], None, None
# یعنی درست بعد از چک n < 33 (تا مطمئن شویم داده کافی است) و قبل از
# محاسبه‌ی rsi_val/macd_line/... این تکه را اضافه کنید:
# ======================================================================
"""
# --- AFTER (اضافه کنید) ---
    # ============================================================
    # 🔗 PyneCore Bridge — اجرای اسکریپت کامپایل‌شده روی همین داده
    # فقط سیگنال نهایی (BUY/SELL) از آن استخراج می‌شود؛ محاسبه‌ی
    # entry/stop/target همچنان توسط منطق pivot-state زیر (بدون تغییر)
    # انجام می‌شود، چون اسکریپت پاین شما entry/stop/target تولید نمی‌کند.
    # اگر PyneCore در دسترس نباشد یا خطا بدهد، pyne_result برابر None
    # می‌ماند و کل منطق تشخیص داخلی زیر بدون هیچ تغییری اجرا می‌شود
    # (fail-safe — بات هرگز به خاطر این پل متوقف نمی‌شود).
    # ============================================================
    pyne_plots = run_pyne_indicator(closed_df, PYNE_SCRIPT_PATH, symbol, PYNE_MTF_TIMEFRAME)
    pyne_result = extract_final_signal(pyne_plots)
    pyne_signal = pyne_result["signal"] if pyne_result else None
    if pyne_result is not None:
        log(f"   🔗 PyneCore → signal={pyne_signal or '—'} ({pyne_result.get('label') or '-'})")
    else:
        log(f"   🔗 PyneCore → در دسترس نیست، fallback به منطق تشخیص داخلی")
"""

# ======================================================================
# پچ ۴ — چهار بلاک تصمیم‌گیری (Classic Bearish / Classic Bullish /
# Hidden Bullish / Hidden Bearish) هرکدام یک شرط IF دارند که باید عوض شود.
# فقط خط IF عوض می‌شود؛ محاسبه‌ی entry_price/stop_price/target_price/
# details/score/pivot1/pivot2 زیر آن‌ها کاملاً دست‌نخورده می‌ماند.
# ======================================================================

# ---- ۴.۱ Classic Bearish (بخش «# 1. Classic Bearish») --------------
"""
# --- BEFORE (کد فعلی شما) ---
        if classic_bearish_base3:
            if passes_min_requirement(classic_bearish_base3, fib_ok, pa_ok):
                entry_price = float(close_series.iloc[-1])

# --- AFTER (جایگزین کنید) ---
        classic_bearish_confirmed = (
            (pyne_signal == "SELL") if pyne_result is not None
            else passes_min_requirement(classic_bearish_base3, fib_ok, pa_ok)
        )
        if classic_bearish_base3:
            if classic_bearish_confirmed:
                entry_price = float(close_series.iloc[-1])
"""

# ---- ۴.۲ Classic Bullish (بخش «# 2. Classic Bullish») --------------
"""
# --- BEFORE (کد فعلی شما) ---
        if classic_bullish_base3:
            if passes_min_requirement(classic_bullish_base3, fib_ok, pa_ok):
                entry_price = float(close_series.iloc[-1])

# --- AFTER (جایگزین کنید) ---
        classic_bullish_confirmed = (
            (pyne_signal == "BUY") if pyne_result is not None
            else passes_min_requirement(classic_bullish_base3, fib_ok, pa_ok)
        )
        if classic_bullish_base3:
            if classic_bullish_confirmed:
                entry_price = float(close_series.iloc[-1])
"""

# ---- ۴.۳ Hidden Bullish (بخش «# 3. Hidden Bullish») -----------------
"""
# --- BEFORE (کد فعلی شما) ---
        if hidden_bullish_base3:
            if passes_min_requirement(hidden_bullish_base3, fib_ok, pa_ok):
                entry_price = float(close_series.iloc[-1])

# --- AFTER (جایگزین کنید) ---
        hidden_bullish_confirmed = (
            (pyne_signal == "BUY") if pyne_result is not None
            else passes_min_requirement(hidden_bullish_base3, fib_ok, pa_ok)
        )
        if hidden_bullish_base3:
            if hidden_bullish_confirmed:
                entry_price = float(close_series.iloc[-1])
"""

# ---- ۴.۴ Hidden Bearish (بخش «# 4. Hidden Bearish») -----------------
"""
# --- BEFORE (کد فعلی شما) ---
        if hidden_bearish_base3:
            if passes_min_requirement(hidden_bearish_base3, fib_ok, pa_ok):
                entry_price = float(close_series.iloc[-1])

# --- AFTER (جایگزین کنید) ---
        hidden_bearish_confirmed = (
            (pyne_signal == "SELL") if pyne_result is not None
            else passes_min_requirement(hidden_bearish_base3, fib_ok, pa_ok)
        )
        if hidden_bearish_base3:
            if hidden_bearish_confirmed:
                entry_price = float(close_series.iloc[-1])
"""

# ======================================================================
# همین چهار پچ کل ادغام است. جمع‌بندی رفتار نهایی:
#   • اگر PyneCore در دسترس و سالم باشد → تأییدیه‌ی نهایی هر واگرایی از
#     خروجی plotshape اسکریپت کامپایل‌شده گرفته می‌شود (منبع حقیقت،
#     چون دقیقاً همان چیزی است که در TradingView هم دیده می‌شود).
#   • اگر PyneCore نصب نباشد / فایل اسکریپت پیدا نشود / خطا بدهد →
#     pyne_result همیشه None است و passes_min_requirement داخلی شما
#     دقیقاً مثل قبل از این پچ عمل می‌کند (صفر تغییر رفتار / fail-safe).
#   • تلگرام، ثبت سفارش، ذخیره‌ی state (save_states/save_history)،
#     محاسبه‌ی stop/target/score/pivot1/pivot2 و کل حلقه‌ی main_loop
#     کاملاً دست‌نخورده باقی می‌مانند.
# ======================================================================
