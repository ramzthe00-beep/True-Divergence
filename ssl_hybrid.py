"""
@pyne
"""
from pynecore import Series
from pynecore.lib import script, close, high, low, open, input, ta, plot, color, math, nz, na

@script.indicator(title="SSL Hybrid")
def main():
    # === DISPLAY CONTROLS ===
    display_mode = input.string("Full Display", title="Display Mode", options=["Baseline Only", "Baseline + SSL", "SSL Only", "Entry/Exit Only", "Full Display"])
    color_bars = input.bool(False, title="Color Bars")
    show_signals = input.bool(True, title="Show Signal Diamonds")
    show_risk_table = input.bool(True, title="Show Risk Table")

    # === MASTER COLOR SETTINGS ===
    master_bullish_color = input.color("#00c3ff", title="Bullish Color")
    master_bearish_color = input.color("#ff0062", title="Bearish Color")

    # === BASELINE SETTINGS ===
    maType = input.string("HMA", title="Baseline Type", options=["SMA","EMA","DEMA","TEMA","LSMA","WMA","MF","VAMA","TMA","HMA", "JMA", "Kijun v2", "EDSMA","McGinley"])
    len_ = input.int(60, title="Baseline Length")
    src = input(close, title="Source")
    show_baseline_channel = input.bool(True, title="Show Baseline Channel")
    multy = input.float(0.2, step=0.05, title="Channel Multiplier")
    useTrueRange = input.bool(True, title="Use True Range for Channel")

    # === SSL SETTINGS ===
    SSL2Type = input.string("JMA", title="SSL2 Type", options=["SMA","EMA","DEMA","TEMA","WMA","MF","VAMA","TMA","HMA", "JMA","McGinley"])
    len2 = input.int(5, title="SSL2 Length")
    atr_crit = input.float(0.9, step=0.1, title="Continuation ATR Criteria")

    # === EXIT SETTINGS ===
    SSL3Type = input.string("HMA", title="Exit Type", options=["DEMA","TEMA","LSMA","VAMA","TMA","HMA","JMA", "Kijun v2", "McGinley", "MF"])
    len3 = input.int(15, title="Exit Length")

    # === ATR SETTINGS ===
    atrlen = input.int(14, title="ATR Period")
    mult = input.float(1.0, title="ATR Multiplier", step=0.1)
    smoothing = input.string("WMA", title="ATR Smoothing", options=["RMA", "SMA", "EMA", "WMA"])
    show_atr_bands = input.bool(False, title="Show ATR Bands")

    # === RISK ASSESSMENT ===
    risk_lookback = input.int(100, title="Risk Lookback Period", minval=50, maxval=500)
    risk_sensitivity = input.float(2, title="Risk Sensitivity", minval=0.2, maxval=3.0, step=0.1)
    enable_risk_gradient = input.bool(True, title="Enable Risk Gradient")

    # === JURIK (JMA) SETTINGS ===
    jurik_phase = input.int(3, title="Phase")
    jurik_power = input.int(1, title="Power")

    # === KIJUN SETTINGS ===
    kidiv = input.int(1, maxval=4, title="Kijun MOD Divider")

    # === VAMA SETTINGS ===
    volatility_lookback = input.int(10, title="Volatility Lookback Length")

    # === MODULAR FILTER SETTINGS ===
    beta = input.float(0.8, minval=0, maxval=1, step=0.1, title="Beta")
    feedback = input.bool(False, title="Feedback")
    z = input.float(0.5, title="Feedback Weighting", step=0.1, minval=0, maxval=1)

    # === EDSMA SETTINGS ===
    ssfLength = input.int(20, title="Super Smoother Filter Length", minval=1)
    ssfPoles = input.int(2, title="Super Smoother Filter Poles", options=[2, 3])

    # ============================================================
    # === MOVING AVERAGE FUNCTIONS ===
    # ============================================================
    def tema(src, len_):
        ema1 = ta.ema(src, len_)
        ema2 = ta.ema(ema1, len_)
        ema3 = ta.ema(ema2, len_)
        return (3 * ema1) - (3 * ema2) + ema3

    def get2PoleSSF(src, length):
        PI = 2 * math.asin(1)
        arg = math.sqrt(2) * PI / length
        a1 = math.exp(-arg)
        b1 = 2 * a1 * math.cos(arg)
        c2 = b1
        c3 = -math.pow(a1, 2)
        c1 = 1 - c2 - c3
        ssf = Series.auto()
        ssf = c1 * src + c2 * nz(ssf[1]) + c3 * nz(ssf[2])
        return ssf

    def get3PoleSSF(src, length):
        PI = 2 * math.asin(1)
        arg = PI / length
        a1 = math.exp(-arg)
        b1 = 2 * a1 * math.cos(1.738 * arg)
        c1 = math.pow(a1, 2)
        coef2 = b1 + c1
        coef3 = -(c1 + b1 * c1)
        coef4 = math.pow(c1, 2)
        coef1 = 1 - coef2 - coef3 - coef4
        ssf = Series.auto()
        ssf = coef1 * src + coef2 * nz(ssf[1]) + coef3 * nz(ssf[2]) + coef4 * nz(ssf[3])
        return ssf

    def ma(type, src, len_):
        result = Series.auto()
        if type == "TMA":
            result = ta.sma(ta.sma(src, math.ceil(len_ / 2)), math.floor(len_ / 2) + 1)
        elif type == "MF":
            ts = Series.auto()
            b = Series.auto()
            c = Series.auto()
            os_ = Series.auto()
            alpha = 2 / (len_ + 1)
            a = feedback ? z * src + (1 - z) * nz(ts[1], src) : src
            b = a > alpha * a + (1 - alpha) * nz(b[1], a) ? a : alpha * a + (1 - alpha) * nz(b[1], a)
            c = a < alpha * a + (1 - alpha) * nz(c[1], a) ? a : alpha * a + (1 - alpha) * nz(c[1], a)
            os_ = a == b ? 1 : a == c ? 0 : os_[1]
            upper = beta * b + (1 - beta) * c
            lower = beta * c + (1 - beta) * b
            ts = os_ * upper + (1 - os_) * lower
            result = ts
        elif type == "LSMA":
            result = ta.linreg(src, len_, 0)
        elif type == "SMA":
            result = ta.sma(src, len_)
        elif type == "EMA":
            result = ta.ema(src, len_)
        elif type == "DEMA":
            e = ta.ema(src, len_)
            result = 2 * e - ta.ema(e, len_)
        elif type == "TEMA":
            result = tema(src, len_)
        elif type == "WMA":
            result = ta.wma(src, len_)
        elif type == "VAMA":
            mid = ta.ema(src, len_)
            dev = src - mid
            vol_up = ta.highest(dev, volatility_lookback)
            vol_down = ta.lowest(dev, volatility_lookback)
            result = mid + math.avg(vol_up, vol_down)
        elif type == "HMA":
            result = ta.wma(2 * ta.wma(src, len_ / 2) - ta.wma(src, len_), math.round(math.sqrt(len_)))
        elif type == "JMA":
            phaseRatio = jurik_phase / 100 + 1.5
            beta_ = 0.45 * (len_ - 1) / (0.45 * (len_ - 1) + 2)
            alpha = math.pow(beta_, jurik_power)
            jma = Series.auto()
            e0 = Series.auto()
            e0 = (1 - alpha) * src + alpha * nz(e0[1])
            e1 = Series.auto()
            e1 = (src - e0) * (1 - beta_) + beta_ * nz(e1[1])
            e2 = Series.auto()
            e2 = (e0 + phaseRatio * e1 - nz(jma[1])) * math.pow(1 - alpha, 2) + math.pow(alpha, 2) * nz(e2[1])
            jma = e2 + nz(jma[1])
            result = jma
        elif type == "Kijun v2":
            kijun = math.avg(ta.lowest(len_), ta.highest(len_))
            conversionLine = math.avg(ta.lowest(len_ / kidiv), ta.highest(len_ / kidiv))
            delta = (kijun + conversionLine) / 2
            result = delta
        elif type == "McGinley":
            mg = Series.auto()
            mg = na(mg[1]) ? ta.ema(src, len_) : mg[1] + (src - mg[1]) / (len_ * math.pow(src / mg[1], 4))
            result = mg
        elif type == "EDSMA":
            zeros = src - nz(src[2])
            avgZeros = (zeros + zeros[1]) / 2
            ssf = get2PoleSSF(avgZeros, ssfLength) if ssfPoles == 2 else get3PoleSSF(avgZeros, ssfLength)
            stdev = ta.stdev(ssf, len_)
            scaledFilter = ssf / stdev if stdev != 0 else 0
            alpha = 5 * math.abs(scaledFilter) / len_
            edsma = Series.auto()
            edsma = alpha * src + (1 - alpha) * nz(edsma[1])
            result = edsma
        return result

    # ============================================================
    # === ATR CALCULATION ===
    # ============================================================
    def ma_function(source, atrlen):
        if smoothing == "RMA":
            return ta.rma(source, atrlen)
        elif smoothing == "SMA":
            return ta.sma(source, atrlen)
        elif smoothing == "EMA":
            return ta.ema(source, atrlen)
        else:
            return ta.wma(source, atrlen)

    atr_slen = ma_function(ta.tr(True), atrlen)

    # ============================================================
    # === BASELINE CALCULATIONS ===
    # ============================================================
    BBMC = ma(maType, close, len_)
    Keltma = ma(maType, src, len_)
    rangeValue = ta.tr if useTrueRange else high - low
    rangema = ta.ema(rangeValue, len_)
    upperk = Keltma + rangema * multy
    lowerk = Keltma - rangema * multy

    # ============================================================
    # === SSL CALCULATIONS (مقدار اصلی که ما نیاز داریم) ===
    # ============================================================
    emaHigh = ma(maType, high, len_)
    emaLow = ma(maType, low, len_)
    Hlv = Series.auto()
    Hlv = 1 if close > emaHigh else (-1 if close < emaLow else Hlv[1])
    
    # ============================================================
    # === SSL2 CALCULATIONS ===
    # ============================================================
    maHigh = ma(SSL2Type, high, len2)
    maLow = ma(SSL2Type, low, len2)
    Hlv2 = Series.auto()
    Hlv2 = 1 if close > maHigh else (-1 if close < maLow else Hlv2[1])
    sslDown2 = maHigh if Hlv2 < 0 else maLow

    # ============================================================
    # === EXIT CALCULATIONS ===
    # ============================================================
    ExitHigh = ma(SSL3Type, high, len3)
    ExitLow = ma(SSL3Type, low, len3)
    Hlv3 = Series.auto()
    Hlv3 = 1 if close > ExitHigh else (-1 if close < ExitLow else Hlv3[1])
    sslExit = ExitHigh if Hlv3 < 0 else ExitLow

    # ============================================================
    # === SSL2 Continuation Signals ===
    # ============================================================
    upper_half = atr_slen * atr_crit + close
    lower_half = close - atr_slen * atr_crit
    buy_inatr = lower_half < sslDown2
    sell_inatr = upper_half > sslDown2
    sell_cont = close < BBMC and close < sslDown2
    buy_cont = close > BBMC and close > sslDown2
    sell_atr = sell_inatr and sell_cont
    buy_atr = buy_inatr and buy_cont

    # ============================================================
    # ★ مقدار نهایی Hlv که ما در ربات استفاده می‌کنیم
    # ============================================================
    # hlv_final همان Hlv اصلی است (1, -1 یا 0)
    hlv_final = Hlv
    
    # می‌توانیم از Hlv2 هم استفاده کنیم برای ادامه روند
    hlv2_final = Hlv2

    # ============================================================
    # ★ برگرداندن مقادیر مورد نیاز برای ربات
    # ============================================================
    return {
        'hlv': hlv_final,        # مقدار اصلی SSL (1, -1, 0)
        'hlv2': hlv2_final,      # مقدار SSL2 برای ادامه روند
        'ssl2_buy': buy_atr,     # سیگنال خرید SSL2
        'ssl2_sell': sell_atr,   # سیگنال فروش SSL2
        'bbmc': BBMC,            # خط baseline
        'upperk': upperk,        # کانال بالایی
        'lowerk': lowerk,        # کانال پایینی
  }
