# -*- coding: utf-8 -*-
"""
chart_renderer.py — نسخه‌ی اصلاح‌شده برای رسمِ دقیق و واقعیِ کندل‌ها (شبیهِ TradingView/Binance)

مهم — قبل از هر چیز بخوان:
----------------------------------
این فایل فقط «رسم‌کننده» است: هر داده‌ای که در پارامترِ df به آن بدهی را رسم می‌کند.
اگر خروجی همچنان «من‌درآوردی» به نظر می‌رسد، تقریباً همیشه یکی از این دو دلیل است:

  1) دیتافریمی که از Binance/صرافی می‌گیری واقعی نیست یا timeframe/تعداد کندل درستی ندارد
     (مثلاً به‌جای کلاین‌های واقعی، داده‌ی رندوم/شبیه‌سازی‌شده یا کش قدیمی به تابع داده می‌شود).
  2) محورِ زمان روی چارت اصلاً نمایش داده نمی‌شد (نسخه‌ی قبلی x-axis را کامل حذف کرده بود:
     `ax.set_xticks([])`). یک چارت بدون تاریخ/ساعت روی محورِ x، هرچقدر هم داده‌اش واقعی باشد،
     در نگاهِ اول «ساختگی» به نظر می‌رسد — چون چارت‌های واقعیِ TradingView/Binance همیشه
     برچسبِ زمان دارند. این نسخه این مشکل را رفع کرده است.

توجه: من (Claude) در این محیط به اینترنت دسترسی ندارم، بنابراین نتوانستم مستقیماً کدِ
پروژه‌های متن‌بازِ مشخصی (مثل mplfinance که این‌جا هم نصب نبود) را واکشی و مقایسه کنم.
آنچه در ادامه آمده بر مبنای best-practice‌های شناخته‌شده در رسمِ کندل‌استیک با matplotlib
است (همان اصولی که خودِ mplfinance هم استفاده می‌کند: precision واقعی، محورِ زمانِ درست،
doji-handling صحیح، و OHLC بدون دست‌کاری). اگر امکانش هست پیشنهاد می‌کنم واقعاً کتابخانه‌ی
`mplfinance` را نصب کنی (pip install mplfinance) که خروجی‌اش استاندارد صنعت است؛ در ادامه
هم نسخه‌ای بدونِ وابستگی به آن آورده‌ام و هم (کامنت‌شده) نسخه‌ی مبتنی بر mplfinance.
"""

import io
import logging
from typing import Optional

import matplotlib
matplotlib.use("Agg")
import matplotlib.pyplot as plt
import matplotlib.dates as mdates
import matplotlib.ticker as mticker
from matplotlib.patches import Rectangle
import pandas as pd
import numpy as np

logger = logging.getLogger("chart_renderer")

BG_COLOR = "#ffffff"
GRID_COLOR = "#eef0f2"
UP_COLOR = "#26a69a"
DOWN_COLOR = "#ef5350"
TP_ZONE_COLOR = "#26a69a"
SL_ZONE_COLOR = "#ef5350"
ENTRY_COLOR = "#5d606b"
TEXT_COLOR = "#131722"
AXIS_TEXT_COLOR = "#787b86"

N_CANDLES = 90
ZONE_CANDLES = 14


def _fmt(price: float, prec: int) -> str:
    return f"{price:.{prec}f}"


def _extract_datetime_index(d: pd.DataFrame) -> Optional[pd.DatetimeIndex]:
    """
    تلاش می‌کند ستونِ زمان را از df استخراج کند (index، یا ستون‌های رایجِ
    timestamp/time/open_time/date). اگر پیدا نشد None برمی‌گرداند و چارت
    بدونِ محورِ زمانِ واقعی رسم می‌شود (که دقیقاً همان چیزی است که باعثِ
    ظاهرِ «من‌درآوردی» می‌شود — پس اگر این تابع None برگرداند، مشکل از
    منبعِ داده است، نه از رسم‌کننده).
    """
    if isinstance(d.index, pd.DatetimeIndex):
        return d.index

    for col in ("timestamp", "open_time", "time", "date", "datetime"):
        if col in d.columns:
            try:
                ts = pd.to_datetime(d[col], unit="ms", errors="raise")
            except Exception:
                try:
                    ts = pd.to_datetime(d[col], errors="raise")
                except Exception:
                    continue
            return pd.DatetimeIndex(ts)
    return None


