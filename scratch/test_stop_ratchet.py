"""ตรวจกติกา "stop ไม่เคยเลื่อนลง" (ข้อ 5)

เคสที่จุดชนวน: AIT ขาดทุน -22.5% ทั้งที่ระบบมีเพดาน -15% เขียนไว้แล้ว
สาเหตุ: Portfolio ไม่มีฟิลด์ stop เลย ช่อง SL ดึงมาจากผลสแกนซึ่งคำนวณโซนใหม่
จากราคาปัจจุบันทุกครั้ง พอราคาลง stop ก็ไหลลงตาม บวกกับสาขา PMS/Dividend/Value
เขียนทับ trailing_stop เองโดยข้ามเพดาน max(stop, entry*0.85) ที่ใส่ไว้ให้

รันจาก repo root: python3 scratch/test_stop_ratchet.py
"""
import ast
import sys
import unittest
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT))

from django.conf import settings

settings.configure(
    SECRET_KEY='offline-test-only',
    INSTALLED_APPS=['django.contrib.auth', 'django.contrib.contenttypes', 'stocks'],
    DATABASES={'default': {'ENGINE': 'django.db.backends.sqlite3', 'NAME': ':memory:'}},
    USE_TZ=True,
)
import django  # noqa: E402

django.setup()

from django.contrib.auth import get_user_model  # noqa: E402
from django.db import connection, transaction  # noqa: E402

from stocks.models import Portfolio  # noqa: E402
from stocks.stop_ratchet import (  # noqa: E402
    MAX_LOSS_FROM_ENTRY_PCT, breach_report, effective_stop, hard_floor,
    is_stop_hit, loss_pct_from_entry, ratchet,
)


class RatchetTests(unittest.TestCase):
    """กติกาเดียว: ขึ้นได้ ลงไม่ได้"""

    def test_never_moves_down(self):
        self.assertEqual(ratchet(10.0, 8.0), 10.0)
        self.assertEqual(ratchet(10.0, 9.99), 10.0)
        self.assertEqual(ratchet(10.0, 0.01), 10.0)

    def test_moves_up(self):
        self.assertEqual(ratchet(10.0, 12.0), 12.0)

    def test_picks_the_highest_candidate(self):
        self.assertEqual(ratchet(5.0, 7.0, 9.0, 6.0), 9.0)

    def test_first_lock(self):
        self.assertEqual(ratchet(None, 9.0), 9.0)

    def test_garbage_is_ignored(self):
        self.assertEqual(ratchet(10.0, None, float('nan'), -5, 0, 'x'), 10.0)
        self.assertIsNone(ratchet(None, None, float('nan'), -5, 'x'))

    def test_repeated_calls_are_monotonic(self):
        """จำลองการรันหน้าพอร์ตหลายรอบขณะราคาผันผวน — stop ต้องไม่ถอย"""
        locked = None
        seen = []
        for trail in [8.0, 9.0, 8.5, 11.0, 6.0, 10.0, 12.0, 3.0]:
            locked = ratchet(locked, trail)
            seen.append(locked)
        self.assertEqual(seen, sorted(seen), f'stop ถอยหลัง: {seen}')
        self.assertEqual(locked, 12.0)


class HardFloorTests(unittest.TestCase):
    def test_floor_is_fifteen_percent_below_entry(self):
        self.assertAlmostEqual(hard_floor(100.0), 85.0)
        self.assertAlmostEqual(hard_floor(6.17), 6.17 * 0.85)

    def test_custom_limit(self):
        self.assertAlmostEqual(hard_floor(100.0, max_loss_pct=10), 90.0)

    def test_bad_entry(self):
        for bad in (0, -1, None, 'x'):
            self.assertEqual(hard_floor(bad), 0.0)


class EffectiveStopTests(unittest.TestCase):
    def test_floor_applies_when_trailing_drifted_below_it(self):
        # นี่คือเคส AIT: val_stop ไหลลงไปต่ำกว่าเพดาน -15%
        eff = effective_stop(100.0, trailing_stop=70.0)
        self.assertAlmostEqual(eff, 85.0, msg='เพดานขาดทุนต้องชนะ trailing ที่ไหลลง')

    def test_trailing_wins_when_it_is_higher(self):
        eff = effective_stop(100.0, trailing_stop=95.0)
        self.assertAlmostEqual(eff, 95.0)

    def test_locked_stop_is_never_given_back(self):
        eff = effective_stop(100.0, locked_stop=110.0, trailing_stop=95.0)
        self.assertAlmostEqual(eff, 110.0, msg='stop ที่ล็อกไว้แล้วต้องไม่ถอย')

    def test_initial_stop_holds_the_line(self):
        eff = effective_stop(100.0, initial_stop=92.0, trailing_stop=88.0)
        self.assertAlmostEqual(eff, 92.0)

    def test_nonsense_initial_stop_above_entry_is_ignored(self):
        # ตั้ง stop เหนือราคาทุน = ข้อมูลเพี้ยน ต้องไม่บังคับขายทิ้งทันที
        eff = effective_stop(100.0, initial_stop=120.0, trailing_stop=95.0)
        self.assertAlmostEqual(eff, 95.0)

    def test_no_entry_price_still_uses_what_it_has(self):
        self.assertAlmostEqual(effective_stop(None, trailing_stop=50.0), 50.0)

    def test_nothing_known_returns_none(self):
        self.assertIsNone(effective_stop(None))
        self.assertIsNone(effective_stop(0, trailing_stop=None))

    def test_every_input_combination_respects_the_floor(self):
        entry = 100.0
        floor = hard_floor(entry)
        for init in (None, 80.0, 92.0):
            for locked in (None, 88.0, 95.0):
                for trail in (None, 60.0, 90.0, 99.0):
                    eff = effective_stop(entry, initial_stop=init,
                                         locked_stop=locked, trailing_stop=trail)
                    self.assertIsNotNone(eff)
                    self.assertGreaterEqual(
                        eff, floor - 1e-9,
                        f'หลุดเพดาน: init={init} locked={locked} trail={trail} -> {eff}')


