"""Portfolio Heat ต้องไม่ขึ้นไฟเขียว ตอนที่มีไม้หลุด stop ค้างอยู่

ที่มา: หน้าพอร์ตจริงขึ้นว่า Heat 0.4% "อยู่ในเกณฑ์" ทั้งที่ 6 ใน 8 ไม้ราคาต่ำกว่า
จุดตัดขาดทุนของตัวเองไปแล้ว สาเหตุอยู่ที่บรรทัดเดียว:

    risk = max(0.0, (cur - stop) * qty)     # stop เหนือราคา = 0 เสมอ

stop อยู่เหนือราคาได้สองแบบที่ความหมายตรงข้ามกัน
  - ราคาวิ่งขึ้นจน stop ไล่ตาม  → ล็อกกำไรแล้ว ความเสี่ยงข้างหน้าเป็น 0 จริง
  - ราคาร่วงลงต่ำกว่า stop     → หลุด stop แล้ว ควรออกไปแล้ว

โค้ดเดิมเห็นเป็นอย่างเดียวกัน อันตรายของมันไม่ใช่ตัวเลขเพี้ยน แต่คือมันบอกว่า
"เปิดไม้ใหม่ได้" ทั้งที่คำตอบที่ถูกคือ "ไปจัดการของเก่าก่อน"

รันจาก repo root: python3 scratch/test_portfolio_heat_breached.py
"""
import sys
import unittest
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT))

from stocks.position_sizing import (  # noqa: E402
    DEFAULT_MAX_HEAT_PCT, calculate_portfolio_heat,
)

EQUITY = 1_000_000.0


def pos(symbol, qty, cur, stop, entry=None):
    row = {'symbol': symbol, 'quantity': qty, 'current_price': cur, 'stop_price': stop}
    if entry is not None:
        row['entry_price'] = entry
    return row


class TellingTheTwoCasesApartTests(unittest.TestCase):
    def test_price_above_entry_with_stop_above_price_is_locked_profit(self):
        # ซื้อ 10 ราคาวิ่งไป 25 แล้วย่อลงมา 20 ส่วน stop ไล่ขึ้นไปค้างที่ 21
        # stop อยู่เหนือราคาปัจจุบัน แต่ยังเหนือทุนเยอะ — ล็อกกำไรแล้วจริง
        out = calculate_portfolio_heat([pos('WIN', 100, 20.0, 21.0, entry=10.0)], EQUITY)
        row = out['positions'][0]
        self.assertTrue(row['locked_profit'])
        self.assertFalse(row['breached'])
        self.assertEqual(out['breached_count'], 0)
        self.assertEqual(out['heat_pct'], 0.0)
        self.assertEqual(out['status'], 'ok')

    def test_price_below_entry_with_stop_above_price_is_breached(self):
        # ซื้อ 20 ราคาร่วงมา 15 แต่ stop ล็อกไว้ที่ 18 — หลุดไปแล้ว ไม่ใช่ล็อกกำไร
        out = calculate_portfolio_heat([pos('LOSE', 100, 15.0, 18.0, entry=20.0)], EQUITY)
        row = out['positions'][0]
        self.assertFalse(row['locked_profit'])
        self.assertTrue(row['breached'])
        self.assertEqual(out['breached'], ['LOSE'])
        self.assertEqual(out['status'], 'breached')

    def test_missing_entry_price_is_treated_as_breached(self):
        # ไม่รู้ทุน = ไม่พิสูจน์ว่ากำไร การเดาเข้าข้างตัวเองเรื่องความเสี่ยงอันตรายกว่า
        out = calculate_portfolio_heat([pos('NOENTRY', 100, 15.0, 18.0)], EQUITY)
        self.assertTrue(out['positions'][0]['breached'])
        self.assertEqual(out['status'], 'breached')

    def test_a_normal_position_still_counts_its_risk(self):
        out = calculate_portfolio_heat([pos('OK', 1000, 50.0, 45.0, entry=48.0)], EQUITY)
        self.assertEqual(out['positions'][0]['risk_amount'], 5000.0)
        self.assertEqual(out['heat_pct'], 0.5)
        self.assertEqual(out['status'], 'ok')
        self.assertFalse(out['positions'][0]['breached'])