def render_signal_chart(df: pd.DataFrame, entry: float, stop: float, target: float,
                         direction: str, symbol: str, signal_number=None,
                         price_precision: int = None,
                         timeframe_label: str = None) -> Optional[bytes]:
    try:
        if df is None or df.empty or entry is None or stop is None or target is None:
            logger.error("[CHART] ورودی نامعتبر: df خالی/None یا entry/stop/target=None")
            return None

        d = df.tail(N_CANDLES).copy().reset_index(drop=False)
        if d.empty:
            logger.error("[CHART] df بعدِ tail خالی شد")
            return None

        for col in ("open", "high", "low", "close"):
            if col not in d.columns:
                logger.error(f"[CHART] ستونِ '{col}' در df موجود نیست: {list(d.columns)}")
                return None

        # اعتبارسنجیِ حداقلیِ OHLC — اگر داده‌ی ورودی خراب/جعلی باشد همین‌جا معلوم می‌شود
        bad = d[(d["high"] < d[["open", "close"]].max(axis=1)) |
                (d["low"] > d[["open", "close"]].min(axis=1))]
        if len(bad) > 0:
            logger.warning(f"[CHART] {len(bad)} کندلِ نامعتبر (high/low ناسازگار با open/close) "
                            f"در داده‌ی ورودی برای {symbol} — این یعنی منبعِ داده مشکل دارد.")

        dt_index = _extract_datetime_index(df.tail(N_CANDLES))
        if dt_index is None:
            logger.warning(f"[CHART] ستونِ زمانِ معتبر برای {symbol} پیدا نشد — "
                            f"چارت بدونِ برچسبِ تاریخ/ساعتِ واقعی رسم می‌شود.")

        if price_precision is None:
            price_precision = 5 if entry < 1 else (3 if entry < 10 else 2)

        fig, ax = plt.subplots(figsize=(9.6, 6.2), dpi=170)
        fig.patch.set_facecolor(BG_COLOR)
        ax.set_facecolor(BG_COLOR)

        width = 0.72
        for i, row in enumerate(d.itertuples()):
            up = row.close >= row.open
            color = UP_COLOR if up else DOWN_COLOR
            ax.plot([i, i], [row.low, row.high], color=color, linewidth=1.0,
                    zorder=3, solid_capstyle="butt")
            lower = min(row.open, row.close)
            height = abs(row.close - row.open)
            if height <= 0:
                # doji واقعی: به‌جای ارتفاعِ جعلیِ نسبی، یک خطِ نازکِ ثابت (مثلِ TradingView)
                rng = (row.high - row.low)
                height = max(rng * 0.004, entry * 10 ** (-price_precision) * 0.5)
            ax.add_patch(Rectangle((i - width / 2, lower), width, height,
                                    facecolor=color, edgecolor=color, zorder=4,
                                    linewidth=0))

        last_x = len(d) - 1
        box_left = max(0, last_x - ZONE_CANDLES)
        box_right = last_x + 1
        box_width = box_right - box_left

        if direction == "BUY":
            tp_low, tp_high = entry, target
            sl_low, sl_high = stop, entry
        else:
            tp_low, tp_high = target, entry
            sl_low, sl_high = entry, stop

        ax.add_patch(Rectangle((box_left, tp_low), box_width, max(tp_high - tp_low, 1e-9),
                                facecolor=TP_ZONE_COLOR, alpha=0.28,
                                edgecolor="none", zorder=2))
        ax.add_patch(Rectangle((box_left, sl_low), box_width, max(sl_high - sl_low, 1e-9),
                                facecolor=SL_ZONE_COLOR, alpha=0.28,
                                edgecolor="none", zorder=2))

        ax.plot([box_left, box_right], [entry, entry], color=ENTRY_COLOR,
                linewidth=1.1, linestyle="--", zorder=5, alpha=0.85)

        target_x_start = box_left + box_width * 0.15
        ax.plot([target_x_start, box_right - 0.4], [entry, target],
                color=ENTRY_COLOR, linewidth=0.9, linestyle=(0, (3, 2)),
                alpha=0.55, zorder=5)

        ax.set_xlim(-1, last_x + 1.5)
        ylow = min(d["low"].min(), stop, target)
        yhigh = max(d["high"].max(), stop, target)
        pad = (yhigh - ylow) * 0.08 if yhigh > ylow else max(entry * 0.01, 1e-4)
        ax.set_ylim(ylow - pad, yhigh + pad)

        ax.yaxis.tick_right()
        ax.yaxis.set_label_position("right")
        ax.yaxis.set_major_formatter(mticker.FormatStrFormatter(f"%.{price_precision}f"))
        ax.tick_params(axis="y", colors=TEXT_COLOR, labelsize=9.5, length=0)
        ax.grid(True, axis="y", color=GRID_COLOR, linewidth=0.7, zorder=0)

        # --- محورِ زمانِ واقعی (بخشِ اصلیِ اصلاح‌شده) ---
        if dt_index is not None:
            n_ticks = min(6, len(d))
            tick_positions = np.linspace(0, last_x, n_ticks).astype(int)
            tick_positions = sorted(set(tick_positions))
            tick_labels = []
            for pos in tick_positions:
                ts = dt_index[pos]
                span = (dt_index[-1] - dt_index[0])
                if span.total_seconds() > 3 * 24 * 3600:
                    tick_labels.append(ts.strftime("%m-%d"))
                else:
                    tick_labels.append(ts.strftime("%H:%M"))
            ax.set_xticks(tick_positions)
            ax.set_xticklabels(tick_labels)
            ax.tick_params(axis="x", colors=AXIS_TEXT_COLOR, labelsize=8.5, length=0)
            ax.grid(True, axis="x", color=GRID_COLOR, linewidth=0.5, zorder=0)
        else:
            ax.set_xticks([])
            ax.grid(False, axis="x")

        for spine in ax.spines.values():
            spine.set_visible(False)

        for price, label, color in [
            (target, "TP", TP_ZONE_COLOR),
            (entry, "Entry", ENTRY_COLOR),
            (stop, "SL", SL_ZONE_COLOR),
        ]:
            ax.annotate(f" {label} {_fmt(price, price_precision)}",
                        xy=(1.0, price), xycoords=("axes fraction", "data"),
                        xytext=(4, 0), textcoords="offset points",
                        va="center", ha="left", fontsize=8.5, fontweight="bold",
                        color="#ffffff",
                        bbox=dict(boxstyle="round,pad=0.28", facecolor=color,
                                  edgecolor="none", alpha=0.95),
                        annotation_clip=False, zorder=6)

        dir_txt = "LONG" if direction == "BUY" else "SHORT"
        dir_color = UP_COLOR if direction == "BUY" else DOWN_COLOR
        tag = f"   #{signal_number}" if signal_number else ""
        header = symbol if not timeframe_label else f"{symbol}  ·  {timeframe_label}"
        ax.text(0.01, 0.965, header, transform=ax.transAxes, color=TEXT_COLOR,
                fontsize=13, fontweight="bold", va="top", ha="left")
        ax.text(0.01, 0.90, f"{dir_txt}{tag}", transform=ax.transAxes, color=dir_color,
                fontsize=11, fontweight="bold", va="top", ha="left")

        fig.subplots_adjust(left=0.02, right=0.90, top=0.96, bottom=0.08)
        buf = io.BytesIO()
        fig.savefig(buf, format="png", facecolor=BG_COLOR)
        plt.close(fig)
        buf.seek(0)
        return buf.getvalue()

    except Exception as e:
        logger.error(f"[CHART] خطا در رسمِ چارتِ سیگنال برای {symbol}: {e}", exc_info=True)
        try:
            plt.close("all")
        except Exception:
            pass
        return None


