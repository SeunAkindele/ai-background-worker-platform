import functools
import logging
import time
from contextlib import contextmanager
from typing import Callable, ParamSpec, TypeVar

logger = logging.getLogger(__name__)

P = ParamSpec("P")
R = TypeVar("R")


class TimerResult:
    """Holds elapsed seconds after a timed_block exits."""

    __slots__ = ("label", "elapsed")

    def __init__(self, label: str):
        self.label = label
        self.elapsed: float = 0.0


@contextmanager
def timed_block(label: str):
    """Time a code block and expose elapsed seconds on the yielded result."""
    result = TimerResult(label)
    start = time.perf_counter()
    try:
        yield result
    finally:
        result.elapsed = time.perf_counter() - start
        logger.info("[%s] finished in %.3fs", label, result.elapsed)


def log_execution_time(func: Callable[P, R]) -> Callable[P, R]:
    """Log wall-clock duration of the wrapped function."""

    @functools.wraps(func)
    def wrapper(*args: P.args, **kwargs: P.kwargs) -> R:
        start = time.perf_counter()
        try:
            return func(*args, **kwargs)
        finally:
            elapsed = time.perf_counter() - start
            logger.info("%s finished in %.3fs", func.__name__, elapsed)

    return wrapper


def monitor_task(func: Callable[P, R]) -> Callable[P, R]:
    """Log start, success, and failure for a Celery task function."""

    @functools.wraps(func)
    def wrapper(*args: P.args, **kwargs: P.kwargs) -> R:
        func_name = func.__name__
        logger.info("[monitor] %s started", func_name)
        start = time.perf_counter()
        try:
            result = func(*args, **kwargs)
            elapsed = time.perf_counter() - start
            logger.info("[monitor] %s succeeded in %.3fs", func_name, elapsed)
            return result
        except Exception as exc:
            elapsed = time.perf_counter() - start
            logger.error(
                "[monitor] %s failed after %.3fs: %s", func_name, elapsed, exc
            )
            raise

    return wrapper
