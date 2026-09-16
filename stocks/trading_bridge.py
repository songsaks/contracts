import logging
import requests
from decimal import Decimal
from django.utils import timezone

from .models import TradingAccount, TradeOrder, BrokerType

logger = logging.getLogger(__name__)

# MetaApi ตอบ 200 เมื่อทำรายการเสร็จทันที และ 202 เมื่อรับคำสั่งเข้าคิวไปแล้ว
# ทั้งสองแบบแปลว่า "โบรกเกอร์รับคำสั่งแล้ว" — ถ้าถือว่า 202 คือความล้มเหลว
# ออเดอร์จะเปิดจริงที่โบรกเกอร์แต่ไม่มีแถวใน DB ซึ่งอันตรายกว่าการสั่งไม่ผ่านเสียอีก
_META_API_OK_STATUSES = (200, 202)
# 10009 = TRADE_RETCODE_DONE ของ MT5 (สำเร็จ) ไม่ใช่รหัสข้อผิดพลาด
_MT_SUCCESS_CODES = {0, 10009}

_DEFAULT_REGION = "new-york"


class RobotBridge:
    """
    Bridge สำหรับเชื่อมโยงระหว่างระบบวิเคราะห์ (AI/Signals) กับโลกแห่งการเทรดจริง
    รองรับการทำงานบน Ubuntu Server และ PostgreSQL
    """

    def __init__(self, account_id=None, user=None, account=None):
        self.account = None
        if account:
            self.account = account
        elif account_id:
            try:
                # ป้องกัน Error: Field 'id' expected a number but got ...
                safe_id = int(str(account_id).strip())
                self.account = TradingAccount.objects.get(pk=safe_id)
            except (ValueError, TypeError, TradingAccount.DoesNotExist):
                if user:
                    self.account = TradingAccount.objects.filter(user=user, is_active=True).first()
        elif user:
            # ดึงบัญชีแรกที่ Active ของผู้ใช้
            self.account = TradingAccount.objects.filter(user=user, is_active=True).first()
        
        if not self.account:
            raise ValueError("No active trading account found for this operation.")
            
        self.broker_type = self.account.broker
        self.user = self.account.user
        self._region_cache = None

    # ────────────────────────────────────────────────────────────────
    # MetaApi helpers — รวมโค้ดที่เคยซ้ำอยู่ 6 ที่ให้เหลือจุดเดียว
    # ────────────────────────────────────────────────────────────────

    def _token(self):
        return (self.account.api_key or '').strip()

    def _region(self, timeout=5):
        """
        ค้นหา Region จริงของบัญชี (New York/London/Singapore) แล้วจำไว้ทั้งอายุของ bridge

        เดิมโค้ดชุดนี้ถูกคัดลอกไว้ทุกเมธอด ทำให้ทุกคำสั่งต้องยิง HTTP เพิ่มอีกหนึ่งครั้ง
        และใน close_all_positions ยังยิงซ้ำ "ทุกโพซิชัน" ในลูปอีกด้วย
        """
        if self._region_cache:
            return self._region_cache

        region = _DEFAULT_REGION
        try:
            info_url = (f"https://mt-provisioning-api-v1.agiliumtrade.ai/users/current/"
                        f"accounts/{self.account.account_id}")
            info_res = requests.get(info_url, headers={"auth-token": self._token()}, timeout=timeout)
            if info_res.status_code == 200:
                region = info_res.json().get('region') or _DEFAULT_REGION
        except Exception as e:
            logger.warning(f"MetaApi region lookup failed, using {_DEFAULT_REGION}: {e}")

        self._region_cache = region
        return region

    def _client_url(self, path, timeout=5):
        """ประกอบ URL ของ mt-client-api ตาม region ของบัญชี"""
        return (f"https://mt-client-api-v1.{self._region(timeout=timeout)}.agiliumtrade.ai"
                f"/users/current/accounts/{self.account.account_id}/{path.lstrip('/')}")

    @staticmethod
    def _meta_api_outcome(response):
        """
        ตีความคำตอบของ MetaApi ให้เป็น (accepted: bool, body: dict, error: str|None)

        ยอมรับทั้ง 200 (sync) และ 202 (queued) แล้วค่อยตรวจ numericCode ข้างใน
        อีกชั้น เพราะ MetaApi ตอบ 2xx ได้แม้ฝั่ง MT จะปฏิเสธคำสั่ง
        """
        try:
            body = response.json() if response.text else {}
        except ValueError:
            body = {}
        if not isinstance(body, dict):
            body = {}

        if response.status_code not in _META_API_OK_STATUSES:
            err = (body.get('message') or body.get('error')
                   or f'HTTP {response.status_code}: {response.text[:200]}')
            return False, body, err

        num_code = body.get('numericCode')
        if num_code is not None and num_code not in _MT_SUCCESS_CODES:
            err = body.get('message') or body.get('error') or f'MT error code {num_code}'
            return False, body, err

        return True, body, None

    @staticmethod
    def _broker_symbol(symbol):
        """แมปชื่อ Symbol ให้เข้ากับ Broker (เช่น GC=F -> XAUUSD, BTC-USD -> BTCUSD)"""
        return (str(symbol or '')
                .replace("GC=F", "XAUUSD")
                .replace("XAUUSD=X", "XAUUSD")
                .replace("BTC-USD", "BTCUSD"))

    def execute_trade(self, symbol, side, volume, price=None, sl=None, tp=None, strategy="Manual"):
        """
        ฟังก์ชันหลักในการส่งคำสั่งเทรด
        """
        logger.info(f"RobotBridge: Executing {side} {volume} units of {symbol} via {self.broker_type}")
        
        # 1. เตรียมข้อมูล Result (จำลองหรือจริง)
        order_result = None
        
        # 2. แยก Logic ตามประเภท Broker
        try:
            if self.broker_type == BrokerType.META_API:
                order_result = self._trade_via_meta_api(symbol, side, volume, price, sl, tp)
            elif self.broker_type == BrokerType.OANDA:
                order_result = self._trade_via_oanda(symbol, side, volume, price, sl, tp)
            else:
                # Demo Mode / Manual
                order_result = {
                    'order_id': f'DEMO-{timezone.now().strftime("%Y%m%d%H%M%S")}',
                    'status': 'OPEN',
                    'actual_price': price or 0.0
                }

            # 3. บันทึกประวัติลง Database ทันที (PostgreSQL)
            # .get(key, default) คืน None เมื่อคีย์มีอยู่แต่ค่าเป็น None ซึ่งเกิดได้จริง
            # ตอนโบรกเกอร์ไม่ส่งราคาที่แมตช์กลับมาและผู้เรียกไม่ได้ระบุ price (market order)
            # ปล่อยไว้จะกลายเป็น Decimal('None') -> InvalidOperation *หลัง* ออเดอร์เปิดไปแล้ว
            entry_price = order_result.get('actual_price')
            if entry_price in (None, ''):
                entry_price = price if price not in (None, '') else 0

            order = TradeOrder.objects.create(
                user=self.user,
                account=self.account,
                symbol=symbol,
                order_id=order_result.get('order_id'),
                order_type=side,
                volume=Decimal(str(volume)),
                entry_price=Decimal(str(entry_price)),
                stop_loss=Decimal(str(sl)) if sl else None,
                take_profit=Decimal(str(tp)) if tp else None,
                status=TradeOrder.OrderStatus.OPEN,
                opened_at=timezone.now(),
                strategy=strategy
            )
            
            logger.info(f"RobotBridge: Order logged successfully. ID: {order.id}")
            return order

        except Exception as e:
            logger.error(f"RobotBridge Error: {str(e)}")
            raise e

    def modify_position(self, position_id, sl=None, tp=None):
        """
        แก้ไขค่า Stop Loss หรือ Take Profit ของออเดอร์ที่เปิดอยู่
        Returns (success: bool, error: str|None)
        """
        url = self._client_url("trade")
        headers = {"auth-token": self._token(), "Content-Type": "application/json"}

        payload = {"actionType": "POSITION_MODIFY", "positionId": str(position_id)}
        if sl is not None: payload["stopLoss"]   = float(sl)
        if tp is not None: payload["takeProfit"] = float(tp)

        try:
            logger.info(f"MetaApi Modify | payload={payload}")
            response = requests.post(url, headers=headers, json=payload, timeout=10)
            logger.info(f"MetaApi Modify | status={response.status_code} body={response.text[:300]}")

            accepted, _body, err = self._meta_api_outcome(response)
            return (True, None) if accepted else (False, err)
        except Exception as e:
            logger.error(f"MetaApi Modify Error: {str(e)}")
            return False, str(e)

    def _trade_via_meta_api(self, symbol, side, volume, price, sl, tp):
        """
        ส่งคำสั่งผ่าน MetaApi (MT4/MT5 Cloud API) 
        """
        token = self._token()  # ตัดช่องว่างหัวท้ายเพื่อความชัวร์
        account_id = self.account.account_id

        if not token or not account_id:
            raise ValueError("MetaApi Token or Account ID is missing in TradingAccount configuration.")

        url = self._client_url("trade")
        headers = {
            "auth-token": token,
            "Content-Type": "application/json"
        }

        payload = {
            "symbol": self._broker_symbol(symbol),
            "actionType": "ORDER_TYPE_BUY" if side.upper() == "BUY" else "ORDER_TYPE_SELL",
            "volume": float(volume),
        }

        if sl: payload["stopLoss"] = float(sl)
        if tp: payload["takeProfit"] = float(tp)

        try:
            logger.info(f"MetaApi Request: {url} | Payload: {payload}")
            response = requests.post(url, headers=headers, json=payload, timeout=15)
            logger.info(f"MetaApi Trade | status={response.status_code} body={response.text[:300]}")

            accepted, res_data, err = self._meta_api_outcome(response)
            if not accepted:
                logger.error(f"MetaApi Error ({response.status_code}): {err}")
                raise Exception(f"MetaApi Error: {err}")

            logger.info(f"MetaApi Success: {res_data}")
            return {
                # positionId คือสิ่งที่ get_open_positions ใช้เทียบ ส่วน orderId เป็นของคำสั่ง
                # ถ้าเก็บผิดตัว sync_trade_status จะมองว่าออเดอร์ถูกปิดไปแล้วทันทีที่ sync ครั้งแรก
                'order_id': (res_data.get('positionId') or res_data.get('orderId')
                             or f"MT5-{timezone.now().timestamp()}"),
                'status': 'OPEN',
                'actual_price': res_data.get('price') or price
            }

        except Exception as e:
            logger.error(f"MetaApi Connection Error: {str(e)}")
            raise e

    def _trade_via_oanda(self, symbol, side, volume, price, sl, tp):
        """
        ส่งคำสั่งผ่าน OANDA v20 REST API
        """
        # TODO: Implement oandapyV20
        return {
            'order_id': f'OAN-{timezone.now().timestamp()}',
            'status': 'OPEN',
            'actual_price': price
        }

    def sync_account_balance(self):
        """
        ดึงยอดคงเหลือปัจจุบันจาก Broker มาอัปเดตใน Database
        รองรับการตรวจหา Region (New York/London/Singapore) อัตโนมัติ
        """
        if self.broker_type != BrokerType.META_API:
            return False

        headers = {"auth-token": self._token()}

        try:
            # Fast Sync: ลด Timeout เหลือ 3 วินาทีเพื่อไม่ให้หน้าเว็บค้าง
            url = self._client_url("account-information", timeout=3)
            response = requests.get(url, headers=headers, timeout=5)
            
            if response.status_code == 200:
                data = response.json()
                self.account.balance  = Decimal(str(data.get('balance', 0)))
                self.account.equity   = Decimal(str(data.get('equity', 0)))
                self.account.currency = data.get('currency', 'USD')
                self.account.save()
                return True
            else:
                return False

        except Exception as e:
            logger.error(f"Fast Sync Exception: {str(e)}")
            return False

    def get_open_positions(self):
        """
        ดึงรายการออเดอร์ที่เปิดค้างอยู่ทั้งหมด
        """
        if self.broker_type != BrokerType.META_API:
            return []

        return self.fetch_open_positions() or []

    def fetch_open_positions(self):
        """
        เหมือน get_open_positions แต่แยก "ไม่มีโพซิชัน" ([]) ออกจาก "ดึงไม่สำเร็จ" (None)

        ความต่างนี้สำคัญมาก: ผู้เรียกบางรายใช้ "ไม่อยู่ในลิสต์" เป็นหลักฐานว่าออเดอร์ปิดแล้ว
        ถ้าเน็ตหลุดหรือ API ตอบ 5xx แล้วเราคืน [] เฉยๆ ออเดอร์ที่ยังเปิดอยู่จริงทั้งหมด
        จะถูกมาร์คเป็น CLOSED พร้อมราคาปิด/กำไรขาดทุนที่กุขึ้นมา
        """
        if self.broker_type != BrokerType.META_API:
            return []

        try:
            res = requests.get(self._client_url("positions"),
                               headers={"auth-token": self._token()}, timeout=5)
        except Exception as e:
            logger.error(f"MetaApi positions error: {e}")
            return None

        if res.status_code != 200:
            logger.warning(f"MetaApi positions HTTP {res.status_code}: {res.text[:200]}")
            return None

        try:
            positions = res.json()
        except ValueError as e:
            logger.error(f"MetaApi positions returned non-JSON: {e}")
            return None

        return positions if isinstance(positions, list) else None

    def sync_trade_status(self):
        """
        ตรวจสอบและอัปเดตสถานะ TradeOrder ใน DB ให้ตรงกับ Broker
        และดึงค่า Exit Price / P/L จริงมาจากประวัติการเทรด (Deals)
        """
        # คืนรูปทรงเดียวกันเสมอ ผู้เรียกจะได้ไม่ต้องเดาว่าได้ int หรือ dict
        if self.broker_type != BrokerType.META_API:
            return {'updated': 0, 'errors': []}

        # sync เฉพาะ OPEN orders — CLOSED ที่ขาดข้อมูลให้ user กรอกเองผ่านปุ่ม ✏️
        orders_to_sync = TradeOrder.objects.filter(
            user=self.user,
            account=self.account,
            status=TradeOrder.OrderStatus.OPEN,
        )[:50]

        if not orders_to_sync.exists():
            return {'updated': 0, 'errors': []}

        # ดึงรายการ Position ที่ยังเปิดอยู่จริง
        # ถ้าดึงไม่สำเร็จต้องหยุดทันที ห้ามเดาว่า "ไม่อยู่ในลิสต์ = ปิดแล้ว"
        # ไม่งั้นเน็ตสะดุดครั้งเดียวจะปิดออเดอร์ที่ยังเปิดอยู่ทั้งพอร์ตพร้อมราคาปิดที่กุขึ้น
        live_positions = self.fetch_open_positions()
        if live_positions is None:
            return {'updated': 0,
                    'errors': ['ดึงรายการ position จากโบรกเกอร์ไม่สำเร็จ — ข้ามการ sync รอบนี้ '
                               'เพื่อไม่ให้ออเดอร์ที่ยังเปิดอยู่ถูกมาร์คว่าปิดแล้ว']}

        updated_count = 0
        sync_errors = []

        # build live lookup dict: order_id → position data
        live_map = {str(p.get('id')): p for p in live_positions}

        for order in orders_to_sync:
            # queryset กรอง status=OPEN ไว้แล้ว ทุกตัวที่เข้ามาถึงตรงนี้จึงยังเปิดอยู่
            live_pos = live_map.get(str(order.order_id))
            if live_pos:
                # อัปเดต floating P/L และ current price ทุก sync
                try:
                    from decimal import Decimal as _Dec
                    order.profit_loss   = _Dec(str(live_pos.get('profit', 0)))
                    # บันทึก current price ไว้ใช้เป็น exit price หาก position ปิด
                    cur_price = live_pos.get('currentPrice') or live_pos.get('price')
                    if cur_price:
                        order.exit_price = _Dec(str(cur_price))
                    order.save(update_fields=['profit_loss', 'exit_price'])
                except Exception as e:
                    sync_errors.append(f"order {order.order_id}: อัปเดต floating P/L ไม่สำเร็จ — {e}")
                continue  # ยังไม่ปิด ข้ามไป

            # ไม่อยู่ใน live list → ปิดแล้ว
            order.status = TradeOrder.OrderStatus.CLOSED
            order.closed_at = timezone.now()

            # ปิดแล้ว — ใช้ exit_price/profit_loss ที่ snapshot ไว้ระหว่าง OPEN
            # (history-deals API ไม่พร้อมใช้งานสำหรับ account นี้)
            try:
                from decimal import Decimal as _Dec

                # คำนวณ pips จาก exit_price ที่บันทึกไว้ตอน live
                if order.entry_price and order.exit_price and float(order.exit_price) > 0:
                    diff = float(order.exit_price) - float(order.entry_price)
                    if order.order_type == 'SELL': diff = -diff
                    order.pips = round(diff, 2)
                    # คำนวณ gross_pl = pips × volume × multiplier (gold: 100, crypto: 1)
                    if not order.profit_loss:
                        symbol_upper = str(order.symbol or "").upper()
                        is_gold = any(x in symbol_upper for x in ['XAU', 'GC=F', 'GOLD'])
                        mult = 100 if is_gold else 1
                        lot = float(order.volume) if order.volume else 0.01
                        order.gross_pl  = round(diff * lot * mult, 2)
                        order.profit_loss = _Dec(str(order.gross_pl))

                if not order.exit_reason:
                    order.exit_reason = 'MANUAL'

                if order.opened_at and order.closed_at:
                    order.duration_sec = int((order.closed_at - order.opened_at).total_seconds())

            except Exception as e:
                sync_errors.append(f"Calc error for {order.order_id}: {e}")

            if not order.exit_price or float(order.exit_price or 0) == 0:
                sync_errors.append(f"order {order.order_id}: ไม่มี exit_price — เปิด position ก่อนปิดหน้าเว็บ snapshot ยังไม่บันทึก")

            order.save()
            updated_count += 1

        return {'updated': updated_count, 'errors': sync_errors}

    def close_all_positions(self, symbol=None):
        """
        สั่งปิดออเดอร์ทั้งหมดในพอร์ตทันที (Panic Button) หรือกรองตามสัญลักษณ์ที่ระบุ

        ปุ่มนี้คือทางออกฉุกเฉิน ถ้าดึงรายการโพซิชันไม่สำเร็จต้องโยน error ให้ผู้ใช้เห็น
        ห้ามเงียบแล้วคืน "สำเร็จ" เพราะผู้ใช้จะเข้าใจว่าปิดหมดแล้วทั้งที่ยังลอยอยู่
        """
        positions = self.fetch_open_positions()
        if positions is None:
            raise RuntimeError("ดึงรายการ position จากโบรกเกอร์ไม่สำเร็จ — ยังไม่ได้ปิดออเดอร์ใดๆ กรุณาลองใหม่")
        success_count = 0

        # ปรับรูปแบบสัญลักษณ์ให้ตรงกับ Broker
        target_symbol = None
        if symbol:
            target_symbol = self._broker_symbol(symbol)

        # ส่งคำสั่งปิดผ่าน Trade Endpoint — ประกอบ URL/headers ครั้งเดียวนอกลูป
        # (เดิมยิงหา region ใหม่ "ทุกโพซิชัน" ทำให้ปุ่ม Panic ช้าเป็นเท่าตัวโดยไม่จำเป็น)
        url = self._client_url("trade")
        headers = {"auth-token": self._token(), "Content-Type": "application/json"}

        attempted = 0
        for pos in positions:
            if target_symbol and pos.get('symbol') != target_symbol:
                continue
            pos_id = pos.get('id')
            attempted += 1

            payload = {
                "actionType": "POSITION_CLOSE_ID",
                "positionId": str(pos_id),
            }

            try:
                res = requests.post(url, headers=headers, json=payload, timeout=10)
                # 202 = โบรกเกอร์รับคำสั่งปิดเข้าคิวแล้ว ถือว่าสำเร็จเช่นเดียวกับ 200
                # เดิมนับเฉพาะ 200 ปุ่ม Panic จึงรายงานว่า "ปิดไม่สำเร็จ" ทั้งที่ปิดไปแล้ว
                accepted, _body, err = self._meta_api_outcome(res)
                if accepted:
                    success_count += 1
                else:
                    logger.error(f"MetaApi close position {pos_id} failed: {err}")
            except Exception as e:
                logger.error(f"MetaApi close position {pos_id} error: {e}")
                continue

        # ไม่มีโพซิชันให้ปิดคือ "ไม่มีอะไรค้าง" ไม่ใช่ความล้มเหลว
        return success_count == attempted

    def get_symbol_price(self, symbol="XAUUSD"):
        """
        ดึงราคา Bid/Ask ล่าสุดของ symbol จาก MetaApi
        """
        if self.broker_type != BrokerType.META_API:
            return None

        # ปรับชื่อสัญลักษณ์ให้ตรงกับ Broker
        clean_symbol = self._broker_symbol(symbol)

        url = self._client_url(f"symbols/{clean_symbol}/current-price")
        headers = {"auth-token": self._token()}
        
        try:
            res = requests.get(url, headers=headers, timeout=6)
            if res.status_code == 200:
                data = res.json()
                # คืนค่าเฉลี่ยของ Bid และ Ask (Mid Price)
                bid = float(data.get('bid') or 0)
                ask = float(data.get('ask') or 0)
                if bid > 0 and ask > 0:
                    return (bid + ask) / 2
                elif bid > 0:
                    return bid
                elif ask > 0:
                    return ask
            return None
        except Exception as e:
            logger.error(f"Error fetching symbol price from MetaApi: {e}")
            return None
