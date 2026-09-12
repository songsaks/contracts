"""Offline regression checks with an in-memory DB; never load project settings.

Load the selected view definitions directly to avoid scanner/AI imports and
startup side effects. Uses real Django models, forms, decorators and transactions.
Run from the repository root: python scratch/test_stocks_view_regressions.py
"""
import ast
from pathlib import Path
import sys
import unittest
from unittest.mock import Mock, patch

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT))

from django.conf import settings
settings.configure(
    SECRET_KEY='offline-test-only',
    INSTALLED_APPS=['django.contrib.auth', 'django.contrib.contenttypes', 'stocks'],
    DATABASES={'default': {'ENGINE': 'django.db.backends.sqlite3', 'NAME': ':memory:'}},
    USE_TZ=True,
)
import django
django.setup()

from django.contrib.auth import get_user_model
from django.contrib.auth.decorators import login_required
from django.db import connection, transaction
from django.http import HttpResponse, Http404
from django.shortcuts import get_object_or_404
from django.test import RequestFactory
from django.views.decorators.http import require_POST
from stocks.forms import SellStockForm
from stocks.models import Portfolio, SoldStock, Watchlist, MarketType, PrecisionScanRun
from stocks.precision_runs import rank_valid_returns, scan_timestamps


def load_view(filename, name):
    tree = ast.parse((ROOT / 'stocks/views' / filename).read_text(encoding='utf-8'))
    node = next(n for n in tree.body if isinstance(n, ast.FunctionDef) and n.name == name)
    namespace = dict(globals(), messages=Mock(), redirect=lambda *a: HttpResponse(status=302))
    exec(compile(ast.Module(body=[node], type_ignores=[]), filename, 'exec'), namespace)
    return namespace[name]


sell = load_view('portfolio.py', 'sell_stock')
delete_portfolio = load_view('portfolio.py', 'delete_from_portfolio')
delete_watchlist = load_view('watchlist.py', 'delete_from_watchlist')


