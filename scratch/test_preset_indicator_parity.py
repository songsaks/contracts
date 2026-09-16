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

วัดความแข็งแรงด้วยการทำให้โค้ดกลายพันธุ์ (แก้ utils.py ทีละจุดแล้วดูว่าจับได้ไหม)
จับได้: ถอด break ใน _scanner_pocket_pivot, หน้าต่าง fallback 20 วัน (ทั้งเพิ่มและลด),
ค่า tolerance 0.98, เพดาน not_extended 0.25, เกณฑ์ EP ทั้ง gap 4.5% และวอลุ่ม 2.5x,
หน้าต่าง acc/dist 10 วัน, เส้นแบ่ง warm-up ของ tt_price_score ที่แท่ง 220,
เกณฑ์ 1.25 เหนือ low 52 สัปดาห์, หน้าต่าง shift ของ TTM, เกณฑ์ surge 70% ของ HTF,
และหน้าต่าง 20 วันของ rvol20

ข้อจำกัดที่รู้ตัว: เส้นแบ่ง warm-up ของ _htf_flag_series (range(34, n)) ยังจับไม่ได้
เพราะต้องมีหุ้นที่พุ่ง ≥70% ภายใน 35 แท่งแรกพอดี ซึ่งจัดฉากแล้วจะบิดข้อมูลชุดอื่นด้วย
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
from stocks.pandas_ta_compat import ta

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

# ── ตัดซอร์สจริงมารันตรงๆ ไม่พิมพ์ใหม่ ──
_SCANNERS = (ROOT / 'stocks/views/scanners.py').read_text().split('\n')
_UTILS_L = (ROOT / 'stocks/utils.py').read_text().split('\n')


def _find(lines, needle, after=-1, what=''):
    """หาบรรทัดแรกที่มี needle — ถ้าไม่เจอให้ฟ้องว่าซอร์สเปลี่ยนไป
    ไม่ใช่ StopIteration เปล่าๆ ที่อ่านไม่ออกว่าเกิดอะไรขึ้น"""
    for i, l in enumerate(lines):
        if i > after and needle in l:
            return i
    raise AssertionError(f'ตัดซอร์สไม่ได้: หา {what or needle!r} ไม่เจอ — ซอร์สเปลี่ยนไปแล้ว')


def _slice(lines, head, tail_pred, what):
    starts = [i for i, l in enumerate(lines) if head in l]
    assert starts, f'ตัดซอร์สไม่ได้: หา {what} ไม่เจอ'
    out = []
    for s in starts:
        e = s
        while e < len(lines) and not tail_pred(lines[e], e, s):
            e += 1
        assert e < len(lines), f'ตัดซอร์สไม่ได้: หาจุดจบของ {what} ไม่เจอ'
        out.append(textwrap.dedent('\n'.join(lines[s:e + 1])))
    # สำเนาทุกชุดต้องเหมือนกัน ไม่งั้นการทดสอบชุดเดียวไม่ครอบคลุมอีกชุด
    assert len(set(out)) == 1, f'{what} มี {len(starts)} สำเนาและเนื้อหาไม่ตรงกัน: {starts}'
    return out[0], starts


# Pocket Pivot — มีสองสำเนา (precision_momentum_scanner / us_precision_scanner)
_pp_src, _pp_at = _slice(
    _SCANNERS, 'Moving averages for Kacher/Morales exit rule',
    lambda l, i, s: l.strip() == 'pass' and i > s + 30, 'บล็อก Pocket Pivot')
assert 'break' in _pp_src and 'pocket_pivot_flag = True' in _pp_src
_PP_BLOCK = compile(_pp_src, 'scanner_pp', 'exec')

# acc/dist — ตัดจาก analyze_momentum_technical_v2 แทนการพิมพ์สูตรใหม่ในเทสต์
_ad_s = _find(_UTILS_L, '# 9. Accumulation / Distribution Days', what='บล็อก acc/dist')
_ad_e = _find(_UTILS_L, 'dist_days += 1', after=_ad_s, what='ท้ายบล็อก acc/dist')
_AD_BLOCK = compile(textwrap.dedent('\n'.join(_UTILS_L[_ad_s:_ad_e + 1])), 'utils_accdist', 'exec')


