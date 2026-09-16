"""ตรวจพฤติกรรมที่เพิ่งแก้ในฝั่งบอท/โบรกเกอร์ และการแปลงค่าเงินของคริปโต

ครอบคลุมข้อบกพร่องที่เคยทำให้:
  1. ออเดอร์เปิดจริงที่โบรกเกอร์แต่ไม่มีแถวใน DB (MetaApi ตอบ 202 แล้วถูกมองว่าล้มเหลว)
  2. ปุ่ม Panic รายงานว่าปิดไม่สำเร็จ ทั้งที่คำสั่งปิดถูกรับเข้าคิวแล้ว
  3. เน็ตสะดุดครั้งเดียวแล้วออเดอร์ที่ยังเปิดอยู่ถูกมาร์คว่าปิดพร้อมราคาปิดที่กุขึ้น
  4. market order ที่ไม่ส่ง price มาทำให้ Decimal('None') ระเบิดหลังยิงคำสั่งไปแล้ว
  5. กำไรคริปโตถูกบันทึกเป็นบาททั้งที่เป็นดอลลาร์ (ต่ำกว่าจริงราว 30 เท่า)
  6. ดึงข้อมูลดัชนีไม่ได้แล้วระบบแจ้งว่าตลาด GREEN ชวนให้เข้าซื้อ

ใช้ DB ในหน่วยความจำ ไม่โหลด config.settings ของโปรเจกต์ (เลี่ยง daphne/channels)
รันจาก repo root: python3 scratch/test_trading_bridge_and_fx.py
"""
import sys
import unittest
from decimal import Decimal
from pathlib import Path
from unittest.mock import Mock, patch

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT))

from django.conf import settings

settings.configure(
    SECRET_KEY='offline-test-only',
    INSTALLED_APPS=['django.contrib.auth', 'django.contrib.contenttypes', 'stocks'],
    DATABASES={'default': {'ENGINE': 'django.db.backends.sqlite3', 'NAME': ':memory:'}},
    USE_TZ=True,
    CACHES={'default': {'BACKEND': 'django.core.cache.backends.locmem.LocMemCache'}},
)
import django  # noqa: E402

django.setup()

from django.contrib.auth import get_user_model  # noqa: E402
from django.db import connection, transaction  # noqa: E402

from stocks.models import BrokerType, TradeOrder, TradingAccount  # noqa: E402
from stocks.trading_bridge import RobotBridge  # noqa: E402


def _response(status, payload=None, text=None):
    """สร้าง requests.Response ปลอมแบบง่ายๆ"""
    res = Mock()
    res.status_code = status
    if text is not None:
        res.text = text
        res.json.side_effect = ValueError('no json')
    else:
        import json as _json
        body = {} if payload is None else payload
        res.text = _json.dumps(body)
        res.json.return_value = body
    return res


class MetaApiOutcomeTests(unittest.TestCase):
    """_meta_api_outcome — หัวใจของการตัดสินว่า 'โบรกเกอร์รับคำสั่งแล้วหรือยัง'"""

    def test_200_is_accepted(self):
        ok, _body, err = RobotBridge._meta_api_outcome(_response(200, {'orderId': '1'}))
        self.assertTrue(ok)
        self.assertIsNone(err)

    def test_202_queued_is_accepted(self):
        # นี่คือบั๊กหลัก: 202 แปลว่ารับเข้าคิวแล้ว ไม่ใช่ล้มเหลว
        ok, _body, err = RobotBridge._meta_api_outcome(_response(202, {'orderId': '1'}))
        self.assertTrue(ok, '202 (queued) ต้องถือว่าโบรกเกอร์รับคำสั่งแล้ว')
        self.assertIsNone(err)

    def test_202_with_empty_body_is_accepted(self):
        ok, _body, err = RobotBridge._meta_api_outcome(_response(202, text=''))
        self.assertTrue(ok)
        self.assertIsNone(err)

    def test_mt_success_code_10009_is_accepted(self):
        ok, _b, _e = RobotBridge._meta_api_outcome(_response(200, {'numericCode': 10009}))
        self.assertTrue(ok)

    def test_mt_error_code_inside_2xx_is_rejected(self):
        ok, _b, err = RobotBridge._meta_api_outcome(
            _response(200, {'numericCode': 10019, 'message': 'no money'}))
        self.assertFalse(ok, '2xx ที่มี numericCode ผิดพลาดต้องถือว่าไม่สำเร็จ')
        self.assertEqual(err, 'no money')

    def test_http_error_is_rejected_with_message(self):
        ok, _b, err = RobotBridge._meta_api_outcome(_response(400, {'message': 'bad symbol'}))
        self.assertFalse(ok)
        self.assertEqual(err, 'bad symbol')

    def test_non_json_error_body_does_not_raise(self):
        ok, _b, err = RobotBridge._meta_api_outcome(_response(500, text='<html>oops</html>'))
        self.assertFalse(ok)
        self.assertIn('500', err)


