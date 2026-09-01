import aiohttp

def fmt(s,stats):
    icon='🟢' if s.direction.value=='LONG' else '🔴'
    r='\n'.join('✓ '+x for x in s.reasons)
    t='\n'.join(f'Take Profit {i}: {p}' for i,p in enumerate(s.take_profits,1))
    d,m,a=stats['daily'],stats['monthly'],stats['total']
    return f'''#{s.trade_number:04d}\n\n{icon} {s.direction.value} — APPROVED\n\nCoin Pair: {s.symbol}\nPosition: {s.direction.value}\nTrade Type: {s.trade_type}\nMarket Condition: {s.market_condition}\nSignal Timeframe: {s.signal_timeframe}\nConfirmation TF: {s.confirmation_timeframe}\nHigher TF Context: {s.higher_timeframe}\n\nEntry Type: LIMIT ORDER\nEntry Zone: {s.entry_low} – {s.entry_high}\nLeverage: {s.leverage}X ISOLATED\nStop Loss: {s.stop_loss}\n{t}\nRisk : Reward: 1 : {s.rr:.2f}\nExpected Time: {s.expected_holding}\nEntry Validity: {s.entry_validity}\nConfidence: {s.confidence:.0f}/100\n\nSetup Validation\n{r}\n\nStatus: 🟢 APPROVED\n\n━━━━━━━━━━━━━━━━━━━━\n📊 PERFORMANCE\n━━━━━━━━━━━━━━━━━━━━\nWin Rate — Today: {d['win_rate']:.2f}% | Month: {m['win_rate']:.2f}% | Total: {a['win_rate']:.2f}%\nModel PNL (R) — Today: {d['pnl_r']:+.2f}R | Month: {m['pnl_r']:+.2f}R | Total: {a['pnl_r']:+.2f}R\nWins: {a['wins']} | Losses: {a['losses']} | Breakeven: {a['breakeven']}\nHighest TP Distribution — TP1 Only: {a['tp1']} | TP2: {a['tp2']} | TP3: {a['tp3']} | TP4: {a['tp4']} | TP5: {a['tp5']} | No TP: {a['no_tp']}\n━━━━━━━━━━━━━━━━━━━━'''

class Notifier:
    def __init__(self,s):self.s=s
    async def send(self,signal,stats):
        text=fmt(signal,stats); tasks=[]
        if self.s.telegram_enabled and self.s.telegram_token and self.s.telegram_chat_id:tasks.append(self.telegram(text))
        if self.s.discord_enabled and self.s.discord_webhook:tasks.append(self.discord(text))
        if tasks: await __import__('asyncio').gather(*tasks,return_exceptions=True)
    async def telegram(self,text):
        url=f'https://api.telegram.org/bot{self.s.telegram_token}/sendMessage'
        async with aiohttp.ClientSession(timeout=aiohttp.ClientTimeout(total=15)) as x:
            await x.post(url,json={'chat_id':self.s.telegram_chat_id,'text':text})
    async def discord(self,text):
        async with aiohttp.ClientSession(timeout=aiohttp.ClientTimeout(total=15)) as x:
            await x.post(self.s.discord_webhook,json={'content':text[:1900]})