class BreachReportTests(unittest.TestCase):
    def test_the_ait_case(self):
        """AIT: ทุน ~6.17 ราคา 4.78 = -22.5% ซึ่งเลยเพดาน -15% มา 7.5%"""
        entry = 4.78 / (1 - 0.225)
        eff = effective_stop(entry, trailing_stop=4.20)
        rep = breach_report(entry, 4.78, eff)
        self.assertTrue(rep['over_limit'], 'ต้องจับได้ว่าขาดทุนเกินเพดาน')
        self.assertAlmostEqual(rep['loss_pct'], 22.5, places=1)
        self.assertAlmostEqual(rep['excess_pct'], 7.5, places=1)
        self.assertTrue(rep['stop_hit'])
        self.assertAlmostEqual(eff, entry * 0.85, places=4)

    def test_healthy_position_reports_nothing(self):
        rep = breach_report(100.0, 120.0, 95.0)
        self.assertFalse(rep['over_limit'])
        self.assertFalse(rep['stop_hit'])
        self.assertEqual(rep['excess_pct'], 0.0)

    def test_small_loss_within_limit(self):
        rep = breach_report(100.0, 95.0, 85.0)
        self.assertFalse(rep['over_limit'])
        self.assertAlmostEqual(rep['loss_pct'], 5.0)

    def test_exactly_at_the_limit_is_not_over(self):
        rep = breach_report(100.0, 85.0, 85.0)
        self.assertFalse(rep['over_limit'], 'ที่เพดานพอดียังไม่ถือว่าเกิน')
        self.assertTrue(rep['stop_hit'])

    def test_missing_data_is_safe(self):
        rep = breach_report(None, None, None)
        self.assertIsNone(rep['loss_pct'])
        self.assertFalse(rep['over_limit'])
        self.assertFalse(rep['stop_hit'])


class HelperTests(unittest.TestCase):
    def test_is_stop_hit(self):
        self.assertTrue(is_stop_hit(9.0, 10.0))
        self.assertTrue(is_stop_hit(10.0, 10.0), 'แตะพอดีถือว่าหลุด')
        self.assertFalse(is_stop_hit(11.0, 10.0))
        self.assertFalse(is_stop_hit(9.0, None), 'ไม่มี stop = ตอบไม่ได้')

    def test_loss_pct(self):
        self.assertAlmostEqual(loss_pct_from_entry(100.0, 80.0), 20.0)
        self.assertAlmostEqual(loss_pct_from_entry(100.0, 120.0), -20.0)
        self.assertIsNone(loss_pct_from_entry(0, 80.0))


class ModelFieldTests(unittest.TestCase):
    def test_portfolio_has_the_stop_fields(self):
        names = {f.name for f in Portfolio._meta.get_fields()}
        for field in ('initial_stop', 'locked_stop', 'stop_updated_at'):
            self.assertIn(field, names,
                          f'Portfolio ต้องมี {field} ไม่งั้นไม่มีอะไรยึด stop ไว้กับไม้')

    def test_stop_fields_are_nullable(self):
        # ไม้เก่าที่มีอยู่แล้วต้องไม่พังเพราะยังไม่มีค่า
        for field in ('initial_stop', 'locked_stop', 'stop_updated_at'):
            self.assertTrue(Portfolio._meta.get_field(field).null,
                            f'{field} ต้องเป็น null ได้ เพื่อรองรับไม้ที่มีอยู่ก่อนแล้ว')


