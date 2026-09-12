# -*- coding: utf-8 -*-
"""
run_with_diagnostics.py
=====================================================================
یک فایلِ کاملاً جداگانه — کنار main.py / divergence_engine.py /
ssl_hybrid.py / exchange_client.py / telegram_logger.py قرار می‌گیرد.
هیچ‌کدام از آن ۵ فایل تغییر نمی‌کنند و نباید تغییر کنند.

روی Railway فقط یک تنظیم عوض می‌شود: Start Command از
    python main.py
به
    python run_with_diagnostics.py

این فایل main.py واقعی شما را با import صدا می‌زند (نه کپی/بازنویسیِ
منطقش)، پس هر رفتاری که همین الان دارید دقیقاً همان می‌ماند؛ فقط قبل از
شروعِ حلقه، توابعِ واقعیِ divergence_engine.py و ssl_hybrid.py را در
حافظه دور می‌زند (monkey-patch) تا هر بار که واقعاً در چرخه‌ی زنده صدا
زده می‌شوند، ورودی/خروجی/استثناء با فایل و شماره‌خطِ دقیقِ خودِ همان
فایلِ مبدأ ثبت شود — بدون این‌که یک نسخه‌ی موازی/تکراری از منطق تشخیص
جایی نوشته شود (که خودش می‌توانست منبع باگِ جدید باشد).

━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━
چه چیزی رد‌گیری می‌شود (طبق درخواست شما، شاملِ فیلتر SSL هم هست):
━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━
  • divergence_engine.DivergenceEngine.process   → CP-ENGINE / CP-EVENT
  • divergence_engine.calc_rsi                    → CP-RSI
  • divergence_engine.calc_macd                   → CP-MACD
  • divergence_engine.calc_adx                     → CP-ADX
  • divergence_engine.find_pivot_high/low          → CP-PIVOT-HIGH/LOW
  • ssl_hybrid.compute_gate_series (فیلتر SSL)     → CP-SSL-GATE / CP-SSL-GATE-FLIP
  • ssl_hybrid.compute_ssl_hybrid (محاسبه‌ی کامل)  → CP-SSL-CALC
  • main.process_symbol / main.analyze_and_execute → CP-SYM-* / CP-CYCLE-*
  علاوه بر این‌ها، هر سه loggerِ موجودِ پروژه (dtm_bot از main.py،
  exchange از exchange_client.py، telegram از telegram_logger.py) هم
  به همین بافر وصل می‌شوند — یعنی خطاهای همان جاهایی که خودِ شما از قبل
  logger.error(...) نوشته‌اید هم توی همین گزارش ساعتی می‌آید.

━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━
رفتار خروجی:
━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━
  • کنسول Railway: فقط یک خطِ ✅/❌ در هر چرخه (هر ۶۰ ثانیه) — سالم بودنِ
    اجرا را نشان می‌دهد، نه محتوای لاگ.
  • تلگرام: هر ۱ ساعت، کل لاگِ جمع‌شده به‌صورت یک فایل .log فرستاده و
    خالی می‌شود.
  • استثنا (ERROR/CRITICAL) در هر لحظه: بلافاصله (نه منتظرِ ساعت) به‌صورت
    پیامِ کوتاه به تلگرام هم می‌رود — تا هیچ باگِ جدی یک ساعت دیرتر دیده
    نشود.
"""

from __future__ import annotations

import contextvars
import functools
import inspect
import logging
import threading
import time
import traceback
from datetime import datetime
from pathlib import Path
from typing import Any, Callable

import pandas as pd

from telegram_logger import IRAN_TZ

