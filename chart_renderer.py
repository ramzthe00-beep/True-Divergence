# -*- coding: utf-8 -*-
"""
chart_renderer.py
=====================================================================
تولیدِ تصویرِ چارتِ کندل‌استیک به‌همراهِ باکسِ ناحیه‌ی ورود/حدسود/حدضرر
(شبیهِ چیزی که کاربر در TradingView رسم می‌کند) تا هر پیامِ سیگنال با
یک عکسِ چارت همراه شود — دقیقاً مطابقِ درخواست: پیام در ذیلِ عکس (به‌صورتِ
کپشنِ همان عکس) ارسال می‌شود.

خروجیِ اصلی: render_signal_chart(...) → بایت‌های PNG یا None (در صورتِ خطا،
main.py باید به ارسالِ پیامِ متنیِ ساده برگردد).
"""

import io
import logging
from typing import Optional

import matplotlib
matplotlib.use("Agg")  # بدون نیاز به دیسپلی/GUI — مناسبِ سرور
import matplotlib.pyplot as plt
from matplotlib.patches import Rectangle
import pandas as pd

logger = logging.getLogger("chart_renderer")

# ── پالتِ رنگیِ روشن (دقیقاً مطابقِ تمِ پیش‌فرضِ سفیدِ TradingView) ────
BG_COLOR = "#ffffff"
GRID_COLOR = "#e6e9ec"
UP_COLOR = "#26a69a"        # کندلِ سبز/تیل
DOWN_COLOR = "#ef5350"      # کندلِ قرمز
TP_ZONE_COLOR = "#26a69a"   # باکسِ تیل (ناحیه‌ی سود) — مثلِ عکسِ نمونه
SL_ZONE_COLOR = "#ef5350"   # باکسِ صورتی/قرمز (ناحیه‌ی ضرر) — مثلِ عکسِ نمونه
ENTRY_COLOR = "#787b86"
TEXT_COLOR = "#131722"

N_CANDLES = 70          # تعدادِ کندل‌های نمایش‌داده‌شده در چارت
ZONE_CANDLES = 16       # عرضِ باکسِ ورود/حدسود/حدضرر بر حسبِ تعدادِ کندل


def _fmt(price: float, prec: int) -> str:
    return f"{price:.{prec}f}"


def render_signal_chart(df: pd.DataFrame, entry: float, stop: float, target: float,
                         direction: str, symbol: str, signal_number=None,
                         price_precision: int = None) -> Optional[bytes]:
    """
    df: دیتافریمِ OHLC با ستون‌های open/high/low/close (ایندکسِ زمانی
        اختیاری است — از خروجیِ market.fetch_ohlcv_binance می‌آید).
    entry/stop/target: سطوحِ قیمتی برای رسمِ باکس‌ها.
    direction: "BUY" یا "SELL".
    برمی‌گرداند: بایت‌های PNG، یا None اگر رسم ممکن نبود.
    """
    try:
        if df is None or df.empty or entry is None or stop is None or target is None:
            return None

        d = df.tail(N_CANDLES).copy().reset_index(drop=True)
        if d.empty:
            return None

        if price_precision is None:
            price_precision = 5 if entry < 1 else (3 if entry < 10 else 2)

        fig, ax = plt.subplots(figsize=(10, 6.2), dpi=160)
        fig.patch.set_facecolor(BG_COLOR)
        ax.set_facecolor(BG_COLOR)

        width = 0.62
        for i, row in enumerate(d.itertuples()):
            color = UP_COLOR if row.close >= row.open else DOWN_COLOR
            ax.plot([i, i], [row.low, row.high], color=color, linewidth=1.1, zorder=3, solid_capstyle="round")
            lower = min(row.open, row.close)
            height = abs(row.close - row.open)
            if height <= 0:
                height = (row.high - row.low) * 0.01 or 0.0000001
            ax.add_patch(Rectangle((i - width / 2, lower), width, height,
                                    facecolor=color, edgecolor=color, zorder=4))

        last_x = len(d) - 1
        box_left = max(0, last_x - ZONE_CANDLES)
        box_width = (last_x - box_left) + 2.5   # کمی جلوتر از آخرین کندل هم بکشد

        if direction == "BUY":
            tp_low, tp_high = entry, target
            sl_low, sl_high = stop, entry
        else:
            tp_low, tp_high = target, entry
            sl_low, sl_high = entry, stop

        ax.add_patch(Rectangle((box_left, tp_low), box_width, max(tp_high - tp_low, 1e-9),
                                facecolor=TP_ZONE_COLOR, alpha=0.30,
                                edgecolor=TP_ZONE_COLOR, linewidth=1.3, zorder=2))
        ax.add_patch(Rectangle((box_left, sl_low), box_width, max(sl_high - sl_low, 1e-9),
                                facecolor=SL_ZONE_COLOR, alpha=0.30,
                                edgecolor=SL_ZONE_COLOR, linewidth=1.3, zorder=2))

        # خطِ چین‌دارِ ورود روی کل عرضِ چارت
        ax.axhline(entry, color=ENTRY_COLOR, linewidth=1.1, linestyle="--", zorder=5, alpha=0.9)

        label_x = last_x + 1.2
        for price, label, color in [
            (target, f"TP  {_fmt(target, price_precision)}", TP_ZONE_COLOR),
            (entry, f"Entry  {_fmt(entry, price_precision)}", ENTRY_COLOR),
            (stop, f"SL  {_fmt(stop, price_precision)}", SL_ZONE_COLOR),
        ]:
            ax.text(label_x, price, label, color=color, fontsize=10, va="center", ha="left",
                    fontweight="bold")

        ax.set_xlim(-1.5, last_x + 12)
        ylow = min(d["low"].min(), stop, target)
        yhigh = max(d["high"].max(), stop, target)
        pad = (yhigh - ylow) * 0.10 if yhigh > ylow else max(entry * 0.01, 0.0001)
        ax.set_ylim(ylow - pad, yhigh + pad)

        ax.grid(True, color=GRID_COLOR, linewidth=0.6, zorder=0)
        ax.tick_params(axis="y", colors=TEXT_COLOR, labelsize=9)
        ax.set_xticks([])
        for spine in ax.spines.values():
            spine.set_color(GRID_COLOR)

        dir_txt = "LONG" if direction == "BUY" else "SHORT"
        dir_color = UP_COLOR if direction == "BUY" else DOWN_COLOR
        tag = f"  #Signal_{signal_number}" if signal_number else ""
        ax.set_title(f"{symbol}   {dir_txt}{tag}", color=dir_color, fontsize=13,
                     loc="left", fontweight="bold", pad=10)

        fig.tight_layout()
        buf = io.BytesIO()
        fig.savefig(buf, format="png", facecolor=BG_COLOR)
        plt.close(fig)
        buf.seek(0)
        return buf.getvalue()

    except Exception as e:
        logger.error(f"[CHART] خطا در رسمِ چارتِ سیگنال برای {symbol}: {e}")
        try:
            plt.close("all")
        except Exception:
            pass
        return None

