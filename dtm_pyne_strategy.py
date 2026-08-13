"""
@pyne edge

This code was compiled by PyneComp v6.0.54 — the Pine Script to Python compiler.
Run with open-source PyneCore: https://pynecore.org
Compile Pine Scripts online at PyneSys: https://pynesys.io
"""
from pynecore import pine_range
from pynecore.lib import (
    bar_index, barmerge, close, color, high, input, location, low, math, na,
    open, plotshape, request, script, shape, size, strategy, syminfo, ta
)
from pynecore.types import Persistent, Series

grp_pivot: str = "Pivot"
grp_ind: str = "Indicators"
grp_trend: str = "Trend"
grp_score: str = "Min Confirmations"
grp_fib: str = "Fibonacci"
grp_candle: str = "Price Action"


@script.strategy("DTM Divergence Light", overlay=True, initial_capital=500, default_qty_type=strategy.fixed, default_qty_value=1, commission_type=strategy.commission.percent, commission_value=0.1, pyramiding=3, process_orders_on_close=True, max_labels_count=50, max_lines_count=50)
def main(
    pivotMode=input.string("سریع (5/3)", "روش Pivot", options=("استاندارد (5/5)", "سریع (5/3)"), group=grp_pivot),
    rsiLen=input.int(14, "RSI", group=grp_ind),
    macdFast=input.int(12, "MACD Fast", group=grp_ind),
    macdSlow=input.int(26, "MACD Slow", group=grp_ind),
    macdSig=input.int(9, "MACD Signal", group=grp_ind),
    trendLookback=input.int(20, "Trend Lookback", group=grp_trend),
    trendSlopeMinPct=input.float(0.05, "Min Slope %", step=0.01, group=grp_trend),
    minConfirmations=input.string("۳ تعییدیه (حداقل مجاز)", "حداقل شرط", options=("۳ تعییدیه (حداقل مجاز)", "۳ تعییدیه + فیبوناچی (۴ امتیاز) [Custom]", "۳ تعییدیه + پرایس‌اکشن (۴ امتیاز) [Custom]", "۵ امتیاز کامل (ایده‌آل)"), group=grp_score),
    enableHidden=input.bool(True, "Enable Hidden Divergence"),
    fibUse618=input.bool(True, "Use 0.618", group=grp_fib),
    fibUse786=input.bool(True, "Use 0.786", group=grp_fib),
    fibTolerancePct=input.float(0.5, "Fib Tolerance %", step=0.1, group=grp_fib),
    fibTrendSearchBars=input.int(100, "Fib Search Bars", group=grp_fib),
    shadowToBodyRatio=input.float(2.0, "Shadow/Body Ratio", group=grp_candle),
    maxOppositeShadowPct=input.float(20.0, "Max Opposite Shadow %", group=grp_candle),
    minCandleATRRatio=input.float(0.3, "Min Candle ATR Ratio", group=grp_candle),
    bigCandleAvgLen=input.int(14, "Big Candle Avg Len", group=grp_candle),
    bigCandleMultiplier=input.float(1.5, "Big Candle Mult", group=grp_candle),
    enableMTF=input.bool(False, "Enable MTF Filter"),
    mtfTimeframe=input.timeframe("240", "MTF Timeframe")
):
    leftBars: int = 5
    rightBars = 5 if pivotMode == 'استاندارد (5/5)' else 3

    rsiVal: Series = ta.rsi(close, rsiLen)
    macdLine: Series
    histLine: Series
    macdLine, signalLine, histLine = ta.macd(close, macdFast, macdSlow, macdSig)
    atr14 = ta.atr(14)
    mtf_hist: Series = request.security(syminfo.tickerid, mtfTimeframe, histLine[1], lookahead=barmerge.lookahead_off)

    pivotHighPrice = ta.pivothigh(high, leftBars, rightBars)
    pivotLowPrice = ta.pivotlow(low, leftBars, rightBars)

    rsiAtPivotHigh = ta.valuewhen(not na(pivotHighPrice), rsiVal[rightBars], 0)
    rsiAtPivotLow = ta.valuewhen(not na(pivotLowPrice), rsiVal[rightBars], 0)
    macdLineAtPivotHigh = ta.valuewhen(not na(pivotHighPrice), macdLine[rightBars], 0)
    macdLineAtPivotLow = ta.valuewhen(not na(pivotLowPrice), macdLine[rightBars], 0)
    histAtPivotHigh = ta.valuewhen(not na(pivotHighPrice), histLine[rightBars], 0)
    histAtPivotLow = ta.valuewhen(not na(pivotLowPrice), histLine[rightBars], 0)

    ph_price_2: Persistent[float] = na(float)
    ph_price_1 = na(float)
    ph_bar_2: Persistent[int] = na(int)
    ph_bar_1 = na(int)
    ph_rsi_2: Persistent[float] = na(float)
    ph_rsi_1 = na(float)
    ph_macdline_2: Persistent[float] = na(float)
    ph_macdline_1 = na(float)
    ph_hist_2: Persistent[float] = na(float)
    ph_hist_1 = na(float)

    pl_price_2: Persistent[float] = na(float)
    pl_price_1 = na(float)
    pl_bar_2: Persistent[int] = na(int)
    pl_bar_1 = na(int)
    pl_rsi_2: Persistent[float] = na(float)
    pl_rsi_1 = na(float)
    pl_macdline_2: Persistent[float] = na(float)
    pl_macdline_1 = na(float)
    pl_hist_2: Persistent[float] = na(float)
    pl_hist_1 = na(float)

    newPivotHigh = not na(pivotHighPrice)
    newPivotLow = not na(pivotLowPrice)

    if newPivotHigh:
        ph_price_1 = ph_price_2
        ph_bar_1 = ph_bar_2
        ph_rsi_1 = ph_rsi_2
        ph_macdline_1 = ph_macdline_2
        ph_hist_1 = ph_hist_2
        ph_price_2 = pivotHighPrice
        ph_bar_2 = bar_index - rightBars
        ph_rsi_2 = rsiAtPivotHigh
        ph_macdline_2 = macdLineAtPivotHigh
        ph_hist_2 = histAtPivotHigh

    if newPivotLow:
        pl_price_1 = pl_price_2
        pl_bar_1 = pl_bar_2
        pl_rsi_1 = pl_rsi_2
        pl_macdline_1 = pl_macdline_2
        pl_hist_1 = pl_hist_2
        pl_price_2 = pivotLowPrice
        pl_bar_2 = bar_index - rightBars
        pl_rsi_2 = rsiAtPivotLow
        pl_macdline_2 = macdLineAtPivotLow
        pl_hist_2 = histAtPivotLow

    def checkColorChange(barStart, barEnd, needRedPhase):
        found: bool = False
        if not na(barStart) and (not na(barEnd)) and (barEnd > barStart):
            startOffset = bar_index - (barEnd - 1)
            endOffset = bar_index - (barStart + 1)
            if startOffset >= 0 and endOffset <= 5000 and (endOffset >= startOffset):
                for j in pine_range(startOffset, endOffset):
                    h = histLine[j]
                    if needRedPhase and h < 0:
                        found = True
                        break
                    if not needRedPhase and h > 0:
                        found = True
                        break
        return found

    macdColorChangedForHighs = checkColorChange(ph_bar_1, ph_bar_2, True) if newPivotHigh and (not na(ph_bar_1)) else False
    macdColorChangedForLows = checkColorChange(pl_bar_1, pl_bar_2, False) if newPivotLow and (not na(pl_bar_1)) else False

    def mtfColorChanged(barStart, barEnd, needRedPhase):
        found: bool = False
        if not na(barStart) and (not na(barEnd)) and (barEnd > barStart):
            startOffset = bar_index - (barEnd - 1)
            endOffset = bar_index - (barStart + 1)
            if startOffset >= 0 and endOffset <= 5000 and (endOffset >= startOffset):
                for j in pine_range(startOffset, endOffset):
                    h = mtf_hist[j]
                    if needRedPhase and h < 0:
                        found = True
                        break
                    if not needRedPhase and h > 0:
                        found = True
                        break
        return found

    mtfColorChangedForHighs = mtfColorChanged(ph_bar_1, ph_bar_2, True) if newPivotHigh and (not na(ph_bar_1)) else False
    mtfColorChangedForLows = mtfColorChanged(pl_bar_1, pl_bar_2, False) if newPivotLow and (not na(pl_bar_1)) else False
    mtfFilterOkForBearish = not enableMTF or mtfColorChangedForHighs
    mtfFilterOkForBullish = not enableMTF or mtfColorChangedForLows

    def isTrendingUp(refBar):
        result: bool = False
        if not na(refBar):
            offset = bar_index - refBar
            if offset >= 0 and offset + trendLookback < 5000:
                slope = ta.linreg(close[offset], trendLookback, 0) - ta.linreg(close[offset + trendLookback], trendLookback, 0)
                avgPrice = ta.sma(close[offset], trendLookback)
                slopePct = slope / avgPrice * 100 if avgPrice != 0 else 0.0
                result = slopePct > trendSlopeMinPct
        return result

    def isTrendingDown(refBar):
        result: bool = False
        if not na(refBar):
            offset = bar_index - refBar
            if offset >= 0 and offset + trendLookback < 5000:
                slope = ta.linreg(close[offset], trendLookback, 0) - ta.linreg(close[offset + trendLookback], trendLookback, 0)
                avgPrice = ta.sma(close[offset], trendLookback)
                slopePct = slope / avgPrice * 100 if avgPrice != 0 else 0.0
                result = slopePct < -trendSlopeMinPct
        return result

    trendOkForBearish = isTrendingUp(ph_bar_1) if newPivotHigh and (not na(ph_bar_1)) else False
    trendOkForBullish = isTrendingDown(pl_bar_1) if newPivotLow and (not na(pl_bar_1)) else False

    def findTrendStartLow(refBar):
        result: float = na(float)
        if not na(refBar):
            offset = bar_index - refBar
            if offset >= 0 and offset + fibTrendSearchBars < 5000:
                result = ta.lowest(low[offset], fibTrendSearchBars)
        return result

    def findTrendStartHigh(refBar):
        result: float = na(float)
        if not na(refBar):
            offset = bar_index - refBar
            if offset >= 0 and offset + fibTrendSearchBars < 5000:
                result = ta.highest(high[offset], fibTrendSearchBars)
        return result

    def checkFibLevel(fibStart, fibEnd, targetPrice, isRetraceDown):
        ok: bool = False
        if not na(fibStart) and (not na(fibEnd)) and (fibEnd != fibStart):
            range_ = fibEnd - fibStart
            tol = math.abs(range_) * (fibTolerancePct / 100.0)
            level618 = fibEnd - range_ * 0.618 if isRetraceDown else fibEnd + math.abs(range_) * 0.618
            level786 = fibEnd - range_ * 0.786 if isRetraceDown else fibEnd + math.abs(range_) * 0.786
            if fibUse618 and math.abs(targetPrice - level618) <= tol:
                ok = True
            if fibUse786 and math.abs(targetPrice - level786) <= tol:
                ok = True
        return ok

    fibScoreBearish: bool = False
    if newPivotHigh and (not na(ph_bar_1)):
        trendStart = findTrendStartLow(ph_bar_1)
        fibScoreBearish = checkFibLevel(trendStart, ph_price_1, ph_price_2, True)

    fibScoreBullish: bool = False
    if newPivotLow and (not na(pl_bar_1)):
        trendStart = findTrendStartHigh(pl_bar_1)
        fibScoreBullish = checkFibLevel(trendStart, pl_price_1, pl_price_2, False)

    candleRange = high - low
    candleBody = math.abs(close - open)
    upperShadow = high - math.max(close, open)
    lowerShadow = math.min(close, open) - low
    avgBody = ta.sma(math.abs(close - open), bigCandleAvgLen)
    sizeOk = candleRange >= minCandleATRRatio * atr14

    bullishWick = candleRange > 0 and lowerShadow >= shadowToBodyRatio * candleBody and (upperShadow / candleRange * 100 <= maxOppositeShadowPct) and sizeOk
    bigGreenCandle = close > open and candleBody >= bigCandleMultiplier * avgBody and sizeOk
    priceActionBullish = bullishWick or bigGreenCandle

    bearishWick = candleRange > 0 and upperShadow >= shadowToBodyRatio * candleBody and (lowerShadow / candleRange * 100 <= maxOppositeShadowPct) and sizeOk
    bearishHangingMan = candleRange > 0 and lowerShadow >= shadowToBodyRatio * candleBody and (upperShadow / candleRange * 100 <= maxOppositeShadowPct) and sizeOk
    bigRedCandle = close < open and candleBody >= bigCandleMultiplier * avgBody and sizeOk
    priceActionBearish = bearishWick or bearishHangingMan or bigRedCandle

    priceActionBullishAtPivot = priceActionBullish
    priceActionBearishAtPivot = priceActionBearish

    priceHigherHigh = newPivotHigh and (not na(ph_price_1)) and (ph_price_2 > ph_price_1)
    rsiLowerHighOnPeaks = newPivotHigh and (not na(ph_rsi_1)) and (ph_rsi_2 < ph_rsi_1)
    macdLineLowerHighOnPeaks = newPivotHigh and (not na(ph_macdline_1)) and (ph_macdline_2 < ph_macdline_1)
    histLowerHighOnPeaks = newPivotHigh and (not na(ph_hist_1)) and (ph_hist_2 < ph_hist_1)
    bothPeaksGreen = newPivotHigh and (not na(ph_hist_1)) and (ph_hist_1 > 0) and (ph_hist_2 > 0)

    classicBearishCond1_RSI = priceHigherHigh and rsiLowerHighOnPeaks
    classicBearishCond2_MACDl = priceHigherHigh and macdLineLowerHighOnPeaks
    classicBearishCond3_MACDh = priceHigherHigh and histLowerHighOnPeaks and bothPeaksGreen and macdColorChangedForHighs
    classicBearishBase3 = priceHigherHigh and trendOkForBearish and classicBearishCond3_MACDh and classicBearishCond1_RSI and classicBearishCond2_MACDl

    priceLowerLow = newPivotLow and (not na(pl_price_1)) and (pl_price_2 < pl_price_1)
    rsiHigherLowOnTroughs = newPivotLow and (not na(pl_rsi_1)) and (pl_rsi_2 > pl_rsi_1)
    macdLineHigherLowOnTroughs = newPivotLow and (not na(pl_macdline_1)) and (pl_macdline_2 > pl_macdline_1)
    histHigherLowOnTroughs = newPivotLow and (not na(pl_hist_1)) and (pl_hist_2 > pl_hist_1)
    bothTroughsRed = newPivotLow and (not na(pl_hist_1)) and (pl_hist_1 < 0) and (pl_hist_2 < 0)

    classicBullishCond1_RSI = priceLowerLow and rsiHigherLowOnTroughs
    classicBullishCond2_MACDl = priceLowerLow and macdLineHigherLowOnTroughs
    classicBullishCond3_MACDh = priceLowerLow and histHigherLowOnTroughs and bothTroughsRed and macdColorChangedForLows
    classicBullishBase3 = priceLowerLow and trendOkForBullish and classicBullishCond3_MACDh and classicBullishCond1_RSI and classicBullishCond2_MACDl

    priceHigherLow = newPivotLow and (not na(pl_price_1)) and (pl_price_2 > pl_price_1)
    rsiLowerLowOnTroughs = newPivotLow and (not na(pl_rsi_1)) and (pl_rsi_2 < pl_rsi_1)
    macdLineLowerLowOnTroughs = newPivotLow and (not na(pl_macdline_1)) and (pl_macdline_2 < pl_macdline_1)
    histLowerLowOnTroughs = newPivotLow and (not na(pl_hist_1)) and (pl_hist_2 < pl_hist_1)

    hiddenBullishCond1_RSI = priceHigherLow and rsiLowerLowOnTroughs
    hiddenBullishCond2_MACDl = priceHigherLow and macdLineLowerLowOnTroughs
    hiddenBullishCond3_MACDh = priceHigherLow and histLowerLowOnTroughs and bothTroughsRed and macdColorChangedForLows
    hiddenBullishBase3 = enableHidden and priceHigherLow and hiddenBullishCond3_MACDh and hiddenBullishCond1_RSI and hiddenBullishCond2_MACDl

    priceLowerHigh = newPivotHigh and (not na(ph_price_1)) and (ph_price_2 < ph_price_1)
    rsiHigherHighOnPeaks = newPivotHigh and (not na(ph_rsi_1)) and (ph_rsi_2 > ph_rsi_1)
    macdLineHigherHighOnPeaks = newPivotHigh and (not na(ph_macdline_1)) and (ph_macdline_2 > ph_macdline_1)
    histHigherHighOnPeaks = newPivotHigh and (not na(ph_hist_1)) and (ph_hist_2 > ph_hist_1)

    hiddenBearishCond1_RSI = priceLowerHigh and rsiHigherHighOnPeaks
    hiddenBearishCond2_MACDl = priceLowerHigh and macdLineHigherHighOnPeaks
    hiddenBearishCond3_MACDh = priceLowerHigh and histHigherHighOnPeaks and bothPeaksGreen and macdColorChangedForHighs
    hiddenBearishBase3 = enableHidden and priceLowerHigh and hiddenBearishCond3_MACDh and hiddenBearishCond1_RSI and hiddenBearishCond2_MACDl

    def passesMinRequirement(base3, fibOk, paOk):
        result: bool = False
        if base3:
            if minConfirmations == '۳ تعییدیه (حداقل مجاز)':
                result = True
            elif minConfirmations == '۳ تعییدیه + فیبوناچی (۴ امتیاز) [Custom]':
                result = fibOk
            elif minConfirmations == '۳ تعییدیه + پرایس\u200cاکشن (۴ امتیاز) [Custom]':
                result = paOk
            elif minConfirmations == '۵ امتیاز کامل (ایده\u200cآل)':
                result = fibOk and paOk
        return result

    finalClassicBearish = passesMinRequirement(classicBearishBase3, fibScoreBearish, priceActionBearishAtPivot) and mtfFilterOkForBearish
    finalClassicBullish = passesMinRequirement(classicBullishBase3, fibScoreBullish, priceActionBullishAtPivot) and mtfFilterOkForBullish
    finalHiddenBullish = passesMinRequirement(hiddenBullishBase3, fibScoreBullish, priceActionBullishAtPivot) and mtfFilterOkForBullish
    finalHiddenBearish = passesMinRequirement(hiddenBearishBase3, fibScoreBearish, priceActionBearishAtPivot) and mtfFilterOkForBearish

    plotshape(finalClassicBearish, title='CD-', style=shape.triangledown, location=location.abovebar, color=color.red, size=size.small, text='CD-', offset=-rightBars)
    plotshape(finalClassicBullish, title='CD+', style=shape.triangleup, location=location.belowbar, color=color.green, size=size.small, text='CD+', offset=-rightBars)
    plotshape(finalHiddenBullish, title='HD+', style=shape.triangleup, location=location.belowbar, color=color.blue, size=size.small, text='HD+', offset=-rightBars)
    plotshape(finalHiddenBearish, title='HD-', style=shape.triangledown, location=location.abovebar, color=color.orange, size=size.small, text='HD-', offset=-rightBars)


if __name__ == "__main__":
    from pynecore.standalone import run
    run(__file__)

