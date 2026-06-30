# ─── broadcaster.py ────────────────────────────────────────────────────────
# APEX Signal Bot — Message Formatter + Multi-Channel Dispatcher
# Builds the 11-field signal text + stats footer, sends to Telegram + Discord

import logging
from typing import Optional

logger = logging.getLogger("APEX.Broadcaster")

CONDITION_EMOJI = {
    "Strong Bull":       "🚀",
    "Normal Bull":       "📈",
    "Normal Bear":       "📉",
    "Strong Bear":       "🔻",
    "Choppy / Sideways": "↔️",
    "High Volatility":   "⚡",
}

TP_ALLOC = ["25%", "20%", "20%", "20%", "15%"]


class Broadcaster:
    """Formats SignalState + stats into text and dispatches to all channels."""

    def __init__(self, telegram_bot=None, discord_bot=None):
        self.telegram_bot = telegram_bot
        self.discord_bot  = discord_bot

    # ── Build the full message ──────────────────────────────────────────────
    def format_message(self, state, stats: dict, reason: str) -> str:
        emoji = CONDITION_EMOJI.get(state.condition, "📊")

        tp_lines = "\n".join(
            f"   TP{i+1}: {tp:.8g}  →  R:R 1:{[1.4,2.5,3.8,5.3,7.1][i]}  ({TP_ALLOC[i]})"
            for i, tp in enumerate(state.take_profits)
        )

        tp_breakdown_parts = []
        for n in range(1, 6):
            c = stats["tp_counts"].get(f"TP{n}", 0)
            if c > 0:
                tp_breakdown_parts.append(f"TP{n} only: {c}")
        tp_breakdown_str = "  |  ".join(tp_breakdown_parts) if tp_breakdown_parts else "—"

        msg = (
            f"◈ APEX SIGNAL  #{stats['trade_number']}\n"
            f"━━━━━━━━━━━━━━━━━━━━━━━━━━\n"
            f"🪙 {state.pair}   {state.direction}   {state.trade_type}   {state.leverage}×\n\n"
            f"🎯 ENTRY ZONE (Limit Orders)\n"
            f"   Entry 1: {state.entry[0]:.8g}\n"
            f"   Entry 2: {state.entry[1]:.8g}\n\n"
            f"✅ TAKE PROFIT TARGETS\n"
            f"{tp_lines}\n\n"
            f"🛑 STOP LOSS   {state.stop_loss:.8g}\n"
            f"🕐 Signal TF: {state.timeframe}\n"
            f"📐 Pattern: {state.pattern}\n"
            f"⏱ Trade Type: {state.trade_type}\n"
            f"{emoji} Market Condition: {state.condition}\n"
            f"🔢 MTCS Score: {state.mtcs_score}/100\n"
            f"━━━━━━━━━━━━━━━━━━━━━━━━━━\n"
            f"📊 PERFORMANCE STATS\n"
            f"Daily:   WR {stats['daily']['wr']}%   |   PNL {stats['daily']['pnl']:+.2f}%\n"
            f"Monthly: WR {stats['monthly']['wr']}%   |   PNL {stats['monthly']['pnl']:+.2f}%\n"
            f"Total:   WR {stats['total']['wr']}%   |   PNL {stats['total']['pnl']:+.2f}%\n\n"
            f"🏆 W / L:  {stats['total']['wins']} Wins  /  {stats['total']['losses']} Losses\n\n"
            f"🎯 TP Breakdown (highest TP per signal):\n"
            f"{tp_breakdown_str}\n"
            f"🛑 SL Hit: {stats['sl_count']}\n"
            f"━━━━━━━━━━━━━━━━━━━━━━━━━━\n"
            f"⚠️ Not financial advice · Always use stop-loss · Trade at your own risk"
        )
        return msg

    # ── Dispatch ──────────────────────────────────────────────────────────
    async def send_signal(self, state, stats: dict, reason: str = ""):
        text = self.format_message(state, stats, reason)
        logger.info(f"Broadcasting signal [{state.signal_id}] {state.pair} {state.direction} | reason={reason}")

        if self.telegram_bot:
            try:
                await self.telegram_bot.send_message(text)
            except Exception as e:
                logger.error(f"Telegram send failed: {e}")

        if self.discord_bot:
            try:
                await self.discord_bot.send_message(text)
            except Exception as e:
                logger.error(f"Discord send failed: {e}")

        if not self.telegram_bot and not self.discord_bot:
            logger.warning("No broadcast channels configured — signal logged only")
            print(text)
