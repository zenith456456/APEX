# 🤖 IDS Bot v2.0 — Ignition Detection System

> Live 24/7 Binance Futures scanner that fires crypto pump/dump signals  
> to **Telegram** and **Discord** — before the blow-off move.

---

## What it does

- Connects to **Binance Futures WebSocket** (`fstream.binance.com` — non-geo-blocked)
- Scans **every active USDT-M perpetual** on every closed 5-minute candle
- Runs the **13-layer IDS pipeline** and scores each coin 0–100
- **Auto-detects new exchange listings** — universe refreshed every 10 minutes
- Fires an alert when `AI Score ≥ 72` **AND** `R:R ≥ 1:1`
- **Deduplicates signals** — same coin/direction suppressed until SL hit, all TPs hit, or direction flips
- Every alert includes all **11 signal fields** + live **stats block** (win rate, PNL, TP distribution)

---

## Signal Format — 11 Fields

| # | Field | Detail |
|---|-------|--------|
| ① | Coin Pair | e.g. `SOLUSDT` |
| ② | Entry Zone | Limit order band ±0.2% — never market |
| ③ | Position | `BUY / LONG` or `SELL / SHORT` |
| ④ | Leverage | Scalp 15× / Day 10× / Swing 5× |
| ⑤ | TP Targets | 5 levels — 30/25/20/15/10% front-loaded |
| ⑥ | Stop Loss | Behind structure, % from entry |
| ⑦ | Trade Type | Scalp / Day Trade / Swing |
| ⑧ | R:R | ≥1:1 gate, ≥1:6 = Elite |
| ⑨ | Timeframe | Signal detection timeframe |
| ⑩ | Expected Time | Time estimate to TP1 |
| ⑪ | Market Condition | Strong Bull / Normal / Choppy / Strong Bear / High Vol |

**Stats block** on every alert:
- Daily / Monthly / All-time **win rate** with bar graph
- Daily / Monthly / All-time **PNL** in R-multiples
- **Win/Loss count** per window
- **TP distribution** — mutually exclusive (TP2 = trades that ended at TP2 only)

---

## Project Structure

```
ids-bot/
├── main.py                  ← Entry point (run this)
├── Dockerfile               ← Container definition for Northflank
├── requirements.txt         ← Python dependencies
├── .env.example             ← Config template (copy → .env)
├── .gitignore
├── README.md
├── src/                     ← All application code (Python package)
│   ├── __init__.py
│   ├── config.py            ← Settings from environment variables
│   ├── logger.py            ← Structured logging (loguru)
│   ├── state.py             ← Signal deduplication state machine
│   ├── stats.py             ← Trade statistics + TP distribution
│   ├── pipeline.py          ← 13-layer IDS scoring engine
│   ├── scanner.py           ← Binance WebSocket + universe manager
│   ├── formatter.py         ← Alert message builder (Telegram + Discord)
│   ├── telegram_sender.py   ← Telegram channel sender
│   └── discord_sender.py    ← Discord embed sender
└── data/                    ← Runtime state — gitignored
    ├── signal_state.json    ← Dedup state (survives restarts)
    └── stats.json           ← Trade history (survives restarts)
```

---

## Local Setup

```bash
git clone https://github.com/YOUR_USERNAME/ids-bot.git
cd ids-bot

# Create virtual environment
python -m venv .venv
source .venv/bin/activate      # Windows: .venv\Scripts\activate

# Install dependencies
pip install -r requirements.txt

# Configure
cp .env.example .env
# Edit .env — add your Telegram + Discord tokens

# Run
python main.py
```

---

## Get Your Bot Tokens

### Telegram
1. Open Telegram → message **@BotFather** → `/newbot`
2. Copy the token it gives you → `TELEGRAM_BOT_TOKEN`
3. Create a channel, add your bot as **Admin** with "Post Messages" permission
4. Forward any message from your channel to **@userinfobot**
5. Copy the `id` value (starts with `-100`) → `TELEGRAM_CHANNEL_ID`

