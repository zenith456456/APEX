# APEX SYSTEM™ — Dockerfile
# Northflank: connect this repo and Northflank builds this automatically.
# Local test:  docker build -t apex-bot . && docker run --env-file .env apex-bot

FROM python:3.11-slim

# Set working directory
WORKDIR /app

# Install dependencies first (layer caching)
COPY requirements.txt .
RUN pip install --no-cache-dir -r requirements.txt

# Copy all bot files
COPY . .

# Northflank / Render injects env vars at runtime.
# No ENV instructions here — secrets never go in the image.

# Health check port (Northflank uses 8080 by default)
EXPOSE 8080

# Start the bot
CMD ["python", "main.py"]
