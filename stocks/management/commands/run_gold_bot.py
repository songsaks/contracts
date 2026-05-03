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
                        _pf = {'Open', 'High', 'Low', 'Close', 'Volume', 'Adj Close'}
                        if any(v in _pf for v in df.columns.get_level_values(0)):
                            df.columns = df.columns.get_level_values(0)
                        else:
                            df.columns = df.columns.get_level_values(1)

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
                                balance = float(acc.equity or acc.balance) if (acc.equity or acc.balance) > 0 else 1000.0
                                risk_money = balance * self.RISK_PER_TRADE

                                # กำหนดระยะ Stop Loss และ Take Profit ตามความเร็วของกลยุทธ์
                                if signal_type == "SNIPER_EMA9":
                                    sl_mult = 0.5
                                    tp_mult = 1.5
                                elif signal_type == "SCALPER_10D":
                                    sl_mult = 1.0
                                    tp_mult = 2.0
                                else:
                                    sl_mult = 1.5
                                    tp_mult = 3.5

                                sl_dist = sl_mult * atr
                                tp_dist = tp_mult * atr

                                # คำนวณ Lot Size อัตโนมัติ (ความเสี่ยงคงที่ 2%)
                                # อัปเดต: ต้องหารด้วย Contract Size (100 สำหรับ XAUUSD) เพื่อไม่ให้ Lot ใหญ่เกินจริง 100 เท่า!
                                contract_size = 100.0
                                raw_lots = risk_money / (sl_dist * contract_size) if sl_dist > 0 else self.MIN_LOT
                                lots = round(max(self.MIN_LOT, raw_lots), 2)
                                
                                # 🚨 BOT CIRCUIT BREAKER
                                if lots > 0.05:
                                    self.stdout.write(self.style.ERROR(f"🚨 CIRCUIT BREAKER: ระบบระงับคำสั่ง! คำนวณได้ {lots} Lots ซึ่งเกินขีดจำกัดความปลอดภัย (0.05 Lots)"))
                                    self.update_heartbeat(status="ACTIVE", message=f"🚨 ป้องกันพอร์ตระเบิด: ระงับการเปิดออเดอร์ {lots} Lots")
                                    continue

                                sl_price = curr_price - sl_dist
                                tp_price = curr_price + tp_dist

                                self.stdout.write(self.style.SUCCESS(f"สั่งซื้อ {signal_type} สำหรับพอร์ต {acc.account_id} | Lot: {lots} | TP: {tp_price:.2f} | SL: {sl_price:.2f}"))

                                current_tp = tp_price if signal_type == "SNIPER_EMA9" else None

                                res = bridge.execute_trade(
                                    symbol=self.BROKER_SYMBOL, side="BUY", volume=lots,
                                    strategy=signal_type, sl=sl_price, tp=current_tp
                                )
                                
                                # บันทึก Log การเทรดลงหน้า Dashboard
                                log_msg = f"เข้าซื้อ: {signal_type} {lots} Lots @ {curr_price}"
                                if current_tp: log_msg += f" (TP: {current_tp:.2f})"
                                self.update_heartbeat(status="ACTIVE", message=log_msg)
                    
                    # --- ส่วนใหม่: ระบบ SMART TRAILING STOP (เฝ้าดูแลออเดอร์ที่เปิดอยู่) ---
                    active_accounts = TradingAccount.objects.filter(is_active=True)
                    for acc in active_accounts:
                        bridge = RobotBridge(user=acc.user)
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
                        # ถ้ายังไม่มีสัญญาณใหม่ ให้รายงานสถานะราคาปัจจุบัน
                        self.update_heartbeat(status="ACTIVE", message=f"เฝ้าระวัง... ราคา: {curr_price:.2f} | RSI: {rsi:.1f}")

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