class StockViewRegressionTests(unittest.TestCase):
    @classmethod
    def setUpClass(cls):
        with connection.schema_editor() as editor:
            for model in (get_user_model(), Portfolio, SoldStock, Watchlist, PrecisionScanRun):
                editor.create_model(model)

    def setUp(self):
        self.atomic = transaction.atomic()
        self.atomic.__enter__()
        self.user = get_user_model().objects.create(username=self.id())
        self.item = Portfolio.objects.create(user=self.user, symbol='TEST', quantity=10, entry_price=100)
        self.factory = RequestFactory()

    def tearDown(self):
        transaction.set_rollback(True)
        self.atomic.__exit__(None, None, None)

    def request(self, method, data=None):
        request = getattr(self.factory, method)('/', data or {})
        request.user = self.user
        return request

    def test_get_cannot_delete(self):
        watched = Watchlist.objects.create(user=self.user, symbol='TEST')
        self.assertEqual(delete_portfolio(self.request('get'), self.item.pk).status_code, 405)
        self.assertEqual(delete_watchlist(self.request('get'), watched.pk).status_code, 405)
        self.assertTrue(Portfolio.objects.filter(pk=self.item.pk).exists())
        self.assertTrue(Watchlist.objects.filter(pk=watched.pk).exists())

    def test_post_deletes_owned_records(self):
        watched = Watchlist.objects.create(user=self.user, symbol='TEST')
        self.assertEqual(delete_portfolio(self.request('post'), self.item.pk).status_code, 302)
        self.assertEqual(delete_watchlist(self.request('post'), watched.pk).status_code, 302)
        self.assertFalse(Portfolio.objects.filter(pk=self.item.pk).exists())
        self.assertFalse(Watchlist.objects.filter(pk=watched.pk).exists())

    def test_other_user_cannot_delete(self):
        other = get_user_model().objects.create(username='other')
        request = self.request('post')
        request.user = other
        with self.assertRaises(Http404):
            delete_portfolio(request, self.item.pk)
        self.assertTrue(Portfolio.objects.filter(pk=self.item.pk).exists())

    def test_partial_sale(self):
        sell(self.request('post', {'quantity': '4', 'sell_price': '120'}), self.item.pk)
        self.item.refresh_from_db()
        self.assertEqual(self.item.quantity, 6)
        self.assertEqual(SoldStock.objects.get(user=self.user).profit_loss, 80)

    def test_sale_rolls_back_if_portfolio_update_fails(self):
        with patch.object(Portfolio, 'save', side_effect=RuntimeError('write failed')):
            with self.assertRaises(RuntimeError):
                sell(self.request('post', {'quantity': '4', 'sell_price': '120'}), self.item.pk)
        self.item.refresh_from_db()
        self.assertEqual(self.item.quantity, 10)
        self.assertFalse(SoldStock.objects.filter(user=self.user).exists())

    def test_oversell_rejected(self):
        sell(self.request('post', {'quantity': '11', 'sell_price': '120'}), self.item.pk)
        self.item.refresh_from_db()
        self.assertEqual(self.item.quantity, 10)
        self.assertFalse(SoldStock.objects.filter(user=self.user).exists())

    def test_bridge_imports_resolve(self):
        import importlib
        tree = ast.parse((ROOT / 'stocks/views/trading_bots.py').read_text(encoding='utf-8'))
        imports = [n for n in ast.walk(tree) if isinstance(n, ast.ImportFrom)
                   and any(a.name == 'RobotBridge' for a in n.names)]
        self.assertTrue(imports)
        for node in imports:
            name = '.' * node.level + node.module
            module = importlib.import_module(name, package='stocks.views')
            self.assertTrue(callable(module.RobotBridge))

    def test_rs_missing_values_are_not_ranked(self):
        values = {str(i): i for i in range(10)}
        values.update(missing=None, invalid=float('nan'), infinite=float('inf'))
        ranks, count = rank_valid_returns(values)
        self.assertEqual(count, 10)
        self.assertEqual(set(ranks), {str(i) for i in range(10)})
        self.assertEqual(ranks['9'], 99)
        self.assertIn('0', ranks)  # An actual zero return is valid.

    def test_rs_insufficient_data_has_no_scores(self):
        ranks, count = rank_valid_returns({'one': 12, 'missing': None})
        self.assertEqual(count, 1)
        self.assertEqual(ranks, {})

    def test_empty_scan_is_latest_and_preserves_legacy_history(self):
        from datetime import timedelta
        from django.utils import timezone
        now = timezone.now()
        old = now - timedelta(days=1)
        record = PrecisionScanRun.objects.create(
            user=self.user, started_at=now, status='completed', candidate_count=0,
        )
        runs = scan_timestamps([old], [record])
        self.assertEqual(runs, [now, old])
        self.assertEqual(PrecisionScanRun.objects.get(pk=record.pk).candidate_count, 0)

    def test_failed_scan_is_visible_in_history(self):
        from django.utils import timezone
        record = PrecisionScanRun.objects.create(
            user=self.user, started_at=timezone.now(), status='failed', message='RS unavailable',
        )
        self.assertEqual(scan_timestamps([], [record]), [record.started_at])

    def test_precision_status_template(self):
        for filename in ('precision_scan.html', 'us_precision_scan.html'):
            with self.subTest(template=filename):
                self.check_precision_status_template(filename)

    def check_precision_status_template(self, filename):
        from django.template import Context, Engine
        from types import SimpleNamespace
        template = (ROOT / 'stocks/templates/stocks' / filename).read_text(encoding='utf-8')
        # Render the actual status banner without loading scanner/network dependencies.
        start = template.index('{% if scan_run_info %}')
        end = template.index('</div>\n{% endif %}', start) + len('</div>\n{% endif %}')
        compiled = Engine().from_string(template[start:end])
        record = SimpleNamespace(started_at=None, status='completed', candidate_count=0,
                                 rs_count=80, total_symbols=400)
        html = compiled.render(Context({'scan_run_info': record}))
        self.assertIn('รอบนี้ไม่พบหุ้นผ่านเกณฑ์', html)
        self.assertIn('80/400', html)
        record.status = 'failed'
        record.message = 'ข้อมูล RS ไม่เพียงพอ'
        html = compiled.render(Context({'scan_run_info': record}))
        self.assertIn('ข้อมูล RS ไม่เพียงพอ', html)

    def test_scanner_history_keeps_markets_and_users_separate(self):
        from datetime import timedelta
        from django.utils import timezone
        from types import SimpleNamespace
        now = timezone.now()
        other = get_user_model().objects.create(username='other-scanner-user')
        for user in (self.user, other):
            for market in ('SET', 'US'):
                PrecisionScanRun.objects.create(
                    user=user, market=market, started_at=now, status='completed', candidate_count=0,
                )
        PrecisionScanRun.objects.create(
            user=self.user, market='US', started_at=now + timedelta(seconds=1), status='running',
        )
        tree = ast.parse((ROOT / 'stocks/views/scanners.py').read_text(encoding='utf-8'))
        for view_name, market in (('precision_momentum_scanner', 'SET'), ('us_precision_scanner', 'US')):
            with self.subTest(view=view_name):
                view = next(n for n in tree.body if isinstance(n, ast.FunctionDef) and n.name == view_name)
                idx = next(i for i, n in enumerate(view.body) if isinstance(n, ast.Assign)
                           and isinstance(n.targets[0], ast.Name) and n.targets[0].id == 'run_records')
                # Execute the actual history selection code with real database rows.
                old = now - timedelta(days=1)
                scope = dict(globals(), request=SimpleNamespace(user=self.user), all_runs=[old])
                exec(compile(ast.Module(body=view.body[idx:idx + 3], type_ignores=[]), view_name, 'exec'), scope)
                self.assertEqual(scope['all_runs'], [now, old])
                self.assertEqual(len(scope['run_records']), 1)
                self.assertEqual(scope['run_metadata'][now].market, market)
                self.assertEqual(scope['run_metadata'][now].user_id, self.user.pk)


if __name__ == '__main__':
    unittest.main(verbosity=2)
