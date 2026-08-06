# ============================================================
# Builder — compile native deps and install Python packages
# ============================================================
FROM python:3.12-slim AS builder

WORKDIR /build

# Build-time system packages for compiling C extensions
RUN apt-get update && apt-get install -y --no-install-recommends \
    gcc \
    g++ \
    libpq-dev \
    libffi-dev \
    && rm -rf /var/lib/apt/lists/*

COPY requirements.txt .

# Install into a venv so the runtime image can copy a self-contained tree
RUN python -m venv /opt/venv
ENV PATH="/opt/venv/bin:$PATH"

RUN pip install --no-cache-dir --upgrade pip \
    && pip install --no-cache-dir torch --index-url https://download.pytorch.org/whl/cpu \
    && pip install --no-cache-dir -r requirements.txt


# ============================================================
# Runtime — lean image with only what's needed to run
# ============================================================
FROM python:3.12-slim

# Runtime system deps: Postgres client, Tesseract, ffmpeg, OpenMP
RUN apt-get update && apt-get install -y --no-install-recommends \
    libpq5 \
    tesseract-ocr \
    ffmpeg \
    libgomp1 \
    && rm -rf /var/lib/apt/lists/*

COPY --from=builder /opt/venv /opt/venv
ENV PATH="/opt/venv/bin:$PATH"

# Avoid .pyc files in the image; flush logs immediately for containers
ENV PYTHONDONTWRITEBYTECODE=1
ENV PYTHONUNBUFFERED=1

WORKDIR /app

# App code last so dependency layers stay cached when only source changes
COPY . .

RUN mkdir -p /app/uploads

# Bind all interfaces so the API is reachable from outside the container
CMD ["uvicorn", "app.main:app", "--host", "0.0.0.0", "--port", "8000"]
