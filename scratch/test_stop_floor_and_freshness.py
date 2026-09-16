"""ตรวจสองเรื่อง: พื้นระยะ stop ขั้นต่ำ และการหมดอายุของผลสแกน

ข้อ 3 — พื้น stop: stop ที่ชิดราคาเข้ากว่า noise รายวันจะโดนเขี่ยทิ้งแบบสุ่ม
        เคสจริง: หุ้นในพอร์ตมี stop ห่างจากราคาแค่ 0.33%
ข้อ 6 — อายุผลสแกน: ผลสแกนไม่เคยหมดอายุ หน้าพอร์ตจึงโชว์ SL/TP/คะแนนของ
        เมื่อ 3 สัปดาห์ก่อนเหมือนเป็นของสด และ alert ก็ยิงจากโซนที่ไม่มีอยู่แล้ว

ดึงฟังก์ชันพื้น stop ออกจาก utils.py ด้วย ast (ไม่ import ทั้งโมดูล) เพราะ utils.py
ลาก pandas_ta มาด้วย ซึ่งติดตั้งบน Python 3.11 ไม่ได้แล้ว (0.3.x ถูกถอดจาก PyPI)

รันจาก repo root: python3 scratch/test_stop_floor_and_freshness.py
"""
import ast
import sys
import unittest
from datetime import timedelta
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT))

from django.conf import settings

settings.configure(
    SECRET_KEY='offline-test-only',
    INSTALLED_APPS=['django.contrib.auth', 'django.contrib.contenttypes'],
    DATABASES={'default': {'ENGINE': 'django.db.backends.sqlite3', 'NAME': ':memory:'}},
    USE_TZ=True,
)
import django  # noqa: E402

django.setup()

from django.utils import timezone as dj_tz  # noqa: E402

from stocks.scan_freshness import (  # noqa: E402
    SCAN_STALE_AFTER_DAYS, annotate, fresh_cutoff, fresh_only,
    freshness_label, is_stale, scan_age_days,
)

# ── ดึงเฉพาะฟังก์ชันพื้น stop จาก utils.py ──────────────────────────────
_UTILS_SRC = (ROOT / 'stocks' / 'utils.py').read_text(encoding='utf-8')
_TREE = ast.parse(_UTILS_SRC)
_WANTED_FUNCS = {'min_stop_distance', 'apply_min_stop_distance'}
_WANTED_CONSTS = {'MIN_STOP_ATR_MULT', 'MIN_STOP_PCT'}

_ns = {}
_picked = set()
for node in _TREE.body:
    if isinstance(node, ast.FunctionDef) and node.name in _WANTED_FUNCS:
        exec(compile(ast.Module([node], []), 'utils-extract', 'exec'), _ns)
        _picked.add(node.name)
    elif isinstance(node, ast.Assign):
        for t in node.targets:
            if isinstance(t, ast.Name) and t.id in _WANTED_CONSTS:
                exec(compile(ast.Module([node], []), 'utils-extract', 'exec'), _ns)
                _picked.add(t.id)

assert _picked >= _WANTED_FUNCS | _WANTED_CONSTS, f'สกัดจาก utils.py ไม่ครบ: {_picked}'

min_stop_distance = _ns['min_stop_distance']
apply_min_stop_distance = _ns['apply_min_stop_distance']
MIN_STOP_ATR_MULT = _ns['MIN_STOP_ATR_MULT']
MIN_STOP_PCT = _ns['MIN_STOP_PCT']


class MinStopDistanceTests(unittest.TestCase):
    def test_atr_wins_when_volatility_is_high(self):
        # ATR 1.0 บนราคา 20 → 1 ATR = 5% ซึ่งกว้างกว่าพื้น 2%
        self.assertAlmostEqual(min_stop_distance(20.0, atr=1.0), 1.0)

    def test_percent_floor_wins_when_atr_is_tiny(self):
        # นี่คือเคสที่ทำให้เกิดบั๊ก: ATR เล็กผิดปกติ
        self.assertAlmostEqual(min_stop_distance(20.0, atr=0.05), 0.4)   # 2% ของ 20

    def test_no_atr_still_has_a_floor(self):
        self.assertAlmostEqual(min_stop_distance(100.0, atr=0), 2.0)
        self.assertAlmostEqual(min_stop_distance(100.0, atr=None), 2.0)

    def test_bad_input_returns_zero(self):
        for entry in (0, -5, None, 'x'):
            self.assertEqual(min_stop_distance(entry, atr=1.0), 0.0)


