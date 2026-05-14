from discord import Webhook, RequestsWebhookAdapter
from telegram import Bot
from typing import Dict

class Notifier:
    def __init__(self, config, stats_tracker):
        self.config = config
        self.stats = stats_tracker
        # Discord webhook
        self.discord_webhook_url = (
            f"https://discord.com/api/webhooks/"
            f"{config.DISCORD_CHANNEL_ID}/{config.DISCORD_TOKEN}"
        )
        # Telegram bot
        if config.TELEGRAM_TOKEN and config.TELEGRAM_CHAT_ID:
            self.tg_bot = Bot(token=config.TELEGRAM_TOKEN)
            self.tg_chat_id = config.TELEGRAM_CHAT_ID
        else:
            self.tg_bot = None

    def format_signal_message(self, signal: Dict) -> str:
        trade_id = signal["trade_id"]
        sym = signal["symbol"]
        direction_emoji = "🔴 SHORT" if signal["direction"] == "SHORT" else "🟢 LONG"
        entry = f"${signal['entry_min']:.4f} – ${signal['entry_max']:.4f}"

        targets_lines = []
        for i, t in enumerate(signal["targets"]):
            rr = self._calc_rr(signal, i)
            targets_lines.append(
                f"TP{i+1} ({t['pct']}%): ${t['price']:.4f} → RR 1:{rr:.1f}"
            )
        targets_str = "\n".join(targets_lines)

        sl = f"${signal['stop_loss']:.4f}"
        trade_type = signal.get("type", "Day Trade")
        market = signal.get("market_condition", "Normal")
        expected = signal.get("expected_time_min", 0)
        if expected < 60:
            expected_str = f"{expected} min"
        else:
            expected_str = f"{expected // 60}h {expected % 60}m"

        daily = self.stats.get_daily_stats()
        monthly = self.stats.get_monthly_stats()
        alltime = self.stats.get_alltime_stats()
        precision = self.stats.get_precision_histogram()

        prec_lines = []
        for tp_num in sorted(precision.keys(), reverse=True):
            prec_lines.append(f"max TP{tp_num} only : {precision[tp_num]} signals")
        precision_str = "\n".join(prec_lines) if prec_lines else "No data"

        # Build the final message using a single f-string with correct closure
        msg = (
            f"**CSM OMEGA TRIGGER – PROMETHEUS UNBOUND**\n"
            f"# **Trade #{trade_id}**\n\n"
            f"**1. Coin Pair:** {sym}\n"
            f"**2. Entry Zone (Limit Order):** {entry}\n"
            f"**3. Position:** {direction_emoji}\n"
            f"**4. Leverage:** {signal['leverage']}x Isolated\n"
            f"**5. Take Profit Targets:**\n{targets_str}\n"
            f"**6. Stop Loss:** {sl}\n"
            f"**7. Trade Type:** {trade_type}\n"
            f"**8. Weighted Avg R:R:** 1:{signal['rr_weighted']}\n"
            f"**9. Expected Time:** {expected_str}\n"
            f"**10. Market Condition:** {market}\n"
            f"────────────────────────\n"
            f"**SYSTEM STATE – LIVE TRACK RECORD**\n"
            f"```\n"
            f"┌──────────────────────────┐\n"
            f"│ TODAY       Win Rate: {daily['wr']}% │ PnL: {daily['pnl']}R  │\n"
            f"│ Wins: {daily['wins']} / Losses: {daily['losses']}\n"
            f"├──────────────────────────┤\n"
            f"│ THIS MONTH  Win Rate: {monthly['wr']}% │ PnL: {monthly['pnl']}R │\n"
            f"│ Wins: {monthly['wins']} / Losses: {monthly['losses']}\n"
            f"├──────────────────────────┤\n"
            f"│ ALL-TIME    Win Rate: {alltime['wr']}% │ PnL: {alltime['pnl']}R│\n"
            f"│ Wins: {alltime['wins']} / Losses: {alltime['losses']}\n"
            f"└──────────────────────────┘\n"
            f"```\n"
            f"🔬 TAKE-PROFIT PRECISION (closed trades only)\n"
            f"{precision_str}"
        )
        return msg

    def _calc_rr(self, signal, idx):
        entry = (signal["entry_min"] + signal["entry_max"]) / 2
        risk = abs(entry - signal["stop_loss"])
        tp_price = signal["targets"][idx]["price"]
        reward = abs(tp_price - entry)
        return reward / risk if risk > 0 else 0

    async def send_discord(self, message: str):
        webhook = Webhook.from_url(
            self.discord_webhook_url,
            adapter=RequestsWebhookAdapter()
        )
        webhook.send(message, username="CSM Oracle")

    async def send_telegram(self, message: str):
        if self.tg_bot:
            await self.tg_bot.send_message(
                chat_id=self.tg_chat_id,
                text=message[:4096]
            )

    async def broadcast(self, signal: Dict):
        msg = self.format_signal_message(signal)
        await self.send_discord(msg)
        if self.tg_bot:
            await self.send_telegram(msg)