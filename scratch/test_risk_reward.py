"""ตรวจ R:R จากราคาปัจจุบัน (ข้อ 2)

ปัญหาเดิม: risk_reward_ratio ที่เก็บไว้คิดตอนสแกนด้วยสมมติฐานว่าเข้าที่ขอบบน
ของ demand zone (entry_price = refined_upper) ซึ่งเป็น RR ของ *setup*
พอถือแล้วราคาขยับ ไม่เคยมีใครคิดใหม่ว่า "จากตรงนี้ไปข้างหน้ายังคุ้มอยู่ไหม"

PrecisionScanCandidate.current_rr ทำเรื่องนี้อยู่ แต่ใช้ได้เฉพาะหน้าสแกนเพราะ
ต้องมี live_price ที่ scanners.py เซ็ตให้ — หน้าพอร์ตไม่เคยเซ็ต จึงตกไปใช้ราคา
ณ วันที่สแกน และยังอิง stop_loss จากผลสแกนที่ไหลลงตามราคา (ดูข้อ 5)

ผลจริงในพอร์ต: AIT ได้ 0.78 และ BCP 0.80 คือเสี่ยงมากกว่าที่จะได้ แต่ไม่มีอะไรเตือน

รันจาก repo root: python3 scratch/test_risk_reward.py
"""
import sys
import unittest
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT))

from stocks.risk_reward import (  # noqa: E402
    MIN_MEANINGFUL_RISK_PCT, RR_MIN_OK, RR_POOR, STATUS_OK, STATUS_POOR,
    STATUS_STOP_HIT, STATUS_TARGET_HIT, STATUS_THIN, STATUS_UNKNOWN,
    STATUS_UNRELIABLE, assess, badge_color, current_rr, rr_status,
)

# (symbol, ราคา, SL, TP) จากหน้าพอร์ตจริง
REAL_ROWS = [
    ('AIT', 4.78, 4.60, 4.92), ('BA', 18.20, 18.14, 20.66),
    ('BCH', 11.20, 10.67, 13.42), ('BCP', 54.00, 45.85, 60.50),
    ('CCET', 9.10, 9.07, 11.14), ('CHG', 1.55, 1.48, 1.70),
    ('SCC', 260.00, 251.30, 280.61), ('TASCO', 17.10, 16.58, 19.14),
]


class CurrentRrTests(unittest.TestCase):
    def test_basic_maths(self):
        # ราคา 10 / stop 9 (เสี่ยง 1) / เป้า 13 (ได้ 3) -> 3:1
        self.assertAlmostEqual(current_rr(10, 9, 13), 3.0)

    def test_matches_the_real_portfolio(self):
        got = {s: round(current_rr(p, sl, tp), 2) for s, p, sl, tp in REAL_ROWS}
        self.assertAlmostEqual(got['AIT'], 0.78, places=2)
        self.assertAlmostEqual(got['BCP'], 0.80, places=2)
        self.assertAlmostEqual(got['BCH'], 4.19, places=2)

    def test_price_at_or_below_stop_is_meaningless(self):
        self.assertIsNone(current_rr(9.0, 9.0, 13))
        self.assertIsNone(current_rr(8.0, 9.0, 13))

    def test_price_at_or_above_target_has_no_upside(self):
        self.assertIsNone(current_rr(13.0, 9.0, 13.0))
        self.assertIsNone(current_rr(14.0, 9.0, 13.0))

    def test_missing_or_bad_input(self):
        for args in ((None, 9, 13), (10, None, 13), (10, 9, None),
                     (0, 9, 13), ('x', 9, 13), (10, 9, float('nan'))):
            self.assertIsNone(current_rr(*args))


class RrStatusTests(unittest.TestCase):
    def test_bands_follow_the_thresholds_the_system_already_uses(self):
        self.assertEqual(rr_status(0.5), STATUS_POOR)
        self.assertEqual(rr_status(RR_POOR - 0.01), STATUS_POOR)
        self.assertEqual(rr_status(RR_POOR), STATUS_THIN)
        self.assertEqual(rr_status(RR_MIN_OK - 0.01), STATUS_THIN)
        self.assertEqual(rr_status(RR_MIN_OK), STATUS_OK)
        self.assertEqual(rr_status(5.0), STATUS_OK)
        self.assertEqual(rr_status(None), STATUS_UNKNOWN)


