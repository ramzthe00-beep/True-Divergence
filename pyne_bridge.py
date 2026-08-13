# -*- coding: utf-8 -*-
"""
pyne_bridge.py — پل ادغام PyneCore با بات معاملاتی (DataFrame Bridge)
"""

from __future__ import annotations

import logging
from pathlib import Path
from typing import Any, Dict, Iterator, List, Optional, Union

import numpy as np
import pandas as pd

logger = logging.getLogger(__name__)

# =====================================================================================
# Import PyneCore
# =====================================================================================
PYNECORE_AVAILABLE = True
_import_error: Optional[BaseException] = None

ScriptRunner: Any = None
OHLCV: Any = None
SymInfo: Any = None
pyne_na: Any = None

try:
    from pynecore.core.script_runner import ScriptRunner as _ScriptRunner
    ScriptRunner = _ScriptRunner
except ImportError as e1:
    try:
        from pynecore import ScriptRunner as _ScriptRunner
        ScriptRunner = _ScriptRunner
    except ImportError as e2:
        PYNECORE_AVAILABLE = False
        _import_error = e2

try:
    from pynecore.core.syminfo import SymInfo as _SymInfo
    SymInfo = _SymInfo
except ImportError as e1:
    try:
        from pynecore import SymInfo as _SymInfo
        SymInfo = _SymInfo
    except ImportError as e2:
        try:
            from pynecore.types.syminfo import SymInfo as _SymInfo
            SymInfo = _SymInfo
        except ImportError as e3:
            PYNECORE_AVAILABLE = False
            _import_error = _import_error or e3

try:
    from pynecore.types.ohlcv import OHLCV as _OHLCV
    OHLCV = _OHLCV
except ImportError as e:
    try:
        from pynecore import OHLCV as _OHLCV
        OHLCV = _OHLCV
    except ImportError:
        PYNECORE_AVAILABLE = False
        _import_error = _import_error or e

try:
    from pynecore.lib import na as _pyne_na
    pyne_na = _pyne_na
except ImportError:
    pyne_na = None

if not PYNECORE_AVAILABLE:
    logger.error(f"[PYNE_BRIDGE] PyneCore در دسترس نیست ({_import_error}).")

# =====================================================================================
# نگاشت سیگنال
# =====================================================================================
SIGNAL_PLOT_MAP: Dict[str, Dict[str, str]] = {
    "CD-": {"side": "SELL", "label": "Classic Bearish"},
    "CD+": {"side": "BUY", "label": "Classic Bullish"},
    "HD+": {"side": "BUY", "label": "Hidden Bullish"},
    "HD-": {"side": "SELL", "label": "Hidden Bearish"},
}

# =====================================================================================
# توابع کمکی
# =====================================================================================
def _pyne_value_is_na(value: Any) -> bool:
    if value is None:
        return True
    if pyne_na is not None:
        try:
            if bool(pyne_na(value)):
                return True
        except Exception:
            pass
    try:
        return bool(np.isnan(float(value)))
    except (TypeError, ValueError):
        return False

def _pyne_to_float(value: Any) -> float:
    if _pyne_value_is_na(value):
        return float("nan")
    try:
        return float(value)
    except (TypeError, ValueError):
        return float("nan")

def _pyne_to_bool(value: Any) -> bool:
    if _pyne_value_is_na(value):
        return False
    if isinstance(value, bool):
        return value
    try:
        return bool(value)
    except Exception:
        return False

# =====================================================================================
# DataFrame Bridge
# =====================================================================================
def _dataframe_to_ohlcv_iter(df: pd.DataFrame) -> Iterator[Any]:
    if OHLCV is None:
        raise RuntimeError("pynecore.types.ohlcv.OHLCV در دسترس نیست.")
    idx = df.index
    if getattr(idx, "tz", None) is None:
        idx = idx.tz_localize("UTC")
    cols = {c.lower(): c for c in df.columns}
    for ts, row in zip(idx, df.itertuples(index=False)):
        row_dict = row._asdict()
        yield OHLCV(
            timestamp=int(ts.timestamp()),
            open=float(row_dict.get(cols.get("open", "open"), 0.0)),
            high=float(row_dict.get(cols.get("high", "high"), 0.0)),
            low=float(row_dict.get(cols.get("low", "low"), 0.0)),
            close=float(row_dict.get(cols.get("close", "close"), 0.0)),
            volume=float(row_dict.get(cols.get("volume", "volume"), 0.0) or 0.0),
        )

