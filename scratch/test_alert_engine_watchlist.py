"""ตรวจ alert ของหุ้นใน Watchlist โดยรัน evaluate_user_alerts ของจริงกับ model ปลอม

ไม่แตะฐานข้อมูลและไม่ต่อเน็ต — patch ทุก queryset, cache, ราคา และผลสแกน
รันด้วย:  python3 scratch/test_alert_engine_watchlist.py
(ใส่พาธโฟลเดอร์ที่มี stubs/ เป็น argv[1] ได้ ถ้าเครื่องนั้นไม่มี pandas_ta)
"""
import sys, types
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT))      # ให้ import config.settings / stocks ได้เมื่อรันจากที่ไหนก็ได้
if len(sys.argv) > 1:
    sys.path.insert(0, sys.argv[1] + '/stubs')
import os, django
os.environ.setdefault('DJANGO_SETTINGS_MODULE', 'config.settings'); django.setup()

import stocks.alert_engine as ae
from unittest.mock import patch
import stocks.views.base as vb

class Cfg:
    def __init__(self, wl=False, brk=True, **on):
        self.alert_watchlist_entry = wl; self.alert_breakout_add = brk
        self.alert_sl = False; self.alert_tp = False
        self.__dict__.update(on)        # เปิดสวิตช์อื่นเฉพาะเคสที่ต้องใช้
    def __getattr__(self, n):   # สวิตช์อื่นๆ ปิดหมด
        return False

class Scan:
    def __init__(self, **kw):
        d = dict(market='SET', rvol=2.0, stage2=True, is_extended=False, is_52w_breakout=False,
                 pocket_pivot=False, wyckoff_spring=False, turtle_dist_pct=99.0,
                 demand_zone_start=None, demand_zone_end=None, technical_score=70,
                 vp_poc_price=None, vp_status='', pp_at_ma50=False, cmf=0.2, rsi=55)
        d.update(kw); self.__dict__.update(d)
    def __getattr__(self, n):   # ฟิลด์อื่นที่ไม่ได้ตั้ง = None/ไม่มีสัญญาณ
        return None

class W:
    def __init__(self, sym): self.symbol=sym; self.is_active=True; self.last_alerted_at=None
    def save(self, **k): pass

class P:
    def __init__(self, sym): 
        self.symbol=sym; self.market='SET'; self.category='STOCK'; self.quantity=100
        self.entry_price=10.0; self.strategy=''; self.stop_loss=None; self.take_profit=None
    def __getattr__(self, n): return None

from django.contrib.auth import get_user_model
U = lambda: get_user_model()(id=1, username='t')

class MemCache:
    def __init__(self): self.d = {}; self.ttl = {}
    def get(self, k, default=None): return self.d.get(k, default)
    def set(self, k, v, timeout=None): self.d[k] = v; self.ttl[k] = timeout
    def clear(self): self.d.clear(); self.ttl.clear()

def _prices(pairs):
    """จำลอง fetch_live_prices จริง: แปลงผ่าน _to_yf_symbol แล้วให้ราคาเฉพาะ ticker ที่ถูกต้อง
    หุ้น US ที่ถูกเติม .BK จะไม่มีราคา เหมือนที่เกิดขึ้นกับ yfinance จริง"""
    out = {}
    for sym, mkt in pairs:
        yf_sym = ae._to_yf_symbol(sym, mkt)
        want_bk = (_UNIVERSE.get(sym, 'SET') == 'SET')
        if yf_sym.endswith('.BK') == want_bk:
            out[(sym, mkt)] = 10.0
    return out

_UNIVERSE = {}

