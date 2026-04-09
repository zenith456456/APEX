# ⚡ APEX-EDS v4.0 — Signal Bot

**7-Layer Bayesian Scalp Signal Engine for Binance USDT-M Futures**

Scans all Binance perpetual pairs 24x7, fires Telegram + Discord signals with R:R ≥ 1:4.

---

## Features

- ✅ Scans **all** Binance USDT-M perpetual futures (300+ pairs)
- ✅ Auto-detects **new listings** every hour
- ✅ **7-layer Bayesian** scoring engine (CVD, VPIN, Regime, VPOC, RSI, MACD, AI proxy)
- ✅ **R:R ≥ 1:4** hard gate — only high-quality setups
- ✅ Smart **signal memory** — no duplicate signals (price-state driven, no timers)
- ✅ Rich **Telegram HTML** + **Discord embed** messages
- ✅ 3 scalp types: ⚡ 1M Micro · 🎯 5M Standard · 🔭 15M Extended
- ✅ Deploy-ready on **Northflank** via Docker

---

## Quick Start (local)

```bash
git clone https://github.com/YOUR_USERNAME/apex-eds-bot.git
cd apex-eds-bot
pip install -r requirements.txt
cp .env.example .env
# Fill in your keys in .env
python main.py
```

---

## Environment Variables

| Variable | Description |
|---|---|
| `BINANCE_API_KEY` | Binance read-only API key |
| `BINANCE_API_SECRET` | Binance API secret |
| `TELEGRAM_TOKEN` | Telegram bot token (from @BotFather) |
| `TELEGRAM_CHAT_IDS` | Comma-separated chat/channel IDs |
| `DISCORD_WEBHOOK_URL` | Discord webhook URL (recommended) |
| `DISCORD_BOT_TOKEN` | Discord bot token (alternative) |
| `DISCORD_CHANNEL_ID` | Discord channel ID (if using bot token) |

---

## Northflank Deploy

1. Push this repo to GitHub
2. Create a new **Service** in Northflank → connect GitHub repo
3. Set all env vars above as **Runtime Environment Variables**
4. Build command: *(auto — uses Dockerfile)*
5. Start command: `python -u main.py`
6. Set **restart policy** to `always`

---

## File Structure

```
apex-eds-bot/
├── main.py              ← Entry point
├── config.py            ← All settings
├── models.py            ← Shared data classes
├── exchange_monitor.py  ← Binance WS + REST feeds
├── indicators.py        ← ATR, RSI, MACD, CVD, VPIN, etc.
├── apex_engine.py       ← 7-layer scoring engine
├── signal_memory.py     ← Deduplication state machine
├── scanner.py           ← 24x7 scan loop
├── formatter.py         ← Telegram + Discord message builder
├── telegram_sender.py   ← Telegram delivery
├── discord_sender.py    ← Discord delivery
├── requirements.txt
├── Dockerfile
├── .gitignore
└── .env.example
```

---

## Signal Format

Every signal includes:
1. Coin pair
2. Entry zone (limit order range)
3. Position (LONG / SHORT)
4. Leverage (5× or 10×)
5. TP1 / TP2 / TP3 with % and R:R
6. Stop Loss with %
7. Scalp type (1M / 5M / 15M)
8. R:R ratio
9. Expected hold time
10. Market condition
11. 🧠 APEX SCORE (0–100) with 7-layer breakdown
