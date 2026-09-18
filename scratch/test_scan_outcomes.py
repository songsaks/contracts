"""ตรวจระบบตามผลการสแกน (ScanOutcome) — ทั้งตรรกะวัดผลและการบันทึก snapshot

สิ่งที่ต้องกันไม่ให้พลาด:
  1. การวัดผลต้องไม่เข้าข้างตัวเอง — แท่งเดียวกันแตะทั้ง TP และ SL ต้องนับ SL
  2. แถวที่ยังไม่รู้ผล (pending) ต้องไม่ถูกนับรวมในสถิติ ไม่งั้นตัวเลขจะถูกเจือจาง
  3. สแกนซ้ำในวันเดียวกันต้องไม่สร้างแถวซ้ำ (ไม่งั้นหุ้นที่ถูกสแกนบ่อยจะถ่วงสถิติ)
  4. record_candidates ต้องไม่ทำให้การสแกนพัง ไม่ว่าจะเกิดอะไรขึ้น

ใช้ DB ในหน่วยความจำ ไม่โหลด config.settings ของโปรเจกต์
รันจาก repo root: python3 scratch/test_scan_outcomes.py
"""
import sys
import unittest
from pathlib import Path
from unittest.mock import patch

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT))

from django.conf import settings

settings.configure(
    SECRET_KEY='offline-test-only',
    INSTALLED_APPS=['django.contrib.auth', 'django.contrib.contenttypes', 'stocks'],
    DATABASES={'default': {'ENGINE': 'django.db.backends.sqlite3', 'NAME': ':memory:'}},
    USE_TZ=True,
    TEMPLATES=[{'BACKEND': 'django.template.backends.django.DjangoTemplates',
                'APP_DIRS': True, 'DIRS': [], 'OPTIONS': {}}],
)
import django  # noqa: E402
import django.utils.timezone  # noqa: E402,F401

django.setup()

from django.contrib.auth import get_user_model  # noqa: E402
from django.db import connection, transaction  # noqa: E402

from stocks.models import ScanOutcome  # noqa: E402
from stocks import scan_outcomes as so  # noqa: E402


class ForwardEvaluationTests(unittest.TestCase):
    """evaluate_forward — หัวใจของการวัดผล"""

    def test_take_profit_hit_first(self):
        # entry 100 / stop 95 (risk 5) / target 115 → แตะ target แท่งที่ 4
        r = so.evaluate_forward(100, 95, 115,
                                highs=[102, 104, 108, 116], lows=[99, 101, 103, 110],
                                closes=[101, 103, 107, 115])
        self.assertEqual(r['first_hit'], 'TP')
        self.assertEqual(r['r_multiple'], 3.0)      # (115-100)/5
        self.assertEqual(r['mfe_pct'], 16.0)
        self.assertEqual(r['mae_pct'], -1.0)

    def test_stop_hit_first(self):
        r = so.evaluate_forward(100, 95, 115, [102, 101], [99, 94], [101, 96])
        self.assertEqual(r['first_hit'], 'SL')
        self.assertEqual(r['r_multiple'], -1.0)

    def test_same_bar_touching_both_counts_as_stop(self):
        # ข้อมูลรายวันไม่บอกลำดับ ต้องเลือกทางที่ไม่เข้าข้างตัวเอง
        r = so.evaluate_forward(100, 95, 115, [116], [94], [100])
        self.assertEqual(r['first_hit'], 'SL',
                         'แท่งเดียวกันแตะทั้งคู่ ต้องนับ SL ไม่ใช่ TP')

    def test_no_hit_marks_to_market(self):
        r = so.evaluate_forward(100, 95, 115, [104] * 6, [98] * 6, [103] * 6)
        self.assertEqual(r['first_hit'], '')
        self.assertEqual(r['r_multiple'], 0.6)      # (103-100)/5

    def test_horizon_returns(self):
        closes = [100 + i for i in range(1, 21)]    # 101..120
        r = so.evaluate_forward(100, None, None, closes, closes, closes)
        self.assertEqual(r['ret_d5'], 5.0)
        self.assertEqual(r['ret_d10'], 10.0)
        self.assertEqual(r['ret_d20'], 20.0)
        self.assertEqual(r['status'], so.STATUS_COMPLETE)

    def test_partial_window_leaves_later_horizons_none(self):
        r = so.evaluate_forward(100, 95, 115, [101] * 7, [99] * 7, [101] * 7)
        self.assertEqual(r['status'], so.STATUS_PARTIAL)
        self.assertIsNotNone(r['ret_d5'])
        self.assertIsNone(r['ret_d10'], 'ยังไม่ถึง 10 แท่ง ต้องยังไม่มีค่า')
        self.assertIsNone(r['ret_d20'])

    def test_window_is_capped_at_max_horizon(self):
        # ส่งมา 40 แท่ง ต้องวัดแค่ 20 — แท่งหลังจากนั้นไม่เกี่ยว
        r = so.evaluate_forward(100, 95, 115, [101] * 40, [99] * 40, [101] * 40)
        self.assertEqual(r['bars_evaluated'], so.MAX_HORIZON)

    def test_bad_input_does_not_raise(self):
        for args in (
            (0, 95, 115, [1], [1], [1]),          # ไม่มีราคาเข้า
            (100, 95, 115, [], [], []),           # ไม่มีแท่งเลย
            (None, None, None, [], [], []),
        ):
            r = so.evaluate_forward(*args)
            self.assertEqual(r['bars_evaluated'], 0)
            self.assertEqual(r['status'], so.STATUS_PENDING)

    def test_stop_above_entry_is_ignored_for_r_multiple(self):
        # stop สูงกว่า entry = ข้อมูลเพี้ยน ต้องไม่คำนวณ R ออกมามั่วๆ
        r = so.evaluate_forward(100, 105, 115, [101], [99], [100])
        self.assertIsNone(r['r_multiple'])