# =============================================================================
# 1) TraceRecorder — بافرِ مرکزیِ همه‌ی لاگ‌ها (نه کنسول، نه فایلِ دائمی روی دیسک)
# =============================================================================
class TraceRecorder:
    def __init__(self, flush_interval_sec: int = 3600, log_dir: str = "parity_logs"):
        self.flush_interval_sec = flush_interval_sec
        self.log_dir = Path(log_dir)
        self.log_dir.mkdir(exist_ok=True)
        self._lock = threading.Lock()
        self._buffer: list[str] = []
        self._cycle_count = 0
        self._error_count_since_flush = 0
        self._last_flush = time.time()
        self._notifier = None

    def attach_notifier(self, notifier) -> None:
        self._notifier = notifier

    @staticmethod
    def _fmt(level: str, msg: str) -> str:
        ts = datetime.now(IRAN_TZ).strftime("%Y-%m-%d %H:%M:%S")
        return f"{ts} | {level:<7} | {msg}"

    def debug(self, msg: str) -> None:
        with self._lock:
            self._buffer.append(self._fmt("DEBUG", msg))

    def info(self, msg: str) -> None:
        with self._lock:
            self._buffer.append(self._fmt("INFO", msg))

    def warning(self, msg: str) -> None:
        with self._lock:
            self._buffer.append(self._fmt("WARNING", msg))

    def error(self, msg: str, exc_info: bool = False) -> None:
        line = self._fmt("ERROR", msg)
        if exc_info:
            line += "\n" + traceback.format_exc()
        with self._lock:
            self._buffer.append(line)
            self._error_count_since_flush += 1
        self._send_urgent(line)

    def _send_urgent(self, line: str) -> None:
        # خطاها منتظرِ چرخه‌ی ساعتی نمی‌مانند -- بلافاصله یک پیام کوتاه به تلگرام
        if self._notifier is None:
            return
        try:
            self._notifier.send(f"🚨 *خطای فوری — run_with_diagnostics*\n```\n{line[:1500]}\n```")
        except Exception:
            pass

    def heartbeat_console(self, ok: bool, extra: str = "") -> None:
        # تنها چیزی که واقعاً روی stdout/کنسول Railway چاپ می‌شود
        mark = "✅" if ok else "❌"
        print(f"{mark} [run_with_diagnostics] cycle={self._cycle_count} buffered_lines={len(self._buffer)} {extra}",
              flush=True)
        self._cycle_count += 1

    def maybe_flush(self, force: bool = False) -> None:
        now = time.time()
        if not force and (now - self._last_flush) < self.flush_interval_sec:
            return
        with self._lock:
            lines = self._buffer
            self._buffer = []
            errs = self._error_count_since_flush
            self._error_count_since_flush = 0
        self._last_flush = now
        if not lines:
            return

        ts = datetime.now(IRAN_TZ).strftime("%Y%m%d_%H%M%S")
        path = self.log_dir / f"parity_trace_{ts}.log"
        path.write_text("\n".join(lines), encoding="utf-8")

        sent = False
        if self._notifier is not None:
            caption = f"📋 لاگ تشخیصی {ts} | {len(lines)} خط | {errs} خطا"
            try:
                sent = bool(self._notifier.send_document(str(path), caption=caption))
            except Exception:
                sent = False

        if sent:
            try:
                path.unlink()
            except Exception:
                pass
        else:
            # ارسال ناموفق بود -- خطوط برای تلاشِ بعدی نگه داشته می‌شوند (فایل هم می‌ماند)
            with self._lock:
                self._buffer = lines + self._buffer
            print(f"⚠️ [run_with_diagnostics] ارسال لاگ به تلگرام ناموفق بود؛ در چرخه‌ی بعد دوباره تلاش می‌شود ({path})",
                  flush=True)


RECORDER = TraceRecorder(flush_interval_sec=3600)


# =============================================================================
# 2) اتصال سه loggerِ موجودِ پروژه (dtm_bot / exchange / telegram) + root
#    به همین بافر — بدون دست‌زدن به فایلی که آن‌ها را ساخته
# =============================================================================
class _RecorderLoggingHandler(logging.Handler):
    def __init__(self, recorder: TraceRecorder):
        super().__init__()
        self.recorder = recorder

    def emit(self, record: logging.LogRecord) -> None:
        msg = self.format(record)
        if record.levelno >= logging.ERROR:
            self.recorder.error(msg, exc_info=bool(record.exc_info))
        elif record.levelno >= logging.WARNING:
            self.recorder.warning(msg)
        else:
            self.recorder.info(msg)


