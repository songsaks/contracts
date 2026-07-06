import os
import time
import datetime
import pandas as pd
import pandas_ta as ta
import yfinance as yf
from django.core.management.base import BaseCommand
from django.utils import timezone
from stocks.models import TradingAccount, TradeOrder, BotActivity
from stocks.trading_bridge import RobotBridge

class Command(BaseCommand):
    help = 'รันบอทเทรดคริปโตอัตโนมัติ (Sniper / Scalper / Swing) สำหรับ BTC/USD'

    def add_arguments(self, parser):
        parser.add_argument('--strategy', type=str, default='ALL', help='กลยุทธ์ที่จะรัน (SNIPER, SCALPER, SWING, ALL)')
        parser.add_argument('--once', action='store_true', help='รันจนจบ 1 ออเดอร์แล้วหยุดทันที')
        parser.add_argument('--user_id', type=int, required=True, help='ID ของผู้ใช้ที่เป็นเจ้าของบอทตัวนี้')

    # --- การตั้งค่าพื้นฐานสำหรับคริปโต ---
    SYMBOL = "BTC-USD"         # สัญลักษณ์ราคาคริปโตจาก Yahoo Finance
    BROKER_SYMBOL = "BTCUSD"   # สัญลักษณ์คริปโตฝั่งโบรกเกอร์ (MetaApi)
    RISK_PER_TRADE = 0.02      # ความเสี่ยงต่อไม้ (2% ของเงินทุน)
    MIN_LOT = 0.01             # ขนาด Lot ต่ำสุดที่อนุญาต

    def get_bot_identity(self, user_id):
        from django.contrib.auth.models import User
        try:
            u = User.objects.get(id=user_id)
            return f"Crypto Bot (User: {u.username})"
        except:
            return f"Crypto Bot (User: ID {user_id})"

    def update_heartbeat(self, user_id, status="ACTIVE", message=""):
        """ อัปเดตสถานะการทำงานของบอทคริปโตลงฐานข้อมูล แยกราย User """
        bot_name = self.get_bot_identity(user_id)
        BotActivity.objects.update_or_create(
            bot_name=bot_name,
            defaults={
                'status': status,
                'last_heartbeat': timezone.now(),
                'message': message
            }
        )

    def handle(self, *args, **options):
        """ จุดเริ่มต้นการทำงานของบอท (Main Entry Point) """
        target_strat = options.get('strategy', 'ALL').upper()
        run_once = options.get('once', False)
        user_id = options.get('user_id')
        # โหมด --once: จบงานเมื่อ "ออเดอร์ที่เปิดจริง" ถูกปิดแล้วเท่านั้น
        # (แค่เจอสัญญาณแต่ผู้ใช้ไม่กดเทรด บอทต้องเฝ้าต่อ ไม่หยุดเอง)
        session_saw_position = False
        has_open_position = False
        
        bot_name = self.get_bot_identity(user_id)
        # PID File แยกของ Crypto
        user_pid_file = os.path.join(os.path.dirname(os.path.dirname(os.path.dirname(os.path.dirname(__file__)))), f'crypto_bot_{user_id}.pid')

        self.stdout.write(self.style.SUCCESS(f'--- {bot_name} เริ่มทำงาน (กลยุทธ์: {target_strat}, โหมดรอบเดียว: {run_once}) ---'))
        
        try:
            # แจ้งหน้าจอว่าบอทกำลังเริ่มระบบ
            self.update_heartbeat(user_id, status="ACTIVE", message=f"เฝ้าระวัง {target_strat} (One-Shot: {run_once})")
            
            while True:
                # ตรวจสอบสถานะจาก DB ว่าถูกสั่งหยุดหรือไม่ (Graceful Shutdown)
                activity = BotActivity.objects.filter(bot_name=bot_name).first()
                if activity and activity.status == "STOPPED":
                    self.stdout.write(self.style.WARNING(f"--- {bot_name} ตรวจพบสถานะ STOPPED: กำลังหยุดการทำงาน... ---"))
                    if os.path.exists(user_pid_file): os.remove(user_pid_file)
                    return

                try:
                    # 1. ดึงข้อมูลราคาสดคริปโตจาก Yahoo Finance
                    df = yf.download(self.SYMBOL, period='1y', interval='1d', progress=False, auto_adjust=True, timeout=15)
                    
                    if df.empty:
                        self.update_heartbeat(user_id, status="ACTIVE", message="กำลังรอข้อมูลราคาจาก Yahoo...")
                        time.sleep(30)
                        continue
                    
                    # Flatten columns (MultiIndex fix)
                    if isinstance(df.columns, pd.MultiIndex):
                        df.columns = df.columns.get_level_values(0)
                    
                    # 2. คำนวณ Technical Indicators
                    df['ema9'] = ta.ema(df['Close'], length=9)
                    df['ema200'] = ta.ema(df['Close'], length=200)
                    df['rsi'] = ta.rsi(df['Close'], length=14)
                    df['atr'] = ta.atr(df['High'], df['Low'], df['Close'], length=20)
                    
                    # ดึงค่าปัจจุบันและค่าก่อนหน้า
                    curr_row = df.iloc[-1]
                    prev_row = df.iloc[-2]
                    curr_price = float(curr_row['Close'])
                    ema9 = float(curr_row['ema9'])
                    ema200 = float(curr_row['ema200'])
                    rsi = float(curr_row['rsi'])
                    atr = float(curr_row['atr'])
                    
                    # 3. ตรวจสอบสถานะพอร์ต (กรองเฉพาะออเดอร์ Crypto ของโบรกเกอร์)
                    accounts = TradingAccount.objects.filter(is_active=True, user_id=user_id)
                    has_open_position = False
                    
                    for acc in accounts:
                        bridge = RobotBridge(user=acc.user)
                        positions = bridge.get_open_positions()
                        if any(pos.get('symbol') == self.BROKER_SYMBOL for pos in positions):
                            has_open_position = True
                            break
                    
                    if has_open_position:
                        session_saw_position = True

                    # ถ้าใช้โหมด Once และเคยมีออเดอร์เปิดจริง และตอนนี้ปิดหมดแล้ว = จบงาน
                    if run_once and session_saw_position and not has_open_position:
                        self.stdout.write(self.style.SUCCESS("--- จบงาน: ออเดอร์ปิดแล้ว หยุดบอทตามโหมด One-Shot ---"))
                        self.update_heartbeat(user_id, status="STOPPED", message="ปิดงานเรียบร้อยแล้ว (รอคุณตัดสินใจรอบถัดไป)")
                        if os.path.exists(user_pid_file): os.remove(user_pid_file)
                        return

                    # 4. ค้นหาสัญญาณการเทรด (เฉพาะเมื่อยังไม่มีออเดอร์ค้าง)
                    signal_type = None
                    if not has_open_position:
                        # A: กลยุทธ์ SNIPER (ราคาตัดเส้น EMA 9)
                        sn_buy = curr_price >= ema9 and prev_row['Close'] < prev_row['ema9'] and curr_price > ema200
                        sn_sell = curr_price <= ema9 and prev_row['Close'] > prev_row['ema9'] and curr_price < ema200
                        
                        # B: กลยุทธ์ SCALPER (ทะลุ High/Low 20 วัน)
                        high_20d = df['High'].rolling(window=20).max().iloc[-2]
                        low_20d = df['Low'].rolling(window=20).min().iloc[-2]
                        sc_buy = curr_price > high_20d and curr_price > ema200
                        sc_sell = curr_price < low_20d and curr_price < ema200
                        
                        # C: กลยุทธ์ SWING (ทะลุ High/Low 55 วัน)
                        high_55d = df['High'].rolling(window=55).max().iloc[-2]
                        low_55d = df['Low'].rolling(window=55).min().iloc[-2]
                        sw_buy = curr_price > high_55d and curr_price > ema200
                        sw_sell = curr_price < low_55d and curr_price < ema200

                        # กรองตามที่ user เลือก
                        if (target_strat == 'ALL' or target_strat == 'SNIPER'):
                            if sn_buy: signal_type, side = "SNIPER_EMA9", "BUY"
                            elif sn_sell: signal_type, side = "SNIPER_EMA9", "SELL"
                        
                        if not signal_type and (target_strat == 'ALL' or target_strat == 'SCALPER'):
                            if sc_buy: signal_type, side = "SCALPER_H20", "BUY"
                            elif sc_sell: signal_type, side = "SCALPER_H20", "SELL"
                            
                        if not signal_type and (target_strat == 'ALL' or target_strat == 'SWING'):
                            if sw_buy: signal_type, side = "SWING_H55", "BUY"
                            elif sw_sell: signal_type, side = "SWING_H55", "SELL"

                        if signal_type:
                            self.stdout.write(self.style.SUCCESS(f"🚀 SIGNAL DETECTED: {side} {signal_type} at {curr_price}"))
                            # ในโหมดแมนนวล: ส่งสัญญาณไปที่ UI แทนการเปิดออเดอร์
                            self.update_heartbeat(user_id, status="SIGNAL", message=f"SIGNAL_{side}:{signal_type}:{curr_price:.2f}")

                    if not signal_type:
                        self.update_heartbeat(user_id, status="ACTIVE", message=f"เฝ้าระวัง ({target_strat})... ราคา: {curr_price:.2f} | RSI: {rsi:.1f}")

                except Exception as e:
                    import traceback
                    error_msg = f"เกิดข้อผิดพลาด: {str(e)}\n{traceback.format_exc()}"
                    self.stdout.write(self.style.ERROR(error_msg))
                    self.update_heartbeat(user_id, status="ERROR", message=str(e)[:200])
                    time.sleep(30)

                # สัญญาณคำนวณจากแท่ง Daily — เช็คทุก 5 นาทีพอ (คริปโตเทรด 24 ชม. แต่แท่ง daily เปลี่ยนช้า)
                # ถ้ามีออเดอร์ค้างอยู่ เช็คถี่ขึ้นเป็นทุก 1 นาทีเพื่อจับจังหวะปิด
                time.sleep(60 if has_open_position else 300)
                
        except Exception as e:
            self.stdout.write(self.style.ERROR(f"บอทหยุดการทำงานถาวร: {str(e)}"))
            self.update_heartbeat(user_id, status="ERROR", message=f"FATAL: {str(e)}")