class AssessTests(unittest.TestCase):
    def test_flags_the_real_problems_and_says_which_kind(self):
        """สองแบบคนละเรื่อง ต้องแยกให้ออก ไม่ใช่เหมารวมว่า 'เตือน'

        AIT / BCP  — เสี่ยงมากกว่าได้จริงๆ (R:R < 1)
        BA / CCET  — R:R ดูสูงลิ่ว แต่มาจาก stop ที่ชิดจนเชื่อตัวเลขไม่ได้
        """
        by_status = {}
        for s, p, sl, tp in REAL_ROWS:
            by_status.setdefault(assess(p, sl, tp)['status'], []).append(s)

        self.assertEqual(by_status.get(STATUS_POOR), ['AIT', 'BCP'])
        self.assertEqual(by_status.get(STATUS_UNRELIABLE), ['BA', 'CCET'])
        self.assertEqual(sorted(by_status.get(STATUS_OK)),
                         ['BCH', 'CHG', 'SCC', 'TASCO'])

    def test_unreliable_is_flagged_but_not_confused_with_poor(self):
        unreliable = assess(18.20, 18.14, 20.66)
        poor = assess(4.78, 4.60, 4.92)
        self.assertTrue(unreliable['is_warning'] and poor['is_warning'])
        self.assertNotEqual(unreliable['status'], poor['status'],
                            'คนละปัญหา ต้องบอกคนละอย่าง')

    def test_poor_case_explains_itself_in_percentages(self):
        a = assess(4.78, 4.60, 4.92)      # AIT
        self.assertEqual(a['status'], STATUS_POOR)
        self.assertTrue(a['is_warning'])
        self.assertAlmostEqual(a['rr'], 0.78, places=2)
        # ได้อีก ~2.9% แต่เสี่ยง ~3.8%
        self.assertLess(a['reward_pct'], a['risk_pct'])
        self.assertIn('%', a['detail'])

    def test_healthy_case(self):
        a = assess(11.20, 10.67, 13.42)   # BCH
        self.assertEqual(a['status'], STATUS_OK)
        self.assertFalse(a['is_warning'])
        self.assertGreater(a['reward_pct'], a['risk_pct'])

    def test_stop_hit_is_its_own_state_not_a_zero(self):
        a = assess(9.0, 10.0, 15.0)
        self.assertEqual(a['status'], STATUS_STOP_HIT)
        self.assertIsNone(a['rr'], 'ไม่ควรยัดเป็น 0 แล้วจบ')
        self.assertTrue(a['is_warning'])

    def test_target_hit_is_its_own_state(self):
        a = assess(16.0, 10.0, 15.0)
        self.assertEqual(a['status'], STATUS_TARGET_HIT)
        self.assertIsNone(a['rr'])
        self.assertTrue(a['is_warning'])
        self.assertIn('เป้าหมาย', a['label'])

    def test_thin_case_is_not_a_warning_but_is_labelled(self):
        # ราคา 10 / stop 9 / เป้า 11.2 -> RR 1.2 (ระหว่าง 1.0 กับ 1.5)
        a = assess(10.0, 9.0, 11.2)
        self.assertEqual(a['status'], STATUS_THIN)
        self.assertFalse(a['is_warning'])
        self.assertIn('1.5', a['detail'])

    def test_always_returns_a_dict_with_every_key(self):
        keys = {'rr', 'status', 'label', 'detail', 'risk', 'reward',
                'risk_pct', 'reward_pct', 'is_warning'}
        for args in ((None, None, None), (10, 9, 13), (9, 10, 13), (16, 10, 15)):
            self.assertEqual(set(assess(*args)) , keys,
                             'template ต้องไม่ต้องเช็ค None เอง')

    def test_unknown_when_data_is_missing(self):
        a = assess(10.0, None, 15.0)
        self.assertEqual(a['status'], STATUS_UNKNOWN)
        self.assertIn('ข้อมูลไม่พอ', a['detail'])


class BadgeColorTests(unittest.TestCase):
    def test_every_status_has_a_colour(self):
        for st in (STATUS_OK, STATUS_THIN, STATUS_POOR, STATUS_STOP_HIT,
                   STATUS_TARGET_HIT, STATUS_UNKNOWN):
            self.assertTrue(badge_color(st))
        self.assertEqual(badge_color(STATUS_POOR), 'danger')
        self.assertEqual(badge_color(STATUS_OK), 'success')

    def test_unknown_status_falls_back(self):
        self.assertEqual(badge_color('something-else'), 'secondary')


