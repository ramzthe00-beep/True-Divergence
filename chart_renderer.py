# -*- coding: utf-8 -*-
"""
chart_renderer.py — نسخه‌ی اصلاح‌شده، مطابقِ ظاهرِ واقعیِ TradingView
"""

import io
import logging
from typing import Optional

import matplotlib
matplotlib.use("Agg")
import matplotlib.pyplot as plt
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
AXIS_BG = "#f5f6f8"

N_CANDLES = 90
ZONE_CANDLES = 14


def _fmt(price: float, prec: int) -> str:
    return f"{price:.{prec}f}"


def render_signal_chart(df: pd.DataFrame, entry: float, stop: float, target: float,
                         direction: str, symbol: str, signal_number=None,
                         price_precision: int = None) -> Optional[bytes]:
    try:
        if df is None or df.empty or entry is None or stop is None or target is None:
            logger.error("[CHART] ورودی نامعتبر: df خالی/None یا entry/stop/target=None")
            return None

        d = df.tail(N_CANDLES).copy().reset_index(drop=True)
        if d.empty:
            logger.error("[CHART] df بعدِ tail خالی شد")
            return None

        for col in ("open", "high", "low", "close"):
            if col not in d.columns:
                logger.error(f"[CHART] ستونِ '{col}' در df موجود نیست: {list(d.columns)}")
                return None

        if price_precision is None:
            price_precision = 5 if entry < 1 else (3 if entry < 10 else 2)

        fig, ax = plt.subplots(figsize=(9.6, 6.2), dpi=170)
        fig.patch.set_facecolor(BG_COLOR)
        ax.set_facecolor(BG_COLOR)

        # فاصله‌ی بینِ کندل‌ها فشرده‌تر و باریک‌تر — دقیقاً حسِ TradingView
        width = 0.72
        for i, row in enumerate(d.itertuples()):
            up = row.close >= row.open
            color = UP_COLOR if up else DOWN_COLOR
            ax.plot([i, i], [row.low, row.high], color=color, linewidth=1.0,
                    zorder=3, solid_capstyle="butt")
            lower = min(row.open, row.close)
            height = abs(row.close - row.open)
            if height <= 0:
                height = (row.high - row.low) * 0.015 or 1e-7
            ax.add_patch(Rectangle((i - width / 2, lower), width, height,
                                    facecolor=color, edgecolor=color, zorder=4,
                                    linewidth=0))

        last_x = len(d) - 1
        box_left = max(0, last_x - ZONE_CANDLES)
        box_right = last_x + 1  # جعبه فقط تا آخرین کندلِ رسم‌شده، بدون overhang زیاد
        box_width = box_right - box_left

        if direction == "BUY":
            tp_low, tp_high = entry, target
            sl_low, sl_high = stop, entry
        else:
            tp_low, tp_high = target, entry
            sl_low, sl_high = entry, stop

        # دو باکس دقیقاً چسبیده به هم، بدون شکاف — مثلِ نمونه‌ی واقعی
        ax.add_patch(Rectangle((box_left, tp_low), box_width, max(tp_high - tp_low, 1e-9),
                                facecolor=TP_ZONE_COLOR, alpha=0.28,
                                edgecolor="none", zorder=2))
        ax.add_patch(Rectangle((box_left, sl_low), box_width, max(sl_high - sl_low, 1e-9),
                                facecolor=SL_ZONE_COLOR, alpha=0.28,
                                edgecolor="none", zorder=2))

        # خطِ مرزیِ ورود فقط در محدوده‌ی باکس (نه کل عرض چارت) — شبیهِ نمونه
        ax.plot([box_left, box_right], [entry, entry], color=ENTRY_COLOR,
                linewidth=1.1, linestyle="--", zorder=5, alpha=0.85)

        # خطِ مسیرِ مورب داخلِ ناحیه‌ی هدف (افکتِ حرکتِ قیمت به سمتِ TP)
        target_x_start = box_left + box_width * 0.15
        ax.plot([target_x_start, box_right - 0.4], [entry, target],
                color=ENTRY_COLOR, linewidth=0.9, linestyle=(0, (3, 2)),
                alpha=0.55, zorder=5)

        ax.set_xlim(-1, last_x + 1.5)
        ylow = min(d["low"].min(), stop, target)
        yhigh = max(d["high"].max(), stop, target)
        pad = (yhigh - ylow) * 0.08 if yhigh > ylow else max(entry * 0.01, 1e-4)
        ax.set_ylim(ylow - pad, yhigh + pad)

        # محورِ قیمت سمتِ راست — دقیقاً مثلِ TradingView
        ax.yaxis.tick_right()
        ax.yaxis.set_label_position("right")
        ax.yaxis.set_major_formatter(mticker.FormatStrFormatter(f"%.{price_precision}f"))
        ax.tick_params(axis="y", colors=TEXT_COLOR, labelsize=9.5, length=0)
        ax.grid(True, axis="y", color=GRID_COLOR, linewidth=0.7, zorder=0)
        ax.grid(False, axis="x")
        ax.set_xticks([])
        for spine in ax.spines.values():
            spine.set_visible(False)

        # برچسب‌های TP/Entry/SL دقیقاً چسبیده به محورِ راست (به‌جای شناور در فضای خالی)
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
        ax.text(0.01, 0.965, f"{symbol}", transform=ax.transAxes, color=TEXT_COLOR,
                fontsize=13, fontweight="bold", va="top", ha="left")
        ax.text(0.01, 0.90, f"{dir_txt}{tag}", transform=ax.transAxes, color=dir_color,
                fontsize=11, fontweight="bold", va="top", ha="left")

        fig.subplots_adjust(left=0.02, right=0.90, top=0.96, bottom=0.03)
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