def silence_console_and_redirect(
    recorder: TraceRecorder,
    extra_logger_names: tuple[str, ...] = ("dtm_bot", "exchange", "telegram", "werkzeug"),
) -> None:
    fmt = logging.Formatter("%(asctime)s - %(levelname)s - %(name)s - %(message)s")
    bridge = _RecorderLoggingHandler(recorder)
    bridge.setFormatter(fmt)

    root = logging.getLogger()
    for h in list(root.handlers):
        if isinstance(h, logging.StreamHandler):
            root.removeHandler(h)
    root.addHandler(bridge)

    for name in extra_logger_names:
        lg = logging.getLogger(name)
        for h in list(lg.handlers):
            if isinstance(h, logging.StreamHandler):
                lg.removeHandler(h)
        lg.propagate = False
        lg.addHandler(bridge)


# =============================================================================
# 3) کانتکستِ «نمادِ در حال پردازش» -- بدون نیاز به تغییرِ امضای هیچ تابعی
# =============================================================================
_current_symbol: contextvars.ContextVar[str] = contextvars.ContextVar("current_symbol", default="-")


# =============================================================================
# 4) خلاصه‌سازیِ امنِ ورودی/خروجی برای لاگ (کل DataFrame/Series چاپ نمی‌شود)
# =============================================================================
def _summarize_value(val: Any) -> str:
    try:
        if isinstance(val, pd.DataFrame):
            nan_counts = val.isna().sum().to_dict()
            last_row = val.tail(1).to_dict("records")
            return f"DataFrame shape={val.shape} last_row={last_row} nan_counts={nan_counts}"
        if isinstance(val, pd.Series):
            n_nan = int(val.isna().sum())
            valid = val.dropna()
            last_valid = valid.iloc[-1] if len(valid) else None
            return f"Series len={len(val)} nan={n_nan} last_valid={last_valid} tail={val.tail(3).tolist()}"
        if isinstance(val, (list, tuple)):
            # بازگشتی خلاصه می‌کند -- وگرنه یک تاپل از چند Series (مثل خروجی
            # calc_macd) باعث می‌شد repr کاملِ هر Series (صدها خط) در لاگ بیفتد.
            # این باگ واقعی بود و در همین تست پیدا و اصلاح شد.
            items = [_summarize_value(v) for v in list(val)[:5]]
            return f"{type(val).__name__}(len={len(val)}) items={items}"
        return repr(val)[:300]
    except Exception as e:  # noqa: BLE001 - خلاصه‌سازی هرگز نباید خودش باعث کرش شود
        return f"<summarize failed: {e!r}>"


def _summarize_args(args: tuple, kwargs: dict) -> str:
    parts = []
    for a in args:
        if isinstance(a, pd.DataFrame):
            parts.append(f"DataFrame(shape={a.shape})")
        elif isinstance(a, pd.Series):
            parts.append(f"Series(len={len(a)})")
        else:
            parts.append(repr(a)[:80])
    kw = {k: repr(v)[:80] for k, v in kwargs.items()}
    return f"args={parts} kwargs={kw}"


# =============================================================================
# 5) دکوریتورِ عمومیِ monkey-patch — شماره‌خط را از خودِ تابعِ اصلی
#    (در فایلِ واقعی‌اش، نه این فایل) می‌گیرد
# =============================================================================
def _wrap_traced(func: Callable, checkpoint: str) -> Callable:
    fname = Path(inspect.getsourcefile(func) or "?").name
    lineno = func.__code__.co_firstlineno

    @functools.wraps(func)
    def wrapper(*args: Any, **kwargs: Any) -> Any:
        symbol = _current_symbol.get()
        t0 = time.time()
        try:
            result = func(*args, **kwargs)
        except Exception as exc:
            RECORDER.error(
                f"[{checkpoint}] symbol={symbol} EXCEPTION in {func.__name__} "
                f"(defined @ {fname}:{lineno}) {_summarize_args(args, kwargs)}: {exc!r}",
                exc_info=True,
            )
            raise
        dt_ms = (time.time() - t0) * 1000
        RECORDER.debug(
            f"[{checkpoint}] symbol={symbol} {func.__name__}() [@ {fname}:{lineno}] "
            f"({dt_ms:.1f}ms) -> {_summarize_value(result)}"
        )
        return result

    return wrapper


