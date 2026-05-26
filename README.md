# ⚡ APEX-QUANT Signal Bot v4.0

> 24/7 crypto scalp signals · Binance WebSocket · Telegram + Discord · Auto new-listing detection

---

## 🚀 Quick Deploy (Northflank)

### Step 1 — Create your Telegram bot

```
1. Open Telegram → search @BotFather → /start
2. Send: /newbot
3. Choose a name: e.g.  APEX Quant Bot
4. Choose a username: e.g.  apexquant_signals_bot
5. BotFather replies with your token:
   123456789:ABCdefGHIjklMNOpqrSTUvwxYZ
   ← COPY THIS  (this is your TELEGRAM_BOT_TOKEN)
```

### Step 2 — Get your Telegram Chat ID

```
For a GROUP:
  1. Create a group or use existing one
  2. Add your bot to the group as admin
  3. Add @userinfobot to the group
  4. It replies with: Chat ID: -1001234567890
     ← COPY THIS  (this is your TELEGRAM_CHAT_ID)

For a CHANNEL:
  1. Create a channel
  2. Add your bot as admin (can post messages)
  3. Forward any message from the channel to @userinfobot
  4. It replies with the channel ID
```

### Step 3 — Create your Discord webhook

```
1. Open Discord → go to your server
2. Click the channel you want signals in → Edit Channel (⚙️)
3. Integrations → Webhooks → New Webhook
4. Name it: APEX-QUANT
5. Click "Copy Webhook URL"
   https://discord.com/api/webhooks/XXXXXXXXXX/XXXX...
   ← COPY THIS  (this is your DISCORD_WEBHOOK_URL)
```

### Step 4 — Push to GitHub

```bash
git clone https://github.com/YOUR_USERNAME/apex-quant-bot.git
cd apex-quant-bot
# copy all project files here, then:
git add .
git commit -m "Initial APEX-QUANT deploy"
git push origin main
```

### Step 5 — Deploy on Northflank

```
1. Go to  northflank.com  → Log in → New Project → "apex-quant"

2. New Service → Deployment Service
   Source:  GitHub → select your repo → branch: main
   Build:   Dockerfile

3. ⚠️  CRITICAL: Set Environment Variables
   Go to: Service → Environment → Add Variable

   Add these 3 variables EXACTLY as shown:

   ┌─────────────────────────┬──────────────────────────────────────┐
   │ Key                     │ Value                                │
   ├─────────────────────────┼──────────────────────────────────────┤
   │ TELEGRAM_BOT_TOKEN      │ 123456789:ABCdefGHI...  (your token) │
   │ TELEGRAM_CHAT_ID        │ -1001234567890  (your chat id)       │
   │ DISCORD_WEBHOOK_URL     │ https://discord.com/api/webhooks/... │
   └─────────────────────────┴──────────────────────────────────────┘

4. Port → Add Port:  8080  (HTTP, public)

5. Click Deploy

6. Watch logs → you should see:
   ✅ All required env vars present — starting scanner
   ✅ Bot ONLINE message in Telegram + Discord within 30 seconds
```

---

## 🔍 Troubleshooting

### "Telegram not configured — skipping"

The `TELEGRAM_BOT_TOKEN` or `TELEGRAM_CHAT_ID` env var is missing or empty.

**Check in Northflank:**
```
Service → Environment → verify both variables exist and have values
(no spaces, no quotes around the value)
```

### "Discord webhook not configured — skipping"

The `DISCORD_WEBHOOK_URL` env var is missing or empty.

**Check in Northflank:**
```
Service → Environment → verify DISCORD_WEBHOOK_URL exists
Value must start with: https://discord.com/api/webhooks/
```

### "Telegram 401 Unauthorized"

Bot token is wrong. Re-copy from @BotFather and update the env var.

### "Telegram 400 — chat not found"

Bot is not added to the group/channel. Add it as an **admin** with "Post Messages" permission.

### Test locally before deploying

```bash
cp .env.example .env
# edit .env with your real values
python check_config.py
# shows ✅ or ❌ for every setting and sends a test message
```

---

## Environment Variables

| Variable | Required | Default | Description |
|---|---|---|---|
| `TELEGRAM_BOT_TOKEN` | ✅ | — | From @BotFather |
| `TELEGRAM_CHAT_ID` | ✅ | — | Group/channel numeric ID |
| `DISCORD_WEBHOOK_URL` | ✅ | — | From Discord → Integrations → Webhooks |
| `SCAN_TIMEFRAMES` | ❌ | `1m,3m,5m` | Timeframes to scan |
| `MIN_VOLUME_USDT` | ❌ | `5000000` | Min 24h volume ($5M) |
| `MIN_CSS_SCORE` | ❌ | `75` | Min signal quality score |
| `MAX_PAIRS` | ❌ | `30` | Max pairs to track |
| `SIGNAL_COOLDOWN_MINUTES` | ❌ | `5` | Cooldown per pair |
| `VPI_MIN_ABS` | ❌ | `20` | VPI filter threshold |
| `FDI_MAX` | ❌ | `1.60` | FDI choppy-market filter |
| `PORT` | ❌ | `8080` | Health check port |
| `LOG_LEVEL` | ❌ | `INFO` | INFO / DEBUG / WARNING |

---

## Signal Format (all 11 fields)

```
⚡ APEX-QUANT SIGNAL  #42
━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━
① Coin Pair      :  BTCUSDT
② Entry Zone     :  67,180.00 – 67,260.00  📌 LIMIT ORDER
③ Position       :  🟢 LONG  ▲
④ Leverage       :  10×
⑥ Stop Loss      :  🛑 66,940.00
⑤ Take Profits   :
  ✅ TP1 (1:1.0)  →  67,420.00
  ✅ TP2 (1:2.0)  →  67,640.00
  ✅ TP3 (1:3.0)  →  67,980.00  ⭐
  ✅ TP4 (1:4.5)  →  68,250.00
  ✅ TP5 (1:6.0)  →  68,600.00  🔥
⑦ Trade Type     :  SCALP
⑧ Best R:R       :  1:6.0
⑨ Timeframe      :  5M
⑩ Expected Time  :  ⏳ 15–25 min
⑪ Market         :  🚀 STRONG BULL
━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━
Win Rate  Day: 95% │ Month: 97% │ Total: 97.8%
PNL       Day: +12R │ Month: +184R │ Total: +2840R
W/L       41W / 1L  (#42 signals)
━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━
⚠️  Not financial advice  |  APEX-QUANT
```

---

⚠️ **Not financial advice. For educational and research purposes only.**
