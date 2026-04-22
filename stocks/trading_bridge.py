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
    
    def __init__(self, account_id=None, user=None):
        if account_id:
            self.account = TradingAccount.objects.get(pk=account_id)
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

    def _trade_via_meta_api(self, symbol, side, volume, price, sl, tp):
        """
        ส่งคำสั่งผ่าน MetaApi (MT4/MT5 Cloud API) 
        โดยใช้ REST API เพื่อความรวดเร็วและไม่ต้องติดตั้ง SDK ขนาดใหญ่บน Server
        """
        token = self.account.api_key      # MetaApi Personal Access Token
        account_id = self.account.account_id # MetaApi Account ID (UUID)
        
        if not token or not account_id:
            raise ValueError("MetaApi Token or Account ID is missing in TradingAccount configuration.")

        # 1. จัดเตรียมข้อมูล Order
        # สำหรับ MetaApi REST: https://metaapi.cloud/docs/client/restApi/trading/trade/
        # URL: https://mt-client-api-v1.new-york.agiliumtrade.ai/users/current/accounts/:accountId/trade
        
        region = "new-york" # หรือเปลี่ยนตาม Account Region
        url = f"https://mt-client-api-v1.{region}.agiliumtrade.ai/users/current/accounts/{account_id}/trade"
        
        headers = {
            "auth-token": token,
            "Content-Type": "application/json"
        }
        
        # แปลง Side เป็น MetaApi format
        # MetaApi types: ORDER_TYPE_BUY, ORDER_TYPE_SELL
        order_type = "ORDER_TYPE_BUY" if side.upper() == "BUY" else "ORDER_TYPE_SELL"
        
        payload = {
            "symbol": symbol.replace("GC=F", "XAUUSD"), # แมปชื่อ Symbol ให้เข้ากับ Broker
            "actionType": "ORDER_TYPE_BUY" if side.upper() == "BUY" else "ORDER_TYPE_SELL",
            "volume": float(volume),
        }
        
        # เพิ่ม SL/TP ถ้ามี
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
            # 1. ตรวจสอบ Region ของ Account นี้ก่อน
            info_url = f"https://mt-provisioning-api-v1.agiliumtrade.ai/users/current/accounts/{account_id}"
            info_res = requests.get(info_url, headers=headers, timeout=10)
            
            region = "new-york" # default
            if info_res.status_code == 200:
                region = info_res.json().get('region', 'new-york')
                logger.info(f"MetaApi Region Detected: {region}")
            else:
                logger.warning(f"Could not detect MetaApi region, using default. Status: {info_res.status_code}")

            # 2. ดึงข้อมูล Account Information ตาม Region ที่ถูกต้อง
            url = f"https://mt-client-api-v1.{region}.agiliumtrade.ai/users/current/accounts/{account_id}/account-information"
            response = requests.get(url, headers=headers, timeout=10)
            
            if response.status_code == 200:
                data = response.json()
                self.account.balance  = Decimal(str(data.get('balance', 0)))
                self.account.equity   = Decimal(str(data.get('equity', 0)))
                self.account.currency = data.get('currency', 'USD')
                self.account.save()
                logger.info(f"Sync Balance Success: {self.account.balance} {self.account.currency}")
                return True
            else:
                logger.error(f"Sync Balance Failed ({response.status_code}): {response.text}")
                return False

        except Exception as e:
            logger.error(f"Sync Balance Exception: {str(e)}")
            return False