class BridgeDbTests(unittest.TestCase):
    """เทสต์ที่ต้องมี TradingAccount/TradeOrder จริง"""

    @classmethod
    def setUpClass(cls):
        with connection.schema_editor() as editor:
            for model in (get_user_model(), TradingAccount, TradeOrder):
                editor.create_model(model)

    def setUp(self):
        # ใช้ transaction ที่ roll back ทุกเทสต์ แบบเดียวกับ test_stocks_view_regressions
        self.atomic = transaction.atomic()
        self.atomic.__enter__()
        self.user = get_user_model().objects.create(username=self.id())
        self.account = TradingAccount.objects.create(
            user=self.user, broker=BrokerType.META_API,
            api_key=' token ', account_id='acc-1', is_active=True,
        )
        self.bridge = RobotBridge(account=self.account)
        self.bridge._region_cache = 'new-york'  # กันไม่ให้ยิงเน็ตจริงหา region

    def tearDown(self):
        transaction.set_rollback(True)
        self.atomic.__exit__(None, None, None)

    # ── 1. market order ที่ไม่มีราคา ต้องไม่ทำให้ Decimal ระเบิด ──
    def test_execute_trade_without_price_does_not_crash(self):
        with patch.object(RobotBridge, '_trade_via_meta_api',
                          return_value={'order_id': 'P1', 'status': 'OPEN', 'actual_price': None}):
            order = self.bridge.execute_trade(symbol='XAUUSD', side='BUY', volume=0.01, price=None)
        self.assertEqual(order.entry_price, Decimal('0'))
        self.assertEqual(order.order_id, 'P1')

    def test_execute_trade_falls_back_to_requested_price(self):
        with patch.object(RobotBridge, '_trade_via_meta_api',
                          return_value={'order_id': 'P2', 'status': 'OPEN', 'actual_price': None}):
            order = self.bridge.execute_trade(symbol='XAUUSD', side='BUY', volume=0.01, price=2400.5)
        self.assertEqual(order.entry_price, Decimal('2400.5'))

    # ── 2. แยก "ไม่มีโพซิชัน" ออกจาก "ดึงไม่สำเร็จ" ──
    def test_fetch_open_positions_returns_none_on_http_error(self):
        with patch('stocks.trading_bridge.requests.get', return_value=_response(503, text='down')):
            self.assertIsNone(self.bridge.fetch_open_positions())

    def test_fetch_open_positions_returns_none_on_exception(self):
        with patch('stocks.trading_bridge.requests.get', side_effect=OSError('boom')):
            self.assertIsNone(self.bridge.fetch_open_positions())

    def test_fetch_open_positions_returns_empty_list_when_flat(self):
        with patch('stocks.trading_bridge.requests.get', return_value=_response(200, [])):
            self.assertEqual(self.bridge.fetch_open_positions(), [])

    def test_get_open_positions_still_returns_list_on_failure(self):
        # ผู้เรียกเดิมยังคาดหวัง list เสมอ
        with patch('stocks.trading_bridge.requests.get', side_effect=OSError('boom')):
            self.assertEqual(self.bridge.get_open_positions(), [])

    # ── 3. เน็ตสะดุดต้องไม่ปิดออเดอร์ที่ยังเปิดอยู่ ──
    def _open_order(self, order_id='POS-1'):
        return TradeOrder.objects.create(
            user=self.user, account=self.account, symbol='XAUUSD', order_id=order_id,
            order_type='BUY', volume=Decimal('0.01'), entry_price=Decimal('2400'),
            status=TradeOrder.OrderStatus.OPEN,
        )

    def test_sync_does_not_close_orders_when_fetch_fails(self):
        order = self._open_order()
        with patch.object(RobotBridge, 'fetch_open_positions', return_value=None):
            result = self.bridge.sync_trade_status()
        order.refresh_from_db()
        self.assertEqual(order.status, TradeOrder.OrderStatus.OPEN,
                         'ดึง position ไม่สำเร็จ ต้องไม่มาร์คออเดอร์ว่าปิด')
        self.assertEqual(result['updated'], 0)
        self.assertTrue(result['errors'])

    def test_sync_closes_order_that_is_genuinely_gone(self):
        order = self._open_order()
        with patch.object(RobotBridge, 'fetch_open_positions', return_value=[]):
            self.bridge.sync_trade_status()
        order.refresh_from_db()
        self.assertEqual(order.status, TradeOrder.OrderStatus.CLOSED)

    def test_sync_returns_dict_for_non_metaapi_broker(self):
        self.account.broker = BrokerType.MANUAL if hasattr(BrokerType, 'MANUAL') else 'OTHER'
        bridge = RobotBridge(account=self.account)
        result = bridge.sync_trade_status()
        self.assertIsInstance(result, dict, 'ต้องคืนรูปทรงเดียวกันเสมอ ผู้เรียกจะได้ไม่ต้องเดา')
        self.assertEqual(result['updated'], 0)

    # ── 4. ปุ่ม Panic ──
    def test_close_all_counts_202_as_success(self):
        positions = [{'id': '1', 'symbol': 'XAUUSD'}, {'id': '2', 'symbol': 'XAUUSD'}]
        with patch.object(RobotBridge, 'fetch_open_positions', return_value=positions), \
             patch('stocks.trading_bridge.requests.post', return_value=_response(202, {})):
            self.assertTrue(self.bridge.close_all_positions())

    def test_close_all_reports_failure_when_one_close_is_rejected(self):
        positions = [{'id': '1', 'symbol': 'XAUUSD'}, {'id': '2', 'symbol': 'XAUUSD'}]
        with patch.object(RobotBridge, 'fetch_open_positions', return_value=positions), \
             patch('stocks.trading_bridge.requests.post',
                   side_effect=[_response(202, {}), _response(400, {'message': 'nope'})]):
            self.assertFalse(self.bridge.close_all_positions(),
                             'ปิดได้ไม่ครบต้องไม่รายงานว่าสำเร็จ')

    def test_close_all_raises_when_positions_cannot_be_read(self):
        with patch.object(RobotBridge, 'fetch_open_positions', return_value=None):
            with self.assertRaises(RuntimeError):
                self.bridge.close_all_positions()

    def test_close_all_looks_up_region_once_not_per_position(self):
        positions = [{'id': str(i), 'symbol': 'XAUUSD'} for i in range(5)]
        self.bridge._region_cache = None
        with patch.object(RobotBridge, 'fetch_open_positions', return_value=positions), \
             patch('stocks.trading_bridge.requests.get',
                   return_value=_response(200, {'region': 'london'})) as mock_get, \
             patch('stocks.trading_bridge.requests.post', return_value=_response(200, {})):
            self.bridge.close_all_positions()
        self.assertEqual(mock_get.call_count, 1,
                         'region ต้องหาแค่ครั้งเดียว ไม่ใช่ทุกโพซิชันในลูป')


