"""@pyne

CT-DTM (Ichimoku) — Signal Generator (PyneCore 6.10 compatible) — v5

تغییرات نسبت به v4 (فقط در بخش «محاسبه و تشخیص سیگنال» / مدیریت پوزیشن؛
بخش‌های ایچیموکو/ابر/لگ/eligibility دست‌نخورده ماندند):

  ه) باگ واقعی #۳ — قیمت entry اشتباه بود (اثر روی TP و ریسک‌فری، نه روی
     زمان‌بندی خودِ سیگنال):
       نسخه‌ی v4 عمداً entry را close همان کندل فیل می‌گذاشت (تصمیم آگاهانه‌ی
       نسخه‌های قبلی، طبق کامنت «د» در v4). این با رفتار واقعی Pine مغایر
       است: Pine مقدار anLEntry را از f_entryPrice() می‌گیرد که دقیقاً همان
       قیمت پرشدن سفارش limit توسط بروکر-امولاتور است — یعنی همان چیزی که
       این فایل already به‌عنوان an_l_pine_px/an_s_pine_px/at_l_pine_px/
       at_s_pine_px محاسبه می‌کرد (min(open, limit) برای لانگ، max(open,
       limit) برای شورت) ولی فقط برای لاگ استفاده می‌شد، نه برای منطق واقعی.

       این تفاوت روی TP اثر مستقیم دارد (چون TP = entry ± (entry-SL)*rr)
       و روی سطح ریسک‌فری (breakeven = max/min(SL, entry)) و به‌تبع آن،
       روی نقطه‌ی SL/TP که بعداً در sim_exit چک می‌شود — یعنی می‌تواند
       زمان و قیمت خروج واقعی را هم عوض کند و در یک بک‌تست طولانی به‌مرور
       باعث واگرایی کامل از رفتار Pine شود.

       تأیید تجربی: با پردازش pine-logs-CT-Strategy-v3.csv (135 رویداد FILL)
       و تطبیق kumoTop/kumoBot هم‌کندلِ هرکدام (از رویدادهای TOUCH هم‌بار)،
       در تمام 101 مورد قابل‌تطبیق: SL دقیقاً برابر cloud-mid بود و
       rr = (TP-entry)/(entry-SL) دقیقاً 10.0 بود — وقتی entry همان قیمتِ
       «@» چاپ‌شده در لاگ (یعنی pine_px) در نظر گرفته شود. اگر entry به‌جای
       آن close کندل فیل بود، این نسبت‌ها adari این‌قدر تمیز و یکنواخت
       نمی‌شدند (چون close کندل فیل معمولاً با قیمت لمسِ عبر یکی نیست).
       این خودش مدرک مستقل (غیر از خواندن کد Pine) است که Pine واقعاً از
       قیمت fill بروکر استفاده می‌کند، نه close کندل.

       رفع شد: an_l_entry / an_s_entry / at_l_entry / at_s_entry حالا
       مستقیماً برابر همان an_l_pine_px / an_s_pine_px / at_l_pine_px /
       at_s_pine_px قرار می‌گیرند (که پیش‌تر فقط برای لاگ محاسبه می‌شدند).

  و) هم‌ترازی متن لاگ‌ها با Pine (صرفاً کازمتیک، اثر منطقی ندارد، ولی برای
     دیف مستقیمِ متن لاگ با CSV لازم است):
       - پیام [FILL] حالا دقیقاً فرمت Pine را دارد: "<Kind> @ <entry> SL=..
         TP=.." — فیلد اضافه‌ی "mkt=" که در v4 بود (و بعد از رفع بند «ه»
         دیگر مقدار تکراری/بی‌فایده بود) حذف شد.
       - پیام [STALE-GUARD] کلمه‌ی "intrabar" را هم مثل Pine دارد.
       - پیام‌های [LEG-UP]/[LEG-DOWN] حالا "zone=[low,high]" را هم مثل
         Pine چاپ می‌کنند (مقدار low/high همان کندلی که لگ تایید شده).

  نکته‌ی مهم: در pine-logs-CT-Strategy-v3.csv هیچ رویداد [EXIT] وجود ندارد
  (Pine v3 اصلاً exit را log.info نمی‌کند) — پس صحت زمان/قیمتِ خروج
  (SL/TP hit) را نمی‌توان از روی همین CSV راستی‌آزمایی کرد؛ فقط رویدادهای
  LEG-UP/DOWN, ELIG-ON/OFF, TOUCH, AATI-ARMED, FILL, RISK-FREE, STALE-GUARD
  قابل تطبیق مستقیم با این فایل هستند.

  همچنین: راستی‌آزمایی واقعی «اجرا کن و با لاگ پاین دیف بگیر» به داده‌ی
  کندل (OHLC) نیاز دارد که در این CSV وجود ندارد (این فایل فقط متنِ
  رویدادهای لاگ‌شده را دارد، نه سری قیمت ورودی). اگر داده‌ی OHLC همان
  نماد/تایم‌فریمی که این لاگ از رویش تولید شده در اختیار باشد، می‌شود
  این اسکریپت را روی آن ران کرد و خروجی‌اش را خط‌به‌خط با همین CSV
  مقایسه کرد.
"""
from pynecore.lib import (
    bar_index, barstate, close, high, input, low, math, na,
    open, plot, script, ta,
)
from pynecore.types import Persistent, na_float
import logging

