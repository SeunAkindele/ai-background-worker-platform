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
    """
    Context manager for timing arbitrary blocks of code.

    Usage:
        with timed_block("summarization") as timer:
            result = do_heavy_work()
        print(timer.elapsed)  # seconds as float

    Python Internals Focus:
    -----------------------
    A context manager implements __enter__ and __exit__.
    @contextmanager is a decorator that converts a generator function
    into a context manager — the yield point is where the `with` block runs.

    The TimerResult object is yielded so the caller can read elapsed time
    AFTER the block completes. This works because:
    1. __enter__ runs → creates TimerResult, starts clock, yields it
    2. The `with` block runs (user code)
    3. __exit__ runs → stops clock, stores elapsed in the same object
    The caller already has a reference to the TimerResult from step 1.

    This is a mutable reference pattern — the caller holds a reference
    to an object that gets mutated after yield.
    """
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
    """
    Decorator: logs how long a function took.

    Python internals: closure — inner wrapper captures func, logger, time.
    """
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
    """
    Decorator: wraps a Celery task function with heartbeat + logging.

    This decorator is meant to be stacked ON TOP of @celery_app.task.
    It catches exceptions, logs them, and re-raises.

    Python Internals Focus:
    -----------------------
    Decorator stacking: when you write
        @monitor_task
        @celery_app.task(...)
        def process_job(self, job_id): ...

    Python applies them bottom-up:
        process_job = monitor_task(celery_app.task(...)(process_job))

    The outermost decorator (monitor_task) runs first on each call.
    """
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