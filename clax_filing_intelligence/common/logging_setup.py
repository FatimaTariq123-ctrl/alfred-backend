"""
Structured Logging & Per-Stage Timing Setup (§3, Logging Architecture)

Provides contextvars logging filter [worker=N ticker=XXX] and per-stage timing context manager.
"""

import time
import logging
import contextvars
from contextlib import contextmanager
from typing import Dict, Any, Optional

# Context variables for worker and ticker logging context
worker_ctx: contextvars.ContextVar[str] = contextvars.ContextVar("worker_ctx", default="main")
ticker_ctx: contextvars.ContextVar[str] = contextvars.ContextVar("ticker_ctx", default="SYS")


class WorkerContextFilter(logging.Filter):
    """
    Injects worker ID and ticker symbol into log records.
    """
    def filter(self, record: logging.LogRecord) -> bool:
        record.worker = worker_ctx.get()
        record.ticker = ticker_ctx.get()
        return True


def setup_structured_logging(level: int = logging.INFO):
    """
    Configures root logger format to include worker and ticker context.
    """
    fmt = "%(asctime)s [%(levelname)s] [worker=%(worker)s ticker=%(ticker)s] %(name)s: %(message)s"
    root_logger = logging.getLogger()
    root_logger.setLevel(level)
    
    ctx_filter = WorkerContextFilter()
    root_logger.addFilter(ctx_filter)

    if not root_logger.handlers:
        handler = logging.StreamHandler()
        handler.addFilter(ctx_filter)
        handler.setFormatter(logging.Formatter(fmt))
        root_logger.addHandler(handler)
    else:
        for handler in root_logger.handlers:
            handler.addFilter(ctx_filter)
            handler.setFormatter(logging.Formatter(fmt))


@contextmanager
def stage(name: str, store: Dict[str, float], log: Optional[logging.Logger] = None):
    """
    Context manager to log and record the execution duration of a pipeline stage in seconds.
    """
    logger_inst = log or logging.getLogger("clax.stage")
    start_time = time.monotonic()
    logger_inst.info(f"stage-start {name}")
    try:
        yield
    finally:
        duration = time.monotonic() - start_time
        store[name] = round(duration, 3)
        logger_inst.info(f"stage-end {name} {duration:.2f}s")