# =============================================================================
# 6) پچ‌های اختصاصیِ فیلتر SSL — چون شما صریحاً خواسته‌اید این جداگانه بررسی شود
# =============================================================================
_last_gate_dir: dict[str, int] = {}


def _wrap_ssl_gate(func: Callable) -> Callable:
    fname = Path(inspect.getsourcefile(func) or "?").name
    lineno = func.__code__.co_firstlineno

    @functools.wraps(func)
    def wrapper(df: pd.DataFrame) -> pd.Series:
        symbol = _current_symbol.get()
        try:
            result = func(df)
        except Exception as exc:
            RECORDER.error(
                f"[CP-SSL-GATE] symbol={symbol} EXCEPTION in ssl_hybrid.compute_gate_series "
                f"(@ {fname}:{lineno}): {exc!r}",
                exc_info=True,
            )
            raise

        cur = int(result.iloc[-1]) if len(result) else 0
        prev = _last_gate_dir.get(symbol)
        changed = prev is not None and cur != prev
        _last_gate_dir[symbol] = cur

        RECORDER.info(
            f"[CP-SSL-GATE] symbol={symbol} [@ {fname}:{lineno}] last_dir={cur} "
            f"(prev={prev}, changed={changed}) nan_count={int(result.isna().sum())} len={len(result)}"
        )
        if changed:
            RECORDER.info(f"[CP-SSL-GATE-FLIP] symbol={symbol} گیت SSL از {prev} به {cur} تغییر کرد")
        return result

    return wrapper


# =============================================================================
# 7) پچِ اختصاصیِ DivergenceEngine.process — چون خروجی‌اش لیستی از
#    LabelEvent است و شایسته‌ی لاگِ رویدادبه‌رویداد است، نه یک repr خام
# =============================================================================
def _wrap_engine_process(func: Callable) -> Callable:
    fname = Path(inspect.getsourcefile(func) or "?").name
    lineno = func.__code__.co_firstlineno

    @functools.wraps(func)
    def wrapper(self, df: pd.DataFrame):
        symbol = _current_symbol.get()
        t0 = time.time()
        try:
            events = func(self, df)
        except Exception as exc:
            RECORDER.error(
                f"[CP-ENGINE] symbol={symbol} EXCEPTION in DivergenceEngine.process "
                f"(@ {fname}:{lineno}) df.shape={getattr(df, 'shape', None)}: {exc!r}",
                exc_info=True,
            )
            raise

        dt_ms = (time.time() - t0) * 1000
        last_ts = df.index[-1] if len(df) else None
        last_close = float(df["close"].iloc[-1]) if len(df) else None
        RECORDER.info(
            f"[CP-ENGINE] symbol={symbol} process() [@ {fname}:{lineno}] ({dt_ms:.1f}ms) "
            f"bars={len(df)} last_ts={last_ts} last_close={last_close} events={len(events)}"
        )
        for ev in events:
            RECORDER.info(
                f"[CP-EVENT] symbol={symbol} kind={ev.kind} dir={ev.direction} "
                f"bar_index={ev.bar_index} ts={ev.timestamp} price={ev.price_at_signal} "
                f"score={getattr(ev, 'score', None)}"
            )
        return events

    return wrapper


# =============================================================================
# 8) پچِ main.process_symbol / main.analyze_and_execute برای کانتکست نماد
#    و هارت‌بیت هر چرخه
# =============================================================================
def _wrap_process_symbol(orig_func: Callable) -> Callable:
    @functools.wraps(orig_func)
    def wrapper(symbol: str, engine):
        token = _current_symbol.set(symbol)
        RECORDER.debug(f"[CP-SYM-START] symbol={symbol}")
        try:
            return orig_func(symbol, engine)
        except Exception as exc:
            RECORDER.error(f"[CP-SYM-ERROR] symbol={symbol} استثنا در process_symbol: {exc!r}", exc_info=True)
            raise
        finally:
            RECORDER.debug(f"[CP-SYM-END] symbol={symbol}")
            _current_symbol.reset(token)

    return wrapper