class UnreliableRatioTests(unittest.TestCase):
    """stop ที่ชิดกว่า noise รายวันทำให้ตัวหารเล็กจน R:R พองเกินจริง"""

    def test_razor_thin_stop_produces_a_silly_number(self):
        # BA ตามที่โชว์เดิม: stop ห่างแค่ 0.33% -> ได้ 41:1
        self.assertGreater(current_rr(18.20, 18.14, 20.66), 40)

    def test_but_assess_refuses_to_call_it_good(self):
        a = assess(18.20, 18.14, 20.66)
        self.assertEqual(a['status'], STATUS_UNRELIABLE,
                         'R:R 41:1 จาก stop ห่าง 0.33% ต้องไม่ถูกโชว์เป็นของดี')
        self.assertTrue(a['is_warning'])
        self.assertIn('0.33%', a['detail'])

    def test_ccet_case_too(self):
        a = assess(9.10, 9.07, 11.14)      # 68:1
        self.assertEqual(a['status'], STATUS_UNRELIABLE)

    def test_a_normal_stop_is_trusted(self):
        a = assess(11.20, 10.67, 13.42)    # BCH, stop ห่าง 4.7%
        self.assertEqual(a['status'], STATUS_OK)

    def test_threshold_matches_the_stop_floor_in_utils(self):
        """ต้องตรงกับ utils.MIN_STOP_PCT — อ่านด้วย ast เพื่อไม่ต้อง import pandas_ta"""
        import ast
        tree = ast.parse((ROOT / 'stocks' / 'utils.py').read_text(encoding='utf-8'))
        found = [n.value.value for n in tree.body if isinstance(n, ast.Assign)
                 for t in n.targets
                 if isinstance(t, ast.Name) and t.id == 'MIN_STOP_PCT']
        self.assertEqual(found, [MIN_MEANINGFUL_RISK_PCT],
                         'เกณฑ์ "stop ชิดเกินไป" ต้องเป็นค่าเดียวกับพื้นระยะ stop ขั้นต่ำ')

    def test_locked_stop_brings_it_back_to_earth(self):
        # BA ขาดทุน -7.8% -> ทุนราว 19.74 -> เพดาน -15% อยู่ที่ราว 16.78
        from stocks.stop_ratchet import effective_stop
        entry = 18.20 / (1 - 0.078)
        eff = effective_stop(entry, trailing_stop=None)
        rr = current_rr(18.20, eff, 20.66)
        self.assertLess(rr, 5, 'ใช้ stop ที่ล็อกไว้แล้วตัวเลขต้องสมเหตุผล')
        self.assertGreater(rr, 1)


class WiredInTests(unittest.TestCase):
    def setUp(self):
        self.view_src = (ROOT / 'stocks' / 'views' / 'portfolio.py').read_text(encoding='utf-8')
        self.tpl_src = (ROOT / 'stocks' / 'templates' / 'stocks' / 'portfolio.html').read_text(encoding='utf-8')

    def test_portfolio_computes_rr_from_the_live_price_and_locked_stop(self):
        self.assertIn('_assess_rr(current_price, _eff_stop,', self.view_src,
                      'ต้องใช้ราคาสดกับ stop ที่ล็อกไว้ ไม่ใช่ราคา/stop จากผลสแกน')
        self.assertIn("'rr_now': _rr_now", self.view_src)

    def test_stale_target_is_marked(self):
        self.assertIn("_rr_now['target_is_stale']", self.view_src,
                      'เป้าหมายมาจากผลสแกน ถ้าเก่าต้องบอก')

    def test_both_views_show_it(self):
        # หนึ่งบล็อกต่อหนึ่งมุมมอง — ตาราง (คอลัมน์ TP) และการ์ด (กล่อง Stop Loss)
        self.assertEqual(self.tpl_src.count('{% elif item.rr_now.rr %}'), 2,
                         'ต้องโชว์ตัวเลข R:R ทั้งมุมมองตารางและมุมมองการ์ด')
        self.assertEqual(self.tpl_src.count("item.rr_now.status == 'target_hit'"), 2,
                         'เคส "ถึงเป้าแล้ว" ก็ต้องโชว์ทั้งสองมุมมอง')
        self.assertEqual(self.tpl_src.count("item.rr_now.status == 'unreliable'"), 2,
                         'เคส "เชื่อไม่ได้" ต้องไม่ถูกโชว์เป็นตัวเลขสวยๆ ในมุมมองไหนเลย')

    def test_card_view_uses_the_locked_stop_too(self):
        # เคยเขียนเป็น item.effective_stop|default:item.trailing_stop_data.trailing_stop
        # ซึ่งพังทั้งหน้าเมื่อ trailing_stop_data เป็น None (อาร์กิวเมนต์ของ filter
        # ไม่ถูก Django จับ VariableDoesNotExist) — ย้ายไปคิดในวิวเป็น display_stop
        # รายละเอียดและเทสต์ของบั๊กนั้นอยู่ใน scratch/test_portfolio_error_row.py
        self.assertIn('item.display_stop', self.tpl_src,
                      'มุมมองการ์ดต้องโชว์ stop ตัวเดียวกับมุมมองตาราง')
        self.assertNotIn('default:item.trailing_stop_data', self.tpl_src)

    def test_thresholds_are_defined_once(self):
        mod = (ROOT / 'stocks' / 'risk_reward.py').read_text(encoding='utf-8')
        self.assertEqual(mod.count('RR_MIN_OK = '), 1)
        self.assertEqual(mod.count('RR_POOR = '), 1)


if __name__ == '__main__':
    unittest.main(verbosity=2)
