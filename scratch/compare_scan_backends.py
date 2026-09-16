"""ดัมพ์ผลของฟังก์ชันวิเคราะห์ทั้งชุด เพื่อเทียบก่อน/หลังเปลี่ยน dependency

ใช้ตอบคำถาม "เปลี่ยนไลบรารีแล้วผลสแกนเปลี่ยนไหม" โดยไม่ต้องเดา
เทียบผลลัพธ์ของฟังก์ชันสแกนจริง 22 ตัว + indicator ดิบที่ views เรียกตรงๆ
บนข้อมูลจำลอง 5 สภาพตลาด (ขาขึ้น/ขาลง/ไซด์เวย์/เบรกเอาต์/ฐานแคบ)
seed คงที่ ผลจึงเทียบกันได้ข้ามเครื่องและข้ามเวลา

วิธีใช้:
    # 1. ดัมพ์ผลด้วยของเดิม
    pip install "pandas-ta-classic==0.3.14b2"
    python3 scratch/compare_scan_backends.py /tmp/before.json

    # 2. ดัมพ์ผลด้วยของใหม่
    pip install -r requirements.txt
    python3 scratch/compare_scan_backends.py /tmp/after.json

    # 3. เทียบ
    python3 scratch/compare_scan_diff.py /tmp/before.json /tmp/after.json

อยากใช้ข้อมูลจริงแทนข้อมูลจำลอง: แก้ make_ohlcv() ให้อ่านจาก yfinance หรือ CSV
ของหุ้นที่ถืออยู่จริง จะได้คำตอบที่ตรงกับพอร์ตตัวเองมากกว่า

ผลที่บันทึกไว้ตอนเปลี่ยนจาก pandas-ta เป็น pandas-ta-classic:
    0.3.14b2 -> 0.3.78     : 2135 ค่าตรงกัน ต่าง 0 (ยกเว้น mfi ที่ b2 พังแล้ว 0.3.78 แก้ให้)
    0.3.78   -> 0.4.71b0   : ฟังก์ชันสแกน 1645 ค่าตรงกันหมด ต่างเฉพาะ indicator ดิบ (bbands, ADXR)
"""
import json
import sys
import warnings

warnings.filterwarnings('ignore')
sys.path.insert(0, '/home/user/contracts')

import django
from django.conf import settings

settings.configure(
    SECRET_KEY='x',
    INSTALLED_APPS=['django.contrib.auth', 'django.contrib.contenttypes', 'stocks'],
    DATABASES={'default': {'ENGINE': 'django.db.backends.sqlite3', 'NAME': ':memory:'}},
    USE_TZ=True,
    CACHES={'default': {'BACKEND': 'django.core.cache.backends.locmem.LocMemCache'}},
)
django.setup()

import numpy as np
import pandas as pd

from stocks import ultra_indicators as UI
from stocks import utils as U
from stocks.pandas_ta_compat import backend_name, backend_version


# ────────────────────────────────────────────────────────────────
# ชุดข้อมูลจำลองหลายสภาพตลาด — seed คงที่ ผลจึงเทียบกันได้ทุกครั้ง
# ────────────────────────────────────────────────────────────────
def make_ohlcv(kind, n=320, seed=11):
    rng = np.random.default_rng(seed)
    t = np.arange(n)
    if kind == 'uptrend':
        base = 20 + t * 0.06 + np.sin(t / 18) * 1.1
        vol_mult = 1.0
    elif kind == 'downtrend':
        base = 60 - t * 0.09 + np.sin(t / 15) * 1.4
        vol_mult = 1.2
    elif kind == 'choppy':
        base = 35 + np.sin(t / 9) * 3.2 + rng.normal(0, 0.6, n).cumsum() * 0.12
        vol_mult = 0.9
    elif kind == 'breakout':
        base = np.where(t < n - 45, 25 + np.sin(t / 22) * 0.9, 25 + (t - (n - 45)) * 0.42)
        vol_mult = 1.6
    elif kind == 'tight_base':
        base = 18 + np.concatenate([np.linspace(0, 4, n - 60), np.full(60, 4.0)])
        vol_mult = 0.7
    else:
        raise ValueError(kind)

    noise = rng.normal(0, 0.28, n)
    close = np.maximum(base + noise, 0.5)
    op = np.maximum(close + rng.normal(0, 0.22, n), 0.4)
    spread = np.abs(rng.normal(0.34, 0.16, n))
    high = np.maximum(close, op) + spread
    low = np.minimum(close, op) - spread
    low = np.maximum(low, 0.2)
    vol = (rng.integers(900_000, 7_000_000, n) * vol_mult).astype(float)
    # ใส่แท่งวอลุ่มพุ่ง เพื่อให้ ERC / episodic pivot มีโอกาสติด
    for i in (n - 3, n - 40, n - 120):
        if 0 <= i < n:
            vol[i] *= 4.2
            close[i] = close[i] * 1.06
            high[i] = max(high[i], close[i] * 1.01)

    idx = pd.date_range('2024-01-01', periods=n, freq='B')
    return pd.DataFrame({'Open': op, 'High': high, 'Low': low,
                         'Close': close, 'Volume': vol}, index=idx)


