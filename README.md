# IDS Bot v2.0 — Ignition Detection System

Live 24/7 Binance Futures scanner → Telegram + Discord signals.

## Structure (flat — no packages)
```
ids-bot/
├── main.py              ← Entry point
├── config.py            ← All settings
├── logger.py            ← Logging setup
├── state.py             ← Dedup state machine
├── stats.py             ← Trade statistics
├── pipeline.py          ← 13-layer IDS scoring engine
├── scanner.py           ← Binance WebSocket + universe
├── formatter.py         ← Message builder
├── telegram_sender.py   ← Telegram alerts
├── discord_sender.py    ← Discord alerts
├── Dockerfile
├── requirements.txt
├── .env.example
└── data/                ← Runtime state (gitignored)
```

## Local run
```bash
python -m venv .venv && source .venv/bin/activate
pip install -r requirements.txt
cp .env.example .env    # fill in tokens
python main.py
```

## Deploy to Northflank
```bash
git init && git add . && git commit -m "IDS Bot v2.0"
git remote add origin https://github.com/YOUR_USERNAME/ids-bot.git
git branch -M main && git push -u origin main
```
Northflank → New Project → New Service → Deployment Service
→ GitHub repo → Dockerfile → add env vars → Deploy

## Environment Variables
| Variable | Default | Description |
|---|---|---|
| TELEGRAM_BOT_TOKEN | — | From @BotFather |
| TELEGRAM_CHANNEL_ID | — | e.g. -100123456789 |
| DISCORD_BOT_TOKEN | — | From Discord Developer Portal |
| DISCORD_CHANNEL_ID | — | Integer channel ID |
| MIN_VOLUME_USDT | 5000000 | 24h volume gate |
| AI_SCORE_THRESHOLD | 72 | Min AI score to fire |
| MIN_RR | 1.0 | Min R:R (hard gate) |
| UNIVERSE_REFRESH_SECS | 600 | New listing check interval |
| LOG_LEVEL | INFO | DEBUG/INFO/WARNING/ERROR |