def run(cfg, wl_syms, pf_syms, scans, market_open=True):
    _UNIVERSE.clear()
    _UNIVERSE.update({k: getattr(v, 'market', 'SET') for k, v in scans.items()})
    for _s in list(wl_syms) + list(pf_syms):
        _UNIVERSE.setdefault(_s, _UNIVERSE.get(_s.replace('.BK',''), 'SET'))
    created = []
    with patch.object(ae, 'cache', MemCache()), \
         patch.object(vb, '_compute_signals', lambda sc, current_price=0: {'buy_score': 80, 'reversal_score': 0, 'buy_reasons': []}), \
         patch.object(ae.Watchlist.objects, 'filter', lambda **k: [W(s) for s in wl_syms]), \
         patch.object(ae.Portfolio.objects, 'filter', lambda **k: [P(s) for s in pf_syms]), \
         patch.object(ae, 'fetch_live_prices', _prices), \
         patch.object(ae, '_latest_scan', lambda sym, market=None, user=None: scans.get(sym.replace('.BK',''))), \
         patch.object(ae, '_watchlist_scan', lambda sym, user=None: scans.get(sym.replace('.BK',''))), \
         patch.object(ae, 'is_market_open', lambda m: market_open), \
         patch.object(ae.StockAlertEvent.objects, 'bulk_create', lambda evs: created.extend(evs)):
        ev = ae.evaluate_user_alerts(U(), cfg)
    return [e for e in ev if e.alert_type == ae.StockAlertEvent.AlertType.BREAKOUT]

# ── 1. ค่าปริยาย (watchlist_entry=False, breakout_add=True) ต้องยิงได้ ──
scans = {'AAA': Scan(rvol=2.0, turtle_dist_pct=0.2)}
r = run(Cfg(wl=False, brk=True), ['AAA'], [], scans)
print('1) ค่าปริยาย: watchlist breakout ยิงได้ ->', len(r) == 1, f'({len(r)} ใบ)')

# ── 2. Preset 7: RVOL สูงแต่ห่างจุดเบรคมาก ต้องไม่ยิง ──
scans = {'BBB': Scan(rvol=3.0, stage2=True, turtle_dist_pct=8.0)}
r = run(Cfg(), ['BBB'], [], scans)
print('2) RVOL 3x แต่ห่าง High 20 วัน 8% -> ไม่ยิง:', len(r) == 0, f'({len(r)} ใบ)')
scans = {'BBB': Scan(rvol=3.0, stage2=False, turtle_dist_pct=0.3)}
r = run(Cfg(), ['BBB'], [], scans)
print('   RVOL 3x + ห่าง 0.3% (ไม่ Stage 2) -> ยิง:', len(r) == 1, f'({len(r)} ใบ)')

# ── 3. หุ้นที่ถืออยู่แล้ว ไม่ควรได้ BREAKOUT ซ้ำจากฝั่ง watchlist ──
scans = {'CCC': Scan(rvol=2.0, turtle_dist_pct=0.2, is_52w_breakout=True)}
r = run(Cfg(), ['CCC'], ['CCC'], scans)
wl = [e for e in r if e.strategy == 'Watchlist Breakout']
print('3) หุ้นถืออยู่ + อยู่ watchlist -> ไม่มีใบซ้ำจาก watchlist:', len(wl) == 0,
      f'(watchlist {len(wl)} ใบ, รวม {len(r)} ใบ)')

# ── 4. ตลาดปิด ต้องไม่ยิง ──
scans = {'DDD': Scan(rvol=2.0, turtle_dist_pct=0.2)}
r = run(Cfg(), ['DDD'], [], scans, market_open=False)
print('4) ตลาดปิด -> ไม่ยิง:', len(r) == 0, f'({len(r)} ใบ)')

# ── 5. turtle_dist_pct = 0.0 (ราคาแตะ High 20 วันพอดี) = breakout แรงสุด ต้องยิง ──
scans = {'EEE': Scan(rvol=2.0, turtle_dist_pct=0.0)}
r = run(Cfg(), ['EEE'], [], scans)
print('5) turtle_dist 0.0 (แตะ High พอดี) -> ยิง:', len(r) == 1, f'({len(r)} ใบ)')