def scanner_acc_dist(df):
    g = {'df': df, 'len': len, 'float': float}
    exec(_AD_BLOCK, g)
    return g['acc_days'], g['dist_days']


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
    # ── ฉากทดสอบเส้นทาง fallback 20 วันของ Morales & Kacher ──
    # ต้นฉบับ: ถ้าไม่มี "วันลง" ใน 10 วันก่อนหน้า ให้ขยายหน้าต่างเป็น 20 วัน
    # ถ้าไม่จัดฉาก เส้นทางนี้แทบไม่เคยถูกเรียกเลยกับข้อมูลสุ่ม (ต้องขึ้นรวด 10 วันติด)
    #   • ขึ้นรวด 12 วัน (250-261) -> หน้าต่าง 10 วันของแท่ง 261 ไม่มีวันลงเลย
    #   • บังคับให้ 242 เป็นวันลง (อยู่ในหน้าต่าง 20 วันเท่านั้น) วอลุ่มหนัก
    #   • บังคับให้ 247 เป็นวันลง (อยู่ทั้งหน้าต่าง 15 และ 20 วัน) วอลุ่มเบา
    # แล้วตั้งวอลุ่มแท่ง 261 ให้อยู่ระหว่างสองค่า -> หน้าต่าง 20 วันตัดสินว่าไม่ผ่าน
    # ส่วนหน้าต่างที่สั้นกว่าตัดสินว่าผ่าน การเปลี่ยนเลข 20 จึงเห็นผลทันที
    close[242] = close[241] * 0.97
    close[247] = close[246] * 0.98
    close[250:262] = close[249] * np.cumprod(np.full(12, 1.004))   # เบาพอให้ยังไม่ยืดเกิน 25% จาก SMA50

    opn = close * (1 + rng.normal(0, 0.004, n))
    # แท่ง gap สำหรับ Episodic Pivot — ต้องคร่อมขอบเกณฑ์ทั้งสองด้าน ไม่ใช่เกินไปไกล
    # ทุกแท่ง ไม่งั้นเปลี่ยน 4.5% เป็น 4.0% หรือ 2.5x เป็น 2.0x เทสต์ก็ยังผ่าน
    #   (gap%, vol×)  ผ่าน / ไม่ผ่านอย่างละคู่ รอบๆ เส้น 4.5% กับ 2.5x
    _EP_CASES = {280: (1.046, 2.6), 320: (1.044, 2.6),
                 360: (1.046, 2.4), 400: (1.050, 3.0), 470: (1.047, 2.55)}
    for g, (gap, _v) in _EP_CASES.items():
        opn[g] = close[g - 1] * gap
        close[g] = opn[g] * 1.001
    high = np.maximum(opn, close) * (1 + np.abs(rng.normal(0, 0.006, n)))
    low = np.minimum(opn, close) * (1 - np.abs(rng.normal(0, 0.006, n)))
    for k in (150, 300):           # แท่งราคานิ่ง High == Low -> ทดสอบ CMF
        opn[k] = close[k] = high[k] = low[k] = close[k - 1]
    vol = rng.integers(200_000, 3_000_000, n).astype(float)
    for g, (_gap, vx) in _EP_CASES.items():
        vol[g] = vol[g - 20:g].mean() * vx

    # บังคับให้เส้นทาง fallback "ขยายหน้าต่างเป็น 20 วัน" ต่างจาก 15 วันอย่างชัดเจน:
    # แท่ง 261 อยู่ปลายช่วงขึ้นรวด จึงไม่มีวันลงใน 10 วันก่อนหน้า ต้องถอยไปใช้หน้าต่าง
    # 20 วัน = [241, 261) ซึ่งครอบวันลงที่ 242 (วอลุ่มสูงมาก) ส่วนหน้าต่าง 15 วัน
    # = [246, 261) ไม่ครอบ — ตั้งวอลุ่มของแท่ง 261 ให้อยู่ "ระหว่าง" สองค่านี้
    # ผลคือหน้าต่าง 20 วันตัดสินว่าไม่ผ่าน ส่วน 15 วันตัดสินว่าผ่าน เทสต์จึงจับความต่างได้
    vol[241:262] = 1_000_000.0      # พื้นหลังวอลุ่มต่ำสม่ำเสมอ
    vol[242] = 9_000_000.0          # วันลงวอลุ่มหนัก — อยู่เฉพาะในหน้าต่าง 20 วัน
    vol[247] = 1_000_000.0          # วันลงวอลุ่มเบา — อยู่ในหน้าต่างที่สั้นกว่าด้วย
    vol[261] = 5_000_000.0          # สูงกว่า 1M แต่ต่ำกว่า 9M
    return pd.DataFrame({'Open': opn, 'High': high, 'Low': low, 'Close': close, 'Volume': vol},
                        index=pd.bdate_range('2021-01-04', periods=n))





