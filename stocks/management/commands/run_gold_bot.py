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
    help = 'รันบอทเทรดทองคำอัตโนมัติ (Sniper / Scalper / Swing)'

    # --- การตั้งค่าพื้นฐาน ---
    SYMBOL = "GC=F"           # สัญลักษณ์ราคาทองคำจาก Yahoo Finance
    BROKER_SYMBOL = "XAUUSD"  # สัญลักษณ์ทองคำฝั่งโบรกเกอร์ (MetaApi)
    RISK_PER_TRADE = 0.02     # ความเสี่ยงต่อไม้ (2% ของเงินทุน)
    MIN_LOT = 0.01            # ขนาด Lot ต่ำสุดที่อนุญาต

    def update_heartbeat(self, status="ACTIVE", message=""):
        """ อัปเดตสถานะการทำงานของบอทลงฐานข้อมูล เพื่อแสดงผลที่หน้า Dashboard """
        BotActivity.objects.update_or_create(
            bot_name="Gold Server Bot",
            defaults={
                'status': status,
                'last_heartbeat': timezone.now(),
                'message': message
            }
        )

    def handle(self, *args, **options):
        """ จุดเริ่มต้นการทำงานของบอท (Main Entry Point) """
        self.stdout.write(self.style.SUCCESS(f'--- บอททองคำเริ่มทำงาน (ความเสี่ยง: {self.RISK_PER_TRADE*100}%) ---'))
        
        try:
            # แจ้งหน้าจอว่าบอทกำลังเริ่มระบบ
            self.update_heartbeat(status="ACTIVE", message="กำลังเริ่มระบบ...")
            
            while True:
                try:
                    # 1. ดึงข้อมูลราคาสดจาก Yahoo Finance
                    # ดึงข้อมูลย้อนหลัง 1 ปี แบบรายวัน (Daily)
                    df = yf.download(self.SYMBOL, period='1y', interval='1d', progress=False, auto_adjust=True, timeout=15)
                    
                    if df.empty:
                        self.update_heartbeat(status="ACTIVE", message="กำลังรอข้อมูลราคาจาก Yahoo...")
                        time.sleep(30)
                        continue
                    
                    # จัดการรูปแบบ Column ของข้อมูล
                    if isinstance(df.columns, pd.MultiIndex): 
                        df.columns = df.columns.get_level_values(0)

                    # 2. คำนวณตัวชี้วัดทางเทคนิค (Technical Indicators)
                    # Donchian Channels (จุดสูงสุดย้อนหลัง 10 และ 20 วัน)
                    df['dc10_upper'] = df['High'].rolling(10).max()
                    df['dc20_upper'] = df['High'].rolling(20).max()
                    # Exponential Moving Average (เส้นค่าเฉลี่ย 9 และ 200 วัน)
                    df['ema9'] = ta.ema(df['Close'], length=9)
                    df['ema200'] = ta.ema(df['Close'], length=200)
                    # Relative Strength Index (ดัชนีกำลังสัมพัทธ์)
                    df['rsi'] = ta.rsi(df['Close'], length=14)
                    # Average True Range (ค่าเฉลี่ยความผันผวน)
                    df['atr'] = ta.atr(df['High'], df['Low'], df['Close'], length=20)
                    
                    # ลบข้อมูลแถวที่คำนวณไม่ได้ (ช่วงแรกๆ ของข้อมูล)
                    df = df.dropna()
                    if df.empty:
                        time.sleep(30)
                        continue

                    # ดึงข้อมูลแถวล่าสุด (ปัจจุบัน) และแถวก่อนหน้า (เมื่อวาน)
                    last_row, prev_row = df.iloc[-1], df.iloc[-2]
                    
                    curr_price = float(last_row['Close'])
                    upper10 = float(prev_row['dc10_upper'])
                    upper20 = float(prev_row['dc20_upper'])
                    ema9 = float(last_row['ema9'])
                    ema200 = float(last_row['ema200'])
                    rsi = float(last_row['rsi'])
                    atr = float(last_row['atr'])
                    
                    # 3. ตรวจสอบเงื่อนไขการเข้าซื้อ (Logic Check - ขาขึ้นเท่านั้น)
                    
                    # A: กลยุทธ์ SNIPER (ราคาตัดเส้น EMA 9 ขึ้นมา)
                    sn_buy = curr_price >= ema9 and prev_row['Close'] < prev_row['ema9'] and curr_price > ema200
                    
                    # B: กลยุทธ์ SCALPER (ราคาทะลุ High เดิมของ 10 วัน)
                    sc_buy = curr_price >= upper10 and rsi > 50 and curr_price > ema9
                    
                    # C: กลยุทธ์ SWING (ราคาทะลุ High เดิมของ 20 วัน)
                    sw_buy = curr_price >= upper20 and rsi < 70 and curr_price > ema200

                    # จัดลำดับความสำคัญของสัญญาณ
                    signal_type = None
                    if sw_buy: signal_type = "SWING_20D"
                    elif sc_buy: signal_type = "SCALPER_10D"
                    elif sn_buy: signal_type = "SNIPER_EMA9"

                    if signal_type:
                        self.stdout.write(self.style.WARNING(f"ตรวจพบสัญญาณ: {signal_type} ที่ราคา {curr_price}"))
                        
                        # วนลูปส่งออเดอร์สำหรับทุกบัญชีเทรดที่ Active อยู่
                        accounts = TradingAccount.objects.filter(is_active=True)
                        for acc in accounts:
                            # ป้องกันการเปิดออเดอร์ซ้ำในวันเดียวกันสำหรับกลยุทธ์เดิม
                            today = datetime.date.today()
                            already_traded = TradeOrder.objects.filter(
                                user=acc.user, symbol=self.BROKER_SYMBOL, 
                                created_at__date=today, strategy__icontains=signal_type
                            ).exists()

                            if not already_traded:
                                # ใช้ระบบ Bridge เพื่อคุยกับโบรกเกอร์
                                bridge = RobotBridge(user=acc.user)
                                balance = float(acc.balance) if acc.balance > 0 else 1000.0
                                risk_money = balance * self.RISK_PER_TRADE
                                
                                # กำหนดระยะ Stop Loss ตามความเร็วของกลยุทธ์
                                if signal_type == "SNIPER_EMA9": sl_mult = 0.5  # แคบมาก
                                elif signal_type == "SCALPER_10D": sl_mult = 1.0 # ปานกลาง
                                else: sl_mult = 1.5                             # กว้างหน่อย
                                
                                sl_dist = sl_mult * atr
                                # คำนวณ Lot Size อัตโนมัติ (ความเสี่ยงคงที่ 2%)
                                lots = round(max(self.MIN_LOT, risk_money / sl_dist if sl_dist > 0 else self.MIN_LOT), 2)
                                sl_price = curr_price - sl_dist
                                
                                self.stdout.write(self.style.SUCCESS(f"สั่งซื้อ {signal_type} สำหรับพอร์ต {acc.account_name}"))
                                
                                # ส่งคำสั่งซื้อจริงไปยังโบรกเกอร์
                                res = bridge.execute_trade(
                                    symbol=self.BROKER_SYMBOL, side="BUY", volume=lots,
                                    strategy=signal_type, stop_loss=sl_price
                                )
                                
                                # บันทึก Log การเทรดลงหน้า Dashboard
                                self.update_heartbeat(status="ACTIVE", message=f"เข้าซื้อ: {signal_type} {lots} Lots @ {curr_price}")
                    else:
                        # ถ้ายังไม่มีสัญญาณ ให้รายงานสถานะราคาปัจจุบันเฉยๆ
                        self.update_heartbeat(status="ACTIVE", message=f"เฝ้าระวัง... ราคา: {curr_price:.2f} | เส้น EMA9: {ema9:.2f}")

                except Exception as e:
                    # จัดการข้อผิดพลาดที่อาจเกิดขึ้นระหว่างลูป (เช่น เน็ตหลุด)
                    import traceback
                    error_msg = f"เกิดข้อผิดพลาด: {str(e)}\n{traceback.format_exc()}"
                    self.stdout.write(self.style.ERROR(error_msg))
                    self.update_heartbeat(status="ERROR", message=str(e)[:200])
                    time.sleep(30) # รอสักพักเผื่อเน็ตกลับมา

                # พักการทำงาน 1 นาทีก่อนเช็ครอบถัดไป
                time.sleep(60)
                
        except Exception as e:
            # จัดการข้อผิดพลาดร้ายแรงที่ทำให้บอทหยุดรัน
            self.stdout.write(self.style.ERROR(f"บอทหยุดการทำงานถาวร: {str(e)}"))
            self.update_heartbeat(status="ERROR", message=f"FATAL: {str(e)}")
