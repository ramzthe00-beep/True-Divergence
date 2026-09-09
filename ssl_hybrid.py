# -*- coding: utf-8 -*-
"""
SSL Hybrid — بازنویسی کامل بدون وابستگی به PyneCore (Mihkel00 Pine Script, ۱۰۰٪ منطبق)
====================================================================================
چرا این نسخه جایگزین نسخه‌ی PyneCore شد؟
--------------------------------------------------------------------
نسخه‌ی قبلی از `pynecore` استفاده می‌کرد، اما دو مشکل ساختاری داشت که باعث خطای
دائمی می‌شد:

1) در PyneCore، ورودی‌ها (input.*) باید به‌صورت **مقدار پیش‌فرض پارامترهای تابع
   main** تعریف شوند، نه با فراخوانی داخل بدنه‌ی تابع. کد قبلی همه‌ی input()ها را
   داخل بدنه فراخوانی می‌کرد که با معماری واقعی PyneCore (AST transform روی
   امضای تابع) سازگار نیست.
2) مهم‌تر از آن: در فایل `True-Divergence-Bot.py`، این اندیکاتور این‌طور صدا زده
   می‌شود:

       result = ssl_hybrid_indicator(data)   # data = دیکشنری آرایه‌های numpy

   یعنی به یک **تابع معمولی پایتون** نیاز دارید که یک دیکشنری OHLCV بگیرد و یک
   دیکشنری آرایه برگرداند. اما یک اسکریپت `@script.indicator` در PyneCore اصلاً
   این‌طور اجرا نمی‌شود — باید از طریق runtime خودِ PyneCore (`pyne run ...`)
   بار به بار اجرا شود و `close/high/low` را از globals خودش می‌گیرد، نه از
   آرگومان `data` (که در فایل قبلی اصلاً استفاده نمی‌شد!). به همین دلیل بات همیشه
   خطا می‌گرفت.

راه‌حل: کل منطق Pine Script با pandas/numpy به‌صورت برداری (و برای بخش‌های
بازگشتی مثل JMA/MF/McGinley/EDSMA با یک حلقه‌ی سبک) پیاده‌سازی شده — بدون هیچ
وابستگی خارجی جز pandas و numpy. خروجی این تابع دقیقاً همان کلیدهایی است که
`compute_ssl_hlv()` در بات انتظار دارد.

فقط MA هایی که خواسته بودید (JMA, VAMA, Kijun v2, EDSMA) به‌همراه بقیه‌ی انواع
موجود در اسکریپت اصلی (SMA, EMA, DEMA, TEMA, LSMA, WMA, MF, TMA, HMA, McGinley)
پیاده‌سازی شده‌اند — یعنی از تمام گزینه‌های Baseline Type / SSL2 Type / Exit Type
می‌توانید استفاده کنید.
"""
from __future__ import annotations

import numpy as np
import pandas as pd

__all__ = ["main", "ssl_hybrid"]


# ============================================================
# === ابزارهای پایه (برداری) ===
# ============================================================
def _sma(s: pd.Series, n: int) -> pd.Series:
    n = max(1, int(round(n)))
    return s.rolling(n, min_periods=1).mean()


def _ema(s: pd.Series, n: int) -> pd.Series:
    n = max(1, int(round(n)))
    return s.ewm(span=n, adjust=False, min_periods=1).mean()


def _rma(s: pd.Series, n: int) -> pd.Series:
    n = max(1, int(round(n)))
    return s.ewm(alpha=1.0 / n, adjust=False, min_periods=1).mean()


def _wma(s: pd.Series, n) -> pd.Series:
    n = max(1, int(round(n)))
    w = np.arange(1, n + 1, dtype=float)
    w_sum = w.sum()

    def f(x):
        wi = w[-len(x):]
        return float(np.dot(x, wi) / wi.sum()) if len(x) else np.nan

    return s.rolling(n, min_periods=1).apply(f, raw=True)


def _stdev(s: pd.Series, n: int) -> pd.Series:
    n = max(1, int(round(n)))
    return s.rolling(n, min_periods=1).std(ddof=0).fillna(0.0)


def _highest(s: pd.Series, n) -> pd.Series:
    n = max(1, int(round(n)))
    return s.rolling(n, min_periods=1).max()


