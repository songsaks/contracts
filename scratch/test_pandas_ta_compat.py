"""ตรวจว่าโปรเจกต์ยังหา pandas_ta เจอ หลังจาก pin เปลี่ยนไปใช้ fork

ที่มา: requirements.txt เคย pin `pandas-ta==0.3.14b1` ซึ่ง
  1. ถูกถอดออกจาก PyPI ไปแล้ว — `pip install -r requirements.txt` จากเครื่องเปล่าจะล้ม
  2. ถึงหาเจอก็ import ไม่ผ่านกับ numpy 2.x ที่ pin ไว้ (เรียก np.NaN ที่ถูกถอดไปแล้ว)

เปลี่ยนไปใช้ pandas-ta-classic ซึ่ง fork จาก 0.3.14b1 ตัวนั้นพอดี
โค้ดเรียกผ่าน stocks/pandas_ta_compat.py ที่รองรับทั้งสองชื่อแพ็กเกจ เพื่อให้เครื่อง
ที่ยังไม่ได้อัปเดตแพ็กเกจรันต่อได้ ไม่ต้องอัปแพ็กเกจกับ deploy พร้อมกัน

รันจาก repo root: python3 scratch/test_pandas_ta_compat.py
"""
import ast
import re
import sys
import unittest
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT))

import numpy as np  # noqa: E402
import pandas as pd  # noqa: E402

from stocks.pandas_ta_compat import backend_name, backend_version, ta  # noqa: E402

# ฟังก์ชันที่โปรเจกต์เรียกใช้จริง (นับจาก grep ta.* ทั้ง stocks/)
USED_FUNCS = ('ema', 'rsi', 'sma', 'adx', 'atr', 'macd', 'mfi', 'bbands')


def _series(n=120, seed=7):
    rng = np.random.default_rng(seed)
    close = pd.Series(np.cumsum(rng.normal(0.05, 1.0, n)) + 100)
    high = close + np.abs(rng.normal(0.6, 0.3, n))
    low = close - np.abs(rng.normal(0.6, 0.3, n))
    vol = pd.Series(rng.integers(1_000_000, 9_000_000, n).astype(float))
    return high, low, close, vol


class BackendResolutionTests(unittest.TestCase):
    def test_a_backend_was_found(self):
        self.assertIsNotNone(ta)
        self.assertIn(backend_name, ('pandas_ta_classic', 'pandas_ta'))

    def test_version_is_reportable(self):
        self.assertTrue(backend_version())

    def test_every_function_the_project_uses_exists(self):
        missing = [f for f in USED_FUNCS if not callable(getattr(ta, f, None))]
        self.assertEqual(missing, [], f'backend {backend_name} ขาดฟังก์ชัน: {missing}')


class IndicatorsActuallyComputeTests(unittest.TestCase):
    """stub ที่คืน None เงียบๆ เคยทำให้เทสต์พังกลางทางแล้วดูเหมือนโค้ดจริงมีบั๊ก"""

    def setUp(self):
        self.high, self.low, self.close, self.vol = _series()

    def test_single_series_indicators(self):
        for name, kwargs in (('ema', {'length': 14}), ('sma', {'length': 20}),
                             ('rsi', {'length': 14})):
            out = getattr(ta, name)(self.close, **kwargs)
            self.assertIsInstance(out, pd.Series, f'{name} คืนค่าผิดชนิด')
            self.assertTrue(out.notna().any(), f'{name} คืน NaN ทั้งชุด')

    def test_ohlc_indicators(self):
        atr = ta.atr(self.high, self.low, self.close, length=14)
        self.assertIsInstance(atr, pd.Series)
        self.assertTrue(atr.notna().any())

        adx = ta.adx(self.high, self.low, self.close, length=14)
        self.assertIsInstance(adx, pd.DataFrame)
        self.assertTrue(any('ADX' in c for c in adx.columns))

        mfi = ta.mfi(self.high, self.low, self.close, self.vol, length=14)
        self.assertIsInstance(mfi, pd.Series)
        self.assertTrue(mfi.notna().any())

    def test_frame_indicators_keep_the_column_names_the_code_greps_for(self):
        # โค้ดหาคอลัมน์ด้วย substring ('BBU' in c) ไม่ใช่ชื่อเต็ม จึงทนการเปลี่ยนชื่อได้
        # แต่ substring หลักต้องยังอยู่ ไม่งั้นเจอ None เงียบๆ
        bb = ta.bbands(self.close, length=20, std=2)
        self.assertIsInstance(bb, pd.DataFrame)
        for token in ('BBU', 'BBL', 'BBM'):
            self.assertTrue(any(token in c for c in bb.columns),
                            f'bbands ไม่มีคอลัมน์ที่มี {token}: {list(bb.columns)}')

        macd = ta.macd(self.close)
        self.assertIsInstance(macd, pd.DataFrame)
        self.assertTrue(any('MACD' in c for c in macd.columns))

    def test_rsi_stays_in_range(self):
        rsi = ta.rsi(self.close, length=14).dropna()
        self.assertTrue(((rsi >= 0) & (rsi <= 100)).all())

    def test_atr_is_never_negative(self):
        atr = ta.atr(self.high, self.low, self.close, length=14).dropna()
        self.assertTrue((atr >= 0).all())


