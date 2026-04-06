# ══════════════════════════════════════════════════════════════
#  APEX SYSTEM™  —  Dockerfile
#  Northflank · Fly.io · Railway · any Docker host
# ══════════════════════════════════════════════════════════════
FROM python:3.11-slim

WORKDIR /app

# Build Arguments (Northflank requires both Build Args AND Runtime Vars)
ARG TELEGRAM_BOT_TOKEN=""
ARG TELEGRAM_CHANNEL_ID=""
ARG DISCORD_BOT_TOKEN=""
ARG DISCORD_CHANNEL_ID="0"
ARG DISCORD_GUILD_ID="0"
ARG LOG_LEVEL="INFO"
ARG PORT="8080"

# Promote to runtime environment
ENV TELEGRAM_BOT_TOKEN=$TELEGRAM_BOT_TOKEN
ENV TELEGRAM_CHANNEL_ID=$TELEGRAM_CHANNEL_ID
ENV DISCORD_BOT_TOKEN=$DISCORD_BOT_TOKEN
ENV DISCORD_CHANNEL_ID=$DISCORD_CHANNEL_ID
ENV DISCORD_GUILD_ID=$DISCORD_GUILD_ID
ENV LOG_LEVEL=$LOG_LEVEL
ENV PORT=$PORT

# Install dependencies (layer-cached)
COPY requirements.txt .
RUN pip install --no-cache-dir --upgrade pip && \
    pip install --no-cache-dir -r requirements.txt

# Copy all source files
COPY . .

# Health check port
EXPOSE 8080

CMD ["python", "main.py"]
