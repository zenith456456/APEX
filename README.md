# Binance 24/7 Signal Bot

Public-market-data signal scanner for Binance USDⓈ-M perpetual futures. It sends signals only; it does not place trades.

## Core protections
- One active same-direction signal per symbol.
- Opposite direction invalidates the prior signal and can release the new one.
- A same-direction signal is allowed again after the prior signal is fully closed, including TP3/TP5 depending on the configured target set, or after a new post-SL setup is detected.
- Highest TP is stored as a single mutually-exclusive category: TP1 Only, TP2, TP3, TP4, TP5.
- Trade number is persistent from Trade #0001 onward and survives restarts.
- SQLite uses WAL mode; attach a Northflank persistent volume to `/app/data` for state persistence across container replacement.

## Binance connectivity
- Market streams: `wss://fstream.binance.com/public/stream`
- USDⓈ-M WebSocket API: `wss://ws-fapi.binance.com/ws-fapi/v1`
- REST is used only for 24h universe ranking, klines, open interest and funding.

## Install
```bash
python -m venv .venv
source .venv/bin/activate
pip install -r requirements.txt
cp .env.example .env
python app.py
```

## Northflank
Create a continuously-running Deployment Service from this GitHub repo. Select Dockerfile build. Add runtime variables from `.env.example` in Northflank. Optionally expose HTTP port 8080 and use `/health` for health checks. Attach a persistent volume at `/app/data` so the SQLite database survives restarts.

## Telegram
Set `TELEGRAM_BOT_TOKEN` and `TELEGRAM_CHAT_ID`.

## Discord
Set `DISCORD_WEBHOOK_URL`.

## Notes
The RSS news filter is a lightweight free filter, not a professional news feed. The displayed PNL is **model PNL in R**, not real exchange account PNL, because this bot does not place orders. Define `RISK_PER_TRADE_PCT` for a percentage interpretation outside the bot if needed.
