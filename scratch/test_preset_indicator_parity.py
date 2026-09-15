"""ตรวจว่า indicator ที่ backtest ใช้ ให้ค่าตรงกับตัวที่หน้าสแกนใช้จริงทุกแท่ง

ทำไมต้องมี: _build_preset_indicators ใน utils.py เป็นการ "พอร์ต" สูตรมาจาก
หน้าสแกน (scanners.py / ultra_indicators.py) ถ้าสูตรสองฝั่งเพี้ยนกันเมื่อไร
Backtest Lab จะรายงานสถิติของกฎที่ไม่มีอยู่จริงโดยไม่มีอะไรฟ้อง

วิธีตรวจ: ไม่ถอดความสูตรมาเขียนใหม่ (เคยทำแล้วลืม break ตัวเดียวกัน กลายเป็น
เทียบกับความผิดของตัวเอง) แต่ตัดซอร์สจริงจาก scanners.py มา exec ตรงๆ
และเรียก ultra_indicators ตัวจริง แล้วเทียบทีละแท่ง

ไม่ต้องใช้ฐานข้อมูลและไม่ต้อง import Django
รันจาก repo root: python3 scratch/test_preset_indicator_parity.py
(ถ้าเครื่องไม่มี pandas_ta ใส่พาธโฟลเดอร์ที่มี stubs/ เป็น argv[1])
"""
import ast
import importlib.util
import sys
import textwrap
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT))
if len(sys.argv) > 1:
    sys.path.insert(0, sys.argv[1] + '/stubs')

import numpy as np
import pandas as pd
import pandas_ta as ta

# pandas_ta ที่ใช้ต้องคำนวณได้จริง — stub ที่คืน None เงียบๆ เคยทำให้เทสต์พัง
# กลางทางแล้วดูเหมือนโค้ดจริงมีบั๊ก
_probe = ta.rsi(pd.Series(np.linspace(10, 20, 60)), length=14)
assert isinstance(_probe, pd.Series), 'pandas_ta ใช้งานไม่ได้ (คืน %s)' % type(_probe).__name__

# ── ฟังก์ชันที่จะทดสอบ: สกัดจาก utils.py โดยไม่ import ทั้งโมดูล (เลี่ยง Django) ──
_tree = ast.parse((ROOT / 'stocks/utils.py').read_text())
_want = {'_build_preset_indicators', '_htf_flag_series', '_scanner_pocket_pivot',
         'check_trend_template', 'MINERVINI_NEAR_HIGH_RATIO'}
_keep = [n for n in _tree.body
         if getattr(n, 'name', None) in _want
         or (isinstance(n, ast.Assign)
             and any(isinstance(t, ast.Name) and t.id in _want for t in n.targets))]
missing = _want - {getattr(n, 'name', None) or n.targets[0].id for n in _keep}
assert not missing, f'สกัดจาก utils.py ไม่ครบ: {missing}'
U = {'np': np, 'pd': pd, 'ta': ta}
exec(compile(ast.Module(body=_keep, type_ignores=[]), 'utils_subset', 'exec'), U)

# ── ultra_indicators ตัวจริง ──
_spec = importlib.util.spec_from_file_location('ui', ROOT / 'stocks/ultra_indicators.py')
UI = importlib.util.module_from_spec(_spec)
_spec.loader.exec_module(UI)

# ── บล็อก Pocket Pivot: ตัดข้อความจาก scanners.py มารันตรงๆ ไม่พิมพ์ใหม่ ──
_lines = (ROOT / 'stocks/views/scanners.py').read_text().split('\n')
_start = next(i for i, l in enumerate(_lines) if 'Moving averages for Kacher/Morales exit rule' in l)
_anchor = next(i for i, l in enumerate(_lines) if i > _start and 'pp_at_ma50_flag = True' in l)
_end = next(i for i, l in enumerate(_lines) if i > _anchor and l.strip() == 'pass')
_PP_BLOCK = compile(textwrap.dedent('\n'.join(_lines[_start:_end + 1])), 'scanner_pp', 'exec')
assert 'break' in '\n'.join(_lines[_start:_end + 1])


def scanner_pocket_pivot(df):
    g = {'ta': ta, 'pd': pd, 'np': np, 'df': df, 'tech': {'cmf': 0.0},
         'pocket_pivot_flag': False, 'pp_at_ma50_flag': False}
    exec(_PP_BLOCK, g)
    return bool(g['pocket_pivot_flag'])