class CryptoFxTests(unittest.TestCase):
    """คริปโตราคาเป็น USD ต้องถูกแปลงเป็นบาทเหมือนหุ้น US"""

    def test_sell_stock_converts_crypto(self):
        src = (ROOT / 'stocks' / 'views' / 'portfolio.py').read_text(encoding='utf-8')
        self.assertIn('if portfolio_item.market in (MarketType.US, MarketType.CRYPTO):', src,
                      'sell_stock ต้องแปลงค่าเงินให้คริปโตด้วย ไม่ใช่เฉพาะ MarketType.US')

    def test_realized_report_separates_fx_from_thai_commission(self):
        src = (ROOT / 'stocks' / 'views' / 'portfolio.py').read_text(encoding='utf-8')
        self.assertIn('needs_fx = s.market in (MarketType.US, MarketType.CRYPTO)', src)
        self.assertIn('is_thai = s.market == MarketType.SET', src)

    def test_position_sizing_uses_usd_equity_for_crypto(self):
        src = (ROOT / 'stocks' / 'views' / 'portfolio.py').read_text(encoding='utf-8')
        self.assertIn('is_usd_market = market in (MarketType.US, MarketType.CRYPTO)', src,
                      'entry/stop ของคริปโตเป็น USD equity จึงต้องแปลงเป็น USD ด้วย')