class NoMadeUpNumbersTests(unittest.TestCase):
    """เลือกทาง "ไม่ยัดตัวเลขสมมติ" — heat ต้องไม่ขยับเพราะไม้ที่หลุด stop"""

    def test_breached_positions_do_not_change_heat_pct(self):
        clean = [pos('OK', 1000, 50.0, 45.0, entry=48.0)]
        dirty = clean + [pos('LOSE', 100, 15.0, 18.0, entry=20.0)]
        self.assertEqual(calculate_portfolio_heat(clean, EQUITY)['heat_pct'],
                         calculate_portfolio_heat(dirty, EQUITY)['heat_pct'])

    def test_breached_position_reports_zero_risk_not_a_guess(self):
        out = calculate_portfolio_heat([pos('LOSE', 100, 15.0, 18.0, entry=20.0)], EQUITY)
        self.assertEqual(out['positions'][0]['risk_amount'], 0.0)
        self.assertEqual(out['total_risk'], 0.0)

    def test_unrealized_loss_is_reported_instead(self):
        # (20 - 15) * 100 = 500 — เป็นตัวเลขที่รู้จริง ต่างจาก "จะลงต่ออีกเท่าไหร่"
        out = calculate_portfolio_heat([pos('LOSE', 100, 15.0, 18.0, entry=20.0)], EQUITY)
        self.assertEqual(out['positions'][0]['unrealized_loss'], 500.0)
        self.assertEqual(out['breached_loss'], 500.0)

    def test_room_to_add_drops_to_zero(self):
        # ต่อให้ heat ต่ำแค่ไหน มีของค้างก็ไม่ควรเปิดไม้ใหม่
        out = calculate_portfolio_heat([pos('LOSE', 100, 15.0, 18.0, entry=20.0)], EQUITY)
        self.assertEqual(out['room_pct'], 0.0)
        clean = calculate_portfolio_heat([pos('OK', 1000, 50.0, 45.0, entry=48.0)], EQUITY)
        self.assertGreater(clean['room_pct'], 0.0)


class StatusPrecedenceTests(unittest.TestCase):
    def test_breached_beats_a_green_heat(self):
        out = calculate_portfolio_heat([
            pos('OK', 100, 50.0, 49.0, entry=48.0),
            pos('LOSE', 100, 15.0, 18.0, entry=20.0),
        ], EQUITY)
        self.assertEqual(out['status'], 'breached')

    def test_breached_beats_over(self):
        big = pos('BIG', 100_000, 50.0, 45.0, entry=48.0)   # เสี่ยง 500k = 50% เกินเพดานแน่
        alone = calculate_portfolio_heat([big], EQUITY)
        self.assertEqual(alone['status'], 'over')
        out = calculate_portfolio_heat([big, pos('LOSE', 100, 15.0, 18.0, entry=20.0)], EQUITY)
        self.assertEqual(out['status'], 'breached')

    def test_breached_beats_unknown_but_the_label_says_both(self):
        out = calculate_portfolio_heat([
            pos('NOSTOP', 100, 50.0, 0.0, entry=48.0),
            pos('LOSE', 100, 15.0, 18.0, entry=20.0),
        ], EQUITY)
        self.assertEqual(out['status'], 'breached')
        self.assertEqual(out['unprotected'], ['NOSTOP'])
        self.assertIn('หลุด stop', out['label'])
        self.assertIn('ยังไม่ตั้ง stop', out['label'])

    def test_breached_rows_sort_first(self):
        out = calculate_portfolio_heat([
            pos('OK', 1000, 50.0, 45.0, entry=48.0),
            pos('LOSE', 100, 15.0, 18.0, entry=20.0),
        ], EQUITY)
        self.assertEqual([r['symbol'] for r in out['positions']], ['LOSE', 'OK'])


class NothingElseChangedTests(unittest.TestCase):
    """กันการแก้ที่เผลอเปลี่ยนพฤติกรรมเดิมไปด้วย"""

    def test_position_without_a_stop_is_still_unknown(self):
        out = calculate_portfolio_heat([pos('NOSTOP', 100, 50.0, 0.0, entry=48.0)], EQUITY)
        self.assertEqual(out['status'], 'unknown')
        self.assertEqual(out['unprotected_count'], 1)

    def test_over_and_warm_thresholds_are_untouched(self):
        cap = DEFAULT_MAX_HEAT_PCT
        over = calculate_portfolio_heat(
            [pos('A', 1, EQUITY * (cap + 1) / 100 + 1, 1.0, entry=1_000_000.0)], EQUITY)
        self.assertEqual(over['status'], 'over')
        warm_risk = EQUITY * (cap * 0.8) / 100
        warm = calculate_portfolio_heat(
            [pos('B', 1, warm_risk + 10.0, 10.0, entry=1.0)], EQUITY)
        self.assertEqual(warm['status'], 'warm')

    def test_empty_and_zero_equity_do_not_explode(self):
        self.assertEqual(calculate_portfolio_heat([], EQUITY)['status'], 'ok')
        out = calculate_portfolio_heat([pos('A', 100, 50.0, 45.0, entry=48.0)], 0)
        self.assertEqual(out['heat_pct'], 0.0)