# ── 6. หุ้นถืออยู่ + มีแต่สัญญาณ Preset 7 (ฝั่งพอร์ตไม่ยิง) ต้องยังได้ใบจาก watchlist ──
scans = {'FFF': Scan(rvol=2.0, turtle_dist_pct=0.2, is_52w_breakout=False,
                     pocket_pivot=False, wyckoff_spring=False)}
r = run(Cfg(), ['FFF'], ['FFF'], scans)
print('6) ถืออยู่ + มีแต่ Preset 7 -> ยังได้ใบ:', len(r) == 1, f'({len(r)} ใบ)')

# ── 7. ชื่อสะกดต่าง (.BK ในพอร์ต / ไม่มีใน watchlist) ต้องไม่ได้ใบซ้ำ ──
scans = {'GGG': Scan(rvol=2.0, turtle_dist_pct=0.2, is_52w_breakout=True)}
r = run(Cfg(), ['GGG'], ['GGG.BK'], scans)
wl = [e for e in r if e.strategy == 'Watchlist Breakout']
print('7) พอร์ต GGG.BK + watchlist GGG -> ไม่ซ้ำ:', len(wl) == 0,
      f'(watchlist {len(wl)} ใบ, รวม {len(r)} ใบ)')

# ── 8. หุ้น US ใน watchlist ต้องได้ราคา (ไม่ถูกเติม .BK) ──
scans = {'AAPL': Scan(market='US', rvol=2.0, turtle_dist_pct=0.2)}
r = run(Cfg(), ['AAPL'], [], scans)
print('8) หุ้น US ใน watchlist -> ได้ราคาและยิงได้:', len(r) == 1, f'({len(r)} ใบ)')

# ── 9. ตลาดปิด: breakout ต้องไม่ยิง แต่ alert โซนซื้อ (ของเดิม) ต้องยังทำงาน ──
scans = {'HHH': Scan(rvol=2.0, turtle_dist_pct=0.2, demand_zone_start=11.0, demand_zone_end=9.0)}
cfg = Cfg(wl=True, brk=True)
allev = []
import stocks.alert_engine as _ae
_orig = run
def run_all(cfg, wl, pf, sc, mo):
    from unittest.mock import patch as _p
    created=[]
    with _p.object(ae,'cache',MemCache()), \
         _p.object(vb,'_compute_signals', lambda s,current_price=0:{'buy_score':90,'reversal_score':0,'buy_reasons':[]}), \
         _p.object(ae,'_passes_inzone_gate', lambda s: True), \
         _p.object(ae.Watchlist.objects,'filter', lambda **k:[W(x) for x in wl]), \
         _p.object(ae.Portfolio.objects,'filter', lambda **k:[P(x) for x in pf]), \
         _p.object(ae,'fetch_live_prices', lambda pairs:{(s,m):10.0 for s,m in pairs}), \
         _p.object(ae,'_latest_scan', lambda s,market=None,user=None: sc.get(s.replace('.BK',''))), \
         _p.object(ae,'_watchlist_scan', lambda s,user=None: sc.get(s.replace('.BK',''))), \
         _p.object(ae,'is_market_open', lambda m: mo), \
         _p.object(ae.StockAlertEvent.objects,'bulk_create', lambda e: created.extend(e)):
        return ae.evaluate_user_alerts(U(), cfg)
ev = run_all(cfg, ['HHH'], [], scans, False)
brk = [e for e in ev if e.alert_type == ae.StockAlertEvent.AlertType.BREAKOUT]
wle = [e for e in ev if e.alert_type == ae.StockAlertEvent.AlertType.WATCHLIST_ENTRY]
print('9) ตลาดปิด -> breakout ไม่ยิง:', len(brk) == 0, '| โซนซื้อยังทำงาน:', len(wle) == 1,
      f'(breakout {len(brk)}, โซนซื้อ {len(wle)})')