class MarketTimingFallbackTests(unittest.TestCase):
    """ดึงข้อมูลดัชนีไม่ได้ ต้องไม่แต่งสัญญาณเป็น GREEN"""

    def test_unavailable_is_not_green(self):
        from stocks.market_timing import _unavailable_status
        res = _unavailable_status('SET', 'timeout')
        self.assertNotEqual(res['status_code'], 'GREEN',
                            'ข้อมูลล่มต้องไม่รายงานว่าตลาดเอื้ออำนวย')
        self.assertIs(res['data_ok'], False)
        self.assertEqual(res['distribution_count'], 0)

    def test_download_failure_does_not_report_green(self):
        from django.core.cache import cache
        import stocks.market_timing as mt

        cache.clear()
        fake_yf = Mock(download=Mock(side_effect=OSError('net')))
        with patch.dict('sys.modules', {'yfinance': fake_yf}):
            res = mt.get_market_timing_status(market='SET')
        self.assertNotEqual(res['status_code'], 'GREEN')
        self.assertIs(res['data_ok'], False)

    def test_short_history_does_not_report_green(self):
        from django.core.cache import cache
        import pandas as pd
        import stocks.market_timing as mt

        cache.clear()
        tiny = pd.DataFrame({'Close': [1.0, 2.0], 'Volume': [10, 20]})
        fake_yf = Mock(download=Mock(return_value=tiny))
        with patch.dict('sys.modules', {'yfinance': fake_yf}):
            res = mt.get_market_timing_status(market='US')
        self.assertNotEqual(res['status_code'], 'GREEN',
                            'ข้อมูลสั้นเกินไปก็ประเมินไม่ได้ ต้องไม่บอกว่า GREEN')
        self.assertIs(res['data_ok'], False)


class BotAccountResolutionTests(unittest.TestCase):
    """บอทต้องผูกกับบัญชีที่กำลังวนอยู่ ไม่ใช่บัญชี active ตัวแรกเสมอ"""

    def test_bots_bind_bridge_to_the_looped_account(self):
        for name in ('run_gold_bot.py', 'run_crypto_bot.py'):
            src = (ROOT / 'stocks' / 'management' / 'commands' / name).read_text(encoding='utf-8')
            self.assertIn('RobotBridge(account=acc)', src, f'{name} ต้องใช้ account=acc')
            self.assertNotIn('RobotBridge(user=acc.user)', src,
                             f'{name} ยังผูกกับบัญชีแรกของ user อยู่')
            self.assertIn('fetch_open_positions()', src,
                          f'{name} ต้องแยก "ดึงไม่ได้" ออกจาก "ไม่มีออเดอร์"')


if __name__ == '__main__':
    unittest.main(verbosity=2)