def _lowest(s: pd.Series, n) -> pd.Series:
    n = max(1, int(round(n)))
    return s.rolling(n, min_periods=1).min()


def _linreg(s: pd.Series, n: int, offset: int = 0) -> pd.Series:
    """معادل ta.linreg(src, length, offset) در Pine."""
    n = max(2, int(round(n)))
    xi = np.arange(n, dtype=float)

    def f(x):
        y = x
        if len(y) < 2:
            return y[-1]
        xx = xi[-len(y):]
        slope, intercept = np.polyfit(xx, y, 1)
        return intercept + slope * (xx[-1] - offset)

    return s.rolling(n, min_periods=1).apply(f, raw=True)


def _percentrank(s: pd.Series, n: int) -> pd.Series:
    """معادل ta.percentrank: درصد مقادیرِ n میله‌ی قبلی که کمتر از مقدار جاری هستند."""
    n = max(1, int(round(n)))

    def f(x):
        if len(x) < 2:
            return 0.0
        cur = x[-1]
        past = x[:-1]
        return float(np.sum(past < cur) / len(past) * 100.0)

    return s.rolling(n + 1, min_periods=1).apply(f, raw=True).fillna(0.0)


def _true_range(high: pd.Series, low: pd.Series, close: pd.Series) -> pd.Series:
    prev_close = close.shift(1)
    tr = pd.concat(
        [
            (high - low).abs(),
            (high - prev_close).abs(),
            (low - prev_close).abs(),
        ],
        axis=1,
    ).max(axis=1)
    tr.iloc[0] = (high.iloc[0] - low.iloc[0])
    return tr


# ============================================================
# === MAهای بازگشتی (نیاز به حلقه‌ی بار-به-بار) ===
# ============================================================
def _jma(src: pd.Series, length: float, phase: float = 3, power: float = 1) -> pd.Series:
    x = src.to_numpy(dtype=float)
    n = len(x)
    out = np.zeros(n)
    e0 = 0.0
    e1 = 0.0
    e2 = 0.0
    jma_prev = 0.0
    length = max(1e-6, float(length))
    phase_ratio = phase / 100.0 + 1.5
    beta = 0.45 * (length - 1) / (0.45 * (length - 1) + 2)
    alpha = beta ** power
    for i in range(n):
        e0 = (1 - alpha) * x[i] + alpha * e0
        e1 = (x[i] - e0) * (1 - beta) + beta * e1
        e2 = (e0 + phase_ratio * e1 - jma_prev) * (1 - alpha) ** 2 + (alpha ** 2) * e2
        jma_prev = e2 + jma_prev
        out[i] = jma_prev
    return pd.Series(out, index=src.index)


def _mcginley(src: pd.Series, length: float) -> pd.Series:
    x = src.to_numpy(dtype=float)
    n = len(x)
    out = np.empty(n)
    mg = np.nan
    length = max(1e-6, float(length))
    for i in range(n):
        if np.isnan(mg):
            mg = x[i]  # معادل ta.ema(src,len) در همان بار اول (که na است)
        else:
            ratio = x[i] / mg if mg != 0 else 1.0
            mg = mg + (x[i] - mg) / (length * (ratio ** 4 if ratio > 0 else 1.0))
        out[i] = mg
    return pd.Series(out, index=src.index)


def _modular_filter(src: pd.Series, length: float, beta_: float, feedback: bool, z: float) -> pd.Series:
    x = src.to_numpy(dtype=float)
    n = len(x)
    out = np.empty(n)
    ts = 0.0
    b = 0.0
    c = 0.0
    os_ = 0.0
    alpha = 2.0 / (length + 1)
    for i in range(n):
        a = (z * x[i] + (1 - z) * (ts if i > 0 else x[i])) if feedback else x[i]
        prev_b = b if i > 0 else a
        prev_c = c if i > 0 else a
        b = a if a > alpha * a + (1 - alpha) * prev_b else alpha * a + (1 - alpha) * prev_b
        c = a if a < alpha * a + (1 - alpha) * prev_c else alpha * a + (1 - alpha) * prev_c
        if a == b:
            os_ = 1
        elif a == c:
            os_ = 0
        # else: os_ keeps previous value
        upper = beta_ * b + (1 - beta_) * c
        lower = beta_ * c + (1 - beta_) * b
        ts = os_ * upper + (1 - os_) * lower
        out[i] = ts
    return pd.Series(out, index=src.index)


