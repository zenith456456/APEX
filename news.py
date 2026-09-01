import email.utils, time, xml.etree.ElementTree as ET
import aiohttp

class NewsFilter:
    def __init__(self,s):
        self.s=s; self.items=[]
    async def refresh(self):
        if not self.s.news_enabled:return
        out=[]
        async with aiohttp.ClientSession(timeout=aiohttp.ClientTimeout(total=10),headers={"User-Agent":"signal-bot/1.0"}) as sess:
            for url in self.s.rss_urls:
                try:
                    async with sess.get(url) as r:
                        if r.status!=200:continue
                        root=ET.fromstring(await r.text())
                        for item in root.iter():
                            if item.tag.lower().endswith("item"):
                                title=""; pub=""
                                for c in item:
                                    if c.tag.lower().endswith("title"):title=(c.text or "").strip()
                                    if c.tag.lower().endswith("pubdate"):pub=(c.text or "").strip()
                                try: ts=email.utils.mktime_tz(email.utils.parsedate_tz(pub))
                                except Exception:ts=time.time()
                                out.append((title.lower(),ts))
                except Exception:pass
        now=time.time(); self.items=[x for x in out if now-x[1] <= self.s.news_lookback_minutes*60]
    def conflict(self,symbol):
        if not self.s.news_enabled:return False
        base=symbol.replace("USDT","").lower()
        for title,ts in self.items:
            if base and base in title and any(w in title for w in self.s.news_words): return True
        return False
