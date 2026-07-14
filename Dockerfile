# ============================================================
# Stage 1: Builder — install Python dependencies
# ============================================================
# Why multi-stage?
# The builder stage installs compilers, headers, and build tools
# needed to compile C extensions (psycopg2, numpy, torch, etc.).
# The final image only copies the installed packages, not the
# build tools. This shrinks the image by hundreds of MB.
#
# Python Internals:
# When pip installs a package, it may compile C extensions into
# .so files (shared objects). These .so files are what Python
# loads at import time via the `importlib` machinery. The source
# .c files and compiler are only needed during build, not at runtime.
# ============================================================
FROM python:3.12-slim AS builder

WORKDIR /build

# System deps needed to COMPILE wheels (not needed at runtime)
# - gcc/g++: C/C++ compiler for native extensions
# - libpq-dev: PostgreSQL client headers (for psycopg2)
# - libffi-dev: Foreign function interface (for cffi-based packages)
RUN apt-get update && apt-get install -y --no-install-recommends \
    gcc \
    g++ \
    libpq-dev \
    libffi-dev \
    && rm -rf /var/lib/apt/lists/*

COPY requirements.txt .

# Install into a virtual env inside the builder.
# Why a venv even in Docker?
# It gives us a clean, relocatable directory to COPY into the
# final stage. Without it, pip scatters files across /usr/local/lib
# and it's hard to copy only what we installed vs what came with
# the base image.
RUN python -m venv /opt/venv
ENV PATH="/opt/venv/bin:$PATH"

RUN pip install --no-cache-dir --upgrade pip \
    && pip install --no-cache-dir torch --index-url https://download.pytorch.org/whl/cpu \
    && pip install --no-cache-dir -r requirements.txt


# ============================================================
# Stage 2: Runtime — lean image with only what's needed to run
# ============================================================
FROM python:3.12-slim

# System deps needed at RUNTIME (not for building):
# - libpq5: PostgreSQL client library (psycopg2 links against it)
# - tesseract-ocr: OCR engine called by pytesseract
# - ffmpeg: audio/video processing used by Whisper
# - libgomp1: OpenMP runtime (torch/numpy use it for parallelism)
#
# System Design:
# Each runtime dep is here because a specific worker needs it.
# In Stage 11 you'll split workers into separate images and each
# will only install what IT needs. For now, one image serves all.
RUN apt-get update && apt-get install -y --no-install-recommends \
    libpq5 \
    tesseract-ocr \
    ffmpeg \
    libgomp1 \
    && rm -rf /var/lib/apt/lists/*

# Copy the pre-built venv from the builder stage.
# This is the multi-stage payoff: no gcc, no -dev headers, no pip cache.
COPY --from=builder /opt/venv /opt/venv
ENV PATH="/opt/venv/bin:$PATH"

# Python Internals:
# PYTHONDONTWRITEBYTECODE=1
#   Prevents Python from writing .pyc files to __pycache__/.
#   In a container, .pyc files waste disk and layer space.
#   The startup cost of compiling .py → bytecode on each run is
#   negligible for a long-running server.
#
# PYTHONUNBUFFERED=1
#   Forces stdout/stderr to be unbuffered (like running python -u).
#   Without this, Python buffers output and you won't see print()
#   or logging output in `docker compose logs` until the buffer
#   flushes (could be seconds or minutes later).
#   Internally, this sets the C-level FILE* streams to unbuffered mode.
ENV PYTHONDONTWRITEBYTECODE=1
ENV PYTHONUNBUFFERED=1

WORKDIR /app

# Copy application code.
# This is AFTER pip install so changing code doesn't invalidate
# the pip install layer (Docker layer caching).
#
# Python Internals:
# Because we set WORKDIR to /app and our code lives at /app/app/,
# Python can find `app.main`, `app.config`, etc. via normal
# package resolution. The working directory /app is implicitly
# on sys.path for top-level imports.
COPY . .

# Create uploads directory inside the container.
# In production you'd use object storage (S3), but for local Docker
# development this directory needs to exist.
RUN mkdir -p /app/uploads

# Default command: run the FastAPI server.
# Individual services override this in docker-compose.yml.
#
# Why 0.0.0.0?
# Inside a container, localhost (127.0.0.1) means "this container only."
# To accept connections from outside (other containers, your host machine),
# you must bind to 0.0.0.0 (all interfaces).
CMD ["uvicorn", "app.main:app", "--host", "0.0.0.0", "--port", "8000"]