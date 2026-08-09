import functools
import logging
import time
from contextlib import contextmanager
from typing import Callable, ParamSpec, TypeVar

logger = logging.getLogger(__name__)

P = ParamSpec("P")
R = TypeVar("R")


@contextmanager
def timed_block(label: str):
    """Context manager that times a block and exposes elapsed seconds."""
    result = TimerResult(label)
    start = time.perf_counter()
    try:
        yield result
    finally:
        result.elapsed = time.perf_counter() - start
        logger.info("[%s] finished in %.3fs", label, result.elapsed)


class TimerResult:
    """Mutable container so the caller can access elapsed time after the with-block."""
    __slots__ = ("label", "elapsed")

    def __init__(self, label: str):
        self.label = label
        self.elapsed: float = 0.0


def log_execution_time(func: Callable[P, R]) -> Callable[P, R]:
    """Decorator that logs how long a function took."""
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
    """Decorator wrapping a Celery task with logging; re-raises exceptions."""
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