# ── 10. ticker ซ้ำข้ามตลาด: ถือ TU (US) ที่เบรค + TU (SET) ใน watchlist ที่เบรค
#        ทั้งคู่คนละบริษัท ต้องได้ใบคนละใบ ไม่ใช่ตัวหนึ่งปิดปากอีกตัว
from unittest.mock import patch as _pp
def run_cross():
    scan_us  = Scan(market='US',  is_52w_breakout=True, rvol=2.0, turtle_dist_pct=0.2)
    scan_set = Scan(market='SET', rvol=2.0, turtle_dist_pct=0.2)
    def _scan(sym, market=None, user=None):       # พอร์ตส่ง market มา, watchlist ไม่ส่ง
        return scan_us if market == 'US' else scan_set
    class PUS(P):
        def __init__(self, s): super().__init__(s); self.market = 'US'
    created = []
    with _pp.object(ae, 'cache', MemCache()), \
         _pp.object(vb, '_compute_signals', lambda s, current_price=0: {'buy_score': 80, 'reversal_score': 0, 'buy_reasons': []}), \
         _pp.object(ae.Watchlist.objects, 'filter', lambda **k: [W('TU')]), \
         _pp.object(ae.Portfolio.objects, 'filter', lambda **k: [PUS('TU')]), \
         _pp.object(ae, 'fetch_live_prices', lambda pairs: {(s, m): 10.0 for s, m in pairs}), \
         _pp.object(ae, '_latest_scan', _scan), \
         _pp.object(ae, '_watchlist_scan', lambda s, user=None: _scan(s)), \
         _pp.object(ae, 'is_market_open', lambda m: True), \
         _pp.object(ae.StockAlertEvent.objects, 'bulk_create', lambda e: created.extend(e)):
        return ae.evaluate_user_alerts(U(), Cfg())
ev = [e for e in run_cross() if e.alert_type == ae.StockAlertEvent.AlertType.BREAKOUT]
mk = sorted(e.market for e in ev)
print('10) TU(US) ในพอร์ต + TU(SET) ใน watchlist -> ได้คนละใบ:', mk == ['SET', 'US'], f'({len(ev)} ใบ: {mk})')

# ── 11. demand_zone_end = NULL ต้องไม่ทำให้ทั้งรอบพัง ──
scans = {'III': Scan(demand_zone_start=11.0, demand_zone_end=None, rvol=0.5, turtle_dist_pct=99.0)}
try:
    ev = run_all(Cfg(wl=True, brk=True), ['III'], [], scans, True)
    print('11) demand_zone_end = NULL -> ไม่ crash:', True, f'({len(ev)} ใบ)')
except TypeError as e:
    print('11) demand_zone_end = NULL -> ไม่ crash: False  (TypeError:', e, ')')

# ── 12. fetch_live_prices: 'PTT.BK' (พอร์ต) กับ 'PTT' (watchlist) ต้องได้ราคาทั้งคู่ ──
class FakeTicker:
    def __init__(self, s): self.s = s
    @property
    def fast_info(self):
        return type('FI', (), {'last_price': 42.0})()
with patch.object(ae.yf, 'download', lambda *a, **k: None), \
     patch.object(ae.yf, 'Ticker', FakeTicker):
    got = ae.fetch_live_prices([('PTT.BK', 'SET'), ('PTT', 'SET'), ('AAPL', 'US')])
print('12) PTT.BK และ PTT ได้ราคาทั้งคู่:',
      got.get(('PTT.BK', 'SET')) == 42.0 and got.get(('PTT', 'SET')) == 42.0,
      '| AAPL ได้ราคา:', got.get(('AAPL', 'US')) == 42.0, f'-> {got}')