class ApplyMinStopDistanceTests(unittest.TestCase):
    def test_the_real_world_bug_case(self):
        """หุ้น 18.20 ที่เคยได้ stop 18.14 (ห่าง 0.33%) ต้องถูกดันลง"""
        entry, bad_stop, atr = 18.20, 18.14, 0.30
        fixed = apply_min_stop_distance(entry, bad_stop, atr)
        self.assertLess(fixed, bad_stop, 'ต้องดัน stop ลง')
        distance_pct = (entry - fixed) / entry * 100
        self.assertGreaterEqual(round(distance_pct, 2), MIN_STOP_PCT,
                                'ระยะ stop ต้องไม่ต่ำกว่าพื้นที่กำหนด')

    def test_wide_stop_is_left_alone(self):
        # stop ที่กว้างอยู่แล้วคือการตัดสินใจของสูตรนั้น ห้ามไปบีบให้แคบลง
        self.assertEqual(apply_min_stop_distance(100.0, 85.0, atr=1.0), 85.0)

    def test_never_moves_a_stop_upward(self):
        for stop in (99.9, 95.0, 90.0, 50.0):
            fixed = apply_min_stop_distance(100.0, stop, atr=1.0)
            self.assertLessEqual(fixed, stop, f'stop {stop} ถูกดันขึ้น ซึ่งห้ามเกิด')

    def test_stop_above_entry_is_pulled_down_to_the_floor(self):
        fixed = apply_min_stop_distance(100.0, 105.0, atr=1.0)
        self.assertLess(fixed, 100.0)
        self.assertAlmostEqual(fixed, 98.0)

    def test_missing_stop_gets_the_floor(self):
        self.assertAlmostEqual(apply_min_stop_distance(100.0, None, atr=1.0), 98.0)
        self.assertAlmostEqual(apply_min_stop_distance(100.0, 0, atr=1.0), 98.0)

    def test_result_is_always_a_usable_stop(self):
        for entry, stop, atr in [(10, 9.99, 0.02), (1.55, 1.548, 0.01),
                                 (260, 259.5, 3.0), (4.78, 4.77, 0.05)]:
            fixed = apply_min_stop_distance(entry, stop, atr)
            self.assertGreater(fixed, 0, 'stop ต้องเป็นบวกเสมอ')
            self.assertLess(fixed, entry, 'stop ต้องต่ำกว่าราคาเข้าเสมอ')

    def test_bad_entry_returns_input_unchanged(self):
        self.assertEqual(apply_min_stop_distance(0, 5.0, 1.0), 5.0)
        self.assertIsNone(apply_min_stop_distance(None, None, 1.0))

    def test_nan_atr_falls_back_to_percent_floor(self):
        nan = float('nan')
        self.assertAlmostEqual(apply_min_stop_distance(100.0, 99.9, nan), 98.0)


class StopFloorIsWiredInTests(unittest.TestCase):
    """กันไม่ให้มีใครคำนวณ stop จากโซนโดยลืมเรียกพื้น"""

    def test_both_zone_functions_apply_the_floor(self):
        for fn in ('find_supply_demand_zones', 'find_supply_demand_zones_v2'):
            node = next(n for n in _TREE.body
                        if isinstance(n, ast.FunctionDef) and n.name == fn)
            calls = {c.func.id for c in ast.walk(node)
                     if isinstance(c, ast.Call) and isinstance(c.func, ast.Name)}
            self.assertIn('apply_min_stop_distance', calls,
                          f'{fn} คำนวณ stop แต่ไม่ได้เรียกพื้นขั้นต่ำ')

    def test_threshold_is_defined_once(self):
        assigns = [t.id for n in _TREE.body if isinstance(n, ast.Assign)
                   for t in n.targets if isinstance(t, ast.Name) and t.id in _WANTED_CONSTS]
        self.assertEqual(sorted(assigns), ['MIN_STOP_ATR_MULT', 'MIN_STOP_PCT'],
                         'ค่าคงที่ต้องประกาศที่เดียว ห้ามพิมพ์ทับ')


