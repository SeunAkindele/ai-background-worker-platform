import os
import socket

from app.config import settings


def get_process_worker_name() -> str:
    """
    Stable identity for one Celery worker process.

    Format: celery@<hostname>.<pid>.<worker_type>

    Stage 11 change:
    Added worker_type suffix so you can tell WHICH worker type
    a heartbeat row belongs to in the admin dashboard.

    Before: celery@abc123.42        → which type is this?
    After:  celery@abc123.42.ocr    → clearly the OCR worker

    Python Internals:
    settings.worker_type reads from WORKER_TYPE env var. Each Docker
    container gets its own env var value. Even though all containers
    run the same Python code, the environment differs — this is how
    the same image serves different roles.

    This is process-level state isolation via the OS environment,
    not via Python code. The code is identical; the behavior differs
    because the inputs (env vars) differ.
    """
    hostname = socket.gethostname()
    return f"celery@{hostname}.{os.getpid()}.{settings.worker_type}"