def _build_security_data(df: pd.DataFrame, mtf_timeframe: str = "240") -> Optional[Dict[str, List[Any]]]:
    try:
        resample_map = {"240": "4h", "60": "1h", "30": "30min", "15": "15min", "D": "1D", "W": "1W"}
        rule = resample_map.get(mtf_timeframe, "4h")
        htf = df.resample(rule).agg({"open": "first", "high": "max", "low": "min", "close": "last", "volume": "sum"}).dropna()
        if htf.empty:
            return None
        return {mtf_timeframe: list(_dataframe_to_ohlcv_iter(htf))}
    except Exception as e:
        logger.warning(f"[PYNE_BRIDGE] ساخت MTF ناموفق: {e}")
        return None

# =====================================================================================
# ✅ ساخت SymInfo - با try/except کامل برای هر نسخه PyneCore
# =====================================================================================
def _build_syminfo(symbol: str) -> Any:
    """
    ساخت SymInfo - تلاش با پارامترهای مختلف برای سازگاری با نسخه‌های مختلف PyneCore
    """
    su = symbol.upper()
    base = su.replace("USDT", "")
    tick = 0.00001 if su == "DOGEUSDT" else 0.01

    # اگر SymInfo در دسترس نیست -> dict fallback
    if SymInfo is None:
        return {
            "prefix": "BINANCE", "ticker": su, "currency": "USDT",
            "basecurrency": base, "type": "crypto", "mintick": tick,
            "pointvalue": 1.0, "timezone": "UTC",
        }

    # تلاش با پارامترهای مختلف
    for params in [
        # تلاش 1: با period (نسخه‌های جدید)
        {
            "prefix": "BINANCE", "description": f"{base} / USDT",
            "ticker": su, "currency": "USDT", "basecurrency": base,
            "type": "crypto", "period": "1m", "mintick": tick,
            "pricescale": 100, "minmove": 1, "pointvalue": 1.0,
            "mincontract": 0.0001, "timezone": "UTC", "volumetype": "quote",
        },
        # تلاش 2: بدون period (نسخه‌های قدیمی)
        {
            "prefix": "BINANCE", "description": f"{base} / USDT",
            "ticker": su, "currency": "USDT", "basecurrency": base,
            "type": "crypto", "mintick": tick,
            "pricescale": 100, "minmove": 1, "pointvalue": 1.0,
            "timezone": "UTC",
        },
        # تلاش 3: فقط پارامترهای ضروری
        {
            "prefix": "BINANCE", "ticker": su,
            "currency": "USDT", "basecurrency": base,
            "type": "crypto", "mintick": tick,
        },
    ]:
        try:
            return SymInfo(**params)
        except TypeError as e:
            continue
        except Exception as e:
            continue

    # اگر هیچکدام کار نکرد -> dict fallback
    logger.warning(f"[PYNE_BRIDGE] هیچکدام از پارامترهای SymInfo کار نکرد، از dict استفاده می‌شود")
    return {
        "prefix": "BINANCE", "ticker": su, "currency": "USDT",
        "basecurrency": base, "type": "crypto", "mintick": tick,
        "pointvalue": 1.0, "timezone": "UTC",
    }

