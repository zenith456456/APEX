"""
check_config.py — Run this BEFORE deploying to verify all credentials work.

Usage:
    python check_config.py

Tests:
  • All required env vars are present
  • Telegram bot token is valid
  • Telegram chat ID accepts messages
  • Discord webhook URL is valid and accepts messages
  • Binance REST is reachable
"""
import asyncio
import os
import sys
import aiohttp
from dotenv import load_dotenv

load_dotenv()

PASS  = "  ✅"
FAIL  = "  ❌"
WARN  = "  ⚠️ "
SEP   = "─" * 50


async def check_all():
    print("\n⚡ APEX-QUANT CONFIG CHECKER")
    print(SEP)

    errors = 0

    # ── 1. Required env vars ──────────────────────────────────────
    print("\n[1] Required Environment Variables")
    required = {
        "TELEGRAM_BOT_TOKEN": os.getenv("TELEGRAM_BOT_TOKEN", ""),
        "TELEGRAM_CHAT_ID":   os.getenv("TELEGRAM_CHAT_ID", ""),
        "DISCORD_WEBHOOK_URL":os.getenv("DISCORD_WEBHOOK_URL", ""),
    }
    optional = {
        "SCAN_TIMEFRAMES":        os.getenv("SCAN_TIMEFRAMES", "1m,3m,5m (default)"),
        "MIN_VOLUME_USDT":        os.getenv("MIN_VOLUME_USDT", "5000000 (default)"),
        "MIN_CSS_SCORE":          os.getenv("MIN_CSS_SCORE", "75 (default)"),
        "MAX_PAIRS":              os.getenv("MAX_PAIRS", "30 (default)"),
        "SIGNAL_COOLDOWN_MINUTES":os.getenv("SIGNAL_COOLDOWN_MINUTES", "5 (default)"),
    }

    for key, val in required.items():
        if val:
            masked = val[:6] + "…" + val[-4:] if len(val) > 12 else "***"
            print(f"{PASS} {key} = {masked}")
        else:
            print(f"{FAIL} {key} — NOT SET")
            errors += 1

    print()
    for key, val in optional.items():
        print(f"  ℹ️  {key} = {val}")

    if errors:
        print(f"\n{FAIL} {errors} required variable(s) missing. "
              "Set them in Northflank → Service → Environment before deploying.\n")

    # ── 2. Telegram test ──────────────────────────────────────────
    print(f"\n{SEP}\n[2] Telegram Connection Test")
    tg_token = os.getenv("TELEGRAM_BOT_TOKEN", "")
    tg_chat  = os.getenv("TELEGRAM_CHAT_ID", "")

    if not tg_token or not tg_chat:
        print(f"{FAIL} Skipped — token or chat ID missing")
    else:
        try:
            async with aiohttp.ClientSession() as sess:
                # First verify the bot token
                async with sess.get(
                    f"https://api.telegram.org/bot{tg_token}/getMe",
                    timeout=aiohttp.ClientTimeout(total=10)
                ) as r:
                    data = await r.json()
                    if r.status == 200 and data.get("ok"):
                        bot_name = data["result"].get("username", "?")
                        print(f"{PASS} Bot token valid  →  @{bot_name}")
                    else:
                        print(f"{FAIL} Bot token invalid: {data.get('description','')}")
                        errors += 1

                # Send a test message
                async with sess.post(
                    f"https://api.telegram.org/bot{tg_token}/sendMessage",
                    json={"chat_id": tg_chat,
                          "text": "✅ APEX-QUANT config test — Telegram is working!"},
                    timeout=aiohttp.ClientTimeout(total=10)
                ) as r:
                    data = await r.json()
                    if r.status == 200 and data.get("ok"):
                        print(f"{PASS} Test message sent to chat {tg_chat}")
                    else:
                        desc = data.get("description", "")
                        print(f"{FAIL} Could not send to chat {tg_chat}: {desc}")
                        if "chat not found" in desc.lower():
                            print("      → Bot must be added to the group/channel as an admin")
                            print("      → For a channel, forward the channel link to @userinfobot")
                        errors += 1
        except Exception as exc:
            print(f"{FAIL} Telegram connection failed: {exc}")
            errors += 1

    # ── 3. Discord test ───────────────────────────────────────────
    print(f"\n{SEP}\n[3] Discord Webhook Test")
    dc_url = os.getenv("DISCORD_WEBHOOK_URL", "")

    if not dc_url:
        print(f"{FAIL} Skipped — DISCORD_WEBHOOK_URL not set")
    elif not dc_url.startswith("https://discord.com/api/webhooks/"):
        print(f"{FAIL} URL format wrong: {dc_url[:50]}")
        print("      → Must start with: https://discord.com/api/webhooks/")
        errors += 1
    else:
        try:
            async with aiohttp.ClientSession() as sess:
                payload = {"content": "✅ APEX-QUANT config test — Discord is working!"}
                async with sess.post(
                    dc_url, json=payload,
                    timeout=aiohttp.ClientTimeout(total=10)
                ) as r:
                    if r.status in (200, 204):
                        print(f"{PASS} Discord webhook works — test message sent")
                    elif r.status == 401:
                        print(f"{FAIL} Discord 401 — webhook URL is invalid or deleted")
                        errors += 1
                    elif r.status == 404:
                        print(f"{FAIL} Discord 404 — webhook not found (re-create it)")
                        errors += 1
                    else:
                        body = await r.text()
                        print(f"{FAIL} Discord HTTP {r.status}: {body[:100]}")
                        errors += 1
        except Exception as exc:
            print(f"{FAIL} Discord connection failed: {exc}")
            errors += 1

    # ── 4. Binance REST test ──────────────────────────────────────
    print(f"\n{SEP}\n[4] Binance REST Connectivity Test")
    try:
        async with aiohttp.ClientSession() as sess:
            async with sess.get(
                "https://api.binance.com/api/v3/ping",
                timeout=aiohttp.ClientTimeout(total=10)
            ) as r:
                if r.status == 200:
                    print(f"{PASS} Binance REST reachable (api.binance.com)")
                else:
                    print(f"{WARN} api.binance.com returned {r.status} — trying fallback")
                    # Try port-443 fallback
                    async with sess.get(
                        "https://api1.binance.com/api/v3/ping",
                        timeout=aiohttp.ClientTimeout(total=10)
                    ) as r2:
                        if r2.status == 200:
                            print(f"{PASS} Binance fallback (api1.binance.com) reachable")
                        else:
                            print(f"{FAIL} Both Binance endpoints unreachable")
                            errors += 1
    except Exception as exc:
        print(f"{FAIL} Binance connection failed: {exc}")
        errors += 1

    # ── Summary ───────────────────────────────────────────────────
    print(f"\n{SEP}")
    if errors == 0:
        print("✅ ALL CHECKS PASSED — safe to deploy\n")
    else:
        print(f"❌ {errors} CHECK(S) FAILED\n")
        print("Fix the issues above, then re-run:  python check_config.py\n")
    return errors


if __name__ == "__main__":
    errors = asyncio.run(check_all())
    sys.exit(1 if errors else 0)