class SummaryTests(unittest.TestCase):
    def test_pending_rows_are_excluded(self):
        rows = [
            {'ret_d20': 10.0, 'r_multiple': 2.0, 'first_hit': 'TP'},
            {'ret_d20': -5.0, 'r_multiple': -1.0, 'first_hit': 'SL'},
            {'ret_d20': None, 'r_multiple': None, 'first_hit': ''},   # ยังไม่รู้ผล
        ]
        s = so.summarize(rows)
        self.assertEqual(s['n'], 2, 'แถวที่ยังไม่รู้ผลต้องไม่ถูกนับ')
        self.assertEqual(s['n_pending'], 1)
        self.assertEqual(s['win_rate'], 50.0)
        self.assertEqual(s['tp_first'], 1)
        self.assertEqual(s['sl_first'], 1)

    def test_profit_factor(self):
        rows = [{'ret_d20': 30.0, 'r_multiple': 3.0, 'first_hit': 'TP'},
                {'ret_d20': -10.0, 'r_multiple': -1.0, 'first_hit': 'SL'},
                {'ret_d20': -5.0, 'r_multiple': -1.0, 'first_hit': 'SL'}]
        s = so.summarize(rows)
        self.assertAlmostEqual(s['profit_factor'], 2.0)   # 30 / 15
        self.assertEqual(s['win_rate'], 33.3)             # ชนะ 1 ใน 3 แต่ยังทำเงิน

    def test_empty_input_is_safe(self):
        s = so.summarize([])
        self.assertEqual(s['n'], 0)
        self.assertIsNone(s['win_rate'])
        self.assertIsNone(s['profit_factor'])

    def test_group_summary_respects_min_n(self):
        rows = [{'ret_d20': 5.0, 'r_multiple': 1.0, 'first_hit': '', 'k': 'A'} for _ in range(4)]
        rows += [{'ret_d20': 5.0, 'r_multiple': 1.0, 'first_hit': '', 'k': 'B'}]
        out = so.group_summary(rows, lambda r: r['k'], min_n=3)
        self.assertEqual([g['key'] for g in out], ['A'], 'กลุ่มที่ตัวอย่างน้อยเกินต้องถูกตัด')

    def test_flag_comparison_detects_edge(self):
        rows = ([{'ret_d20': 20.0, 'r_multiple': 3.0, 'first_hit': 'TP', 'vcp_setup': True}] * 6
                + [{'ret_d20': -5.0, 'r_multiple': -1.0, 'first_hit': 'SL', 'vcp_setup': False}] * 6)
        cmp_ = so.flag_comparison(rows, 'vcp_setup')
        self.assertEqual(cmp_['on']['n'], 6)
        self.assertEqual(cmp_['off']['n'], 6)
        self.assertEqual(cmp_['edge_r'], 4.0)   # 3.0 − (−1.0)

    def test_score_bucket_boundaries(self):
        self.assertEqual(so.score_bucket(100), '85-100')
        self.assertEqual(so.score_bucket(85), '85-100')
        self.assertEqual(so.score_bucket(84), '70-84')
        self.assertEqual(so.score_bucket(0), '0-54')
        self.assertEqual(so.score_bucket(None), '0-54')


