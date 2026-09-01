import json, sqlite3
from datetime import datetime, timezone

class DB:
    def __init__(self,path):
        self.path=path
        with sqlite3.connect(path) as c:
            c.executescript('''
            PRAGMA journal_mode=WAL;
            CREATE TABLE IF NOT EXISTS counter(id INTEGER PRIMARY KEY CHECK(id=1), n INTEGER NOT NULL);
            INSERT OR IGNORE INTO counter(id,n) VALUES(1,0);
            CREATE TABLE IF NOT EXISTS signals(
              id TEXT PRIMARY KEY, trade_no INTEGER UNIQUE, symbol TEXT, direction TEXT,
              trade_type TEXT, market_condition TEXT, tf TEXT, entry_low REAL, entry_high REAL,
              stop REAL, tps TEXT, rr REAL, leverage INTEGER, score REAL, fingerprint TEXT,
              status TEXT, entry_filled INTEGER DEFAULT 0, highest_tp INTEGER DEFAULT 0,
              final_outcome TEXT, win_loss TEXT, pnl_r REAL DEFAULT 0, created_at TEXT, closed_at TEXT
            );
            CREATE TABLE IF NOT EXISTS events(
              id INTEGER PRIMARY KEY AUTOINCREMENT, signal_id TEXT, event TEXT, price REAL,
              at TEXT, meta TEXT
            );
            CREATE INDEX IF NOT EXISTS ix_symbol_status ON signals(symbol,status);
            ''')
    def next_trade(self):
        with sqlite3.connect(self.path) as c:
            c.execute("UPDATE counter SET n=n+1 WHERE id=1")
            n=c.execute("SELECT n FROM counter WHERE id=1").fetchone()[0]; c.commit(); return n
    def save(self,s):
        with sqlite3.connect(self.path) as c:
            c.execute('''INSERT INTO signals(id,trade_no,symbol,direction,trade_type,market_condition,tf,entry_low,entry_high,stop,tps,rr,leverage,score,fingerprint,status,created_at)
                         VALUES(?,?,?,?,?,?,?,?,?,?,?,?,?,?,?,?,?)''',(s.signal_id,s.trade_number,s.symbol,s.direction.value,s.trade_type,s.market_condition,s.signal_timeframe,s.entry_low,s.entry_high,s.stop_loss,json.dumps(s.take_profits),s.rr,s.leverage,s.confidence,s.fingerprint,"APPROVED",s.created_at)); c.commit()
        self.event(s.signal_id,"SIGNAL_CREATED")
    def active(self,symbol):
        with sqlite3.connect(self.path) as c:
            c.row_factory=sqlite3.Row
            return c.execute("SELECT * FROM signals WHERE symbol=? AND status IN ('APPROVED','WAITING_FOR_ENTRY','ENTRY_FILLED','TP1_HIT','TP2_HIT','TP3_HIT','TP4_HIT') ORDER BY trade_no DESC LIMIT 1",(symbol,)).fetchone()
    def event(self,sid,event,price=None,meta=None):
        with sqlite3.connect(self.path) as c:
            c.execute("INSERT INTO events(signal_id,event,price,at,meta) VALUES(?,?,?,?,?)",(sid,event,price,datetime.now(timezone.utc).isoformat(),json.dumps(meta or {}))); c.commit()
    def entry(self,sid):
        with sqlite3.connect(self.path) as c:c.execute("UPDATE signals SET entry_filled=1,status='ENTRY_FILLED' WHERE id=?",(sid,));c.commit()
        self.event(sid,"ENTRY_FILLED")
    def tp(self,sid,n):
        with sqlite3.connect(self.path) as c:c.execute("UPDATE signals SET highest_tp=?,status=? WHERE id=?",(n,f"TP{n}_HIT",sid));c.commit()
        self.event(sid,f"TP{n}_HIT")
    def close(self,row,status,outcome,wl,pnl_r):
        at=datetime.now(timezone.utc).isoformat()
        with sqlite3.connect(self.path) as c:c.execute("UPDATE signals SET status=?,final_outcome=?,win_loss=?,pnl_r=?,closed_at=? WHERE id=?",(status,outcome,wl,pnl_r,at,row["id"]));c.commit()
        self.event(row["id"],outcome,meta={"pnl_r":pnl_r})
    def stats(self):
        now=datetime.now(timezone.utc); d=now.strftime('%Y-%m-%d'); m=now.strftime('%Y-%m')
        def one(where,par):
            with sqlite3.connect(self.path) as c:
                c.row_factory=sqlite3.Row
                r=c.execute(f'''SELECT COUNT(*) total,
                SUM(CASE WHEN win_loss='WIN' THEN 1 ELSE 0 END) wins,
                SUM(CASE WHEN win_loss='LOSS' THEN 1 ELSE 0 END) losses,
                SUM(CASE WHEN win_loss='BREAKEVEN' THEN 1 ELSE 0 END) be,
                COALESCE(SUM(pnl_r),0) pnl,
                SUM(CASE WHEN highest_tp=1 THEN 1 ELSE 0 END) tp1,
                SUM(CASE WHEN highest_tp=2 THEN 1 ELSE 0 END) tp2,
                SUM(CASE WHEN highest_tp=3 THEN 1 ELSE 0 END) tp3,
                SUM(CASE WHEN highest_tp=4 THEN 1 ELSE 0 END) tp4,
                SUM(CASE WHEN highest_tp=5 THEN 1 ELSE 0 END) tp5,
                SUM(CASE WHEN highest_tp=0 THEN 1 ELSE 0 END) no_tp
                FROM signals WHERE closed_at IS NOT NULL AND {where}''',par).fetchone()
                total=int(r['total'] or 0); wins=int(r['wins'] or 0)
                return {'total':total,'wins':wins,'losses':int(r['losses'] or 0),'breakeven':int(r['be'] or 0),'win_rate':round(wins/total*100,2) if total else 0.0,'pnl_r':round(float(r['pnl'] or 0),2),'tp1':int(r['tp1'] or 0),'tp2':int(r['tp2'] or 0),'tp3':int(r['tp3'] or 0),'tp4':int(r['tp4'] or 0),'tp5':int(r['tp5'] or 0),'no_tp':int(r['no_tp'] or 0)}
        return {'daily':one("substr(closed_at,1,10)=?",(d,)),'monthly':one("substr(closed_at,1,7)=?",(m,)),'total':one("1=1",())}