# ── 13. ฝั่งพอร์ต: รันซ้ำในรอบถัดไปต้องไม่ยิงใบเดิมอีก (เดิมยิงทุก ~90 วินาที) ──
def run_twice():
    sc = {'JJJ': Scan(market='SET', is_52w_breakout=True, rvol=2.0, turtle_dist_pct=0.2)}
    mc = MemCache()                      # cache เดียวกันข้ามรอบ เหมือน production
    out = []
    for _ in range(3):
        created = []
        with patch.object(ae, 'cache', mc), \
             patch.object(vb, '_compute_signals', lambda s, current_price=0: {'buy_score': 80, 'reversal_score': 0, 'buy_reasons': []}), \
             patch.object(ae.Watchlist.objects, 'filter', lambda **k: []), \
             patch.object(ae.Portfolio.objects, 'filter', lambda **k: [P('JJJ')]), \
             patch.object(ae, 'fetch_live_prices', lambda pairs: {(s, m): 10.0 for s, m in pairs}), \
             patch.object(ae, '_latest_scan', lambda s, market=None, user=None: sc.get(s.replace('.BK', ''))), \
             patch.object(ae, '_watchlist_scan', lambda s, user=None: sc.get(s.replace('.BK', ''))), \
             patch.object(ae, 'is_market_open', lambda m: True), \
             patch.object(ae.StockAlertEvent.objects, 'bulk_create', lambda e: created.extend(e)):
            ev = ae.evaluate_user_alerts(U(), Cfg())
        out.append(len([e for e in ev if e.alert_type == ae.StockAlertEvent.AlertType.BREAKOUT]))
    return out
counts = run_twice()
print('13) รัน 3 รอบติดกัน -> ยิงใบเดียว:', counts == [1, 0, 0], f'(ต่อรอบ: {counts})')

# ── 14. โซ่ if/elif ต้องไม่รั่ว: หุ้นที่เบรคแล้วถูกกันซ้ำ ห้ามไหลไปยิง "ย่อเข้าโซน" แทน ──
def run_chain():
    sc = {'KKK': Scan(market='SET', is_52w_breakout=True, rvol=2.0, turtle_dist_pct=0.2,
                      demand_zone_start=11.0, demand_zone_end=9.0)}
    mc = MemCache()
    seen = []
    for _ in range(3):
        created = []
        with patch.object(ae, 'cache', mc), \
             patch.object(vb, '_compute_signals', lambda s, current_price=0: {'buy_score': 90, 'reversal_score': 0, 'buy_reasons': []}), \
             patch.object(ae, '_passes_inzone_gate', lambda s: True), \
             patch.object(ae.Watchlist.objects, 'filter', lambda **k: []), \
             patch.object(ae.Portfolio.objects, 'filter', lambda **k: [P('KKK')]), \
             patch.object(ae, 'fetch_live_prices', lambda pairs: {(s, m): 10.0 for s, m in pairs}), \
             patch.object(ae, '_latest_scan', lambda s, market=None, user=None: sc.get(s.replace('.BK', ''))), \
             patch.object(ae, '_watchlist_scan', lambda s, user=None: sc.get(s.replace('.BK', ''))), \
             patch.object(ae, 'is_market_open', lambda m: True), \
             patch.object(ae.StockAlertEvent.objects, 'bulk_create', lambda e: created.extend(e)):
            ev = ae.evaluate_user_alerts(U(), Cfg())
        seen.append([e.alert_type for e in ev])
    flat = [t for r in seen for t in r]
    ok = seen[0] == [ae.StockAlertEvent.AlertType.BREAKOUT] and not seen[1] and not seen[2]
    print('14) กันซ้ำแล้วไม่ไหลไป elif โซนซื้อ:', ok, f'(ต่อรอบ: {seen})')

run_chain()

