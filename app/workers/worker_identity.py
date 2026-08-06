import os
import socket

from app.config import settings


def get_process_worker_name() -> str:
    """
    Stable identity for one Celery worker process.

    Format: celery@<hostname>.<pid>.<worker_type>
    """
    hostname = socket.gethostname()
    return f"celery@{hostname}.{os.getpid()}.{settings.worker_type}"
