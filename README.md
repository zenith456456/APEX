# ⚡ APEX-EDS v4.0 — Signal Bot
### Binance USDT-M Futures · Telegram + Discord · 24x7 on Northflank

---

## 📁 Complete File List

| File | Purpose |
|---|---|
| `main.py` | Entry point — starts everything |
| `config.py` | All settings via environment variables |
| `models.py` | Shared data classes and enums |
| `exchange_monitor.py` | Binance WebSocket + REST feeds, new listing detection |
| `indicators.py` | ATR, RSI, MACD, CVD, VPIN, Regime, VPOC |
| `apex_engine.py` | 7-layer Bayesian scoring engine |
| `signal_memory.py` | Smart dedup state machine (no timers) |
| `stats_tracker.py` | All-time + daily + monthly win rate tracker |
| `scanner.py` | 24x7 scan loop |
| `formatter.py` | Telegram HTML + Discord embed builder |
| `telegram_sender.py` | Telegram delivery queue |
| `discord_sender.py` | Discord webhook delivery |
| `requirements.txt` | Python dependencies |
| `Dockerfile` | Container definition for Northflank |
| `.gitignore` | Prevents secrets from being committed |
| `.env.example` | Template for your API keys |
| `README.md` | This guide |

---

## 🚀 FULL INSTALLATION GUIDE

### PART 1 — PREPARE YOUR KEYS