# ── 15. สัญญาณ "สับเปลี่ยนหุ้น" ต้องยังทำงานในรอบที่ 2 (หุ้นเด่นต้องนับทุกรอบ) ──
def run_realloc():
    sc = {'STRONG': Scan(market='SET', is_52w_breakout=True, technical_score=90,
                         rvol=2.0, turtle_dist_pct=0.2),
          'WEAK':   Scan(market='SET', technical_score=10, rvol=0.5, turtle_dist_pct=99.0,
                         stop_loss=20.0)}   # ราคา 10 ต่ำกว่า SL 20 = หลุด SL
    mc = MemCache()
    out = []
    for _ in range(2):
        # ล้างเฉพาะ mute 24 ชม.ของสัญญาณสับเปลี่ยน ไม่ล้างคีย์ breakout
        # เพื่อวัดว่ารอบที่สอง "ยังจับคู่ได้" ไหม ไม่ใช่วัดตัว mute เอง
        for _k in [k for k in mc.d if k.startswith('stockalert_reallocate_')]:
            del mc.d[_k]
        created = []
        with patch.object(ae, 'cache', mc), \
             patch.object(vb, '_compute_signals', lambda s, current_price=0: {'buy_score': 50, 'reversal_score': 0, 'buy_reasons': []}), \
             patch.object(ae.Watchlist.objects, 'filter', lambda **k: []), \
             patch.object(ae.Portfolio.objects, 'filter', lambda **k: [P('STRONG'), P('WEAK')]), \
             patch.object(ae, 'fetch_live_prices', lambda pairs: {(s, m): 10.0 for s, m in pairs}), \
             patch.object(ae, '_latest_scan', lambda s, market=None, user=None: sc.get(s.replace('.BK', ''))), \
             patch.object(ae, '_watchlist_scan', lambda s, user=None: sc.get(s.replace('.BK', ''))), \
             patch.object(ae, 'is_market_open', lambda m: True), \
             patch.object(ae.StockAlertEvent.objects, 'bulk_create', lambda e: created.extend(e)):
            ev = ae.evaluate_user_alerts(U(), Cfg(alert_stop_loss=True, alert_reallocate=True))
        out.append(len([e for e in ev if e.alert_type == ae.StockAlertEvent.AlertType.REALLOCATE]))
    return out
rc = run_realloc()
print('15) รอบ 2 ยังจับคู่สับเปลี่ยนหุ้นได้:', rc[1] >= 1, f'(REALLOCATE ต่อรอบ: {rc})')

# ── 16. fetch_live_prices ตัวจริง: TU ที่ SET กับ TU ที่ US ต้องได้ราคาคนละตัว ──
_PX = {'TU.BK': 14.0, 'TU': 89.0}
class FakeTicker2:
    def __init__(self, s): self.s = s
    @property
    def fast_info(self):
        return type('FI', (), {'last_price': _PX.get(self.s)})()
with patch.object(ae.yf, 'download', lambda *a, **k: None), \
     patch.object(ae.yf, 'Ticker', FakeTicker2):
    got2 = ae.fetch_live_prices([('TU', 'SET'), ('TU', 'US')])
print('16) TU(SET) vs TU(US) ได้ราคาคนละตัว:',
      got2.get(('TU', 'SET')) == 14.0 and got2.get(('TU', 'US')) == 89.0, f'-> {got2}')

# ── 17. _watchlist_scan ต้องเลือกตลาดแบบคงเส้นคงวา ไม่ใช่ "ใครสแกนล่าสุด" ──
class FakeQS:
    """จำลอง PrecisionScanCandidate.objects สำหรับ _watchlist_scan (ไม่แตะ DB)"""
    def __init__(self, rows): self.rows = rows
    def filter(self, **kw):
        r = self.rows
        if 'symbol' in kw: r = [x for x in r if x.symbol == kw['symbol']]
        if 'market' in kw: r = [x for x in r if x.market == kw['market']]
        # ต้องกรอง user ด้วย ไม่งั้นเทสต์จะผ่านแม้ถอดตัวกรอง user ออกจากโค้ดจริง
        if 'user' in kw: r = [x for x in r if getattr(x, 'owner', None) == kw['user']]
        return FakeQS(r)
    def order_by(self, *a): return FakeQS(self.rows)
    def values_list(self, f, flat=False): return FakeQS([getattr(x, f) for x in self.rows])
    def distinct(self): return self
    def first(self): return self.rows[0] if self.rows else None
    def __iter__(self): return iter(self.rows)