bad = {k: 0 for k in ('pp', 'htf', 'ttm', 'ep', 'acc', 'dist', 'tt',
                      'rvol20', 'turtle', 'cmf')}
seen_true = {k: 0 for k in bad}
bars = 0

for seed in (1, 2, 3, 11, 29):
    df = make_df(seed)
    d = U['_build_preset_indicators'](df)
    # เริ่มที่ 30 เพื่อคร่อมเส้นแบ่ง warm-up ทั้งสองเส้น: _htf_flag_series เริ่มที่แท่ง 34
    # และ tt_price_score เปิดที่แท่ง 220 ถ้าเริ่มเทียบหลังเส้นพวกนี้ การเลื่อนเส้นจะไม่ถูกจับ
    for i in range(30, len(df)):
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

        a, dd = scanner_acc_dist(sub)          # exec ซอร์สจริงจาก utils.py
        bad['acc'] += int(d['acc_days'].iloc[i]) != a
        bad['dist'] += int(d['dist_days'].iloc[i]) != dd
        seen_true['acc'] += a > 0;  seen_true['dist'] += dd > 0

        tt = U['check_trend_template'](sub, rs_rating=0)
        exp = sum(1 for k, v in tt['checks'].items() if k != 'rs_strong' and v)
        bad['tt'] += int(d['tt_price_score'].iloc[i]) != exp
        seen_true['tt'] += exp >= 7

        exp = float(sub['Volume'].iloc[-1]) / float(sub['Volume'].tail(20).mean())
        got = float(d['rvol20'].iloc[i])
        bad['rvol20'] += not (np.isfinite(got) and abs(got - exp) <= 1e-9)
        seen_true['rvol20'] += np.isfinite(got)

        cp = float(sub['Close'].iloc[-1]); h20 = float(sub['High'].tail(20).max())
        exp = (h20 - cp) / cp * 100
        got = float(d['turtle_dist'].iloc[i])
        bad['turtle'] += not (np.isfinite(got) and abs(got - exp) <= 1e-9)
        seen_true['turtle'] += np.isfinite(got)

        # CMF — สูตรของหน้าสแกน (analyze_momentum_technical_v2) ข้าม NaN ด้วย .sum()
        # ส่วนฝั่ง backtest ใช้ fillna(0) + rolling เพื่อให้ได้ผลเดียวกัน แท่งราคานิ่ง
        # (High == Low) ใน fixture มีไว้ทดสอบจุดนี้โดยเฉพาะ
        if len(sub) >= 20:
            _hi, _lo = sub['High'].tail(20), sub['Low'].tail(20)
            _cl, _vo = sub['Close'].tail(20), sub['Volume'].tail(20).astype(float)
            _rng = (_hi - _lo).replace(0, float('nan'))
            exp = float((((_cl - _lo) - (_hi - _cl)) / _rng * _vo).sum() / _vo.sum())
            got = float(d['cmf'].iloc[i])
            bad['cmf'] += not (np.isfinite(got) and abs(got - exp) <= 1e-9)
            seen_true['cmf'] += np.isfinite(got)

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
