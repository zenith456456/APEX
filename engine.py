import uuid
from datetime import datetime, timezone
import numpy as np
from indicators import atr, bos, condition, fingerprint, rvol, sweep, trend
from models import Direction, Score, Signal


class SignalEngine:
    def __init__(self, s, news):
        self.s = s
        self.news = news

    @staticmethod
    def _pct(a, b):
        return (a / b - 1.0) * 100.0 if b else 0.0

    def analyze(self, m, btc):
        # Primary setup: 15m, confirmed by 5m and 1h.
        rows15 = m.klines.get('15m', [])
        rows5 = m.klines.get('5m', [])
        rows1h = m.klines.get('1h', [])
        if len(rows15) < 80 or len(rows5) < 80 or len(rows1h) < 60 or m.last <= 0:
            return None

        a15 = np.asarray(rows15, float)
        h, l, c, v = a15[:, 2], a15[:, 3], a15[:, 4], a15[:, 5]
        a5 = np.asarray(rows5, float)
        c5, v5 = a5[:, 4], a5[:, 5]
        a1h = np.asarray(rows1h, float)
        c1h = a1h[:, 4]

        tr15 = trend(c)
        tr5 = trend(c5)
        tr1h = trend(c1h)
        if tr15 == 0 or tr5 == 0 or tr15 != tr5:
            return None

        direction = Direction.LONG if tr15 > 0 else Direction.SHORT
        cond = condition(c)

        # Do not score an opposing regime as bullish/bearish support.
        regime_ok = (direction == Direction.LONG and cond in ('STRONG BULL', 'NORMAL MARKET', 'HIGH VOLATILITY')) or \
                    (direction == Direction.SHORT and cond in ('STRONG BEAR', 'NORMAL MARKET', 'HIGH VOLATILITY'))
        if not regime_ok:
            return None
        if cond == 'CHOPPY / SIDEWAYS':
            return None

        bscore, breason = bos(h, l, c)
        sscore, sreason = sweep(h, l, c)
        rv15 = rvol(v)
        rv5 = rvol(v5)

        # Momentum: the scanner should preferentially find coins actually moving.
        mom5 = self._pct(c5[-1], c5[-4])
        mom15 = self._pct(c[-1], c[-4])
        signed_mom5 = mom5 if direction == Direction.LONG else -mom5
        signed_mom15 = mom15 if direction == Direction.LONG else -mom15
        if signed_mom5 < 0.30 or signed_mom15 < 0.50:
            return None

        # 24h mover confirmation; not mandatory by itself, but gives priority to coins
        # appearing in the Gainers/Losers universe.
        mover = abs(m.change_pct) >= self.s.min_mover_24h_pct

        vscore = 15 if rv5 >= 2.2 and rv15 >= 1.5 else 12 if rv5 >= 1.6 else 9 if rv5 >= 1.25 else 4
        trscore = 10 if tr1h in (0, tr15) else 3

        # Recent aggressive order-flow pressure.
        of_ratio = m.buy_qty / max(m.sell_qty, 1e-9)
        of_dir = 1 if of_ratio > 1.12 else -1 if of_ratio < 0.89 else 0
        if of_dir and of_dir != tr15:
            return None
        book_ratio = m.bid_qty / max(m.ask_qty, 1e-9)
        book_dir = 1 if book_ratio > 1.12 else -1 if book_ratio < 0.89 else 0
        if book_dir and book_dir != tr15:
            return None
        ofscore = 10 if of_dir == tr15 and book_dir == tr15 else 8 if of_dir == tr15 or book_dir == tr15 else 4

        oiscore = 5 if m.oi > 0 else 1
        # Funding is a context signal, never a reason to create a trade by itself.
        fscore = 5 if abs(m.funding) < 0.0008 else 3 if abs(m.funding) < 0.0018 else 1

        btcscore = 0
        if btc and len(btc.klines.get('15m', [])) >= 80:
            bc = np.asarray(btc.klines['15m'], float)[:, 4]
            bt = trend(bc)
            btcscore = 3 if bt == tr15 else 2 if bt == 0 else 0
            if bt and bt != tr15:
                return None

        if self.news.conflict(m.symbol):
            return None

        # Direction-aware regime score.
        mascore = 10 if (
            (direction == Direction.LONG and cond == 'STRONG BULL') or
            (direction == Direction.SHORT and cond == 'STRONG BEAR')
        ) else 8 if cond == 'NORMAL MARKET' else 6

        # Price action score must be earned; absence of BOS is not a bonus.
        candle_body = abs(c[-1] - a15[-1, 1])
        atr15 = atr(h, l, c)
        body_ratio = candle_body / max(atr15, 1e-9)
        pa = 8 if bscore == 20 else 3
        pa += 6 if body_ratio >= 0.7 else 3 if body_ratio >= 0.45 else 0
        pa += 5 if signed_mom15 >= 1.2 else 3 if signed_mom15 >= 0.8 else 0
        pascore = min(20, pa)

        # Sweep is useful, but continuation setups may not have one.
        if sscore == 10:
            sweep_score = 10
        elif mover and signed_mom5 >= 0.8:
            sweep_score = 7
        else:
            sweep_score = 2

        # Order block / FVG proxy based on impulse candle and retracement location.
        last_range = float(a5[-2, 2] - a5[-2, 3])
        impulse = float(a5[-2, 4] - a5[-2, 1])
        obscore = 10 if abs(impulse) >= 0.8 * max(atr(h, l, c), 1e-9) else 7 if abs(impulse) >= 0.45 * max(atr(h, l, c), 1e-9) else 3

        news_score = 2
        total_score = Score(mascore, pascore, vscore, trscore, sweep_score, obscore, ofscore, oiscore, fscore, btcscore, news_score)
        total = total_score.total
        if total < self.s.score_threshold or total > 100:
            return None

        # Build an actionable LIMIT zone from the most recent impulse leg, not a generic
        # half-ATR pullback from current price.
        recent = a5[-8:]
        swing_high = float(np.max(recent[:, 2]))
        swing_low = float(np.min(recent[:, 3]))
        leg = swing_high - swing_low
        if leg <= 0:
            return None

        if direction == Direction.LONG:
            zone_low = swing_high - 0.55 * leg
            zone_high = swing_high - 0.35 * leg
            # A long limit entry must be below current price.
            if zone_low >= m.last:
                return None
            entry_low, entry_high = zone_low, min(zone_high, m.last * 0.9995)
            structural_low = min(float(np.min(recent[:, 3])), float(np.min(a15[-8:, 3])))
            stop = structural_low - 0.15 * atr15
            risk = entry_high - stop
            if risk <= 0 or (m.last - entry_high) / max(m.last, 1e-9) > 0.025:
                return None
            tps = [entry_high + risk * 3.0, entry_high + risk * 4.0, entry_high + risk * 5.0]
        else:
            zone_low = swing_low + 0.35 * leg
            zone_high = swing_low + 0.55 * leg
            if zone_high <= m.last:
                return None
            entry_low, entry_high = max(zone_low, m.last * 1.0005), zone_high
            structural_high = max(float(np.max(recent[:, 2])), float(np.max(a15[-8:, 2])))
            stop = structural_high + 0.15 * atr15
            risk = stop - entry_low
            if risk <= 0 or (entry_low - m.last) / max(m.last, 1e-9) > 0.025:
                return None
            tps = [entry_low - risk * 3.0, entry_low - risk * 4.0, entry_low - risk * 5.0]

        rr = abs(tps[-1] - ((entry_low + entry_high) / 2.0)) / max(risk, 1e-9)
        if rr < self.s.min_rr:
            return None

        fp = fingerprint(m.symbol, direction.value, '15m', c)
        reasons = []
        if direction == Direction.LONG:
            reasons.append('Bullish momentum regime confirmed')
        else:
            reasons.append('Bearish momentum regime confirmed')
        if bscore == 20:
            reasons.append(breason)
        if rv5 >= 1.6:
            reasons.append(f'Strong 5M RVOL ({rv5:.2f}x)')
        else:
            reasons.append(f'5M volume expansion ({rv5:.2f}x)')
        reasons.append(f'5M momentum {mom5:+.2f}% / 15M momentum {mom15:+.2f}%')
        if abs(m.change_pct) >= self.s.min_mover_24h_pct:
            reasons.append(f'24H mover confirmed ({m.change_pct:+.2f}%)')
        if sreason:
            reasons.append(sreason)
        reasons.append('Impulse retracement LIMIT zone')
        reasons.append('Order-flow/book pressure aligned')
        reasons.append('BTC context aligned' if btcscore == 3 else 'BTC context neutral')
        reasons.append('No detected high-impact news conflict')

        volatility = atr15 / c[-1]
        trade = 'SCALP' if volatility > 0.018 else 'DAY TRADE' if volatility > 0.008 else 'SWING'
        lev = {'SCALP': self.s.scalp_leverage, 'DAY TRADE': self.s.day_leverage, 'SWING': self.s.swing_leverage}.get(trade, 2)
        holding = {'SCALP': '15–90 Minutes', 'DAY TRADE': '2–12 Hours', 'SWING': '1–5 Days'}[trade]
        valid = {'SCALP': '30 Minutes', 'DAY TRADE': '2 Hours', 'SWING': '12 Hours'}[trade]
        rnd = lambda x: round(float(x), 8) if x < 1 else round(float(x), 4) if x < 100 else round(float(x), 1)

        return Signal(
            str(uuid.uuid4()), 0, m.symbol, direction, trade, cond, '15M', '5M', '1H',
            rnd(entry_low), rnd(entry_high), rnd(stop), [rnd(x) for x in tps], lev, rr,
            holding, valid, total, reasons, fp, datetime.now(timezone.utc).isoformat(), total_score
        )
