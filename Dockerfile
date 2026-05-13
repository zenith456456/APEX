# ─── CSM Omega Trigger Bot ─────────────────────────────────────────────
FROM python:3.11-slim

# System dependencies
RUN apt-get update && apt-get install -y --no-install-recommends \
    gcc curl \
    && rm -rf /var/lib/apt/lists/*

WORKDIR /app

# Install Python dependencies first (cached layer)
COPY requirements.txt .
RUN pip install --no-cache-dir -r requirements.txt

# Copy source code
COPY . .

# Persistent storage for the bot’s memory (trade log, signal state)
RUN mkdir -p /data
ENV MEMORY_FILE=/data/signal_memory.json

# Healthcheck — ensures the process remains alive even in a sandbox
HEALTHCHECK --interval=60s --timeout=10s --start-period=30s --retries=3 \
    CMD pgrep -f "python main.py" || exit 1

# Non-root user for security (named csmbot)
RUN useradd -m -u 1000 csmbot && chown -R csmbot:csmbot /app /data
USER csmbot

# Start the bot with stdout unbuffered for real-time logs
CMD ["python", "-u", "main.py"]
