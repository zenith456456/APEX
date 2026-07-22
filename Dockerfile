# ── Build stage ───────────────────────────────────────────────────────────────
FROM python:3.11-slim

# System packages
RUN apt-get update \
    && apt-get install -y --no-install-recommends gcc curl \
    && rm -rf /var/lib/apt/lists/*

# Working directory = /app
# Python automatically adds the directory containing the script being run
# to sys.path. Since we run `python main.py` from /app, Python adds /app
# to sys.path, which means `from src.xxx import yyy` resolves correctly
# without any PYTHONPATH tricks.
WORKDIR /app

# Unbuffered output — logs appear in Northflank dashboard immediately
ENV PYTHONUNBUFFERED=1

# Install dependencies (separate layer for Docker cache efficiency)
COPY requirements.txt .
RUN pip install --no-cache-dir -r requirements.txt

# Copy source code
COPY . .

# Create data directory for state persistence
RUN mkdir -p /app/data

# Run as non-root (Northflank best practice)
RUN useradd -m -u 1000 ids && chown -R ids:ids /app
USER ids

# Entry point — must be run from /app so src/ package resolves
CMD ["python", "-u", "main.py"]
