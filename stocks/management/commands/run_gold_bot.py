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

    def add_arguments(self, parser):
        parser.add_argument('--strategy', type=str, default='ALL', help='ล็อคกลยุทธ์ที่จะรัน (SNIPER, SCALPER, SWING, ALL)')
        parser.add_argument('--once', action='store_true', help='รันจนจบ 1 ออเดอร์แล้วหยุดทันที')

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
        target_strat = options.get('strategy', 'ALL').upper()
        run_once = options.get('once', False)
        session_has_traded = False

        self.stdout.write(self.style.SUCCESS(f'--- บอททองคำเริ่มทำงาน (กลยุทธ์: {target_strat}, โหมดรอบเดียว: {run_once}) ---'))
        
        try:
            # แจ้งหน้าจอว่าบอทกำลังเริ่มระบบ
            self.update_heartbeat(status="ACTIVE", message=f"เฝ้าระวัง {target_strat} (One-Shot: {run_once})")
            
            while True:
                try:
                    # 1. ดึงข้อมูลราคาสดจาก Yahoo Finance
                    df = yf.download(self.SYMBOL, period='1y', interval='1d', progress=False, auto_adjust=True, timeout=15)
                    
                    if df.empty:
                        self.update_heartbeat(status="ACTIVE", message="กำลังรอข้อมูลราคาจาก Yahoo...")
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
                    
                    # 3. ตรวจสอบสถานะพอร์ต (เช็คว่ามีออเดอร์ค้างอยู่หรือไม่)
                    accounts = TradingAccount.objects.filter(is_active=True)
                    has_open_position = False
                    
                    for acc in accounts:
                        bridge = RobotBridge(user=acc.user)
                        positions = bridge.get_open_positions()
                        if any(pos.get('symbol') == self.BROKER_SYMBOL for pos in positions):
                            has_open_position = True
                            break
                    
                    # ถ้าใช้โหมด Once และเคยเทรดไปแล้ว และตอนนี้ไม่มีออเดอร์ค้าง = จบงาน
                    if run_once and session_has_traded and not has_open_position:
                        self.stdout.write(self.style.SUCCESS("--- จบงาน: ออเดอร์ปิดแล้ว หยุดบอทตามโหมด One-Shot ---"))
                        self.update_heartbeat(status="STOPPED", message="ปิดงานเรียบร้อยแล้ว (รอคุณตัดสินใจรอบถัดไป)")
                        # ลบ PID File ด้วยตัวเอง
                        if os.path.exists("gold_bot.pid"): os.remove("gold_bot.pid")
                        return

                    # 4. ค้นหาสัญญาณการเทรด (เฉพาะเมื่อยังไม่มีออเดอร์ค้าง)
                    signal_type = None
                    if not has_open_position:
                        # A: กลยุทธ์ SNIPER (ราคาตัดเส้น EMA 9 ขึ้นมา)
                        sn_buy = curr_price >= ema9 and prev_row['Close'] < prev_row['ema9'] and curr_price > ema200
                        
                        # B: กลยุทธ์ SCALPER (ทะลุ High 20 วัน)
                        high_20d = df['High'].rolling(window=20).max().iloc[-2]
                        sc_buy = curr_price > high_20d and curr_price > ema200
                        
                        # C: กลยุทธ์ SWING (ทะลุ High 55 วัน)
                        high_55d = df['High'].rolling(window=55).max().iloc[-2]
                        sw_buy = curr_price > high_55d and curr_price > ema200

                        # กรองตามที่ user เลือก
                        if (target_strat == 'ALL' or target_strat == 'SNIPER') and sn_buy: signal_type = "SNIPER_EMA9"
                        elif (target_strat == 'ALL' or target_strat == 'SCALPER') and sc_buy: signal_type = "SCALPER_H20"
                        elif (target_strat == 'ALL' or target_strat == 'SWING') and sw_buy: signal_type = "SWING_H55"

                        if signal_type:
                            session_has_traded = True
                            for acc in accounts:
                                bridge = RobotBridge(user=acc.user)
                                
                                # คำนวณความเสี่ยง
                                balance = float(acc.balance)
                                risk_money = balance * self.RISK_PER_TRADE
                                
                                sl_mult = 2.0
                                tp_mult = 1.5 if signal_type == "SNIPER_EMA9" else (2.0 if "SCALPER" in signal_type else 3.5)
                                
                                sl_dist = sl_mult * atr
                                tp_dist = tp_mult * atr

                                # คำนวณ Lot Size (Fix: หารด้วย 100 contract size)
                                contract_size = 100.0
                                raw_lots = risk_money / (sl_dist * contract_size) if sl_dist > 0 else self.MIN_LOT
                                lots = round(max(self.MIN_LOT, raw_lots), 2)
                                
                                if lots > 0.05:
                                    self.stdout.write(self.style.ERROR(f"🚨 CIRCUIT BREAKER: {lots} Lots"))
                                    continue

                                sl_price = curr_price - sl_dist
                                tp_price = curr_price + tp_dist
                                current_tp = tp_price if signal_type == "SNIPER_EMA9" else None

                                res = bridge.execute_trade(
                                    symbol=self.BROKER_SYMBOL, side="BUY", volume=lots,
                                    strategy=signal_type, sl=sl_price, tp=current_tp
                                )
                        positions = bridge.get_open_positions() # ดึงจากโบรกเกอร์จริง
                        
                        for pos in positions:
                            if pos.get('symbol') == self.BROKER_SYMBOL:
                                pos_id = pos.get('id')
                                current_sl = float(pos.get('stopLoss', 0) or 0)

                                new_sl = curr_price - (2.0 * atr)
                                
                                # เงื่อนไขการเลื่อน: 1. ต้องเป็นบวก 2. ต้องสูงกว่า SL เดิม (เลื่อนขึ้นเท่านั้น)
                                if new_sl > current_sl:
                                    success = bridge.modify_position(pos_id, sl=new_sl)
                                    if success:
                                        self.stdout.write(self.style.SUCCESS(f"Trailing SL Updated: {new_sl:.2f} for {acc.account_id}"))
                                        self.update_heartbeat(status="ACTIVE", message=f"🛡️ ยกจุดป้องกัน (Trailing SL) ไปที่ {new_sl:.2f}")

                    if not signal_type:
                        # ถ้ายังไม่มีสัญญาณใหม่ ให้รายงานสถานะราคาปัจจุบัน โดยติดชื่อโหมดไว้ด้วย
                        self.update_heartbeat(status="ACTIVE", message=f"เฝ้าระวัง ({target_strat})... ราคา: {curr_price:.2f} | RSI: {rsi:.1f}")

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