class TheRealPortfolioTests(unittest.TestCase):
    """ตัวเลขจริงจากหน้าพอร์ตวันที่เจอปัญหา — ต้องได้ 6 ตัวที่หลุด stop"""

    EQUITY = 2_870_547.01
    ROWS = [
        # symbol, qty, price, stop, entry (ถอดจาก P/L% ที่หน้าจอโชว์)
        pos('AIT.BK',   30_000,   4.78,   5.24,   6.168),
        pos('BA.BK',     5_000,  18.20,  18.53,  19.740),
        pos('BCH.BK',   30_000,  11.30,  10.97,  11.155),
        pos('BCP.BK',    4_000,  55.00,  56.44,  58.630),
        pos('CCET.BK',  10_000,   8.95,   9.07,   9.717),
        pos('CHG.BK',  200_000,   1.56,   1.58,   1.620),
        pos('SCC.BK',      500, 258.00, 258.97, 264.600),
        pos('TASCO.BK', 10_000,  16.80,  16.76,  17.480),
    ]

    def setUp(self):
        self.out = calculate_portfolio_heat(self.ROWS, self.EQUITY)

    def test_the_six_breached_names_are_found(self):
        self.assertEqual(sorted(self.out['breached']),
                         ['AIT.BK', 'BA.BK', 'BCP.BK', 'CCET.BK', 'CHG.BK', 'SCC.BK'])

    def test_the_two_healthy_positions_still_carry_risk(self):
        by_sym = {r['symbol']: r for r in self.out['positions']}
        self.assertEqual(by_sym['BCH.BK']['risk_amount'], 9900.0)   # (11.30-10.97)*30000
        self.assertEqual(by_sym['TASCO.BK']['risk_amount'], 400.0)  # (16.80-16.76)*10000

    def test_the_headline_number_stays_honest(self):
        # ตัวเลขไม่เปลี่ยน แต่คำตัดสินเปลี่ยน — นี่คือจุดสำคัญของการแก้ครั้งนี้
        self.assertEqual(self.out['heat_pct'], 0.36)
        self.assertEqual(self.out['status'], 'breached')
        self.assertEqual(self.out['room_pct'], 0.0)

    def test_the_old_behaviour_would_have_said_ok(self):
        # ไม่ส่ง entry มาเลยไม่ได้ เพราะกลายเป็น breached หมด จึงจำลองสูตรเดิมตรงๆ
        old_risk = sum(max(0.0, (r['current_price'] - r['stop_price']) * r['quantity'])
                       for r in self.ROWS)
        old_heat = round(old_risk / self.EQUITY * 100, 2)
        self.assertEqual(old_heat, self.out['heat_pct'],
                         'ตัวเลข heat ต้องเท่าเดิม ไม่ได้ไปแต่งขึ้น')
        self.assertLess(old_heat, DEFAULT_MAX_HEAT_PCT,
                        'สูตรเดิมให้ค่าต่ำกว่าเพดาน จึงขึ้นเขียวว่า ok')


class WiredInTests(unittest.TestCase):
    """ตรรกะถูกอย่างเดียวไม่พอ ต้องถูกต่อเข้าหน้าจอจริงด้วย"""

    VIEW = (ROOT / 'stocks' / 'views' / 'portfolio.py').read_text(encoding='utf-8')
    PORTFOLIO_TPL = (ROOT / 'stocks' / 'templates' / 'stocks'
                     / 'portfolio.html').read_text(encoding='utf-8')
    SIZE_TPL = (ROOT / 'stocks' / 'templates' / 'stocks'
                / 'position_size.html').read_text(encoding='utf-8')

    def test_both_call_sites_pass_entry_price(self):
        # ไม่ส่ง entry มา = แยกล็อกกำไรกับหลุด stop ไม่ออก แล้วจะกลายเป็น breached หมด
        # (ในไฟล์นี้มี 'entry_price' ที่เรื่องอื่นอีก จึงเช็คสองบรรทัดนี้ตรงๆ)
        self.assertIn("'entry_price': float(it['obj'].entry_price or 0) * _fx", self.VIEW,
                      'หน้าพอร์ตยังไม่ส่งทุนเข้า heat')
        self.assertIn("'entry_price': float(p.entry_price or 0) * fx", self.VIEW,
                      'หน้าคำนวณขนาดไม้ยังไม่ส่งทุนเข้า heat')

    def test_portfolio_banner_shows_up_for_breached(self):
        self.assertIn('portfolio_heat.breached_count', self.PORTFOLIO_TPL)
        self.assertIn('portfolio_heat.breached|join', self.PORTFOLIO_TPL)

    def test_position_size_page_does_not_paint_breached_green(self):
        # การ์ดนั้นมี else เป็นสีเขียว ถ้าไม่ดัก status ใหม่ไว้ จะกลายเป็นเขียวเงียบๆ
        self.assertIn("heat.status == 'breached'", self.SIZE_TPL)
        self.assertIn('.ps-heat-breached', self.SIZE_TPL)

    def test_the_risk_table_does_not_show_a_breached_row_as_zero_baht(self):
        self.assertIn('r.breached', self.SIZE_TPL)


if __name__ == '__main__':
    unittest.main(verbosity=2)