class ScanAgeTests(unittest.TestCase):
    def setUp(self):
        self.now = dj_tz.now()

    def _ago(self, days):
        return self.now - timedelta(days=days)

    def test_age_in_days(self):
        self.assertEqual(scan_age_days(self._ago(0), now=self.now), 0)
        self.assertEqual(scan_age_days(self._ago(3), now=self.now), 3)
        self.assertEqual(scan_age_days(self._ago(21), now=self.now), 21)

    def test_missing_timestamp_has_no_age(self):
        self.assertIsNone(scan_age_days(None, now=self.now))

    def test_future_timestamp_clamps_to_zero(self):
        self.assertEqual(scan_age_days(self.now + timedelta(days=2), now=self.now), 0)

    def test_naive_datetime_does_not_raise(self):
        import datetime as _dt
        self.assertIsNone(scan_age_days(_dt.datetime(2026, 1, 1), now=self.now))

    def test_stale_boundary(self):
        self.assertFalse(is_stale(self._ago(SCAN_STALE_AFTER_DAYS), now=self.now),
                         'ที่ขอบพอดียังถือว่าสด')
        self.assertTrue(is_stale(self._ago(SCAN_STALE_AFTER_DAYS + 1), now=self.now))

    def test_unknown_timestamp_is_treated_as_stale(self):
        # พิสูจน์ไม่ได้ว่าสด → ต้องถือว่าเก่า เพราะผู้ใช้เอาไปสั่งซื้อขายจริง
        self.assertTrue(is_stale(None, now=self.now))

    def test_labels_read_naturally(self):
        self.assertEqual(freshness_label(self._ago(0), now=self.now), 'สแกนวันนี้')
        self.assertEqual(freshness_label(self._ago(1), now=self.now), 'สแกนเมื่อวาน')
        self.assertIn('9', freshness_label(self._ago(9), now=self.now))
        self.assertIn('ไม่ทราบ', freshness_label(None, now=self.now))

    def test_cutoff_is_in_the_past(self):
        self.assertLess(fresh_cutoff(now=self.now), self.now)


class _FakeScan:
    def __init__(self, scan_run):
        self.scan_run = scan_run
        self.stop_loss = 9.0


class FreshOnlyAndAnnotateTests(unittest.TestCase):
    def setUp(self):
        self.now = dj_tz.now()

    def test_fresh_scan_passes_through(self):
        obj = _FakeScan(self.now - timedelta(days=2))
        self.assertIs(fresh_only(obj, now=self.now), obj)

    def test_stale_scan_is_dropped(self):
        obj = _FakeScan(self.now - timedelta(days=30))
        self.assertIsNone(fresh_only(obj, now=self.now),
                          'ผลสแกนเก่าต้องไม่ถูกเอาไปขับการตัดสินใจ')

    def test_none_stays_none(self):
        self.assertIsNone(fresh_only(None, now=self.now))
        self.assertIsNone(annotate(None, now=self.now))

    def test_annotate_sets_all_three_fields(self):
        obj = annotate(_FakeScan(self.now - timedelta(days=12)), now=self.now)
        self.assertEqual(obj.scan_age_days, 12)
        self.assertTrue(obj.is_scan_stale)
        self.assertIn('12', obj.scan_freshness_label)

    def test_annotate_keeps_fresh_data_usable(self):
        obj = annotate(_FakeScan(self.now - timedelta(days=1)), now=self.now)
        self.assertFalse(obj.is_scan_stale)
        self.assertEqual(obj.stop_loss, 9.0, 'ต้องไม่ไปแตะข้อมูลเดิม')


class FreshnessIsWiredInTests(unittest.TestCase):
    """ทางที่ตัดสินใจต้องกรองอายุ — กันไม่ให้ใครเผลอถอดออก"""

    def _src(self, rel):
        return (ROOT / rel).read_text(encoding='utf-8')

    def test_alert_engine_latest_scan_filters_stale(self):
        src = self._src('stocks/alert_engine.py')
        self.assertIn('fresh_only(qs.order_by', src,
                      '_latest_scan ต้องกรองผลสแกนเก่าออก ไม่งั้น alert ยิงจากโซนที่หมดอายุ')

    def test_alert_engine_has_no_hardcoded_seven_day_checks(self):
        src = self._src('stocks/alert_engine.py')
        self.assertNotIn('age.days > 7', src,
                         'เกณฑ์อายุต้องมาจาก SCAN_STALE_AFTER_DAYS ที่เดียว')

    def test_telegram_monitor_filters_stale(self):
        src = self._src('stocks/management/commands/monitor_stocks.py')
        self.assertEqual(src.count('fresh_only('), 2,
                         'ทั้งฝั่ง watchlist และฝั่งพอร์ตต้องกรองอายุ')

    def test_portfolio_does_not_trigger_stop_loss_from_stale_scan(self):
        src = self._src('stocks/views/portfolio.py')
        self.assertIn('(not _scan_stale) and getattr(mom_data, \'stop_loss\', None)', src,
                      'คำสั่ง "ตัดขาดทุนทั้งหมด" ต้องไม่มาจากผลสแกนที่หมดอายุ')

    def test_position_sizing_prefill_filters_stale(self):
        src = self._src('stocks/views/portfolio.py')
        self.assertIn('_fresh_only(PrecisionScanCandidate.objects', src,
                      'ราคา/stop ที่ใช้คำนวณขนาดไม้ต้องสด')

    def test_portfolio_template_shows_the_age_badge(self):
        src = self._src('stocks/templates/stocks/portfolio.html')
        self.assertIn('is_scan_stale', src)
        self.assertIn('scan_freshness_label', src)


if __name__ == '__main__':
    unittest.main(verbosity=2)