### Discord
1. Go to **https://discord.com/developers/applications**
2. **New Application** → give it a name → **Bot** tab → **Reset Token** → copy it → `DISCORD_BOT_TOKEN`
3. Under **Bot** → enable **Message Content Intent** (if prompted)
4. **OAuth2** → URL Generator → Scopes: `bot` → Permissions: `Send Messages`, `Embed Links`
5. Open the generated URL → add bot to your server
6. In Discord: **User Settings** → **Advanced** → enable **Developer Mode**
7. Right-click your channel → **Copy Channel ID** → `DISCORD_CHANNEL_ID`

---

## Deploy to Northflank (Free Sandbox — 24/7)

### Step 1 — Push to GitHub
```bash
git add .
git commit -m "feat: IDS Bot v2.0 initial deploy"
git push origin main
```

### Step 2 — Create Northflank account
→ https://northflank.com  (free tier available)

### Step 3 — New Project
Dashboard → **New Project** → name it `ids-bot`

### Step 4 — New Deployment Service
Inside your project → **Add Service** → **Deployment Service**
- **Source**: GitHub → select your `ids-bot` repo
- **Branch**: `main`
- **Build**: Dockerfile (auto-detected from root)
- **Plan**: `nf-compute-10` (free sandbox)

### Step 5 — Add Environment Variables
Service → **Environment** tab → **Add Variable** for each:

```
TELEGRAM_BOT_TOKEN     = <your token>
TELEGRAM_CHANNEL_ID    = <your channel id>
DISCORD_BOT_TOKEN      = <your token>
DISCORD_CHANNEL_ID     = <your channel id>
MIN_VOLUME_USDT        = 5000000
AI_SCORE_THRESHOLD     = 72
MIN_RR                 = 1.0
UNIVERSE_REFRESH_SECS  = 600
LOG_LEVEL              = INFO
```

### Step 6 — Deploy
Click **Deploy** → Northflank builds the Docker image and starts the container.

✅ The bot will:
- Auto-restart on any crash
- Reconnect WebSockets on disconnect
- Persist signal state and stats across restarts (data/ directory)
- Auto-detect new Binance listings every 10 minutes

---

## IDS Pipeline — 13 Layers

| Layer | Weight | What it checks |
|-------|--------|----------------|
| Market Regime | 8 | EMA 21/55/200 trend, RSI zone |
| Price Action | **14** | BOS/CHoCH, compression, conviction candle |
| Volume Analysis | 12 | Dry-up before move, explosion on break, CVD |
| **Liquidity Sweep** | **16** | Sweep + reclaim — smart money fingerprint |
| Order Flow | 12 | Wick absorption, aggression, delta |
| Open Interest | 8 | Volume momentum as OI proxy |
| Funding Rate | 6 | RSI crowding proxy (neutral = best fuel) |
| Liquidation Map | 10 | Prior-wick untapped pool |
| BTC Correlation | 6 | Macro alignment gate |
| R:R | ×multiplier | Applied as score multiplier (not additive) |

**AI Score ≥ 72 AND R:R ≥ 1:1 → signal fires**

---

## Environment Variables Reference

| Variable | Default | Description |
|----------|---------|-------------|
| `TELEGRAM_BOT_TOKEN` | — | Required for Telegram alerts |
| `TELEGRAM_CHANNEL_ID` | — | Target channel (e.g. `-100123456789`) |
| `DISCORD_BOT_TOKEN` | — | Required for Discord alerts |
| `DISCORD_CHANNEL_ID` | — | Target channel (integer ID) |
| `MIN_VOLUME_USDT` | `5000000` | Min 24h volume to scan a coin |
| `AI_SCORE_THRESHOLD` | `72` | Min score to fire signal |
| `MIN_RR` | `1.0` | Min R:R ratio (hard gate) |
| `CANDLE_LIMIT` | `200` | Candle history per symbol |
| `UNIVERSE_REFRESH_SECS` | `600` | New listing check interval |
| `LOG_LEVEL` | `INFO` | DEBUG / INFO / WARNING / ERROR |

---

## License
MIT — free to use, modify, and deploy.