# ---------------------------------------------------------------------------
# جایگزینِ مبتنی بر mplfinance (استانداردِ صنعت برای کندل‌استیک در پایتون)
# ---------------------------------------------------------------------------
# اگر می‌خواهی خروجی را ۱۰۰٪ با استایلِ TradingView تطبیق بدهی، نصب کن:
#     pip install mplfinance --break-system-packages
# و به‌جای حلقه‌ی دستیِ کندل‌ها، از این استفاده کن (نمونه‌ی حداقلی):
#
#   import mplfinance as mpf
#   mc = mpf.make_marketcolors(up=UP_COLOR, down=DOWN_COLOR,
#                               edge={'up': UP_COLOR, 'down': DOWN_COLOR},
#                               wick={'up': UP_COLOR, 'down': DOWN_COLOR})
#   style = mpf.make_mpf_style(base_mpf_style="nightclouds" if dark else "yahoo",
#                               marketcolors=mc, gridcolor=GRID_COLOR)
#   d = df.tail(N_CANDLES).set_index(pd.DatetimeIndex(dt_index))
#   fig, axlist = mpf.plot(d[["open", "high", "low", "close"]], type="candle",
#                           style=style, returnfig=True, figsize=(9.6, 6.2))
#   ax = axlist[0]
#   # ← از این‌جا به بعد همان کدهای رسمِ باکسِ TP/SL و annotate بالا را روی ax بزن.
#
# مزیتِ mplfinance: مدیریتِ خودکارِ گپ‌های زمانی (کندل‌های جاافتاده)، فرمتِ محورِ زمان
# با تراکمِ صحیح، و رندرِ دقیقاً مطابقِ استانداردهای پلتفرم‌های معاملاتی.
