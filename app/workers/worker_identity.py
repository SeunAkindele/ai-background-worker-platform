import os
import socket

from app.config import settings


def get_process_worker_name() -> str:
    """Return a stable worker identity: celery@<host>.<pid>.<worker_type>."""
    hostname = socket.gethostname()
    return f"celery@{hostname}.{os.getpid()}.{settings.worker_type}"