def _wrap_analyze_and_execute(orig_func: Callable) -> Callable:
    @functools.wraps(orig_func)
    def wrapper(engines):
        cycle_ok = True
        try:
            orig_func(engines)
        except Exception as exc:
            cycle_ok = False
            # main.main_loop() خودش هم این استثنا را می‌گیرد و بعد از sleep ادامه
            # می‌دهد؛ این‌جا فقط برای ثبتِ دقیق‌تر (با traceback کامل) دوباره می‌آید.
            RECORDER.error(f"[CP-CYCLE-ERROR] استثنای مدیریت‌نشده در یک چرخه: {exc!r}", exc_info=True)
            raise
        finally:
            RECORDER.heartbeat_console(cycle_ok)
            RECORDER.maybe_flush()

    return wrapper


# =============================================================================
# 9) اعمالِ همه‌ی پچ‌ها (idempotent)
# =============================================================================
_PATCHED = False


def apply_patches() -> None:
    global _PATCHED
    if _PATCHED:
        return

    import divergence_engine as de
    import ssl_hybrid

    de.calc_rsi = _wrap_traced(de.calc_rsi, "CP-RSI")
    de.calc_macd = _wrap_traced(de.calc_macd, "CP-MACD")
    de.calc_adx = _wrap_traced(de.calc_adx, "CP-ADX")
    de.find_pivot_high = _wrap_traced(de.find_pivot_high, "CP-PIVOT-HIGH")
    de.find_pivot_low = _wrap_traced(de.find_pivot_low, "CP-PIVOT-LOW")
    de.DivergenceEngine.process = _wrap_engine_process(de.DivergenceEngine.process)

    ssl_hybrid.compute_gate_series = _wrap_ssl_gate(ssl_hybrid.compute_gate_series)
    ssl_hybrid.compute_ssl_hybrid = _wrap_traced(ssl_hybrid.compute_ssl_hybrid, "CP-SSL-CALC")

    _PATCHED = True
    RECORDER.info("[CP-PATCH] وصله‌های ردیابی روی divergence_engine و ssl_hybrid با موفقیت اعمال شد "
                  "(بدون تغییر هیچ فایل مبدأ)")


# =============================================================================
# 10) نقطه‌ی اجرای واقعی
# =============================================================================
def run() -> None:
    apply_patches()

    import main as bot_main  # کدِ سطح-بالای main.py اجرا می‌شود (چک env، ساخت
                              # notifier/market/exchange) اما چون import است نه
                              # اجرای مستقیم، حلقه‌ی اصلی هنوز شروع نشده است.

    RECORDER.attach_notifier(bot_main.notifier)
    silence_console_and_redirect(RECORDER)

    bot_main.process_symbol = _wrap_process_symbol(bot_main.process_symbol)
    bot_main.analyze_and_execute = _wrap_analyze_and_execute(bot_main.analyze_and_execute)

    RECORDER.info("[CP-BOOT] run_with_diagnostics.py آماده شد؛ همه‌ی پچ‌ها با موفقیت اعمال شدند")
    print("✅ [run_with_diagnostics] بات با موفقیت راه‌اندازی شد -- لاگ کامل هر ۱ ساعت به تلگرام می‌رود",
          flush=True)

    threading.Thread(target=lambda: bot_main.app.run(host="0.0.0.0", port=10000), daemon=True).start()
    bot_main.main_loop()


if __name__ == "__main__":
    try:
        run()
    except Exception as exc:
        print(f"❌ [run_with_diagnostics] CRASH: {exc!r}", flush=True)
        try:
            RECORDER.error(f"[CP-FATAL] برنامه با خطای غیرمنتظره متوقف شد: {exc!r}", exc_info=True)
            RECORDER.maybe_flush(force=True)
        except Exception:
            pass
        raise
