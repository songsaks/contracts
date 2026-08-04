from django.core.management.base import BaseCommand
from django.utils import timezone
from django.core.cache import cache
from stocks.models import Watchlist, Portfolio, UserTelegramProfile, PrecisionScanCandidate
from stocks.telegram_utils import send_telegram_message
from stocks.utils import simple_trailing_stop
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
                        cache_key = f"alert_entry_{user.id}_{w.symbol}_{latest_scan.demand_zone_start}"
                        if not cache.get(cache_key):  # ถ้ายังไม่เคยเตือนจุดราคานี้
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
                                cache.set(cache_key, True, timeout=43200) # มิวต์ไม่ส่งซ้ำ 12 ชั่วโมง
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
                    cache_key = ""
                    entry_price = float(p.entry_price or 0)
                    is_in_profit = entry_price <= 0 or price > entry_price

                    # ====== Let Profit Run: TP แรกล็อกกำไรบางส่วน แล้วเทรลราคาส่วนที่เหลือแทนการเทขายทันที ======
                    if p.tp1_hit:
                        # อยู่ในโหมดเทรลอยู่แล้ว — อัปเดตจุดสูงสุดแล้วเช็คว่าหลุด trailing stop หรือยัง (ไม่ต้อง mute เพราะ state กันการยิงซ้ำอยู่แล้ว)
                        if price > float(p.highest_price or 0):
                            p.highest_price = price
                            p.save(update_fields=['highest_price'])
                        trail_stop = simple_trailing_stop(p.highest_price, p.atr, p.trail_multiplier)
                        if trail_stop and price <= trail_stop:
                            alert_msg = (
                                f"🏁 <b>[TRAILING STOP EXIT] หลุดแนวเทรล!</b>\n"
                                f"หุ้น: <b>{p.symbol}</b> (ในพอร์ต)\n"
                                f"ราคาปัจจุบัน: <b>฿{price:.2f}</b>\n"
                                f"หลุด Trailing Stop ที่ ฿{trail_stop:.2f} แล้ว ควรพิจารณาขายส่วนที่เหลือ"
                            )
                            p.tp1_hit = False
                            p.tp1_price = None
                            p.save(update_fields=['tp1_hit', 'tp1_price'])
                            success = send_telegram_message(chat_id, alert_msg)
                            if success:
                                self.stdout.write(self.style.SUCCESS(f"-> Sent Trailing Exit alert for {p.symbol} to {user.username}"))
                        continue
                    # เช็คเป้าหมายทำกำไรแรก (TAKE PROFIT) — ล็อกกำไรบางส่วน แล้วเริ่มเทรลราคาส่วนที่เหลือ
                    elif latest_scan.supply_zone_start and price >= latest_scan.supply_zone_start and is_in_profit:
                        p.tp1_hit = True
                        p.tp1_price = price
                        update_fields = ['tp1_hit', 'tp1_price']
                        if price > float(p.highest_price or 0):
                            p.highest_price = price
                            update_fields.append('highest_price')
                        p.save(update_fields=update_fields)
                        alert_msg = (
                            f"🚀 <b>[LET PROFIT RUN] ถึงเป้าหมายกำไรแรก!</b>\n"
                            f"หุ้น: <b>{p.symbol}</b> (ในพอร์ต)\n"
                            f"ราคาปัจจุบัน: <b>฿{price:.2f}</b>\n"
                            f"💵 แนะนำล็อกกำไรบางส่วน (30-50%) ส่วนที่เหลือปล่อยให้วิ่งต่อ ระบบจะเริ่มเทรลราคาให้อัตโนมัติ"
                        )
                        success = send_telegram_message(chat_id, alert_msg)
                        if success:
                            self.stdout.write(self.style.SUCCESS(f"-> Sent TP1 Partial alert for {p.symbol} to {user.username}"))
                        continue
                    # เช็คระวังการดิ่งลงทะลุ SL
                    elif latest_scan.stop_loss and price <= latest_scan.stop_loss:
                         cache_key = f"alert_sl_{user.id}_{p.symbol}_{latest_scan.stop_loss}"
                         if not cache.get(cache_key):
                             alert_msg = (
                                f"⚠️ <b>[STOP LOSS ALERT] ระวังหลุดแนวรับ!</b>\n"
                                f"หุ้น: <b>{p.symbol}</b> (ในพอร์ต)\n"
                                f"ราคาปัจจุบัน: <b>฿{price:.2f}</b>\n"
                                f"🩸 ราคาหลุดจุดตัดขาดทุน (SL) ที่ ฿{latest_scan.stop_loss:.2f} ไปแล้ว ควรพิจารณาคัตลอส"
                            )

                    if alert_msg and cache_key:
                        success = send_telegram_message(chat_id, alert_msg)
                        if success:
                            cache.set(cache_key, True, timeout=43200) # มิวต์ไม่ส่งซ้ำ 12 ชั่วโมง
                            self.stdout.write(self.style.SUCCESS(f"-> Sent Exit alert for {p.symbol} to {user.username}"))

        self.stdout.write(self.style.SUCCESS("✅ รันการตรวจสอบเสร็จสิ้น"))
