# Binance 24/7 Momentum Signal Scanner

This version is designed to fix the failure mode where the bot produces many weak limit-entry signals while Binance's strongest gainers/losers continue to make large moves.

## Strategy changes

1. Candidate universe is now dual-source:
   - high-liquidity USDT perpetuals
   - top 24h gainers
   - top 24h losers

2. Signal confirmation is multi-timeframe:
   - 5M trend
   - 15M trend
   - 1H context

3. Momentum is required before a signal can pass:
   - 5M directional momentum
   - 15M directional momentum
   - volume expansion / RVOL

4. Price-action scoring no longer awards points merely because BOS is absent.

5. Entry is a genuine LIMIT pullback zone based on the latest 5M impulse leg, instead of a generic half-ATR offset.

6. Structural stop is based on the recent swing/impulse structure.

7. Opposing order flow/book pressure rejects the setup.

8. Opposing BTC trend rejects the setup.

9. Existing signal-state protection remains active:
   - same symbol + same direction + active previous signal => block
   - direction change => close old signal as DIRECTION_CHANGED and allow the new one
   - TP/SL states remain persistent in SQLite

## Important signal-quality note

This is still a rules-based scanner, not a guarantee of future TP3/TP5 outcomes. Binance's Gainers/Losers page is a momentum ranking, so this scanner now explicitly includes momentum candidates instead of using only quote-volume ranking.

The bot is signal-only. It does not place Binance orders.

## Northflank

Recommended environment:

```text
PORT=8080
MAX_SYMBOLS=100
WS_SYMBOLS_PER_CONNECTION=10
MIN_24H_QUOTE_VOLUME=5000000
MIN_MOVER_24H_PCT=2.0
MOVER_SLOTS=50
VOLUME_SLOTS=75
SCORE_THRESHOLD=90
MIN_RR=3
```

No inbound Binance port is needed. Port 8080 is only for the optional `/health` endpoint.

## Git

```bash
git add .
git commit -m "Improve momentum scanner and signal quality"
git push origin main
```
