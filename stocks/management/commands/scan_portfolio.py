import os
import requests
import yfinance as yf
from django.core.management.base import BaseCommand
from django.conf import settings
from stocks.models import Portfolio

class Command(BaseCommand):
    help = 'Scan portfolio prices and send notifications for DCA and Trailing Stop targets.'

    def send_line_notify(self, message):
        """
        Sends a LINE Notify message.
        Requires LINE_NOTIFY_TOKEN in .env
        """
        token = os.environ.get('LINE_NOTIFY_TOKEN')
        if not token:
            self.stdout.write(self.style.WARNING("LINE_NOTIFY_TOKEN is not set. Skipping LINE notification."))
            return
            
        url = 'https://notify-api.line.me/api/notify'
        headers = {'Authorization': f'Bearer {token}'}
        data = {'message': message}
        try:
            response = requests.post(url, headers=headers, data=data)
            if response.status_code == 200:
                self.stdout.write(self.style.SUCCESS("Line notification sent successfully."))
            else:
                self.stdout.write(self.style.ERROR(f"Failed to send Line notification: {response.text}"))
        except Exception as e:
            self.stdout.write(self.style.ERROR(f"Error sending Line notification: {str(e)}"))

    def handle(self, *args, **kwargs):
        self.stdout.write("Starting Portfolio Scan...")
        
        items = Portfolio.objects.all()
        if not items.exists():
            self.stdout.write("No items in portfolio to scan.")
            return

        alerts = []

        for item in items:
            try:
                t = yf.Ticker(item.symbol)
                try:
                    info = t.info
                    if not isinstance(info, dict): info = {}
                except:
                    info = {}
                
                current_price = info.get('currentPrice') or info.get('regularMarketPrice') or info.get('previousClose')
                
                if current_price is None:
                    # Try history if info failed
                    hist_last = t.history(period="1d")
                    if not hist_last.empty:
                        current_price = hist_last['Close'].iloc[-1]
                    else:
                        continue

                curr_p = float(current_price)
                entry_p = float(item.entry_price)
                qty = float(item.quantity)
                
                if qty == 0 or entry_p == 0:
                    continue
                
                cost_basis = qty * entry_p
                market_value = qty * curr_p
                gain_loss = market_value - cost_basis
                gain_loss_pct = (gain_loss / cost_basis) * 100

                self.stdout.write(f"Scanned {item.symbol}: P/L {gain_loss_pct:.2f}%")

                # 1. DCA Planner Logic (Loss > 20%)
                if gain_loss_pct <= -20:
                    target_cost = curr_p / 0.90 # Target adjusting average cost to just 10% loss
                    if curr_p < target_cost < entry_p:
                        dca_qty = qty * (entry_p - target_cost) / (target_cost - curr_p)
                        dca_amount = dca_qty * curr_p
                        alerts.append(
                            f"\n[DCA ALERT] {item.symbol}"
                            f"\nสถานะ: ขาดทุน {gain_loss_pct:.2f}% (ทุน {entry_p}, ราคาปัจจุบัน {curr_p})"
                            f"\nคำแนะนำ: ซื้อเพิ่ม {dca_qty:.0f} หุ้น (ใช้เงิน {dca_amount:,.2f} บาท) "
                            f"\nเพื่อลดต้นทุนเฉลี่ยมาที่ {target_cost:.2f} (พอร์ตจะติดลบเพียง -10%)"
                        )

                # 2. Trailing Stop Logic (Gain > 10%)
                if gain_loss_pct >= 10:
                    trailing_stop = curr_p * 0.95
                    alerts.append(
                        f"\n[PROFIT ALERT] {item.symbol}"
                        f"\nสถานะ: กำไร {gain_loss_pct:.2f}% (ทุน {entry_p}, ราคาปัจจุบัน {curr_p})"
                        f"\nคำแนะนำ: ขยับ Trailing Stop ล็อกกำไรที่ {trailing_stop:.2f}"
                        f"\nหากราคาหลุดเส้นนี้ ระบบแนะนำให้แบ่งขายเพื่อทำกำไร"
                    )

            except Exception as e:
                self.stdout.write(self.style.ERROR(f"Error processing {item.symbol}: {str(e)}"))

        if alerts:
            self.stdout.write(self.style.SUCCESS(f"Found {len(alerts)} alerts. Sending notifications..."))
            full_message = "📊 แจ้งเตือน AI Portfolio Scanner 🤖" + "".join(alerts)
            self.stdout.write(full_message)
            self.send_line_notify(full_message)
        else:
            self.stdout.write("No critical alerts triggered in this scan.")
            
        self.stdout.write(self.style.SUCCESS("Portfolio Scan Completed."))
