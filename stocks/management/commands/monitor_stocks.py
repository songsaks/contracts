from django.core.management.base import BaseCommand
from django.utils import timezone
from stocks.models import Watchlist, Portfolio, UserTelegramProfile, PrecisionScanCandidate
from stocks.telegram_utils import send_telegram_message
import yfinance as yf
import time

class Command(BaseCommand):
    help = 'Monitor stocks in Watchlist/Portfolio and send Telegram alerts based on Clean v7 Entry points.'

    def handle(self, *args, **kwargs):
        self.stdout.write("🚀 เริ่มรันบอทตรวจจับราคาหุ้นและส่งแจ้งเตือน Telegram...")
        
        # 1. หารายชื่อ User ที่ผูก Telegram ไว้และเปิดแจ้งเตือนบัญชีเป็น Active
        profiles = UserTelegramProfile.objects.filter(is_active=True)
        if not profiles.exists():
            self.stdout.write("❌ ยังไม่มีผู้ใช้คนไหนผูก Telegram Profile เลย (ข้ามการทำงาน)")
            return
            
        # สร้างชุด Symbol(หุ้น) ทั้งหมดที่ต้องเช็คในรอบนี้ (เพื่อประหยัด API requests)
        symbols_to_check = set()
        for profile in profiles:
            watch_symbols = Watchlist.objects.filter(user=profile.user, is_active=True).values_list('symbol', flat=True)
            port_symbols = Portfolio.objects.filter(user=profile.user).values_list('symbol', flat=True)
            symbols_to_check.update(watch_symbols)
            symbols_to_check.update(port_symbols)
            
        if not symbols_to_check:
            self.stdout.write("⚠️ ไม่มีหุ้นใน Watchlist หรือ Portfolio เลย (ข้ามการทำงาน)")
            return
            
        # 2. ดึงราคาปัจจุบัน
        # แปลงเป็น .BK สำหรับหุ้นไทยถ้ายังไม่มี
        yf_symbols = []
        for sym in symbols_to_check:
            if not sym.endswith('=F') and '-' not in sym and not sym.endswith('.BK'):
                yf_symbols.append(f"{sym}.BK")
            else:
                yf_symbols.append(sym)
                
        self.stdout.write(f"📊 กำลังดึงราคาสดจาก YFinance: {yf_symbols}")
        try:
            # ดึงข้อมูลรวดเดียว
            tickers = yf.Tickers(" ".join(yf_symbols))
            live_prices = {}
            for original_sym, yf_sym in zip(symbols_to_check, yf_symbols):
                try:
                    price = tickers.tickers[yf_sym].info.get('currentPrice') or tickers.tickers[yf_sym].fast_info.last_price
                    if price:
                        live_prices[original_sym] = price
                except Exception as e:
                    pass
        except Exception as e:
            self.stdout.write(self.style.ERROR(f"Error fetching prices: {e}"))
            return

        self.stdout.write(f"Live Prices: {live_prices}")

        # 3. วิเคราะห์เพื่อแจ้งเตือนรายคน
        for profile in profiles:
            chat_id = profile.chat_id
            user = profile.user
            
            # 3.1 ตรวจสอบ Watchlist (หาจุดเข้าซื้อ - Entry)
            watchlists = Watchlist.objects.filter(user=user, is_active=True)
            for w in watchlists:
                price = live_prices.get(w.symbol)
                if not price:
                    continue
                    
                # ไปดึง Scanner Data ล่าสุดของหุ้นตัวนี้ (Clean v7 Scanner)
                clean_symbol = w.symbol.replace('.BK', '')
                latest_scan = PrecisionScanCandidate.objects.filter(symbol=clean_symbol).order_by('-scan_run').first()
                if latest_scan and latest_scan.demand_zone_start:
                    # ถ้าราคาไหลลงมาตกมาที่โซนเข้าซื้อ หรือย่อแตะ EMA20 (demand_zone_start ของ v7 มักคือ EMA20/Buy zone)
                    if price <= latest_scan.demand_zone_start and price >= latest_scan.demand_zone_end:
                        msg = (
                            f"🔔 <b>[PRECISION ALERT] โซนเข้าซื้อ!</b>\n"
                            f"หุ้น: <b>{w.symbol}</b>\n"
                            f"ราคาปัจจุบัน: <b>฿{price:.2f}</b>\n"
                            f"⬇️ ทะลุเข้าเป้าหมาย EMA / Demand Zone:\n"
                            f"🎯 โซนยิง: ฿{latest_scan.demand_zone_end:.2f} - ฿{latest_scan.demand_zone_start:.2f}\n"
                            f"🛡️ ตัดขาดทุนถ้าหลุด: ฿{latest_scan.stop_loss:.2f}"
                        )
                        success = send_telegram_message(chat_id, msg)
                        if success:
                            self.stdout.write(self.style.SUCCESS(f"-> Sent Entry alert for {w.symbol} to {user.username}"))

            # 3.2 ตรวจสอบ Portfolio (หาจุดขาย TP / ตัดขาดทุน SL)
            portfolios = Portfolio.objects.filter(user=user)
            for p in portfolios:
                price = live_prices.get(p.symbol)
                if not price:
                    continue
                    
                clean_symbol = p.symbol.replace('.BK', '')
                latest_scan = PrecisionScanCandidate.objects.filter(symbol=clean_symbol).order_by('-scan_run').first()
                if latest_scan:
                    alert_msg = ""
                    # เช็คเป้าหมายทำกำไร (TAKE PROFIT)
                    if latest_scan.supply_zone_start and price >= latest_scan.supply_zone_start:
                        alert_msg = (
                            f"🔴 <b>[TAKE PROFIT ALERT] ชนเป้าหมายกำไร!</b>\n"
                            f"หุ้น: <b>{p.symbol}</b> (ในพอร์ต)\n"
                            f"ราคาปัจจุบัน: <b>฿{price:.2f}</b>\n"
                            f"💵 เข้าสู่โซนเทขายทำกำไรรอบสวิงแล้ว!"
                        )
                    # เช็คระวังการดิ่งลงทะลุ SL
                    elif latest_scan.stop_loss and price <= latest_scan.stop_loss:
                         alert_msg = (
                            f"⚠️ <b>[STOP LOSS ALERT] ระวังหลุดแนวรับ!</b>\n"
                            f"หุ้น: <b>{p.symbol}</b> (ในพอร์ต)\n"
                            f"ราคาปัจจุบัน: <b>฿{price:.2f}</b>\n"
                            f"🩸 ราคาหลุดจุดตัดขาดทุน (SL) ที่ ฿{latest_scan.stop_loss:.2f} ไปแล้ว ควรพิจารณาคัตลอส"
                        )
                    
                    if alert_msg:
                        success = send_telegram_message(chat_id, alert_msg)
                        if success:
                            self.stdout.write(self.style.SUCCESS(f"-> Sent Exit alert for {p.symbol} to {user.username}"))

        self.stdout.write(self.style.SUCCESS("✅ รันการตรวจสอบเสร็จสิ้น"))
