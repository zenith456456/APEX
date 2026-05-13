from discord import Webhook, RequestsWebhookAdapter
import requests
from telegram import Bot
import json
from typing import Dict

class Notifier:
    def __init__(self, config, stats_tracker):
        self.config = config
        self.stats = stats_tracker
        # Discord webhook (or use bot)
        self.discord_webhook_url = f"https://discord.com/api/webhooks/{config.DISCORD_CHANNEL_ID}/{config.DISCORD_TOKEN}"
        # Telegram bot
        if config.TELEGRAM_TOKEN and config.TELEGRAM_CHAT_ID:
            self.tg_bot = Bot(token=config.TELEGRAM_TOKEN)
            self.tg_chat_id = config.TELEGRAM_CHAT_ID
        else:
            self.tg_bot = None

    def format_signal_message(self, signal: Dict) -> str:
        # Build the appropriate message string
        trade_id = signal["trade_id"]
        sym = signal["symbol"]
        direction_emoji = "🔴 SHORT" if signal["direction"] == "SHORT" else "🟢 LONG"
        entry = f"${signal['entry_min']:.4f} – ${signal['entry_max']:.4f}"
        targets = "\n".join(
            [f"TP{i+1} ({t['pct']}%): ${t['price']:.4f} → RR 1:{self._calc_rr(signal, i):.1f}"
             for i, t in enumerate(signal["targets"])]
        )
        sl = f"${signal['stop_loss']:.4f}"
        trade_type = signal.get("type","Day Trade")
        market = signal.get("market_condition","Normal")
        expected = signal.get("expected_time_min",0)
        if expected < 60:
            expected_str = f"{expected} min"
        else:
            expected_str = f"{expected//60}h {expected%60}m"

        # Stats
        daily = self.stats.get_daily_stats()
        monthly = self.stats.get_monthly_stats()
        alltime = self.stats.get_alltime_stats()
        precision = self.stats.get_precision_histogram()
        prec_lines = []
        for tp_num in sorted(precision.keys(), reverse=True):
            prec_lines.append(f"max TP{tp_num} only : {precision[tp_num]} signals")
        precision_str = "\n".join(prec_lines)

        msg = f"""
**CSM OMEGA TRIGGER – PROMETHEUS UNBOUND**
# **Trade #{trade_id}**

**1. Coin Pair:** {sym}
**2. Entry Zone (Limit Order):** {entry}
**3. Position:** {direction_emoji}
**4. Leverage:** {signal['leverage']}x Isolated
**5. Take Profit Targets:**
{targets}
**6. Stop Loss:** {sl}
**7. Trade Type:** {trade_type}
**8. Weighted Avg R:R:** 1:{signal['rr_weighted']}
**9. Expected Time:** {expected_str}
**10. Market Condition:** {market}
────────────────────────
**SYSTEM STATE – LIVE TRACK RECORD**