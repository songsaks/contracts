"""ตรวจเพดานความเสี่ยงของพอร์ต (ข้อ 4)

ปัญหาเดิม: position_sizing.py มีเพดานครบสี่ชั้น แต่ต่อไว้กับหน้าเครื่องคิดเลข
อย่างเดียว ตอนเพิ่มหุ้นจริง add_to_portfolio เรียก update_or_create() ตรงๆ
พอร์ตจึงมีไม้กินน้ำหนัก 22.6% และ 20.8% ทะลุเพดาน 20% ที่ตั้งไว้เองแบบเงียบๆ

ข้อสำคัญของการแก้: "เตือน" ไม่ใช่ "บล็อก" — ฟอร์ม Add Position มีช่องราคาทุน
แปลว่าบันทึกไม้ที่ซื้อไปแล้ว ถ้าบล็อกไม่ให้บันทึก พอร์ตจะไม่ตรงกับความจริง
ซึ่งแย่กว่าการถือไม้ที่ใหญ่เกินเพดาน

รันจาก repo root: python3 scratch/test_portfolio_risk.py
"""
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

from stocks.portfolio_risk import (  # noqa: E402
    add_position_warning, concentration_report, projected_weight,
    weight_breaches, weight_pct,
)
from stocks.position_sizing import (  # noqa: E402
    DEFAULT_MAX_HEAT_PCT, DEFAULT_MAX_WEIGHT_PCT, calculate_portfolio_heat,
)

# พอร์ตจริงจากหน้าจอที่ตั้งต้นเรื่องนี้
REAL_PORTFOLIO = [
    ('AIT', 143400), ('BA', 91000), ('BCH', 336000), ('BCP', 216000),
    ('CCET', 91000), ('CHG', 310000), ('SCC', 130000), ('TASCO', 171000),
]
REAL_EQUITY = sum(v for _s, v in REAL_PORTFOLIO)
REAL_POSITIONS = [{'symbol': s, 'value': v} for s, v in REAL_PORTFOLIO]


class WeightPctTests(unittest.TestCase):
    def test_basic(self):
        self.assertAlmostEqual(weight_pct(200, 1000), 20.0)

    def test_unusable_input_returns_none(self):
        for value, equity in ((0, 1000), (-5, 1000), (100, 0), (100, None),
                              (None, 1000), ('x', 1000)):
            self.assertIsNone(weight_pct(value, equity))


class WeightBreachTests(unittest.TestCase):
    def test_finds_the_two_real_breaches(self):
        breaches = weight_breaches(REAL_POSITIONS, REAL_EQUITY)
        self.assertEqual([b['symbol'] for b in breaches], ['BCH', 'CHG'],
                         'ต้องเจอทั้งสองตัวที่ทะลุเพดาน เรียงจากหนักสุด')
        self.assertEqual(breaches[0]['weight_pct'], 22.6)
        self.assertEqual(breaches[1]['weight_pct'], 20.8)
        self.assertEqual(breaches[0]['excess_pct'], 2.6)

    def test_nothing_breaches_in_a_balanced_book(self):
        even = [{'symbol': f'S{i}', 'value': 100} for i in range(10)]   # 10% ต่อตัว
        self.assertEqual(weight_breaches(even, 1000), [])

    def test_exactly_at_the_cap_is_not_a_breach(self):
        at_cap = [{'symbol': 'X', 'value': 200}]
        self.assertEqual(weight_breaches(at_cap, 1000), [],
                         'ที่เพดานพอดียังไม่ถือว่าเกิน')

    def test_custom_cap_changes_the_answer(self):
        # เพดานแคบลง ไม้ที่ทะลุต้องมากขึ้นตาม (ค่าจริงจากพอร์ตในภาพ)
        for cap, expected in ((20, ['BCH', 'CHG']),
                              (15, ['BCH', 'CHG']),
                              (12, ['BCH', 'CHG', 'BCP']),
                              (10, ['BCH', 'CHG', 'BCP', 'TASCO'])):
            got = [b['symbol'] for b in weight_breaches(REAL_POSITIONS, REAL_EQUITY,
                                                        max_weight_pct=cap)]
            self.assertEqual(got, expected, f'ที่เพดาน {cap}%')

    def test_empty_and_garbage_are_safe(self):
        self.assertEqual(weight_breaches([], 1000), [])
        self.assertEqual(weight_breaches(None, 1000), [])
        self.assertEqual(weight_breaches([{'symbol': 'X'}], 1000), [])
        self.assertEqual(weight_breaches(REAL_POSITIONS, 0), [])