#### A) Binance API Key
1. Go to [binance.com](https://binance.com) → Profile → API Management
2. Click **Create API** → Label it `APEX-EDS`
3. Enable: **Read Only** (do NOT enable trading — bot is signal only)
4. Copy your **API Key** and **Secret Key**

#### B) Telegram Bot Token
1. Open Telegram → search `@BotFather`
2. Send `/newbot`
3. Choose a name: `APEX EDS Bot`
4. Choose a username: `apex_eds_signal_bot`
5. Copy the **token** it gives you (looks like `123456789:ABCdef...`)
6. Create a Telegram channel/group for signals
7. Add your bot as **Admin** to the channel
8. Search `@userinfobot` on Telegram → forward a message from your channel to it
9. Copy the **chat ID** (negative number like `-1001234567890`)

#### C) Discord Webhook
1. Open Discord → go to your signals server
2. Create a channel e.g. `#apex-signals`
3. Click the ⚙️ gear on the channel → **Integrations** → **Webhooks**
4. Click **New Webhook** → name it `APEX-EDS`
5. Click **Copy Webhook URL**

---

### PART 2 — GITHUB SETUP

#### Step 1: Create a new GitHub repository
1. Go to [github.com](https://github.com) → click **+** → **New repository**
2. Name: `apex-eds-bot`
3. Set to **Private** ✅
4. Do NOT add README, .gitignore, or license (we have our own)
5. Click **Create repository**
6. Copy your repo URL: `https://github.com/YOUR_USERNAME/apex-eds-bot.git`

#### Step 2: Upload all files to GitHub

Open a terminal on your computer, navigate to the folder where you extracted the bot files, then run:

```bash
# Navigate to your bot folder
cd apex-eds-bot   # or wherever you extracted the files

# Initialize git
git init

# Add your GitHub repo as remote (replace YOUR_USERNAME)
git remote add origin https://github.com/YOUR_USERNAME/apex-eds-bot.git

# Stage all files
git add .

# Commit
git commit -m "feat: APEX-EDS v4.0 initial deployment"

# Push to GitHub
git branch -M main
git push -u origin main
```

✅ All 17 files are now on GitHub.

---

### PART 3 — NORTHFLANK SETUP

#### Step 1: Create a Northflank account
1. Go to [northflank.com](https://northflank.com)
2. Sign up for free (free tier works for this bot)
3. Create a new **Project** → name it `apex-eds`

#### Step 2: Create a new Service
1. Inside your project → click **New Service**
2. Select **Build and deploy from source code**
3. Click **Connect GitHub** → authorize Northflank to access your repos
4. Select your `apex-eds-bot` repository
5. Branch: `main`
6. Click **Next**

#### Step 3: Configure the build
1. Build type: **Dockerfile** (auto-detected)
2. Dockerfile path: `Dockerfile` (leave as default)
3. Click **Next**

#### Step 4: Set the region
> ⚠️ IMPORTANT: Choose a region where Binance is accessible
- Select **Europe West (Belgium)** ← RECOMMENDED
- Or **US East (Virginia)**
- Do NOT use US-Central (geo-blocked by Binance)

#### Step 5: Set environment variables
Click **Environment** tab → **Add variable** — add each one:

| Variable Name | Your Value |
|---|---|
| `BINANCE_API_KEY` | Your Binance API key |
| `BINANCE_API_SECRET` | Your Binance secret key |
| `TELEGRAM_TOKEN` | Your bot token from @BotFather |
| `TELEGRAM_CHAT_IDS` | Your channel/group chat ID |
| `DISCORD_WEBHOOK_URL` | Your Discord webhook URL |

#### Step 6: Configure runtime settings
1. **Start command**: `python -u main.py`
2. **Restart policy**: `Always` (critical for 24x7)
3. **Resources**: 1 CPU, 512MB RAM minimum (1GB recommended)

#### Step 7: Deploy
1. Click **Deploy** 
2. Northflank will build the Docker image (takes 2-3 minutes)
3. Once built, it starts automatically

#### Step 8: Verify it's working
1. Click on your service → **Logs** tab
2. You should see:
```
APEX-EDS v4.0 — Starting
ExchangeMonitor: starting...
Endpoint OK: https://fapi.binance.com (312 pairs)
Kline bootstrap complete
Scanner: 24x7 loop starting
APEX-EDS running — 24x7 scan active ✓
```
3. Within 35 seconds, your Telegram and Discord will receive a startup message

---

### PART 4 — AUTO-DEPLOY ON CODE CHANGES

Northflank auto-deploys whenever you push to GitHub.

To update the bot after making changes:
```bash
git add .
git commit -m "fix: your change description"
git push
```
Northflank detects the push and redeploys automatically within 2-3 minutes with zero downtime.

---

### PART 5 — MONITORING

#### View live logs
- Northflank → Service → **Logs** tab
- Shows every signal fired, win/loss recorded, errors

#### Bot health indicators in logs
```
✅ GOOD: "SIGNAL #47 BTCUSDT LONG Score=91.2"
✅ GOOD: "Exchange info refreshed — 312 pairs"
⚠️ WARN: "BLOCKED ETHUSDT: same direction active"
❌ BAD:  "geo-blocked (451)" → change Northflank region
```

---

### PART 6 — SIGNAL FORMAT

Every Telegram/Discord signal includes:

**Top of signal:**
- 📊 Trade number (e.g. Trade #47)
- Position direction (LONG/SHORT)

**Signal body:**
1. 💎 Coin pair
2. 📌 Entry zone (limit order range)
3. 📍 Position (LONG/SHORT)
4. ⚖️ Leverage (5× or 10×)
5. 🎯 TP1 / TP2 / TP3 with % and R:R
6. 🛑 Stop Loss with %
7. Scalp type (1M/5M/15M)
8. 📊 R:R ratio
9. ⏱ Expected hold time
10. Market condition + Regime
11. 🧠 APEX SCORE with 7-layer breakdown

**Bottom stats block:**
- 🏆 All-Time Win Rate + W/L count + Total PNL
- 📅 Daily Win Rate + daily W/L + daily PNL
- 🗓 Monthly Win Rate + monthly W/L + monthly PNL

---

### TROUBLESHOOTING

| Error | Fix |
|---|---|
| `HTTP 451 geo-blocked` | Change Northflank region to Europe West |
| `TELEGRAM_TOKEN not set` | Add env var in Northflank |
| `0 pairs active` | Check Binance API key or region |
| `Permission denied: .log` | Already fixed — bot uses stdout only |
| `PermissionError /app/` | Already fixed — uses non-root user |
| Bot restarts constantly | Check logs for Python error, fix and push |

---

### ENVIRONMENT VARIABLES REFERENCE

| Variable | Required | Description |
|---|---|---|
| `BINANCE_API_KEY` | Optional | Read-only key (public data works without it) |
| `BINANCE_API_SECRET` | Optional | Read-only secret |
| `TELEGRAM_TOKEN` | ✅ Yes | From @BotFather |
| `TELEGRAM_CHAT_IDS` | ✅ Yes | Comma-separated channel IDs |
| `DISCORD_WEBHOOK_URL` | ✅ One of these | Webhook URL |
| `DISCORD_BOT_TOKEN` | ✅ One of these | Bot token alternative |
| `DISCORD_CHANNEL_ID` | If using bot token | Channel ID |

---

*APEX-EDS v4.0 · 7-Layer Bayesian · R:R ≥ 1:4 · All Binance USDT-M Perps*