ME, OTHER = 'me', 'other'

def wl_market(rows, sym, who=ME):
    objs = FakeQS(rows)
    seen = []
    def _ls(s, market=None, user=None):
        seen.append(user)
        return next((x for x in rows if x.symbol == s.replace('.BK', '')
                     and (market is None or x.market == market)
                     and (user is None or getattr(x, 'owner', None) == user)), None)
    with patch.object(ae, 'PrecisionScanCandidate', type('M', (), {'objects': objs})), \
         patch.object(ae, '_latest_scan', _ls):
        sc = ae._watchlist_scan(sym, user=who)
    return getattr(sc, 'market', None), seen

def _row(sym, market, owner=ME):
    r = Scan(market=market); r.symbol = sym; r.owner = owner; return r

set_row, us_row = _row('TU', 'SET'), _row('TU', 'US')
nv_row = _row('NVDA', 'US')
print('17) ชื่อ .BK -> SET เสมอ:', wl_market([set_row, us_row], 'TU.BK')[0] == 'SET')
print('    มีตลาดเดียว (NVDA ฝั่ง US) -> US:', wl_market([nv_row], 'NVDA')[0] == 'US')
print('    มีทั้งสองตลาด -> เลือก SET คงที่ ไม่สลับตามลำดับ:',
      wl_market([us_row, set_row], 'TU')[0] == 'SET' and wl_market([set_row, us_row], 'TU')[0] == 'SET')
# ผลสแกนของคนอื่นต้องไม่ถูกหยิบมาใช้ และ user ต้องถูกส่งต่อไปถึง _latest_scan จริง
other_only = [_row('XYZ', 'US', owner=OTHER)]
_m, _seen = wl_market(other_only, 'XYZ')
print('    ไม่หยิบผลสแกนของ user คนอื่น:', _m is None)
_m2, _seen2 = wl_market([set_row], 'TU.BK')
print('    ส่ง user ต่อให้ _latest_scan จริง:', _seen2 == [ME])

# ── 18. symbol ที่ไม่มีผลสแกน ต้องไม่ถูกส่งไปขอราคา ──
asked = []
def _spy(pairs):
    asked.extend(pairs)
    return {(s, m): 10.0 for s, m in pairs}
sc18 = {'HAS': Scan(market='SET', rvol=2.0, turtle_dist_pct=0.2)}
created = []
with patch.object(ae, 'cache', MemCache()), \
     patch.object(vb, '_compute_signals', lambda s, current_price=0: {'buy_score': 80, 'reversal_score': 0, 'buy_reasons': []}), \
     patch.object(ae.Watchlist.objects, 'filter', lambda **k: [W('HAS'), W('NOSCAN')]), \
     patch.object(ae.Portfolio.objects, 'filter', lambda **k: []), \
     patch.object(ae, 'fetch_live_prices', _spy), \
     patch.object(ae, '_latest_scan', lambda s, market=None, user=None: sc18.get(s.replace('.BK', ''))), \
     patch.object(ae, '_watchlist_scan', lambda s, user=None: sc18.get(s.replace('.BK', ''))), \
     patch.object(ae, 'is_market_open', lambda m: True), \
     patch.object(ae.StockAlertEvent.objects, 'bulk_create', lambda e: created.extend(e)):
    ae.evaluate_user_alerts(U(), Cfg())
syms = sorted(s for s, _ in asked)
print('18) ไม่ขอราคาให้ตัวที่ไม่มีผลสแกน:', syms == ['HAS'], f'(ขอราคา: {syms})')

# ── 19. ลูปพอร์ตต้องส่ง user ไปให้ _latest_scan จริง (วัดจากการเรียก ไม่ใช่จากข้อความในซอร์ส) ──
seen_users = []
sc19 = {'ZZZ': Scan(market='SET', rvol=2.0, turtle_dist_pct=0.2)}
def _ls19(s, market=None, user=None):
    seen_users.append(user)
    return sc19.get(s.replace('.BK', ''))