logger = logging.getLogger(__name__)

# ─── گروه‌ها ───
grp_ichi = "ایچیموکو"
grp_logic = "منطق استراتژی CT"
grp_stop = "حد ضرر و تارگت"
grp_rf = "ریسک فری"
grp_filter = "فیلترها"
grp_log = "لاگ تشخیصی"

ANNI_STOP_MID = "Mid-Cloud (وسط ابر)"
ANNI_STOP_FAR = "Far Edge (لبه دور ابر)"
AATI_STOP_SAFE = "Safe (امن)"
AATI_STOP_RISKY = "Risky (ریسکی)"
DIR_BOTH = "هر دو جهت"
DIR_LONG_ONLY = "فقط لانگ"
DIR_SHORT_ONLY = "فقط شورت"

MAX_HIST = 1000


def sim_exit(is_long: bool, o: float, h: float, l: float, sl: float, tp: float):
    """شبیه‌سازی broker emulator تریدینگ‌ویو برای strategy.exit(stop=sl, limit=tp)"""
    if is_long:
        if o <= sl:
            return "SL", o
        if o >= tp:
            return "TP", o
        hit_sl = l <= sl
        hit_tp = h >= tp
        up_first = (h - o) < (o - l)
        if up_first:
            if hit_tp:
                return "TP", tp
            if hit_sl:
                return "SL", sl
        else:
            if hit_sl:
                return "SL", sl
            if hit_tp:
                return "TP", tp
    else:
        if o >= sl:
            return "SL", o
        if o <= tp:
            return "TP", o
        hit_sl = h >= sl
        hit_tp = l <= tp
        up_first = (h - o) < (o - l)
        if up_first:
            if hit_sl:
                return "SL", sl
            if hit_tp:
                return "TP", tp
        else:
            if hit_tp:
                return "TP", tp
            if hit_sl:
                return "SL", sl
    return "", 0.0


def prev_val(buf, k: int) -> float:
    """
    مقدار k کندل قبل. buffer شامل کندل جاری «نیست» (فقط کندل‌های بسته‌شده).
    k=1 → کندل قبلی (معادل Pine [1]) ، k=26 → [26]
    """
    if len(buf) >= k:
        return buf[-k]
    return na_float


