# ─── Dockerfile ────────────────────────────────────────────────────────────
# APEX Signal Bot — Production Container
# Lightweight Python 3.11 slim image for Northflank deployment

FROM python:3.11-slim

# Prevents Python from buffering stdout/stderr — required for live logs
ENV PYTHONUNBUFFERED=1 \
    PYTHONDONTWRITEBYTECODE=1 \
    PIP_NO_CACHE_DIR=1

WORKDIR /app

# Install OS-level deps needed for aiohttp/websockets SSL
RUN apt-get update && apt-get install -y --no-install-recommends \
    build-essential \
    ca-certificates \
    && rm -rf /var/lib/apt/lists/*

# Install Python deps first (better layer caching)
COPY requirements.txt .
RUN pip install --no-cache-dir -r requirements.txt

# Copy application code
COPY . .

# Northflank healthcheck-friendly: bot has no HTTP port by default,
# but we expose 8080 in case a healthcheck endpoint is added later.
EXPOSE 8080

# Run as non-root for security
RUN useradd -m apexuser && chown -R apexuser:apexuser /app
USER apexuser

CMD ["python", "main.py"]