created = []
me = U()
with patch.object(ae, 'cache', MemCache()), \
     patch.object(vb, '_compute_signals', lambda s, current_price=0: {'buy_score': 80, 'reversal_score': 0, 'buy_reasons': []}), \
     patch.object(ae.Watchlist.objects, 'filter', lambda **k: []), \
     patch.object(ae.Portfolio.objects, 'filter', lambda **k: [P('ZZZ')]), \
     patch.object(ae, 'fetch_live_prices', lambda pairs: {(s, m): 10.0 for s, m in pairs}), \
     patch.object(ae, '_latest_scan', _ls19), \
     patch.object(ae, '_watchlist_scan', lambda s, user=None: None), \
     patch.object(ae, 'is_market_open', lambda m: True), \
     patch.object(ae.StockAlertEvent.objects, 'bulk_create', lambda e: created.extend(e)):
    ae.evaluate_user_alerts(me, Cfg())
print('19) ลูปพอร์ตส่ง user ไปให้ _latest_scan:', seen_users == [me], f'(ได้: {seen_users})')

# ── 20. สัญญาณ fallback ต้องถูก cache ไม่ใช่ยิง yfinance ใหม่ทุกรอบเช็ค ──
calls = []
def _fake_fallback(sym, mkt):
    calls.append((sym, mkt))
    return Scan(market=mkt, rvol=0.5, turtle_dist_pct=99.0)
import stocks.utils as _su
mc20 = MemCache()
for _ in range(3):
    created = []
    with patch.object(ae, 'cache', mc20), \
         patch.object(_su, 'compute_fallback_alert_signals', _fake_fallback), \
         patch.object(vb, '_compute_signals', lambda s, current_price=0: {'buy_score': 10, 'reversal_score': 0, 'buy_reasons': []}), \
         patch.object(ae.Watchlist.objects, 'filter', lambda **k: []), \
         patch.object(ae.Portfolio.objects, 'filter', lambda **k: [P('NOSCAN')]), \
         patch.object(ae, 'fetch_live_prices', lambda pairs: {(s, m): 10.0 for s, m in pairs}), \
         patch.object(ae, '_latest_scan', lambda s, market=None, user=None: None), \
         patch.object(ae, '_watchlist_scan', lambda s, user=None: None), \
         patch.object(ae, 'is_market_open', lambda m: True), \
         patch.object(ae.StockAlertEvent.objects, 'bulk_create', lambda e: created.extend(e)):
        ae.evaluate_user_alerts(U(), Cfg())
print('20) รัน 3 รอบ -> ดึงราคา fallback ครั้งเดียว:', len(calls) == 1, f'(เรียก {len(calls)} ครั้ง)')

# ── 21. ดึงราคา fallback ไม่สำเร็จ ต้องหมดอายุเร็ว ไม่ปิดปาก alert ยาว 15 นาที ──
def fallback_ttl(result):
    mc = MemCache()
    with patch.object(ae, 'cache', mc), \
         patch.object(_su, 'compute_fallback_alert_signals', lambda s, m: result):
        ae._cached_fallback_signals('QQQ', 'SET')
    return next(iter(mc.ttl.values()))
ok_ttl = fallback_ttl(Scan(market='SET'))
fail_ttl = fallback_ttl(None)
print('21) TTL สำเร็จ vs ล้มเหลว:', ok_ttl == ae._FALLBACK_SIGNAL_TTL and fail_ttl == ae._FALLBACK_SIGNAL_FAIL_TTL,
      f'(สำเร็จ {ok_ttl} วิ, ล้มเหลว {fail_ttl} วิ)')
print('    ล้มเหลวต้องสั้นกว่าสำเร็จมาก:', fail_ttl < ok_ttl / 4)
