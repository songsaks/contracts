import logging
import requests
from decimal import Decimal
from django.utils import timezone
from .models import TradingAccount, TradeOrder, BrokerType

logger = logging.getLogger(__name__)

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
            order = TradeOrder.objects.create(
                user=self.user,
                account=self.account,
                symbol=symbol,
                order_id=order_result.get('order_id'),
                order_type=side,
                volume=Decimal(str(volume)),
                entry_price=Decimal(str(order_result.get('actual_price', price or 0))),
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
        token = self.account.api_key.strip()
        account_id = self.account.account_id

        try:
            info_url = f"https://mt-provisioning-api-v1.agiliumtrade.ai/users/current/accounts/{account_id}"
            info_res = requests.get(info_url, headers={"auth-token": token}, timeout=5)
            region = info_res.json().get('region', 'new-york') if info_res.status_code == 200 else 'new-york'
        except:
            region = "new-york"

        url = f"https://mt-client-api-v1.{region}.agiliumtrade.ai/users/current/accounts/{account_id}/trade"
        headers = {"auth-token": token, "Content-Type": "application/json"}

        payload = {"actionType": "POSITION_MODIFY", "positionId": str(position_id)}
        if sl is not None: payload["stopLoss"]   = float(sl)
        if tp is not None: payload["takeProfit"] = float(tp)

        try:
            logger.info(f"MetaApi Modify | payload={payload}")
            response = requests.post(url, headers=headers, json=payload, timeout=10)
            logger.info(f"MetaApi Modify | status={response.status_code} body={response.text[:300]}")

            # MetaApi returns 200 (sync) or 202 (async/queued) for successful trades
            if response.status_code in (200, 202):
                body = response.json() if response.text else {}
                # Check for MT-level error inside the response
                num_code = body.get('numericCode', 0)
                if num_code and num_code != 0 and num_code != 10009:
                    err = body.get('message') or body.get('error') or f'MT error code {num_code}'
                    return False, err
                return True, None
            else:
                try:
                    body = response.json()
                    err = body.get('message') or body.get('error') or f'HTTP {response.status_code}'
                except Exception:
                    err = f'HTTP {response.status_code}: {response.text[:200]}'
                return False, err
        except Exception as e:
            logger.error(f"MetaApi Modify Error: {str(e)}")
            return False, str(e)

    def _trade_via_meta_api(self, symbol, side, volume, price, sl, tp):
        """
        ส่งคำสั่งผ่าน MetaApi (MT4/MT5 Cloud API) 
        """
        token = self.account.api_key.strip() # ตัดช่องว่างหัวท้ายเพื่อความชัวร์
        account_id = self.account.account_id
        
        if not token or not account_id:
            raise ValueError("MetaApi Token or Account ID is missing in TradingAccount configuration.")

        # ตรวจหา Region จริงของบัญชี (New York/London/Singapore) เพื่อความแม่นยำ
        try:
            info_url = f"https://mt-provisioning-api-v1.agiliumtrade.ai/users/current/accounts/{account_id}"
            info_res = requests.get(info_url, headers={"auth-token": token}, timeout=5)
            region = info_res.json().get('region', 'new-york') if info_res.status_code == 200 else 'new-york'
        except:
            region = "new-york"

        url = f"https://mt-client-api-v1.{region}.agiliumtrade.ai/users/current/accounts/{account_id}/trade"
        
        headers = {
            "auth-token": token,
            "Content-Type": "application/json"
        }
        
        # แมปชื่อ Symbol ให้เข้ากับ Broker (เช่น GC=F -> XAUUSD)
        clean_symbol = symbol.replace("GC=F", "XAUUSD")
        
        payload = {
            "symbol": clean_symbol,
            "actionType": "ORDER_TYPE_BUY" if side.upper() == "BUY" else "ORDER_TYPE_SELL",
            "volume": float(volume),
        }
        
        if sl: payload["stopLoss"] = float(sl)
        if tp: payload["takeProfit"] = float(tp)

        try:
            logger.info(f"MetaApi Request: {url} | Payload: {payload}")
            response = requests.post(url, headers=headers, json=payload, timeout=15)
            res_data = response.json()
            
            if response.status_code == 200:
                logger.info(f"MetaApi Success: {res_data}")
                return {
                    'order_id': res_data.get('orderId') or f"MT5-{timezone.now().timestamp()}",
                    'status': 'OPEN',
                    'actual_price': res_data.get('price') or price
                }
            else:
                error_msg = res_data.get('message', 'Unknown Error')
                logger.error(f"MetaApi Error ({response.status_code}): {error_msg}")
                raise Exception(f"MetaApi Error: {error_msg}")

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

        token = self.account.api_key
        account_id = self.account.account_id
        headers = {"auth-token": token}

        try:
            # Fast Sync: ลด Timeout เหลือ 3 วินาทีเพื่อไม่ให้หน้าเว็บค้าง
            info_url = f"https://mt-provisioning-api-v1.agiliumtrade.ai/users/current/accounts/{account_id}"
            try:
                info_res = requests.get(info_url, headers=headers, timeout=3)
                region = info_res.json().get('region', 'new-york') if info_res.status_code == 200 else 'new-york'
            except:
                region = 'new-york' # ถ้าช้าให้ใช้ default ทันที

            url = f"https://mt-client-api-v1.{region}.agiliumtrade.ai/users/current/accounts/{account_id}/account-information"
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

        token = self.account.api_key.strip()
        account_id = self.account.account_id
        
        # ค้นหา Region เพื่อความแม่นยำ
        try:
            info_url = f"https://mt-provisioning-api-v1.agiliumtrade.ai/users/current/accounts/{account_id}"
            info_res = requests.get(info_url, headers={"auth-token": token}, timeout=5)
            region = info_res.json().get('region', 'new-york') if info_res.status_code == 200 else 'new-york'
        except:
            region = "new-york"

        url = f"https://mt-client-api-v1.{region}.agiliumtrade.ai/users/current/accounts/{account_id}/positions"
        headers = {"auth-token": token}

        try:
            res = requests.get(url, headers=headers, timeout=5)
            if res.status_code == 200:
                return res.json() # คืนค่า List ของ Positions
            return []
        except:
            return []

    def sync_trade_status(self):
        """
        ตรวจสอบและอัปเดตสถานะ TradeOrder ใน DB ให้ตรงกับ Broker
        และดึงค่า Exit Price / P/L จริงมาจากประวัติการเทรด (Deals)
        """
        if self.broker_type != BrokerType.META_API:
            return 0
            
        # 1. ดึงออเดอร์ที่ยัง OPEN หรือ CLOSED แต่ยังไม่มีข้อมูล Exit
        orders_to_sync = TradeOrder.objects.filter(
            user=self.user, 
            account=self.account
        ).filter(
            models.Q(status=TradeOrder.OrderStatus.OPEN) | 
            models.Q(status=TradeOrder.OrderStatus.CLOSED, exit_price__isnull=True) |
            models.Q(status=TradeOrder.OrderStatus.CLOSED, exit_price=0)
        )[:50] # จำกัดจำนวนเพื่อไม่ให้กระทบ Performance
        
        if not orders_to_sync.exists():
            return 0
            
        # ดึงรายการ Position ที่ยังเปิดอยู่จริง
        live_positions = self.get_open_positions()
        live_ids = [str(p.get('id')) for p in live_positions]
        
        token = self.account.api_key.strip()
        account_id = self.account.account_id
        
        # ค้นหา Region สำหรับดึงประวัติ
        try:
            info_url = f"https://mt-provisioning-api-v1.agiliumtrade.ai/users/current/accounts/{account_id}"
            info_res = requests.get(info_url, headers={"auth-token": token}, timeout=5)
            region = info_res.json().get('region', 'new-york') if info_res.status_code == 200 else 'new-york'
        except:
            region = "new-york"

        updated_count = 0
        for order in orders_to_sync:
            is_closed = False
            
            # 2. ตรวจสอบสถานะ: ถ้าเคย OPEN แต่ไม่อยู่ใน Live List แล้ว แสดงว่าปิดไปแล้ว
            if order.status == TradeOrder.OrderStatus.OPEN:
                if order.order_id and str(order.order_id) not in live_ids:
                    order.status = TradeOrder.OrderStatus.CLOSED
                    order.closed_at = timezone.now()
                    is_closed = True
            else:
                # ถ้าเป็น CLOSED อยู่แล้ว แต่มาหาข้อมูลเพิ่ม
                is_closed = True
            
            # 3. ถ้าปิดแล้ว (หรือกำลังมาซ่อมข้อมูล) ให้ดึงข้อมูลจาก History Deals API
            if is_closed and order.order_id:
                try:
                    history_url = f"https://mt-client-api-v1.{region}.agiliumtrade.ai/users/current/accounts/{account_id}/history-deals/by-position/{order.order_id}"
                    h_res = requests.get(history_url, headers={"auth-token": token}, timeout=5)
                    
                    if h_res.status_code == 200:
                        deals = h_res.json()
                        # กรองเอาเฉพาะ deal ที่เป็นขาออก (out)
                        exit_deal = next((d for d in deals if d.get('entry') == 'out' or d.get('type') in ['deal-sell-out', 'deal-buy-out']), None)
                        
                        if not exit_deal and len(deals) > 1:
                            exit_deal = deals[-1]
                            
                        if exit_deal:
                            order.exit_price = exit_deal.get('price')
                            order.profit_loss = exit_deal.get('profit', 0) + exit_deal.get('commission', 0) + exit_deal.get('swap', 0)
                            
                            # 4. ระบุเหตุผลการปิด (TP, SL, Manual)
                            reason_code = exit_deal.get('reason', '').lower()
                            if 'sl' in reason_code:
                                order.exit_reason = 'STOP LOSS'
                            elif 'tp' in reason_code:
                                order.exit_reason = 'TAKE PROFIT'
                            elif 'expert' in reason_code:
                                order.exit_reason = 'ROBOT'
                            elif 'client' in reason_code:
                                order.exit_reason = 'MANUAL'
                            else:
                                order.exit_reason = reason_code.upper() or 'CLOSED'
                                
                            if not order.closed_at:
                                order.closed_at = timezone.now()
                except Exception as e:
                    print(f"Sync History Error for {order.order_id}: {e}")

            order.save()
            updated_count += 1
                
        return updated_count

    def close_all_positions(self):
        """
        สั่งปิดออเดอร์ทั้งหมดในพอร์ตทันที (Panic Button)
        """
        positions = self.get_open_positions()
        success_count = 0
        
        for pos in positions:
            pos_id = pos.get('id')
            
            # ส่งคำสั่งปิดผ่าน Trade Endpoint
            token = self.account.api_key.strip()
            account_id = self.account.account_id
            
            # ตรวจหา Region
            try:
                info_url = f"https://mt-provisioning-api-v1.agiliumtrade.ai/users/current/accounts/{account_id}"
                info_res = requests.get(info_url, headers={"auth-token": token}, timeout=5)
                region = info_res.json().get('region', 'new-york') if info_res.status_code == 200 else 'new-york'
            except:
                region = "new-york"
            
            url = f"https://mt-client-api-v1.{region}.agiliumtrade.ai/users/current/accounts/{account_id}/trade"
            headers = {"auth-token": token, "Content-Type": "application/json"}
            
            payload = {
                "actionType": "POSITION_CLOSE_ID",
                "positionId": pos_id
            }
            
            try:
                res = requests.post(url, headers=headers, json=payload, timeout=5)
                if res.status_code == 200:
                    success_count += 1
            except:
                continue
                
        return success_count > 0
