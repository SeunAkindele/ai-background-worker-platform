import os
import socket


def get_process_worker_name() -> str:
    """
    Stable identity for one Celery worker process.

    Uses hostname + PID so prefork children each get their own row,
    and the same row is updated across idle beats and job processing.
    """
    hostname = socket.gethostname()
    return f"celery@{hostname}.{os.getpid()}"