def norm(x, depth=0):
    """ทำให้ผลลัพธ์กลายเป็นอะไรที่ JSON เก็บได้ และเทียบกันได้"""
    if depth > 6:
        return '<deep>'
    if x is None or isinstance(x, (bool, str)):
        return x
    if isinstance(x, (int, np.integer)):
        return int(x)
    if isinstance(x, (float, np.floating)):
        return None if (x != x) else round(float(x), 6)
    if isinstance(x, dict):
        return {str(k): norm(v, depth + 1) for k, v in x.items()}
    if isinstance(x, (list, tuple, set)):
        return [norm(v, depth + 1) for v in list(x)[:40]]
    if isinstance(x, pd.Series):
        return [norm(v, depth + 1) for v in x.tail(8)]
    if isinstance(x, pd.DataFrame):
        return {str(c): [norm(v, depth + 1) for v in x[c].tail(6)] for c in x.columns}
    if isinstance(x, np.ndarray):
        return [norm(v, depth + 1) for v in x[-8:]]
    if hasattr(x, 'isoformat'):
        return x.isoformat()
    return str(x)


# ฟังก์ชันวิเคราะห์ตัวจริงที่สแกนเนอร์เรียกใช้
CALLS = [
    ('analyze_momentum_technical_v2', lambda d: U.analyze_momentum_technical_v2(d)),
    ('analyze_momentum_technical',    lambda d: U.analyze_momentum_technical(d)),
    ('find_supply_demand_zones',      lambda d: U.find_supply_demand_zones(d)),
    ('find_supply_demand_zones_v2',   lambda d: U.find_supply_demand_zones_v2(d)),
    ('check_trend_template',          lambda d: U.check_trend_template(d, 85)),
    ('detect_price_pattern',          lambda d: U.detect_price_pattern(d)),
    ('detect_vcp_pattern',            lambda d: U.detect_vcp_pattern(d)),
    ('detect_cup_and_handle',         lambda d: U.detect_cup_and_handle(d)),
    ('detect_abcd_pattern',           lambda d: U.detect_abcd_pattern(d)),
    ('detect_cheat_entry',            lambda d: U.detect_cheat_entry(d)),
    ('detect_wyckoff_spring',         lambda d: U.detect_wyckoff_spring(d)),
    ('detect_wyckoff_upthrust',       lambda d: U.detect_wyckoff_upthrust(d)),
    ('detect_selling_climax',         lambda d: U.detect_selling_climax(d)),
    ('detect_effort_result_div',      lambda d: U.detect_effort_result_divergence(d)),
    ('calculate_volume_profile',      lambda d: U.calculate_volume_profile(d)),
    ('calculate_atr_trailing_stop',   lambda d: U.calculate_atr_trailing_stop(
        d, float(d['Close'].iloc[0]), float(d['High'].max()), 2.5)),
    ('htf_setup',                     lambda d: UI.calculate_htf_setup(d)),
    ('ttm_squeeze',                   lambda d: UI.calculate_ttm_squeeze(d)),
    ('episodic_pivot',                lambda d: UI.calculate_episodic_pivot(d)),
    ('avoidance_and_adr',             lambda d: UI.calculate_avoidance_and_adr(d)),
    ('best_loser_metrics',            lambda d: UI.calculate_best_loser_metrics(
        d, float(d['Close'].iloc[-1]), float(d['Close'].iloc[-1]) * 1.2,
        float(d['Close'].iloc[-1]) * 0.92)),
]

# indicator ที่ views/scanners.py เรียกตรงๆ (ไม่ได้ผ่าน utils) — สำคัญเพราะ mfi
# คือจุดที่รุ่นเก่าพังกับ pandas 3.x ถ้าไม่ทดสอบตรงนี้จะมองไม่เห็น
from stocks.pandas_ta_compat import ta as _TA
CALLS += [
    ('raw_mfi14',   lambda d: _TA.mfi(d['High'], d['Low'], d['Close'], d['Volume'], length=14)),
    ('raw_adx14',   lambda d: _TA.adx(d['High'], d['Low'], d['Close'], length=14)),
    ('raw_bbands',  lambda d: _TA.bbands(d['Close'], length=20, std=2)),
    ('raw_macd',    lambda d: _TA.macd(d['Close'])),
    ('raw_rsi14',   lambda d: _TA.rsi(d['Close'], length=14)),
    ('raw_atr14',   lambda d: _TA.atr(d['High'], d['Low'], d['Close'], length=14)),
    ('raw_ema200',  lambda d: _TA.ema(d['Close'], length=200)),
    ('raw_sma50',   lambda d: _TA.sma(d['Close'], length=50)),
]

# backtest ใช้ตัวชี้วัดชุดเดียวกับหน้าสแกน จึงเป็นตัวจับความต่างที่ดี
PRESET_CALLS = [
    ('run_all_presets_backtest', lambda d: U.run_all_presets_backtest(d)),
]

out = {'_backend': f'{backend_name} {backend_version()}', 'results': {}}
for kind in ('uptrend', 'downtrend', 'choppy', 'breakout', 'tight_base'):
    df = make_ohlcv(kind)
    bucket = {}
    for name, fn in CALLS + PRESET_CALLS:
        try:
            bucket[name] = norm(fn(df.copy()))
        except Exception as e:
            bucket[name] = {'__ERROR__': f'{type(e).__name__}: {str(e)[:160]}'}
    out['results'][kind] = bucket

with open(sys.argv[1], 'w') as fh:
    json.dump(out, fh, sort_keys=True, indent=0)
print(f"backend={out['_backend']}  เขียนแล้ว {sys.argv[1]}")