class _FakeCandidate:
    """เลียนแบบ PrecisionScanCandidate เท่าที่ snapshot ต้องใช้"""
    def __init__(self, symbol, **kw):
        self.symbol = symbol
        self.price = kw.get('price', 10.0)
        self.stop_loss = kw.get('stop_loss', 9.0)
        self.supply_zone_start = kw.get('target', 13.0)
        self.risk_reward_ratio = kw.get('rr', 3.0)
        self.entry_strategy = kw.get('entry_strategy', 'Sniper (DZ)')
        self.sector = kw.get('sector', 'Energy')
        self.technical_score = kw.get('technical_score', 85)
        self.buy_score = kw.get('buy_score', 70)
        self.rs_rating = kw.get('rs_rating', 90)
        self.rsi = 55.0
        self.adx = 25.0
        self.rvol = 1.4
        self.cmf = 0.12
        self.volume_surge = 1.6
        for flag, _ in so.SETUP_FLAGS:
            setattr(self, flag, kw.get(flag, False))


class RecordCandidatesTests(unittest.TestCase):
    @classmethod
    def setUpClass(cls):
        with connection.schema_editor() as editor:
            for model in (get_user_model(), ScanOutcome):
                editor.create_model(model)

    def setUp(self):
        self.atomic = transaction.atomic()
        self.atomic.__enter__()
        self.user = get_user_model().objects.create(username=self.id())
        self.run = django.utils.timezone.now()

    def tearDown(self):
        transaction.set_rollback(True)
        self.atomic.__exit__(None, None, None)

    def test_snapshot_copies_scores_and_flags(self):
        c = _FakeCandidate('AIT', technical_score=88, vcp_setup=True)
        so.record_candidates(self.user, 'SET', self.run, [c])
        row = ScanOutcome.objects.get(symbol='AIT')
        self.assertEqual(row.technical_score, 88)
        self.assertEqual(row.score_bucket, '85-100')
        self.assertTrue(row.vcp_setup)
        self.assertFalse(row.htf_setup)
        self.assertEqual(row.status, so.STATUS_PENDING)
        self.assertEqual(row.price_at_scan, 10.0)
        self.assertEqual(row.target_price, 13.0)

    def test_rescan_same_day_does_not_duplicate(self):
        c = _FakeCandidate('BCH')
        so.record_candidates(self.user, 'SET', self.run, [c])
        # สแกนรอบสองของวันเดียวกัน คะแนนเปลี่ยนไปเล็กน้อย
        c2 = _FakeCandidate('BCH', technical_score=40)
        created = so.record_candidates(self.user, 'SET', self.run, [c2])
        self.assertEqual(created, 0)
        self.assertEqual(ScanOutcome.objects.filter(symbol='BCH').count(), 1)
        # ต้องเก็บค่าของ "ครั้งแรกที่สัญญาณโผล่" ไว้ ไม่ถูกทับ
        self.assertEqual(ScanOutcome.objects.get(symbol='BCH').technical_score, 85)

    def test_duplicate_symbols_in_one_batch(self):
        batch = [_FakeCandidate('CHG'), _FakeCandidate('CHG')]
        created = so.record_candidates(self.user, 'SET', self.run, batch)
        self.assertEqual(created, 1)

    def test_candidate_without_price_is_skipped(self):
        so.record_candidates(self.user, 'SET', self.run, [_FakeCandidate('NOPRICE', price=0)])
        self.assertFalse(ScanOutcome.objects.filter(symbol='NOPRICE').exists())

    def test_markets_are_kept_separate(self):
        so.record_candidates(self.user, 'SET', self.run, [_FakeCandidate('TU')])
        so.record_candidates(self.user, 'US', self.run, [_FakeCandidate('TU')])
        self.assertEqual(ScanOutcome.objects.filter(symbol='TU').count(), 2)

    def test_failure_never_breaks_the_scan(self):
        # ถ้าเขียน DB พัง การสแกนที่ผู้ใช้รอมาทั้งรอบต้องไม่พังตาม
        with patch.object(ScanOutcome.objects, 'bulk_create', side_effect=RuntimeError('db down')):
            created = so.record_candidates(self.user, 'SET', self.run, [_FakeCandidate('X')])
        self.assertEqual(created, 0, 'ต้องกลืน error แล้วคืน 0 ไม่ใช่โยนออกไป')

    def test_empty_input_is_noop(self):
        self.assertEqual(so.record_candidates(self.user, 'SET', self.run, []), 0)
        self.assertEqual(so.record_candidates(None, 'SET', self.run, [_FakeCandidate('A')]), 0)

    def test_end_to_end_record_then_evaluate_then_report(self):
        """เส้นทางจริง: สแกนเจอ → เติมผล → สรุปสถิติ"""
        winners = [_FakeCandidate(f'W{i}', technical_score=90, vcp_setup=True) for i in range(3)]
        losers = [_FakeCandidate(f'L{i}', technical_score=40) for i in range(3)]
        so.record_candidates(self.user, 'SET', self.run, winners + losers)

        for row in ScanOutcome.objects.all():
            if row.symbol.startswith('W'):     # วิ่งถึง target 13
                res = so.evaluate_forward(row.price_at_scan, row.stop_loss, row.target_price,
                                          [11, 12, 13.5] + [13] * 17, [10] * 20, [11, 12, 13] + [13] * 17)
            else:                              # หลุด stop 9
                res = so.evaluate_forward(row.price_at_scan, row.stop_loss, row.target_price,
                                          [10] * 20, [8.5] * 20, [9] * 20)
            for k, v in res.items():
                setattr(row, k, v)
            row.save()

        rows = list(ScanOutcome.objects.filter(user=self.user).values())
        stats = so.summarize(rows)
        self.assertEqual(stats['n'], 6)
        self.assertEqual(stats['tp_first'], 3)
        self.assertEqual(stats['sl_first'], 3)

        by_score = so.group_summary(rows, lambda r: r['score_bucket'], min_n=1)
        best = by_score[0]
        self.assertEqual(best['key'], '85-100',
                         'กลุ่มคะแนนสูงต้องขึ้นมาอันดับแรกเมื่อผลดีกว่าจริง')
        self.assertGreater(best['avg_r'], 0)

        cmp_ = so.flag_comparison(rows, 'vcp_setup')
        self.assertGreater(cmp_['edge_r'], 0, 'VCP ควรมี edge เป็นบวกในชุดข้อมูลนี้')


