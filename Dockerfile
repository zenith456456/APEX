# ── APEX-QUANT Dockerfile ─────────────────────────────────────────
# Minimal Python 3.11 image for Northflank / any container host

FROM python:3.11-slim

# System deps for numpy + websockets
RUN apt-get update && apt-get install -y --no-install-recommends \
    gcc g++ curl \
    && rm -rf /var/lib/apt/lists/*

WORKDIR /app

# Install Python deps first (better layer caching)
COPY requirements.txt .
RUN pip install --no-cache-dir -r requirements.txt

# Copy source
COPY . .

# Health-check for container orchestrators
HEALTHCHECK --interval=30s --timeout=10s --start-period=20s --retries=3 \
    CMD curl -f http://localhost:${PORT:-8080}/health || exit 1

ENV PORT=8080
EXPOSE 8080

CMD ["python", "main.py"]