class ConcentrationReportTests(unittest.TestCase):
    def test_real_portfolio(self):
        rep = concentration_report(REAL_POSITIONS, REAL_EQUITY)
        self.assertTrue(rep['has_breach'])
        self.assertEqual(rep['breach_count'], 2)
        self.assertEqual(rep['top_symbol'], 'BCH')
        self.assertEqual(rep['top_weight_pct'], 22.6)
        self.assertEqual(rep['breached_weight_pct'], 43.4)
        self.assertEqual(rep['max_weight_pct'], DEFAULT_MAX_WEIGHT_PCT)

    def test_positions_are_sorted_heaviest_first(self):
        rep = concentration_report(REAL_POSITIONS, REAL_EQUITY)
        weights = [p['weight_pct'] for p in rep['positions']]
        self.assertEqual(weights, sorted(weights, reverse=True))

    def test_clean_portfolio_reports_no_breach_but_still_shows_the_top(self):
        even = [{'symbol': f'S{i}', 'value': 100} for i in range(10)]
        rep = concentration_report(even, 1000)
        self.assertFalse(rep['has_breach'])
        self.assertEqual(rep['top_weight_pct'], 10.0,
                         'ถึงไม่ทะลุเพดานก็ควรรู้ว่าไม้ใหญ่สุดกินเท่าไร')

    def test_empty_portfolio(self):
        rep = concentration_report([], 0)
        self.assertFalse(rep['has_breach'])
        self.assertIsNone(rep['top_weight_pct'])


class ProjectedWeightTests(unittest.TestCase):
    def test_new_position_counts_itself_in_the_denominator(self):
        # เพิ่ม 100 เข้าพอร์ตที่มีอยู่ 900 -> 100/1000 = 10% ไม่ใช่ 100/900 = 11.1%
        self.assertAlmostEqual(projected_weight(100, [900]), 10.0)

    def test_cash_counts_as_part_of_the_portfolio(self):
        self.assertAlmostEqual(projected_weight(100, [400], cash=500), 10.0)

    def test_real_case_adding_a_big_position(self):
        pct = projected_weight(400000, [v for _s, v in REAL_PORTFOLIO])
        self.assertAlmostEqual(pct, 21.2, places=1)

    def test_unusable_input(self):
        self.assertIsNone(projected_weight(0, [100]))
        self.assertIsNone(projected_weight(None, [100]))
        self.assertIsNone(projected_weight('x', [100]))

    def test_first_position_in_an_empty_portfolio_is_everything(self):
        self.assertAlmostEqual(projected_weight(100, []), 100.0)

    def test_garbage_in_existing_values_is_skipped(self):
        self.assertAlmostEqual(projected_weight(100, [900, None, 'x', -50]), 10.0)


class AddPositionWarningTests(unittest.TestCase):
    def test_warns_when_over_the_cap(self):
        msg = add_position_warning('XYZ', 400000, [v for _s, v in REAL_PORTFOLIO])
        self.assertIsNotNone(msg)
        self.assertIn('XYZ', msg)
        self.assertIn('21.2%', msg)
        self.assertIn('บันทึกให้แล้ว', msg,
                      'ต้องสื่อว่าบันทึกสำเร็จ ไม่ใช่ถูกปฏิเสธ')

    def test_silent_when_within_the_cap(self):
        self.assertIsNone(add_position_warning('SMALL', 50000,
                                               [v for _s, v in REAL_PORTFOLIO]))

    def test_silent_when_it_cannot_tell(self):
        self.assertIsNone(add_position_warning('X', 0, [100]))
        self.assertIsNone(add_position_warning('X', None, [100]))


