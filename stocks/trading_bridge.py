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
        เหมาะที่สุดสำหรับรัน Django บน Linux Ubuntu
        """
        # TODO: ติดตั้ง 'metaapi-cloud-sdk' และส่งคำสั่งจริงที่นี่
        # นี่คือ Placeholder สำหรับจำลองการส่งค่าคืนจาก API
        return {
            'order_id': f'MT5-{timezone.now().timestamp()}',
            'status': 'OPEN',
            'actual_price': price
        }

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
        """
        try:
            # Placeholder: ดึงค่าล่าสุดจาก Broker (ในงานจริงต้องเรียก API)
            # ตัวอย่าง MetaApi result:
            # balance = api.get_account_information().balance
            
            # จำลองค่าเผื่อการทดสอบ
            self.account.balance += Decimal('0.00') 
            self.account.save()
            return True
        except Exception as e:
            logger.error(f"Sync Balance Error: {str(e)}")
            return False
