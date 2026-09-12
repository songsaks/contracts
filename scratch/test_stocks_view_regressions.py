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
from stocks.models import Portfolio, SoldStock, Watchlist, MarketType


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
            for model in (get_user_model(), Portfolio, SoldStock, Watchlist):
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


if __name__ == '__main__':
    unittest.main(verbosity=2)