# =====================================================================================
# تابع اصلی
# =====================================================================================
def run_pyne_indicator(
    df: pd.DataFrame,
    script_path: Union[str, Path],
    symbol: str,
    mtf_timeframe: str = "240",
) -> Optional[Dict[str, pd.Series]]:
    if not PYNECORE_AVAILABLE or ScriptRunner is None:
        return None
    if df is None or df.empty:
        return None

    # ✅ تبدیل به Path (رفع خطای 'str' object has no attribute 'parent')
    script_path = Path(script_path)
    if not script_path.exists():
        logger.error(f"[PYNE_BRIDGE] فایل اسکریپت پیدا نشد: {script_path}")
        return None

    syminfo_obj = _build_syminfo(symbol)
    security_data = _build_security_data(df, mtf_timeframe)

    runner = None
    last_err: Optional[Exception] = None
    attempts = ([{"security_data": security_data}] if security_data else []) + [{}]
    for kwargs in attempts:
        try:
            runner = ScriptRunner(str(script_path), _dataframe_to_ohlcv_iter(df), syminfo_obj, **kwargs)
            break
        except TypeError as e:
            last_err = e
            continue
        except Exception as e:
            logger.error(f"[PYNE_BRIDGE] ساخت ScriptRunner ناموفق: {e}")
            return None

    if runner is None:
        logger.error(f"[PYNE_BRIDGE] ساخت ScriptRunner ناموفق: {last_err}")
        return None

    plot_columns: Dict[str, List[Any]] = {}
    n_bars = 0

    try:
        for result in runner.run_iter():
            plot_data = result[1]
            n_bars += 1
            keys = list(plot_data.keys()) if hasattr(plot_data, "keys") else list(dict(plot_data).keys())
            for key in keys:
                plot_columns.setdefault(key, []).append(plot_data.get(key))
            for key in list(plot_columns.keys()):
                if len(plot_columns[key]) < n_bars:
                    plot_columns[key].append(float("nan"))
    except Exception as e:
        logger.error(f"[PYNE_BRIDGE] اجرای ScriptRunner متوقف شد: {e}")
        return None

    if n_bars == 0 or not plot_columns:
        logger.warning("[PYNE_BRIDGE] هیچ plot/plotshape ای برنگرداند.")
        return None

    aligned_index = df.index[-n_bars:]
    out: Dict[str, pd.Series] = {}
    for key, values in plot_columns.items():
        is_bool_col = all(isinstance(v, bool) or _pyne_value_is_na(v) for v in values)
        if is_bool_col:
            series_vals = [_pyne_to_bool(v) for v in values]
        else:
            series_vals = [_pyne_to_float(v) for v in values]
        out[key] = pd.Series(series_vals, index=aligned_index, name=key)

    return out

# =====================================================================================
# استخراج سیگنال
# =====================================================================================
def extract_final_signal(plots: Optional[Dict[str, pd.Series]]) -> Optional[Dict[str, Optional[str]]]:
    if not plots:
        return None
    for plot_name, meta in SIGNAL_PLOT_MAP.items():
        series = plots.get(plot_name)
        if series is None or len(series) == 0:
            continue
        last_val = series.iloc[-1]
        if _pyne_to_bool(last_val):
            return {"signal": meta["side"], "label": meta["label"]}
    return {"signal": None, "label": None}

# =====================================================================================
# تست
# =====================================================================================
if __name__ == "__main__":
    import sys
    logging.basicConfig(level=logging.INFO)
    if len(sys.argv) < 3:
        print("Usage: python pyne_bridge.py <script_path.py> <ohlcv_csv_path> [symbol]")
        sys.exit(1)
    _script = sys.argv[1]
    _csv = sys.argv[2]
    _symbol = sys.argv[3] if len(sys.argv) > 3 else "LTCUSDT"
    _df = pd.read_csv(_csv, parse_dates=["timestamp"], index_col="timestamp")
    _plots = run_pyne_indicator(_df, _script, _symbol)
    if _plots is None:
        print("❌ run_pyne_indicator چیزی برنگرداند")
    else:
        print(f"✅ ستون‌ها: {list(_plots.keys())}")
        print(f"سیگنال نهایی: {extract_final_signal(_plots)}")