class PersistenceTests(unittest.TestCase):
    """จำลองสิ่งที่หน้าพอร์ตทำจริง: คำนวณ stop แล้วบันทึกเมื่อขยับขึ้น"""

    @classmethod
    def setUpClass(cls):
        with connection.schema_editor() as editor:
            editor.create_model(get_user_model())
            editor.create_model(Portfolio)

    def setUp(self):
        self.atomic = transaction.atomic()
        self.atomic.__enter__()
        self.user = get_user_model().objects.create(username=self.id())
        self.item = Portfolio.objects.create(
            user=self.user, symbol='TEST.BK', quantity=1000, entry_price=100)

    def tearDown(self):
        transaction.set_rollback(True)
        self.atomic.__exit__(None, None, None)

    def _tick(self, trailing):
        """หนึ่งรอบของหน้าพอร์ต — ตรรกะเดียวกับใน portfolio_list"""
        eff = effective_stop(self.item.entry_price,
                             initial_stop=self.item.initial_stop,
                             locked_stop=self.item.locked_stop,
                             trailing_stop=trailing)
        if eff and float(self.item.locked_stop or 0) < eff - 1e-9:
            self.item.locked_stop = eff
            self.item.save(update_fields=['locked_stop'])
        return eff

    def test_stop_persists_and_never_decreases(self):
        history = []
        for trail in [90.0, 105.0, 98.0, 130.0, 60.0, 120.0]:
            history.append(self._tick(trail))
        self.item.refresh_from_db()
        self.assertEqual(history, sorted(history), f'stop ถอยหลัง: {history}')
        self.assertAlmostEqual(self.item.locked_stop, 130.0)

    def test_floor_applies_before_anything_is_locked(self):
        eff = self._tick(trailing=50.0)      # trailing ไหลลงไปไกล
        self.assertAlmostEqual(eff, 85.0, msg='เพดาน -15% ต้องรับไว้')
        self.item.refresh_from_db()
        self.assertAlmostEqual(self.item.locked_stop, 85.0)

    def test_existing_rows_without_stops_still_work(self):
        # ไม้เก่าที่มีอยู่ก่อน migration — ทั้งสองฟิลด์เป็น None
        self.assertIsNone(self.item.initial_stop)
        self.assertIsNone(self.item.locked_stop)
        self.assertIsNotNone(self._tick(trailing=None),
                             'ไม่มี trailing ก็ยังต้องได้เพดานจากราคาทุน')

    def test_dca_raising_entry_raises_the_floor(self):
        self._tick(trailing=None)
        self.item.refresh_from_db()
        first = self.item.locked_stop
        self.item.entry_price = 120          # ถัวขึ้น ต้นทุนเฉลี่ยสูงขึ้น
        self.item.save(update_fields=['entry_price'])
        second = self._tick(trailing=None)
        self.assertGreater(second, first, 'ต้นทุนสูงขึ้น เพดานขาดทุนต้องขยับขึ้นตาม')


class WiredInTests(unittest.TestCase):
    """กันไม่ให้ใครถอดสายออกภายหลัง"""

    def setUp(self):
        self.src = (ROOT / 'stocks' / 'views' / 'portfolio.py').read_text(encoding='utf-8')
        self.tree = ast.parse(self.src)

    def test_three_strategy_branches_apply_the_hard_floor(self):
        # PMS / Dividend / Value เคยเขียนทับ trailing_stop โดยข้ามเพดาน
        self.assertEqual(self.src.count('_hard_floor(item.entry_price)'), 3,
                         'ทั้งสามสาขาต้องผ่านเพดานขาดทุน')

    def test_sell_decision_uses_the_locked_stop_not_the_scan_stop(self):
        self.assertIn("_stop_breach['stop_hit']", self.src)
        self.assertIn("_stop_breach['over_limit']", self.src)
        self.assertNotIn('current_price <= mom_data.stop_loss', self.src,
                         'คำสั่งตัดขาดทุนต้องไม่อิง stop จากผลสแกนอีกแล้ว')

    def test_locked_stop_is_persisted(self):
        self.assertIn("item.locked_stop = _eff_stop", self.src)
        self.assertIn("update_fields=['locked_stop', 'stop_updated_at']", self.src)

    def test_initial_stop_is_not_captured_from_a_stale_scan(self):
        self.assertIn("item.initial_stop is None and not getattr(mom_data, 'is_scan_stale', True)",
                      self.src, 'ยึด stop จากผลสแกนที่หมดอายุ = ไม่ได้ยึดอะไรเลย')

    def test_template_shows_the_locked_stop(self):
        tpl = (ROOT / 'stocks' / 'templates' / 'stocks' / 'portfolio.html').read_text(encoding='utf-8')
        self.assertIn('item.effective_stop', tpl)
        self.assertIn('item.stop_breach.over_limit', tpl)

    def test_max_loss_limit_is_defined_once(self):
        mod = (ROOT / 'stocks' / 'stop_ratchet.py').read_text(encoding='utf-8')
        assigns = [t.id for n in ast.parse(mod).body if isinstance(n, ast.Assign)
                   for t in n.targets
                   if isinstance(t, ast.Name) and t.id == 'MAX_LOSS_FROM_ENTRY_PCT']
        self.assertEqual(len(assigns), 1, 'เพดานต้องประกาศที่เดียว')
        self.assertEqual(MAX_LOSS_FROM_ENTRY_PCT, 15.0)


if __name__ == '__main__':
    unittest.main(verbosity=2)
