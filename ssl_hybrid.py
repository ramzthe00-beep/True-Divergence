"""
SSL Hybrid — نسخه کاملاً مطابق با Pine Script اصلی (Mihkel00)
@pyne
"""
from pynecore import Series
from pynecore.lib import (
    script, close, high, low, open, input, ta, plot, color, 
    math, nz, na, barstate, table, location, size, shape, plotarrow
)

@script.indicator("SSL Hybrid", overlay=True)
def main(data=None):
    # ============================================================
    # === DISPLAY CONTROLS ===
    # ============================================================
    display_mode = input.string(
        "Full Display", title="Display Mode",
        options=["Baseline Only", "Baseline + SSL", "SSL Only", "Entry/Exit Only", "Full Display"]
    )
    color_bars = input.bool(True, title="Color Bars")
    show_signals = input.bool(True, title="Show Signal Diamonds")
    show_risk_table = input.bool(True, title="Show Risk Table")

    # ============================================================
    # === MASTER COLOR SETTINGS ===
    # ============================================================
    master_bullish_color = input.color("#00c3ff", title="Bullish Color")
    master_bearish_color = input.color("#ff0062", title="Bearish Color")

    # ============================================================
    # === BASELINE SETTINGS ===
    # ============================================================
    maType = input.string(
        "HMA", title="Baseline Type",
        options=["SMA", "EMA", "DEMA", "TEMA", "LSMA", "WMA", "MF", "VAMA", "TMA", "HMA", "JMA", "Kijun v2", "EDSMA", "McGinley"]
    )
    len_ = input.int(60, title="Baseline Length")
    src = input(close, title="Source")
    show_baseline_channel = input.bool(True, title="Show Baseline Channel")
    multy = input.float(0.2, step=0.05, title="Channel Multiplier")
    useTrueRange = input.bool(True, title="Use True Range for Channel")

    # ============================================================
    # === SSL SETTINGS ===
    # ============================================================
    SSL2Type = input.string(
        "JMA", title="SSL2 Type",
        options=["SMA", "EMA", "DEMA", "TEMA", "WMA", "MF", "VAMA", "TMA", "HMA", "JMA", "McGinley"]
    )
    len2 = input.int(5, title="SSL2 Length")
    atr_crit = input.float(0.9, step=0.1, title="Continuation ATR Criteria")

    # ============================================================
    # === EXIT SETTINGS ===
    # ============================================================
    SSL3Type = input.string(
        "HMA", title="Exit Type",
        options=["DEMA", "TEMA", "LSMA", "VAMA", "TMA", "HMA", "JMA", "Kijun v2", "McGinley", "MF"]
    )
    len3 = input.int(15, title="Exit Length")

    # ============================================================
    # === ATR SETTINGS ===
    # ============================================================
    atrlen = input.int(14, title="ATR Period")
    mult = input.float(1.0, title="ATR Multiplier", step=0.1)
    smoothing = input.string("WMA", title="ATR Smoothing", options=["RMA", "SMA", "EMA", "WMA"])
    show_atr_bands = input.bool(False, title="Show ATR Bands")

    # ============================================================
    # === RISK ASSESSMENT ===
    # ============================================================
    risk_lookback = input.int(100, title="Risk Lookback Period", minval=50, maxval=500)
    risk_sensitivity = input.float(2, title="Risk Sensitivity", minval=0.2, maxval=3.0, step=0.1)
    enable_risk_gradient = input.bool(True, title="Enable Risk Gradient")

    # ============================================================
    # === JURIK (JMA) SETTINGS ===
    # ============================================================
    jurik_phase = input.int(3, title="Phase")
    jurik_power = input.int(1, title="Power")

    # ============================================================
    # === KIJUN SETTINGS ===
    # ============================================================
    kidiv = input.int(1, maxval=4, title="Kijun MOD Divider")

    # ============================================================
    # === VAMA SETTINGS ===
    # ============================================================
    volatility_lookback = input.int(10, title="Volatility Lookback Length")

    # ============================================================
    # === MODULAR FILTER SETTINGS ===
    # ============================================================
    beta = input.float(0.8, minval=0, maxval=1, step=0.1, title="Beta")
    feedback = input.bool(False, title="Feedback")
    z = input.float(0.5, title="Feedback Weighting", step=0.1, minval=0, maxval=1)

    # ============================================================
    # === EDSMA SETTINGS ===
    # ============================================================
    ssfLength = input.int(20, title="Super Smoother Filter Length", minval=1)
    ssfPoles = input.int(2, title="Super Sm