def make_df(seed, n=520):
    rng = np.random.default_rng(seed)
    ret = rng.normal(0.0015, 0.018, n)
    ret[200:240] += 0.022          # ช่วงพุ่งแรง -> ให้ HTF มีโอกาสติด
    ret[380:410] -= 0.015
    ret[300:320] *= 0.12           # ช่วงบีบตัว -> ให้ TTM squeeze มีโอกาสติด
    close = 7 * np.exp(np.cumsum(ret))
    opn = close * (1 + rng.normal(0, 0.004, n))
    # แท่ง gap -> Episodic Pivot ต้องอยู่ใน "ช่วงที่เทียบจริง" (แท่งที่ 240 ขึ้นไป)
    # ไม่งั้น ep จะไม่มีเคสที่เป็นจริงเลย แล้วการที่ mismatch = 0 ก็ไม่ได้พิสูจน์อะไร
    for g in (280, 360, 470):
        opn[g] = close[g - 1] * 1.06
        close[g] = opn[g] * 1.01
    high = np.maximum(opn, close) * (1 + np.abs(rng.normal(0, 0.006, n)))
    low = np.minimum(opn, close) * (1 - np.abs(rng.normal(0, 0.006, n)))
    for k in (150, 300):           # แท่งราคานิ่ง High == Low -> ทดสอบ CMF
        opn[k] = close[k] = high[k] = low[k] = close[k - 1]
    vol = rng.integers(200_000, 3_000_000, n).astype(float)
    for g in (280, 360, 470):
        vol[g] = vol[g - 20:g].mean() * 4.0
    return pd.DataFrame({'Open': opn, 'High': high, 'Low': low, 'Close': close, 'Volume': vol},
                        index=pd.bdate_range('2021-01-04', periods=n))


bad = {k: 0 for k in ('pp', 'htf', 'ttm', 'ep', 'acc', 'dist', 'tt', 'rvol20', 'turtle')}
seen_true = {k: 0 for k in bad}
bars = 0

for seed in (1, 2, 3, 11, 29):
    df = make_df(seed)
    d = U['_build_preset_indicators'](df)
    for i in range(240, len(df)):
        sub = df.iloc[:i + 1]
        bars += 1

        exp = scanner_pocket_pivot(sub);  seen_true['pp'] += exp
        bad['pp'] += bool(d['pp_scanner'].iloc[i]) != exp

        exp = UI.calculate_htf_setup(sub)[0];  seen_true['htf'] += exp
        bad['htf'] += bool(d['htf_setup'].iloc[i]) != bool(exp)

        exp = UI.calculate_ttm_squeeze(sub)[0] == 'fired';  seen_true['ttm'] += exp
        bad['ttm'] += bool(d['ttm_fired'].iloc[i]) != exp

        exp = UI.calculate_episodic_pivot(sub)[0];  seen_true['ep'] += exp
        bad['ep'] += bool(d['episodic_pivot'].iloc[i]) != bool(exp)

        # acc/dist — สูตรเดียวกับ analyze_technicals_ultra (utils.py)
        a = dd = 0
        av = float(sub['Volume'].tail(10).mean())
        for j in range(-10, 0):
            c, pc, v = (float(sub['Close'].iloc[j]), float(sub['Close'].iloc[j - 1]),
                        float(sub['Volume'].iloc[j]))
            if c > pc and v > av:   a += 1
            elif c < pc and v > av: dd += 1
        bad['acc'] += int(d['acc_days'].iloc[i]) != a
        bad['dist'] += int(d['dist_days'].iloc[i]) != dd
        seen_true['acc'] += a > 0;  seen_true['dist'] += dd > 0

        tt = U['check_trend_template'](sub, rs_rating=0)
        exp = sum(1 for k, v in tt['checks'].items() if k != 'rs_strong' and v)
        bad['tt'] += int(d['tt_price_score'].iloc[i]) != exp
        seen_true['tt'] += exp >= 7

        exp = float(sub['Volume'].iloc[-1]) / float(sub['Volume'].tail(20).mean())
        bad['rvol20'] += abs(float(d['rvol20'].iloc[i]) - exp) > 1e-9
        seen_true['rvol20'] += 1

        cp = float(sub['Close'].iloc[-1]); h20 = float(sub['High'].tail(20).max())
        exp = (h20 - cp) / cp * 100
        bad['turtle'] += abs(float(d['turtle_dist'].iloc[i]) - exp) > 1e-9
        seen_true['turtle'] += 1

print(f'เทียบ {bars} แท่ง จาก 5 ชุดข้อมูล\n')
ok = True
for k in bad:
    hit = seen_true[k]
    line = f'  {k:8s} mismatch {bad[k]:3d}   (เคสที่เป็นจริง {hit:5d})'
    if bad[k]:
        ok = False; line += '  <-- ไม่ตรง'
    elif not hit:
        ok = False; line += '  <-- ไม่มีเคสที่เป็นจริงเลย เทสต์นี้ไม่ได้พิสูจน์อะไร'
    print(line)

print('\nสรุป:', 'ตรงกับซอร์สจริงทุกแท่ง' if ok else 'มีข้อที่ไม่ผ่าน')
raise SystemExit(0 if ok else 1)