@script.indicator(
    "CT-DTM (Ichimoku)",
    shorttitle="CT-Strategy-v5",
    overlay=True,
)
def main(
    # ─── ایچیموکو ───
    conversion_periods=input.int(9, "Conversion Periods (Tenkan)", group=grp_ichi),
    base_periods=input.int(26, "Base Periods (Kijun)", group=grp_ichi),
    lagging_span2_periods=input.int(52, "Leading Span B Periods", group=grp_ichi),
    displacement=input.int(26, "Displacement (Cloud Shift)", group=grp_ichi),

    # ─── منطق CT ───
    use_wicks_for_exit=input.bool(True, "خروج کامل با احتساب سایه", group=grp_logic),
    exit_consecutive_bars=input.int(1, "کندل بسته‌شده برای تایید خروج", minval=1, maxval=10, group=grp_logic),
    max_anni_candles=input.int(5, "حداکثر کندل برای مدل آنی", minval=1, group=grp_logic),
    aati_min_bars=input.int(3, "حداقل کندل قبل از تست آتی", minval=1, group=grp_logic),
    distance_atr_mult=input.float(1.5, "حداقل فاصله از ابر (ATR)", minval=0.1, step=0.1, group=grp_logic),
    atr_len=input.int(14, "دوره ATR", group=grp_logic),
    enable_crescent_filter=input.bool(False, "فعال‌سازی فیلتر هلال", group=grp_logic),


    # ─── حد ضرر / تارگت ───
    anni_stop_mode=input.string(ANNI_STOP_FAR, "حد ضرر آنی", options=(ANNI_STOP_MID, ANNI_STOP_FAR), group=grp_stop),
    aati_stop_mode=input.string(AATI_STOP_SAFE, "حد ضرر آتی", options=(AATI_STOP_SAFE, AATI_STOP_RISKY), group=grp_stop),
    safe_buffer_atr_mult=input.float(0.25, "بافر حالت امن (ATR)", minval=0.0, step=0.05, group=grp_stop),
    rr_anni=input.float(7.0, "R:R آنی", minval=0.5, step=0.5, group=grp_stop),
    rr_aati_risky=input.float(10.0, "R:R آتی (ریسکی)", minval=0.5, step=0.5, group=grp_stop),
    rr_aati_safe=input.float(7.0, "R:R آتی (امن)", minval=0.5, step=0.5, group=grp_stop),

    # ─── ریسک‌فری ───
    enable_rf_second_touch=input.bool(True, "ریسک‌فری با برخورد دوم", group=grp_rf),
    enable_rf_reversal_candle=input.bool(True, "ریسک‌فری با کندل بازگشتی", group=grp_rf),
    enable_catalyst_filter=input.bool(True, "فعال‌سازی کاتالیزور", group=grp_rf),

    # ─── فیلترها ───
    enable_anni=input.bool(True, "فعال‌سازی مدل آنی", group=grp_filter),
    enable_aati=input.bool(True, "فعال‌سازی مدل آتی", group=grp_filter),
    trade_direction=input.string(DIR_BOTH, "جهت مجاز", options=(DIR_BOTH, DIR_LONG_ONLY, DIR_SHORT_ONLY), group=grp_filter),

    # ─── لاگ ───
    enable_log=input.bool(True, "لاگ رویدادها", group=grp_log),
):
    # ═══════════════════════════════════════════════════════════
    # 🔵 History buffers — فقط کندل‌های «بسته‌شده» (کندل جاری داخل نیست)
    # ═══════════════════════════════════════════════════════════
    close_hist: Persistent[list] = []
    open_hist: Persistent[list] = []
    hma20_hist: Persistent[list] = []
    hma50_hist: Persistent[list] = []
    rsi_hist: Persistent[list] = []
    lead1_hist: Persistent[list] = []
    lead2_hist: Persistent[list] = []

    def flog(tag: str, msg: str) -> None:
        if enable_log:
            logger.info(f"{tag} | bar={bar_index} | {msg}")

    bar_o = float(open)
    bar_h = float(high)
    bar_l = float(low)
    bar_c = float(close)

    confirmed = barstate.isconfirmed

    if confirmed and int(bar_index) == 0:
        flog("[PARAMS]", f"aati_min_bars={aati_min_bars} max_anni_candles={max_anni_candles} "
                         f"distance_atr_mult={distance_atr_mult} exit_consecutive_bars={exit_consecutive_bars} "
                         f"use_wicks_for_exit={use_wicks_for_exit} displacement={displacement} "
                         f"crescent={enable_crescent_filter} aati_stop={aati_stop_mode} "
                         f"dir={trade_direction} atr_len={atr_len}")

    # ═══════════════════════════════════════════════════════════
    # 🔵 ایچیموکو (بدون تغییر — در برابر لاگ Pine تایید شد)
    # ═══════════════════════════════════════════════════════════
    conversion_line = (ta.highest(high, conversion_periods) + ta.lowest(low, conversion_periods)) / 2
    base_line = (ta.highest(high, base_periods) + ta.lowest(low, base_periods)) / 2
    lead_line1 = (conversion_line + base_line) / 2
    lead_line2 = (ta.highest(high, lagging_span2_periods) + ta.lowest(low, lagging_span2_periods)) / 2

    lead1_disp = prev_val(lead1_hist, displacement - 1)
    lead2_disp = prev_val(lead2_hist, displacement - 1)

    kumo_valid = (not na(lead1_disp)) and (not na(lead2_disp))

    kumo_top = na_float
    kumo_bot = na_float
    if kumo_valid:
        kumo_top = math.max(lead1_disp, lead2_disp)
        kumo_bot = math.min(lead1_disp, lead2_disp)

    atr_val = float(ta.atr(length=atr_len))

    # ═══════════════════════════════════════════════════════════
    # 🔵 HMA / RSI / کندل قبلی
    # ═══════════════════════════════════════════════════════════
    hma20 = float(ta.hma(close, 20))
    hma50 = float(ta.hma(close, 50))
    hma20_prev = prev_val(hma20_hist, 1)
    hma50_prev = prev_val(hma50_hist, 1)

    bullish_crescent = (
        not na(hma20_prev) and not na(hma50_prev)
        and hma20 > hma50 and hma20 > hma20_prev and hma50 > hma50_prev
    )
    bearish_crescent = (
        not na(hma20_prev) and not na(hma50_prev)
        and hma20 < hma50 and hma20 < hma20_prev and hma50 < hma50_prev
    )

    close_prev = prev_val(close_hist, 1)
    open_prev = prev_val(open_hist, 1)

    rsi_val = float(ta.rsi(source=close, length=14))
    rsi_prev = prev_val(rsi_hist, 1)

    # ═══════════════════════════════════════════════════════════
    # 🔵 فیلترها و برخورد
    # ═══════════════════════════════════════════════════════════
    fully_above_now = False
    fully_below_now = False
    if kumo_valid:
        if use_wicks_for_exit:
            fully_above_now = bar_l > kumo_top
            fully_below_now = bar_h < kumo_bot
        else:
            fully_above_now = min(bar_o, bar_c) > kumo_top
            fully_below_now = max(bar_o, bar_c) < kumo_bot

    touch_cloud_now = kumo_valid and bar_l <= kumo_top and bar_h >= kumo_bot

    def bearish_reversal() -> bool:
        if na(close_prev) or na(open_prev):
            return False
        return bar_c < bar_o and close_prev > open_prev and bar_c < open_prev and bar_o > close_prev

    def bullish_reversal() -> bool:
        if na(close_prev) or na(open_prev):
            return False
        return bar_c > bar_o and close_prev < open_prev and bar_c > open_prev and bar_o < close_prev

    def catalyst() -> bool:
        if na(close_prev) or na(rsi_prev):
            return False
        return (bar_c > close_prev and rsi_val < rsi_prev) or (bar_c < close_prev and rsi_val > rsi_prev)

    # ═══════════════════════════════════════════════════════════
    # 🔵 State
    # ═══════════════════════════════════════════════════════════
    consec_above: Persistent[int] = 0
    consec_below: Persistent[int] = 0
    exit_dir: Persistent[str] = ""
    exit_bar: Persistent[int] = -1
    max_distance_atr: Persistent[float] = 0.0
    anni_done: Persistent[bool] = False
    aati_armed: Persistent[bool] = False
    aati_done: Persistent[bool] = False
    exit_number: Persistent[int] = 0
    touch_prev: Persistent[bool] = False

    pend_an_l: Persistent[bool] = False
    pend_an_l_px: Persistent[float] = na_float
    pend_an_s: Persistent[bool] = False
    pend_an_s_px: Persistent[float] = na_float
    pend_at_l: Persistent[bool] = False
    pend_at_l_px: Persistent[float] = na_float
    pend_at_s: Persistent[bool] = False
    pend_at_s_px: Persistent[float] = na_float

    elig_prev_an_l: Persistent[bool] = False
    elig_prev_an_s: Persistent[bool] = False
    elig_prev_at_l: Persistent[bool] = False
    elig_prev_at_s: Persistent[bool] = False

    an_l_pos: Persistent[bool] = False
    an_l_entry: Persistent[float] = na_float
    an_l_sl: Persistent[float] = na_float
    an_l_tp: Persistent[float] = na_float
    an_l_touches: Persistent[int] = 0

    an_s_pos: Persistent[bool] = False
    an_s_entry: Persistent[float] = na_float
    an_s_sl: Persistent[float] = na_float
    an_s_tp: Persistent[float] = na_float
    an_s_touches: Persistent[int] = 0

    at_l_pos: Persistent[bool] = False
    at_l_entry: Persistent[float] = na_float
    at_l_sl: Persistent[float] = na_float
    at_l_tp: Persistent[float] = na_float
    at_l_touches: Persistent[int] = 0

    at_s_pos: Persistent[bool] = False
    at_s_entry: Persistent[float] = na_float
    at_s_sl: Persistent[float] = na_float
    at_s_tp: Persistent[float] = na_float
    at_s_touches: Persistent[int] = 0

    # ─── خروجی‌های این اجرا ───
    an_l_fire = False
    an_s_fire = False
    at_l_fire = False
    at_s_fire = False
    an_l_pine_px = na_float
    an_s_pine_px = na_float
    at_l_pine_px = na_float
    at_s_pine_px = na_float

    an_l_exit = ""
    an_s_exit = ""
    at_l_exit = ""
    at_s_exit = ""
    an_l_exit_px = na_float
    an_s_exit_px = na_float
    at_l_exit_px = na_float
    at_s_exit_px = na_float

    bars_since_exit = -1
    if exit_bar >= 0:
        bars_since_exit = int(bar_index) - exit_bar

    touch_cloud_event = False
    not_stale = True
    anni_long_elig = False
    anni_short_elig = False
    aati_long_elig = False
    aati_short_elig = False

    allow_long = trade_direction != DIR_SHORT_ONLY
    allow_short = trade_direction != DIR_LONG_ONLY

    # ═══════════════════════════════════════════════════════════
    # 🔵 منطق اصلی — فقط روی کندل بسته‌شده
    # ═══════════════════════════════════════════════════════════
    if confirmed:
        # ── ۰) فیل سفارش‌های معلقِ کندل قبل ──
        fill_an_l = pend_an_l and bar_l <= pend_an_l_px
        fill_an_s = pend_an_s and bar_h >= pend_an_s_px
        fill_at_l = pend_at_l and bar_l <= pend_at_l_px
        fill_at_s = pend_at_s and bar_h >= pend_at_s_px

        # ── ۱) شمارنده خروج + لِگ ──
        f_ac = kumo_valid and ((bar_l > kumo_top) if use_wicks_for_exit else (min(bar_o, bar_c) > kumo_top))
        f_bc = kumo_valid and ((bar_h < kumo_bot) if use_wicks_for_exit else (max(bar_o, bar_c) < kumo_bot))

        consec_above = consec_above + 1 if f_ac else 0
        consec_below = consec_below + 1 if f_bc else 0

        new_leg_up = (consec_above == exit_consecutive_bars) and (exit_dir != "up")
        new_leg_down = (consec_below == exit_consecutive_bars) and (exit_dir != "down")

        if new_leg_up:
            exit_dir = "up"
            exit_bar = int(bar_index)
            max_distance_atr = 0.0
            anni_done = False
            aati_armed = False
            aati_done = False
            exit_number += 1
            flog("[LEG-UP]", f"leg #{exit_number} confirmed after {consec_above} closed candle(s) | zone=[{bar_l},{bar_h}]")

        if new_leg_down:
            exit_dir = "down"
            exit_bar = int(bar_index)
            max_distance_atr = 0.0
            anni_done = False
            aati_armed = False
            aati_done = False
            exit_number += 1
            flog("[LEG-DOWN]", f"leg #{exit_number} confirmed after {consec_below} closed candle(s) | zone=[{bar_l},{bar_h}]")

        bars_since_exit = -1
        if exit_bar >= 0:
            bars_since_exit = int(bar_index) - exit_bar

        # ── ۲) فاصله از ابر / آماده‌شدن آتی ──
        if (exit_dir != "") and kumo_valid and atr_val > 0:
            cur_dist = (bar_l - kumo_top) / atr_val if exit_dir == "up" else (kumo_bot - bar_h) / atr_val
            max_distance_atr = math.max(max_distance_atr, cur_dist)
            if max_distance_atr >= distance_atr_mult and not aati_armed:
                aati_armed = True
                flog("[AATI-ARMED]", f"distance threshold reached | maxDistanceATR={max_distance_atr}")

        # ── ۳) برخورد به ابر ──
        touch_cloud_event = touch_cloud_now and (not touch_prev)
        if touch_cloud_event:
            flog("[TOUCH]", f"H={bar_h} L={bar_l} kumoTop={kumo_top} kumoBot={kumo_bot}")

        not_stale = not ((exit_dir == "down" and fully_above_now) or (exit_dir == "up" and fully_below_now))
        if not not_stale:
            flog("[STALE-GUARD]", f"exitDir={exit_dir} contradicted intrabar → pending orders will cancel")

        # ── ۴) شرایط واجدشرایط‌بودن ──
        anni_long_elig = (enable_anni and allow_long and exit_dir == "up"
            and bars_since_exit >= 0 and bars_since_exit <= max_anni_candles
            and (not anni_done) and not_stale)
        anni_short_elig = (enable_anni and allow_short and exit_dir == "down"
            and bars_since_exit >= 0 and bars_since_exit <= max_anni_candles
            and (not anni_done) and not_stale)
        aati_long_elig = (enable_aati and allow_long and exit_dir == "up" and aati_armed
            and bars_since_exit >= aati_min_bars and (not aati_done) and not_stale
            and ((not enable_crescent_filter) or bullish_crescent))
        aati_short_elig = (enable_aati and allow_short and exit_dir == "down" and aati_armed
            and bars_since_exit >= aati_min_bars and (not aati_done) and not_stale
            and ((not enable_crescent_filter) or bearish_crescent))

        if anni_long_elig and not elig_prev_an_l:
            flog("[ELIG-ON]", f"Anni-L | kumoTop={kumo_top}")
        if (not anni_long_elig) and elig_prev_an_l:
            flog("[ELIG-OFF]", f"Anni-L | anniDone={anni_done} notStale={not_stale} barsSinceExit={bars_since_exit}")
        if anni_short_elig and not elig_prev_an_s:
            flog("[ELIG-ON]", f"Anni-S | kumoBot={kumo_bot}")
        if (not anni_short_elig) and elig_prev_an_s:
            flog("[ELIG-OFF]", f"Anni-S | anniDone={anni_done} notStale={not_stale} barsSinceExit={bars_since_exit}")
        if aati_long_elig and not elig_prev_at_l:
            flog("[ELIG-ON]", f"Aati-L | kumoTop={kumo_top}")
        if aati_short_elig and not elig_prev_at_s:
            flog("[ELIG-ON]", f"Aati-S | kumoBot={kumo_bot}")
        elig_prev_an_l = anni_long_elig
        elig_prev_an_s = anni_short_elig
        elig_prev_at_l = aati_long_elig
        elig_prev_at_s = aati_short_elig

        # ═══════════════════════════════════════════════════════
        # Anni-L
        # ═══════════════════════════════════════════════════════
        if an_l_pos:
            an_l_exit, an_l_exit_px = sim_exit(True, bar_o, bar_h, bar_l, an_l_sl, an_l_tp)
            if an_l_exit != "":
                an_l_pos = False
                flog("[EXIT]", f"Anni-L {an_l_exit} @ {an_l_exit_px}")
            else:
                if touch_cloud_event:
                    an_l_touches += 1
                if (enable_rf_second_touch and an_l_touches >= 2) or (
                    enable_rf_reversal_candle and bearish_reversal()
                    and ((not enable_catalyst_filter) or catalyst())
                ):
                    if an_l_sl < an_l_entry:
                        flog("[RISK-FREE]", f"Anni-L moved to breakeven @ {an_l_entry}")
                    an_l_sl = math.max(an_l_sl, an_l_entry)
        if not an_l_pos:
            if fill_an_l:
                an_l_pine_px = min(bar_o, pend_an_l_px)
                pend_an_l = False
                anni_done = True
                sl_c = (kumo_top + kumo_bot) / 2 if anni_stop_mode == ANNI_STOP_MID else kumo_bot
                an_l_pos = True
                an_l_entry = an_l_pine_px
                an_l_sl = sl_c
                an_l_tp = an_l_entry + (an_l_entry - an_l_sl) * rr_anni
                an_l_touches = 0
                an_l_fire = True
                flog("[FILL]", f"Anni-L @ {an_l_entry} SL={an_l_sl} TP={an_l_tp}")
                # FIX: همان چک‌هایی که Pine در همین کندل (همان بلوک) انجام می‌دهد
                if touch_cloud_event:
                    an_l_touches += 1
                if (enable_rf_second_touch and an_l_touches >= 2) or (
                    enable_rf_reversal_candle and bearish_reversal()
                    and ((not enable_catalyst_filter) or catalyst())
                ):
                    if an_l_sl < an_l_entry:
                        flog("[RISK-FREE]", f"Anni-L moved to breakeven @ {an_l_entry}")
                    an_l_sl = math.max(an_l_sl, an_l_entry)
            elif anni_long_elig and kumo_valid:
                pend_an_l = True
                pend_an_l_px = kumo_top
            else:
                pend_an_l = False
        if not an_l_pos and not fill_an_l:
            an_l_entry = na_float

        # ═══════════════════════════════════════════════════════
        # Anni-S
        # ═══════════════════════════════════════════════════════
        if an_s_pos:
            an_s_exit, an_s_exit_px = sim_exit(False, bar_o, bar_h, bar_l, an_s_sl, an_s_tp)
            if an_s_exit != "":
                an_s_pos = False
                flog("[EXIT]", f"Anni-S {an_s_exit} @ {an_s_exit_px}")
            else:
                if touch_cloud_event:
                    an_s_touches += 1
                if (enable_rf_second_touch and an_s_touches >= 2) or (
                    enable_rf_reversal_candle and bullish_reversal()
                    and ((not enable_catalyst_filter) or catalyst())
                ):
                    if an_s_sl > an_s_entry:
                        flog("[RISK-FREE]", f"Anni-S moved to breakeven @ {an_s_entry}")
                    an_s_sl = math.min(an_s_sl, an_s_entry)
        if not an_s_pos:
            if fill_an_s:
                an_s_pine_px = max(bar_o, pend_an_s_px)
                pend_an_s = False
                anni_done = True
                sl_s = (kumo_top + kumo_bot) / 2 if anni_stop_mode == ANNI_STOP_MID else kumo_top
                an_s_pos = True
                an_s_entry = an_s_pine_px
                an_s_sl = sl_s
                an_s_tp = an_s_entry - (an_s_sl - an_s_entry) * rr_anni
                an_s_touches = 0
                an_s_fire = True
                flog("[FILL]", f"Anni-S @ {an_s_entry} SL={an_s_sl} TP={an_s_tp}")
                if touch_cloud_event:
                    an_s_touches += 1
                if (enable_rf_second_touch and an_s_touches >= 2) or (
                    enable_rf_reversal_candle and bullish_reversal()
                    and ((not enable_catalyst_filter) or catalyst())
                ):
                    if an_s_sl > an_s_entry:
                        flog("[RISK-FREE]", f"Anni-S moved to breakeven @ {an_s_entry}")
                    an_s_sl = math.min(an_s_sl, an_s_entry)
            elif anni_short_elig and kumo_valid:
                pend_an_s = True
                pend_an_s_px = kumo_bot
            else:
                pend_an_s = False
        if not an_s_pos and not fill_an_s:
            an_s_entry = na_float

        # ═══════════════════════════════════════════════════════
        # Aati-L
        # ═══════════════════════════════════════════════════════
        if at_l_pos:
            at_l_exit, at_l_exit_px = sim_exit(True, bar_o, bar_h, bar_l, at_l_sl, at_l_tp)
            if at_l_exit != "":
                at_l_pos = False
                flog("[EXIT]", f"Aati-L {at_l_exit} @ {at_l_exit_px}")
            else:
                if touch_cloud_event:
                    at_l_touches += 1
                if (enable_rf_second_touch and at_l_touches >= 2) or (
                    enable_rf_reversal_candle and bearish_reversal()
                    and ((not enable_catalyst_filter) or catalyst())
                ):
                    if at_l_sl < at_l_entry:
                        flog("[RISK-FREE]", f"Aati-L moved to breakeven @ {at_l_entry}")
                    at_l_sl = math.max(at_l_sl, at_l_entry)
        if not at_l_pos:
            if fill_at_l:
                at_l_pine_px = min(bar_o, pend_at_l_px)
                pend_at_l = False
                aati_done = True
                aati_armed = False
                risky_l = aati_stop_mode == AATI_STOP_RISKY
                cloud_mid_l = (kumo_top + kumo_bot) / 2
                sl_al = cloud_mid_l if risky_l else kumo_bot - safe_buffer_atr_mult * atr_val
                rr_al = rr_aati_risky if risky_l else rr_aati_safe
                at_l_pos = True
                at_l_entry = at_l_pine_px
                at_l_sl = sl_al
                at_l_tp = at_l_entry + (at_l_entry - at_l_sl) * rr_al
                at_l_touches = 0
                at_l_fire = True
                flog("[FILL]", f"Aati-L @ {at_l_entry} SL={at_l_sl} TP={at_l_tp}")
                if touch_cloud_event:
                    at_l_touches += 1
                if (enable_rf_second_touch and at_l_touches >= 2) or (
                    enable_rf_reversal_candle and bearish_reversal()
                    and ((not enable_catalyst_filter) or catalyst())
                ):
                    if at_l_sl < at_l_entry:
                        flog("[RISK-FREE]", f"Aati-L moved to breakeven @ {at_l_entry}")
                    at_l_sl = math.max(at_l_sl, at_l_entry)
            elif aati_long_elig and kumo_valid:
                pend_at_l = True
                pend_at_l_px = kumo_top
            else:
                pend_at_l = False
        if not at_l_pos and not fill_at_l:
            at_l_entry = na_float

        # ═══════════════════════════════════════════════════════
        # Aati-S
        # ═══════════════════════════════════════════════════════
        if at_s_pos:
            at_s_exit, at_s_exit_px = sim_exit(False, bar_o, bar_h, bar_l, at_s_sl, at_s_tp)
            if at_s_exit != "":
                at_s_pos = False
                flog("[EXIT]", f"Aati-S {at_s_exit} @ {at_s_exit_px}")
            else:
                if touch_cloud_event:
                    at_s_touches += 1
                if (enable_rf_second_touch and at_s_touches >= 2) or (
                    enable_rf_reversal_candle and bullish_reversal()
                    and ((not enable_catalyst_filter) or catalyst())
                ):
                    if at_s_sl > at_s_entry:
                        flog("[RISK-FREE]", f"Aati-S moved to breakeven @ {at_s_entry}")
                    at_s_sl = math.min(at_s_sl, at_s_entry)
        if not at_s_pos:
            if fill_at_s:
                at_s_pine_px = max(bar_o, pend_at_s_px)
                pend_at_s = False
                aati_done = True
                aati_armed = False
                risky_s = aati_stop_mode == AATI_STOP_RISKY
                cloud_mid_s = (kumo_top + kumo_bot) / 2
                sl_as = cloud_mid_s if risky_s else kumo_top + safe_buffer_atr_mult * atr_val
                rr_as = rr_aati_risky if risky_s else rr_aati_safe
                at_s_pos = True
                at_s_entry = at_s_pine_px
                at_s_sl = sl_as
                at_s_tp = at_s_entry - (at_s_sl - at_s_entry) * rr_as
                at_s_touches = 0
                at_s_fire = True
                flog("[FILL]", f"Aati-S @ {at_s_entry} SL={at_s_sl} TP={at_s_tp}")
                if touch_cloud_event:
                    at_s_touches += 1
                if (enable_rf_second_touch and at_s_touches >= 2) or (
                    enable_rf_reversal_candle and bullish_reversal()
                    and ((not enable_catalyst_filter) or catalyst())
                ):
                    if at_s_sl > at_s_entry:
                        flog("[RISK-FREE]", f"Aati-S moved to breakeven @ {at_s_entry}")
                    at_s_sl = math.min(at_s_sl, at_s_entry)
            elif aati_short_elig and kumo_valid:
                pend_at_s = True
                pend_at_s_px = kumo_bot
            else:
                pend_at_s = False
        if not at_s_pos and not fill_at_s:
            at_s_entry = na_float

        touch_prev = touch_cloud_now

        lead1_hist.append(float(lead_line1))
        lead2_hist.append(float(lead_line2))
        hma20_hist.append(hma20)
        hma50_hist.append(hma50)
        close_hist.append(bar_c)
        open_hist.append(bar_o)
        rsi_hist.append(rsi_val)
        if len(lead1_hist) > MAX_HIST:
            lead1_hist = lead1_hist[-MAX_HIST:]
            lead2_hist = lead2_hist[-MAX_HIST:]
            hma20_hist = hma20_hist[-MAX_HIST:]
            hma50_hist = hma50_hist[-MAX_HIST:]
            close_hist = close_hist[-MAX_HIST:]
            open_hist = open_hist[-MAX_HIST:]
            rsi_hist = rsi_hist[-MAX_HIST:]

    # ═══════════════════════════════════════════════════════════
    # 🔵 سیگنال اصلی (اولین)
    # ═══════════════════════════════════════════════════════════
    fire_kind = ""
    fire_dir = ""
    fire_entry = na_float
    fire_stop = na_float
    fire_target = na_float
    fire_pine_px = na_float

    if an_l_fire:
        fire_kind, fire_dir = "Anni-L", "LONG"
        fire_entry, fire_stop, fire_target, fire_pine_px = an_l_entry, an_l_sl, an_l_tp, an_l_pine_px
    elif an_s_fire:
        fire_kind, fire_dir = "Anni-S", "SHORT"
        fire_entry, fire_stop, fire_target, fire_pine_px = an_s_entry, an_s_sl, an_s_tp, an_s_pine_px
    elif at_l_fire:
        fire_kind, fire_dir = "Aati-L", "LONG"
        fire_entry, fire_stop, fire_target, fire_pine_px = at_l_entry, at_l_sl, at_l_tp, at_l_pine_px
    elif at_s_fire:
        fire_kind, fire_dir = "Aati-S", "SHORT"
        fire_entry, fire_stop, fire_target, fire_pine_px = at_s_entry, at_s_sl, at_s_tp, at_s_pine_px

    signal_count = int(an_l_fire) + int(an_s_fire) + int(at_l_fire) + int(at_s_fire)

    fire_kind_code = 0
    if fire_kind == "Anni-L":
        fire_kind_code = 1
    elif fire_kind == "Anni-S":
        fire_kind_code = 2
    elif fire_kind == "Aati-L":
        fire_kind_code = 3
    elif fire_kind == "Aati-S":
        fire_kind_code = 4

    # ═══════════════════════════════════════════════════════════
    # 🔵 plot()
    # ═══════════════════════════════════════════════════════════
    plot(1 if an_l_fire else 0, title="an_l_fire")
    plot(1 if an_s_fire else 0, title="an_s_fire")
    plot(1 if at_l_fire else 0, title="at_l_fire")
    plot(1 if at_s_fire else 0, title="at_s_fire")
    plot(signal_count, title="signal_count")

    plot(an_l_entry, title="an_l_entry")
    plot(an_l_sl, title="an_l_sl")
    plot(an_l_tp, title="an_l_tp")
    plot(an_s_entry, title="an_s_entry")
    plot(an_s_sl, title="an_s_sl")
    plot(an_s_tp, title="an_s_tp")
    plot(at_l_entry, title="at_l_entry")
    plot(at_l_sl, title="at_l_sl")
    plot(at_l_tp, title="at_l_tp")
    plot(at_s_entry, title="at_s_entry")
    plot(at_s_sl, title="at_s_sl")
    plot(at_s_tp, title="at_s_tp")

    plot(1 if an_l_exit == "SL" else (2 if an_l_exit == "TP" else 0), title="an_l_exit_code")
    plot(an_l_exit_px, title="an_l_exit_px")
    plot(1 if an_s_exit == "SL" else (2 if an_s_exit == "TP" else 0), title="an_s_exit_code")
    plot(an_s_exit_px, title="an_s_exit_px")
    plot(1 if at_l_exit == "SL" else (2 if at_l_exit == "TP" else 0), title="at_l_exit_code")
    plot(at_l_exit_px, title="at_l_exit_px")
    plot(1 if at_s_exit == "SL" else (2 if at_s_exit == "TP" else 0), title="at_s_exit_code")
    plot(at_s_exit_px, title="at_s_exit_px")

    plot(1 if an_l_pos else 0, title="an_l_pos")
    plot(1 if an_s_pos else 0, title="an_s_pos")
    plot(1 if at_l_pos else 0, title="at_l_pos")
    plot(1 if at_s_pos else 0, title="at_s_pos")

    plot(1 if exit_dir == "up" else (-1 if exit_dir == "down" else 0), title="exit_dir_code")
    plot(exit_number, title="exit_number")
    plot(bars_since_exit, title="bars_since_exit")
    plot(1 if aati_armed else 0, title="aati_armed")
    plot(1 if anni_done else 0, title="anni_done")
    plot(1 if aati_done else 0, title="aati_done")

    plot(kumo_top, title="kumo_top")
    plot(kumo_bot, title="kumo_bot")
    plot(1 if kumo_valid else 0, title="kumo_valid")
    plot(atr_val, title="atr")

    plot(1 if touch_cloud_event else 0, title="touch_cloud_event")
    plot(1 if bullish_crescent else 0, title="bullish_crescent")
    plot(1 if bearish_crescent else 0, title="bearish_crescent")
    plot(1 if not_stale else 0, title="not_stale")

    plot(1 if anni_long_elig else 0, title="anni_long_elig")
    plot(1 if anni_short_elig else 0, title="anni_short_elig")
    plot(1 if aati_long_elig else 0, title="aati_long_elig")
    plot(1 if aati_short_elig else 0, title="aati_short_elig")

    plot(fire_kind_code, title="fire_kind_code")
    plot(fire_entry, title="fire_entry")
    plot(fire_stop, title="fire_stop")
    plot(fire_target, title="fire_target")
    plot(fire_pine_px, title="fire_pine_px")


if __name__ == "__main__":
    from pynecore.standalone import run
    run(__file__)