class HeatStillWorksTests(unittest.TestCase):
    """ใช้ของเดิมใน position_sizing ไม่ได้เขียนซ้ำ — เช็คว่ายังต่อกันได้"""

    def test_heat_over_limit_is_flagged(self):
        positions = [
            {'symbol': 'A', 'quantity': 1000, 'current_price': 100, 'stop_price': 90},
            {'symbol': 'B', 'quantity': 1000, 'current_price': 100, 'stop_price': 90},
        ]
        heat = calculate_portfolio_heat(positions, equity=100000,
                                        max_heat_pct=DEFAULT_MAX_HEAT_PCT)
        self.assertEqual(heat['heat_pct'], 20.0)
        self.assertEqual(heat['status'], 'over')

    def test_position_without_a_stop_makes_heat_unknown(self):
        positions = [{'symbol': 'A', 'quantity': 100, 'current_price': 10, 'stop_price': 0}]
        heat = calculate_portfolio_heat(positions, equity=10000)
        self.assertEqual(heat['status'], 'unknown',
                         'ไม้ที่ไม่มี stop = ประเมินความเสี่ยงไม่ได้ ไม่ใช่ปลอดภัย')
        self.assertEqual(heat['unprotected'], ['A'])


class WiredInTests(unittest.TestCase):
    """กันไม่ให้ใครถอดสายออก และกันไม่ให้มีใครเปลี่ยนเป็นบล็อกการบันทึก"""

    def setUp(self):
        self.view_src = (ROOT / 'stocks' / 'views' / 'portfolio.py').read_text(encoding='utf-8')
        self.tpl_src = (ROOT / 'stocks' / 'templates' / 'stocks' / 'portfolio.html').read_text(encoding='utf-8')

    def test_portfolio_page_computes_both_caps(self):
        self.assertIn('concentration_report(_risk_positions, _equity_thb)', self.view_src)
        self.assertIn('calculate_portfolio_heat(_heat_rows, _equity_thb', self.view_src)

    def test_both_caps_reach_the_template(self):
        self.assertIn("'concentration': concentration", self.view_src)
        self.assertIn("'portfolio_heat': portfolio_heat", self.view_src)
        self.assertIn('concentration.has_breach', self.tpl_src)
        self.assertIn('portfolio_heat.heat_pct', self.tpl_src)

    def test_adding_a_position_still_succeeds_when_over_the_cap(self):
        # ต้องยังคืน success: True เสมอ — คำเตือนเป็นข้อมูลเพิ่ม ไม่ใช่การปฏิเสธ
        self.assertIn("return JsonResponse({'success': True, 'symbol': symbol, 'warning': warning})",
                      self.view_src,
                      'การบันทึกต้องสำเร็จเสมอ ห้ามเปลี่ยนเป็นบล็อก')

    def test_warning_failure_never_breaks_the_save(self):
        self.assertIn('การเตือนต้องไม่ทำให้การบันทึกล้มเหลว', self.view_src)

    def test_weights_are_converted_to_one_currency(self):
        # หุ้น US ราคาเป็น USD ถ้าไม่แปลงจะดูเล็กกว่าความจริงราว 30 เท่า
        self.assertIn("_fx = usd_thb if it.get('market') in (MarketType.US, MarketType.CRYPTO)",
                      self.view_src)

    def test_modal_shows_the_warning_before_reloading(self):
        self.assertIn("json.warning", self.tpl_src)
        self.assertIn("port-warn-box", self.tpl_src)
        self.assertIn("'รับทราบ'", self.tpl_src)

    def test_caps_are_not_redefined(self):
        mod = (ROOT / 'stocks' / 'portfolio_risk.py').read_text(encoding='utf-8')
        self.assertIn('from .position_sizing import DEFAULT_MAX_WEIGHT_PCT', mod,
                      'เพดานต้องมาจาก position_sizing ที่เดียว ห้ามพิมพ์ตัวเลขใหม่')
        self.assertNotIn('= 20.0', mod)
        self.assertNotIn('= 6.0', mod)


if __name__ == '__main__':
    unittest.main(verbosity=2)