def _ssf(src: pd.Series, length: float, poles: int) -> pd.Series:
    x = src.to_numpy(dtype=float)
    n = len(x)
    out = np.zeros(n)
    length = max(1e-6, float(length))
    if poles == 2:
        pi = 2 * np.arcsin(1.0)
        arg = np.sqrt(2) * pi / length
        a1 = np.exp(-arg)
        b1 = 2 * a1 * np.cos(arg)
        c2, c3 = b1, -(a1 ** 2)
        c1 = 1 - c2 - c3
        p1 = p2 = 0.0
        for i in range(n):
            v = c1 * x[i] + c2 * p1 + c3 * p2
            out[i] = v
            p2, p1 = p1, v
    else:
        pi = 2 * np.arcsin(1.0)
        arg = pi / length
        a1 = np.exp(-arg)
        b1 = 2 * a1 * np.cos(1.738 * arg)
        c1_ = a1 ** 2
        coef2 = b1 + c1_
        coef3 = -(c1_ + b1 * c1_)
        coef4 = c1_ ** 2
        coef1 = 1 - coef2 - coef3 - coef4
        p1 = p2 = p3 = 0.0
        for i in range(n):
            v = coef1 * x[i] + coef2 * p1 + coef3 * p2 + coef4 * p3
            out[i] = v
            p3, p2, p1 = p2, p1, v
    return pd.Series(out, index=src.index)


def _edsma(src: pd.Series, length: float, ssf_length: float, ssf_poles: int) -> pd.Series:
    zeros = src - src.shift(2).fillna(src.iloc[0])
    avg_zeros = ((zeros + zeros.shift(1).fillna(zeros.iloc[0])) / 2)
    ssf = _ssf(avg_zeros, ssf_length, ssf_poles)
    stdev = _stdev(ssf, length)
    scaled = np.where(stdev.to_numpy() != 0, ssf.to_numpy() / stdev.to_numpy().clip(min=1e-12), 0.0)
    alpha_arr = np.clip(5 * np.abs(scaled) / max(1e-6, length), 0.0, 1.0)

    x = src.to_numpy(dtype=float)
    n = len(x)
    out = np.empty(n)
    prev = 0.0
    for i in range(n):
        prev = alpha_arr[i] * x[i] + (1 - alpha_arr[i]) * prev
        out[i] = prev
    return pd.Series(out, index=src.index)


# ============================================================
# === توزیع‌کننده‌ی نوع MA (معادل تابع ma() در Pine) ===
# ============================================================
def _ma(ma_type: str, src: pd.Series, length, *, high: pd.Series = None, low: pd.Series = None,
        jurik_phase=3, jurik_power=1, kidiv=1, volatility_lookback=10,
        beta=0.8, feedback=False, z=0.5, ssfLength=20, ssfPoles=2) -> pd.Series:
    n = max(1, length)
    if ma_type == "SMA":
        return _sma(src, n)
    if ma_type == "EMA":
        return _ema(src, n)
    if ma_type == "WMA":
        return _wma(src, n)
    if ma_type == "DEMA":
        e = _ema(src, n)
        return 2 * e - _ema(e, n)
    if ma_type == "TEMA":
        e1 = _ema(src, n)
        e2 = _ema(e1, n)
        e3 = _ema(e2, n)
        return 3 * e1 - 3 * e2 + e3
    if ma_type == "LSMA":
        return _linreg(src, n, 0)
    if ma_type == "TMA":
        return _sma(_sma(src, int(np.ceil(n / 2))), int(np.floor(n / 2)) + 1)
    if ma_type == "HMA":
        return _wma(2 * _wma(src, n / 2) - _wma(src, n), int(round(np.sqrt(n))))
    if ma_type == "VAMA":
        mid = _ema(src, n)
        dev = src - mid
        vol_up = _highest(dev, volatility_lookback)
        vol_down = _lowest(dev, volatility_lookback)
        return mid + (vol_up + vol_down) / 2.0
    if ma_type == "JMA":
        return _jma(src, n, jurik_phase, jurik_power)
    if ma_type == "McGinley":
        return _mcginley(src, n)
    if ma_type == "MF":
        return _modular_filter(src, n, beta, feedback, z)
    if ma_type == "EDSMA":
        return _edsma(src, n, ssfLength, ssfPoles)
    if ma_type == "Kijun v2":
        hi = high if high is not None else src
        lo = low if low is not None else src
        kijun = (_lowest(lo, n) + _highest(hi, n)) / 2.0
        conv_len = max(1, n / max(1, kidiv))
        conversion = (_lowest(lo, conv_len) + _highest(hi, conv_len)) / 2.0
        return (kijun + conversion) / 2.0
    raise ValueError(f"Unknown MA type: {ma_type}")


