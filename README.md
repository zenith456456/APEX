# APEX Signal Bot

24/7 automated crypto trading **signal scanner** for Binance Futures.
Broadcasts free live signals to **Telegram** and **Discord** using a
5-timeframe multi-confluence pattern engine (MTCS), with smart
signal deduplication and live performance stats on every signal.

- **No geo-blocking** — uses Binance **Futures** WebSocket (`fstream.binance.com`), not the geo-restricted Spot stream.
- **Auto-detects new listings** — polls `exchangeInfo` every hour and subscribes new USDT perpetuals automatically.
- **No duplicate signals** — state-machine dedup engine (see `apex_signal_memory.py`), no countdown timers.
- **Runs anywhere** — Docker container, deployable to Northflank's sandbox tier for free 24/7 uptime.

---

## 1. Project Structure

```
apex-signal-bot/
├── main.py                   # Entry point
├── config.py                 # Env-driven configuration
├── binance_scanner.py        # Binance Futures WebSocket scanner
├── engines.py                 # MTCS multi-timeframe pattern scoring
├── apex_signal_memory.py      # Signal dedup state machine
├── stats_engine.py            # WR / PNL / TP breakdown tracker
├── signal_manager.py          # Orchestrates scanner → engine → memory → broadcast
├── broadcaster.py             # Formats + dispatches signal messages
├── telegram_bot.py            # Telegram send integration
├── discord_bot.py             # Discord send integration
├── requirements.txt
├── Dockerfile
├── docker-compose.yml          # local dev only
├── northflank.template.yaml    # reference deployment config
├── .env.example
├── .gitignore
└── README.md
```

---

## 2. Prerequisites

- A GitHub account
- A Telegram bot token from **@BotFather** (free, 1 minute)
- (Optional) A Discord bot token from the **Discord Developer Portal**
- A free **Northflank** account (sandbox tier)
- Git installed locally

---

## 3. Create the Telegram Bot

1. Open Telegram, search **@BotFather**
2. Send `/newbot`, follow prompts → copy the **bot token**
3. Add the bot to your channel/group as **admin**
4. Get the channel ID:
   - For a public channel: `@yourchannelname`
   - For a private channel/group: forward a message from it to **@JsonDumpBot** or use the Telegram API `getUpdates` to read the numeric `chat.id` (looks like `-1001234567890`)

---

## 4. Create the Discord Bot (optional)

1. Go to https://discord.com/developers/applications → **New Application**
2. **Bot** tab → **Add Bot** → copy the **token**
3. **OAuth2 → URL Generator** → scopes: `bot` → permissions: `Send Messages`, `Read Message History`
4. Invite the bot to your server using the generated URL
5. Enable **Developer Mode** in Discord (User Settings → Advanced) → right-click your channel → **Copy Channel ID**

---

## 5. Local Setup (test before deploying)

```bash
# Clone your repo (after pushing — see Section 7)
git clone https://github.com/<your-username>/apex-signal-bot.git
cd apex-signal-bot

# Create virtual environment
python -m venv venv
source venv/bin/activate        # Windows: venv\Scripts\activate

# Install dependencies
pip install -r requirements.txt

# Configure environment
cp .env.example .env
# Edit .env and fill in your real tokens

# Run locally
python main.py
```

You should see logs like:

```
2026-06-30 12:00:01 | INFO | APEX.Main | 🚀 Starting APEX Signal Bot
2026-06-30 12:00:02 | INFO | APEX.Telegram | Telegram bot connected as @YourBot
2026-06-30 12:00:03 | INFO | APEX.Scanner | ExchangeInfo: 312 USDT perpetuals found
2026-06-30 12:00:05 | INFO | APEX.Scanner | Monitoring 200 pairs
```

---

## 6. Test with Docker (optional, mirrors production)

```bash
docker compose build
docker compose up
```

---

## 7. Push to GitHub

```bash
# Initialize git (if not already a repo)
git init
git branch -M main

# Stage all files
git add .

# Confirm .env is NOT staged (it should be ignored)
git status

# First commit
git commit -m "Initial commit: APEX Signal Bot — Binance scanner + Telegram/Discord broadcaster"

# Create the repo on GitHub first (via github.com → New Repository → do NOT
# initialize with README, since you already have one), then:
git remote add origin https://github.com/<your-username>/apex-signal-bot.git
git push -u origin main
```

**If you ever accidentally commit secrets:** rotate the token immediately
(regenerate in BotFather / Discord Developer Portal) — removing it from git
history alone is not sufficient once pushed to a public repo.

---

## 8. Deploy to Northflank (Sandbox Tier — Free)

1. Sign in to **Northflank** → **Create New Project**
2. Inside the project → **Add New** → **Service** → **Combined Service** (Build + Deploy)
3. **Connect repository** → authorize GitHub → select `apex-signal-bot`
4. **Build settings**:
   - Build type: **Dockerfile**
   - Dockerfile path: `Dockerfile`
   - Context: `/`
5. **Compute plan**: select the **sandbox/free tier** instance size
6. **Environment Variables** — add each of the following (mark tokens as *secret*):

   | Key | Value |
   |---|---|
   | `TELEGRAM_BOT_TOKEN` | your token |
   | `TELEGRAM_CHANNEL_ID` | your channel id |
   | `DISCORD_BOT_TOKEN` | your token (optional) |
   | `DISCORD_CHANNEL_ID` | your channel id (optional) |
   | `MAX_PAIRS` | `200` |
   | `MIN_VOLUME_USDT` | `1000000` |
   | `MTCS_MIN_SCORE` | `55` |
   | `SCAN_INTERVAL_SEC` | `30` |
   | `LISTING_CHECK_MIN` | `60` |
   | `LOG_LEVEL` | `INFO` |

7. **Networking**: no public port needed (the bot only makes outbound
   connections to Binance, Telegram, and Discord) — you can leave ports empty.
8. **Restart Policy**: set to **Always** so it auto-recovers from any crash.
9. Click **Deploy**.

Northflank will build the Docker image from your GitHub repo and run it
24/7. Every push to `main` can optionally trigger an automatic redeploy
(enable "Auto-deploy on push" in the service settings).

---

## 9. Updating the Bot Later

```bash
git add .
git commit -m "Update: <describe your change>"
git push origin main
```

If auto-deploy is enabled in Northflank, the new version ships automatically.
Otherwise, click **Redeploy** in the Northflank service dashboard.

---

## 10. How the Binance Connection Avoids Geo-Blocking

Binance's **Spot** WebSocket (`wss://stream.binance.com`) is geo-restricted
in some regions (including some cloud provider IP ranges used by Northflank).
This bot instead uses the **Binance Futures** endpoint:

```
wss://fstream.binance.com/stream
```

which is **not** subject to the same regional blocking and provides the
same kline/aggTrade data needed for the pattern engine, plus open interest
data for free via REST (`fapi.binance.com/fapi/v1/openInterest`).

---

## 11. How New Listings Are Auto-Detected

Every `LISTING_CHECK_MIN` minutes (default 60), the scanner:

1. Calls `GET /fapi/v1/exchangeInfo` → gets the full list of active USDT-margined perpetual contracts
2. Diffs against the currently monitored pair set
3. Any new symbol found is automatically pre-filled with historical candles and subscribed to all WebSocket kline/aggTrade streams — **no code change or redeploy required**

---

## 12. Disclaimer

This software is provided for educational and research purposes only.
It does not constitute financial advice. Cryptocurrency trading carries
substantial risk of loss. Always use proper risk management and never
trade with funds you cannot afford to lose.