class NoBareImportsLeftTests(unittest.TestCase):
    """กันไม่ให้ใครเผลอเขียน `import pandas_ta` ตรงๆ กลับมาอีก

    ถ้าเขียนตรงๆ โค้ดจะพังทันทีบนเครื่องที่ติดตั้งตาม requirements.txt ปัจจุบัน
    เพราะแพ็กเกจชื่อ pandas_ta ไม่มีอยู่แล้ว
    """

    BARE = re.compile(r'^[ \t]*import pandas_ta\b', re.M)

    def _py_files(self):
        for pat in ('stocks/**/*.py', 'scratch/*.py', '*.py'):
            for p in ROOT.glob(pat):
                if p.name != 'pandas_ta_compat.py' and 'v312' not in p.parts:
                    yield p

    def test_no_file_imports_pandas_ta_directly(self):
        offenders = []
        for p in self._py_files():
            try:
                if self.BARE.search(p.read_text(encoding='utf-8')):
                    offenders.append(str(p.relative_to(ROOT)))
            except (UnicodeDecodeError, OSError):
                continue
        self.assertEqual(offenders, [],
                         f'ต้องใช้ `from stocks.pandas_ta_compat import ta` แทน: {offenders}')

    def test_the_shim_itself_is_the_only_place_that_names_the_packages(self):
        shim = (ROOT / 'stocks' / 'pandas_ta_compat.py').read_text(encoding='utf-8')
        self.assertIn('pandas_ta_classic', shim)
        self.assertIn('pandas_ta', shim)


class RequirementsTests(unittest.TestCase):
    def setUp(self):
        self.req = (ROOT / 'requirements.txt').read_text(encoding='utf-8')

    def test_dead_pin_is_gone(self):
        active = [ln.strip() for ln in self.req.splitlines()
                  if ln.strip() and not ln.strip().startswith('#')]
        self.assertNotIn('pandas-ta==0.3.14b1', active,
                         'เวอร์ชันนี้ถูกถอดจาก PyPI แล้ว ติดตั้งไม่ได้')

    def test_the_replacement_is_pinned(self):
        self.assertIn('pandas-ta-classic==0.3.78', self.req)

    def test_the_reason_is_written_down(self):
        # คนที่มาอ่านทีหลังต้องรู้ว่าทำไมถึงไม่ใช่ pandas-ta ตัวปกติ
        self.assertIn('PyPI', self.req)

    def test_pinned_version_matches_what_the_shim_suggests(self):
        shim = (ROOT / 'stocks' / 'pandas_ta_compat.py').read_text(encoding='utf-8')
        m = re.search(r'pandas-ta-classic==([\w.]+)', self.req)
        self.assertIsNotNone(m)
        self.assertIn(m.group(1), shim,
                      'ข้อความแนะนำใน shim ต้องบอกเวอร์ชันเดียวกับที่ pin ไว้')


class ImportSitesAreValidTests(unittest.TestCase):
    def test_every_rewritten_import_parses_and_names_ta(self):
        pat = re.compile(r'^[ \t]*from stocks\.pandas_ta_compat import ta(?: as (\w+))?[ \t]*$', re.M)
        total = 0
        for p in ROOT.glob('stocks/**/*.py'):
            src = p.read_text(encoding='utf-8')
            if 'pandas_ta_compat' not in src or p.name == 'pandas_ta_compat.py':
                continue
            ast.parse(src)                       # ต้อง parse ผ่าน
            total += len(pat.findall(src))
        self.assertGreater(total, 20, 'จำนวนจุด import ดูน้อยผิดปกติ')


if __name__ == '__main__':
    unittest.main(verbosity=2)