def _hold_state(cond_up: pd.Series, cond_down: pd.Series) -> pd.Series:
    """معادل الگوی Pine: val := up ? 1 : down ? -1 : val[1]  (مقدار قبلی حفظ می‌شود تا شرط جدید برقرار شود)."""
    raw = pd.Series(np.where(cond_up, 1, np.where(cond_down, -1, np.nan)), index=cond_up.index)
    return raw.ffill().fillna(0).astype(int)


# ============================================================
# === تابع اصلی — همان چیزی که True-Divergence-Bot صدا می‌زند ===
# ============================================================
def main(
    data: dict,
    *,
    maType: str = "HMA", len_: int = 60,
    SSL2Type: str = "JMA", len2: int = 5, atr_crit: float = 0.9,
    SSL3Type: str = "HMA", len3: int = 15,
    atrlen: int = 14, mult: float = 1.0, smoothing: str = "WMA",
    multy: float = 0.2, useTrueRange: bool = True,
    risk_lookback: int = 100, risk_sensitivity: float = 2.0,
    enable_risk_gradient: bool = True,
    jurik_phase: int = 3, jurik_power: int = 1,
    kidiv: int = 1, volatility_lookback: int = 10,
    beta: float = 0.8, feedback: bool = False, z: float = 0.5,
    ssfLength: int = 20, ssfPoles: int = 2,
) -> dict:
    """
    ورودی `data`: دیکشنری با کلیدهای 'open','high','low','close' (numpy array یا list)
    خروجی: دیکشنری آرایه‌های numpy — دقیقاً هم‌طول با ورودی — با کلیدهای:
        hlv, hlv2, hlv3, ssl2_buy, ssl2_sell, bbmc, upperk, lowerk,
        sslDown, sslDown2, sslExit, atr, risk_level, entry_distance
    """
    if data is None:
        raise ValueError("ssl_hybrid.main: 'data' نمی‌تواند None باشد")

    close = pd.Series(np.asarray(data["close"], dtype=float))
    high = pd.Series(np.asarray(data["high"], dtype=float))
    low = pd.Series(np.asarray(data["low"], dtype=float))
    open_ = pd.Series(np.asarray(data.get("open", data["close"]), dtype=float))
    src = close  # ورودی "Source" در Pine پیش‌فرض close است

    ma_kwargs = dict(
        jurik_phase=jurik_phase, jurik_power=jurik_power, kidiv=kidiv,
        volatility_lookback=volatility_lookback, beta=beta, feedback=feedback, z=z,
        ssfLength=ssfLength, ssfPoles=ssfPoles,
    )

    # --- True Range / ATR ---
    tr = _true_range(high, low, close)
    smoothing_fn = {"RMA": _rma, "SMA": _sma, "EMA": _ema, "WMA": _wma}.get(smoothing, _wma)
    atr_slen = smoothing_fn(tr, atrlen)
    upper_band = atr_slen * mult + close
    lower_band = close - atr_slen * mult

    # --- Risk ---
    atr_percentile = _percentrank(atr_slen, risk_lookback)
    risk_level = pd.Series(
        np.where(atr_percentile > 75, "High", np.where(atr_percentile < 25, "Low", "Normal")),
        index=close.index,
    )

    # --- Baseline ---
    BBMC = _ma(maType, close, len_, high=high, low=low, **ma_kwargs)
    Keltma = _ma(maType, src, len_, high=high, low=low, **ma_kwargs)
    rangeValue = tr if useTrueRange else (high - low)
    rangema = _ema(rangeValue, len_)
    upperk = Keltma + rangema * multy
    lowerk = Keltma - rangema * multy

    # --- SSL1 (Baseline MA type) ---
    emaHigh = _ma(maType, high, len_, high=high, low=low, **ma_kwargs)
    emaLow = _ma(maType, low, len_, high=high, low=low, **ma_kwargs)
    Hlv = _hold_state(close > emaHigh, close < emaLow)
    sslDown = pd.Series(np.where(Hlv < 0, emaHigh, emaLow), index=close.index)

    # --- SSL2 ---
    maHigh = _ma(SSL2Type, high, len2, high=high, low=low, **ma_kwargs)
    maLow = _ma(SSL2Type, low, len2, high=high, low=low, **ma_kwargs)
    Hlv2 = _hold_state(close > maHigh, close < maLow)
    sslDown2 = pd.Series(np.where(Hlv2 < 0, maHigh, maLow), index=close.index)

    # --- Exit ---
    ExitHigh = _ma(SSL3Type, high, len3, high=high, low=low, **ma_kwargs)
    ExitLow = _ma(SSL3Type, low, len3, high=high, low=low, **ma_kwargs)
    Hlv3 = _hold_state(close > ExitHigh, close < ExitLow)
    sslExit = pd.Series(np.where(Hlv3 < 0, ExitHigh, ExitLow), index=close.index)

    # --- Entry distance ---
    dist = (close - BBMC).abs() / atr_slen.replace(0, np.nan)
    entry_distance = pd.Series(
        np.where(dist < 1, "Near", np.where(dist < 2, "Extended", "Far")), index=close.index
    )

    # --- SSL2 Continuation ---
    upper_half = atr_slen * atr_crit + close
    lower_half = close - atr_slen * atr_crit
    buy_inatr = lower_half < sslDown2
    sell_inatr = upper_half > sslDown2
    sell_cont = (close < BBMC) & (close < sslDown2)
    buy_cont = (close > BBMC) & (close > sslDown2)
    sell_atr = (sell_inatr & sell_cont)
    buy_atr = (buy_inatr & buy_cont)

    return {
        "hlv": Hlv.to_numpy(),
        "hlv2": Hlv2.to_numpy(),
        "hlv3": Hlv3.to_numpy(),
        "ssl2_buy": buy_atr.to_numpy(),
        "ssl2_sell": sell_atr.to_numpy(),
        "bbmc": BBMC.to_numpy(),
        "upperk": upperk.to_numpy(),
        "lowerk": lowerk.to_numpy(),
        "sslDown": sslDown.to_numpy(),
        "sslDown2": sslDown2.to_numpy(),
        "sslExit": sslExit.to_numpy(),
        "atr": atr_slen.to_numpy(),
        "atr_percentile": atr_percentile.to_numpy(),
        "risk_level": risk_level.to_numpy(),
        "entry_distance": entry_distance.to_numpy(),
    }


# نام جایگزین راحت برای استفاده‌ی مستقیم به‌جای main()
ssl_hybrid = main


if __name__ == "__main__":
    # تست خودکار کوچک با داده‌ی تصادفی — فقط برای اطمینان از عدم بروز خطا
    rng = np.random.default_rng(42)
    n = 400
    close_ = 100 + np.cumsum(rng.normal(0, 1, n))
    high_ = close_ + rng.uniform(0, 1, n)
    low_ = close_ - rng.uniform(0, 1, n)
    open_ = close_ + rng.normal(0, 0.3, n)
    data = {"open": open_, "high": high_, "low": low_, "close": close_}

    for ma_type in ["SMA", "EMA", "DEMA", "TEMA", "LSMA", "WMA", "MF", "VAMA", "TMA",
                     "HMA", "JMA", "Kijun v2", "EDSMA", "McGinley"]:
        r = main(data, maType=ma_type)
        assert len(r["hlv"]) == n, ma_type
        print(f"{ma_type:10s} OK  last hlv={r['hlv'][-1]}  bbmc={r['bbmc'][-1]:.3f}")

    print("\nAll MA types executed without error.")