class ReportViewTests(unittest.TestCase):
    """หน้ารายงาน — โหลด view ตรงจากไฟล์ เลี่ยง views/__init__ ที่ลาก pandas_ta มาด้วย"""

    @classmethod
    def setUpClass(cls):
        import importlib.util
        spec = importlib.util.spec_from_file_location(
            'sq', ROOT / 'stocks' / 'views' / 'scan_quality.py')
        cls.sq = importlib.util.module_from_spec(spec)
        spec.loader.exec_module(cls.sq)

    def setUp(self):
        self.atomic = transaction.atomic()
        self.atomic.__enter__()
        self.user = get_user_model().objects.create(username=self.id())

    def tearDown(self):
        transaction.set_rollback(True)
        self.atomic.__exit__(None, None, None)

    def _seed(self, n_each=6):
        """คะแนนสูง = ชนะ / คะแนนต่ำ = แพ้ เพื่อดูว่ารายงานแยกความต่างออกไหม"""
        import datetime
        for i in range(n_each * 2):
            hi = i < n_each
            ScanOutcome.objects.create(
                user=self.user, market='SET', symbol=f'S{i}',
                scan_date=datetime.date(2026, 8, 1) + datetime.timedelta(days=i),
                scan_run=django.utils.timezone.now(),
                price_at_scan=10, stop_loss=9, target_price=13,
                technical_score=90 if hi else 40,
                score_bucket=so.score_bucket(90 if hi else 40),
                entry_strategy='Sniper (DZ)', sector='Energy', vcp_setup=hi,
                ret_d5=5 if hi else -2, ret_d10=8 if hi else -4, ret_d20=25 if hi else -9,
                r_multiple=3.0 if hi else -1.0, first_hit='TP' if hi else 'SL',
                mfe_pct=30 if hi else 1, mae_pct=-2 if hi else -12,
                bars_evaluated=20, status=so.STATUS_COMPLETE,
            )

    def _call(self, query='?market=SET&horizon=20'):
        from django.test import RequestFactory
        captured = {}

        def fake_render(request, template, ctx):
            from django.template.loader import get_template
            get_template(template)          # พิสูจน์ว่า template คอมไพล์ได้จริง
            captured['template'] = template
            captured['ctx'] = ctx
            return 'OK'

        req = RequestFactory().get('/scan-quality/' + query)
        req.user = self.user
        with patch.object(self.sq, 'render', fake_render):
            self.sq.scan_quality_report.__wrapped__(req)
        return captured

    def test_template_compiles_and_context_shape(self):
        self._seed()
        cap = self._call()
        self.assertEqual(cap['template'], 'stocks/scan_quality.html')
        ctx = cap['ctx']
        for key in ('overall', 'by_score', 'flags', 'by_preset', 'by_sector',
                    'market', 'horizon', 'has_data'):
            self.assertIn(key, ctx)

    def test_report_separates_high_from_low_scores(self):
        self._seed()
        ctx = self._call()['ctx']
        buckets = {b['key']: b for b in ctx['by_score']}
        self.assertEqual(buckets['85-100']['win_rate'], 100.0)
        self.assertEqual(buckets['0-54']['win_rate'], 0.0)
        self.assertGreater(buckets['85-100']['avg_r'], buckets['0-54']['avg_r'])

    def test_flag_edge_is_surfaced_when_sample_is_big_enough(self):
        self._seed(n_each=6)          # 6 ติดธง / 6 ไม่ติด ผ่านเกณฑ์ขั้นต่ำ 5
        ctx = self._call()['ctx']
        vcp = [f for f in ctx['flags'] if f['flag'] == 'vcp_setup']
        self.assertTrue(vcp, 'ตัวอย่างพอแล้วต้องมี VCP ในตาราง')
        self.assertGreater(vcp[0]['edge_r'], 0)
        # ความกว้างแถบต้องไม่ติดลบ (CSS รับไม่ได้) และไม่เกิน 100
        self.assertGreaterEqual(vcp[0]['edge_width'], 0)
        self.assertLessEqual(vcp[0]['edge_width'], 100)

    def test_small_sample_flags_are_hidden(self):
        self._seed(n_each=2)          # น้อยกว่า 5 ต่อฝั่ง
        ctx = self._call()['ctx']
        self.assertEqual(ctx['flags'], [], 'ตัวอย่างน้อยเกินต้องไม่โชว์ตัวเลขที่เชื่อไม่ได้')

    def test_empty_state_does_not_crash(self):
        ctx = self._call()['ctx']
        self.assertFalse(ctx['has_data'])
        self.assertEqual(ctx['overall']['n'], 0)

    def test_bad_query_params_fall_back_to_defaults(self):
        self._seed()
        for q in ('?market=ZZZ', '?horizon=999', '?horizon=abc', ''):
            ctx = self._call(q)['ctx']
            self.assertIn(ctx['market'], ('SET', 'US'))
            self.assertIn(ctx['horizon'], so.HORIZONS)

    def test_other_users_rows_are_not_counted(self):
        self._seed()
        other = get_user_model().objects.create(username='someone-else')
        import datetime
        ScanOutcome.objects.create(
            user=other, market='SET', symbol='LEAK', scan_date=datetime.date(2026, 8, 1),
            scan_run=django.utils.timezone.now(), price_at_scan=10,
            ret_d20=999.0, r_multiple=99.0, status=so.STATUS_COMPLETE, bars_evaluated=20)
        ctx = self._call('?scope=my')['ctx']
        self.assertEqual(ctx['total_rows'], 12, 'ต้องไม่ดึงข้อมูลของ user คนอื่นมาปน')


class ModelIntegrityTests(unittest.TestCase):
    """ตรวจนิยามโมเดลอย่างเดียว ไม่ต้องใช้ตารางจริง

    กันเคสที่เพิ่มธงใหม่ใน SETUP_FLAGS แล้วลืมเพิ่มฟิลด์ในโมเดล — snapshot จะเงียบๆ
    ไม่เก็บธงนั้น แล้วรายงานจะบอกว่า "ธงนี้ไม่มี edge" ทั้งที่จริงคือไม่เคยถูกบันทึก
    """

    def test_model_has_a_field_for_every_setup_flag(self):
        names = {f.name for f in ScanOutcome._meta.get_fields()}
        for flag, label in so.SETUP_FLAGS:
            self.assertIn(flag, names,
                          f'SETUP_FLAGS มี {flag} ({label}) แต่โมเดลไม่มีฟิลด์นี้')

    def test_model_has_a_field_for_every_horizon(self):
        names = {f.name for f in ScanOutcome._meta.get_fields()}
        for h in so.HORIZONS:
            self.assertIn(f'ret_d{h}', names)
            self.assertIn(f'price_d{h}', names)

    def test_unique_constraint_is_declared(self):
        self.assertIn(('user', 'market', 'symbol', 'scan_date'),
                      [tuple(u) for u in ScanOutcome._meta.unique_together])


if __name__ == '__main__':
    unittest.main(verbosity=2)
