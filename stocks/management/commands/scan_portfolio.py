import os
from collections import defaultdict

import requests
import yfinance as yf
from django.core.management.base import BaseCommand

from stocks.models import MarketType, Portfolio

# สกุลเงินของแต่ละตลาด — ใช้เขียนข้อความให้ตรงความจริง
# เดิมข้อความ DCA เขียน "บาท" ตายตัวกับทุกไม้ รวมหุ้น US ที่เป็น USD
_CURRENCY = {
    MarketType.SET: 'บาท',
    MarketType.US: 'USD',
    MarketType.CRYPTO: 'USD',
}


def _yf_symbol(item):
    """
    แปลง symbol ที่เก็บใน DB ให้เป็น ticker ที่ yfinance รู้จัก

    เดิมส่ง item.symbol เข้า yf.Ticker ตรงๆ โดยไม่สน item.market ซึ่งพังกับ crypto
    (เก็บเป็น BTC แต่ yfinance ต้องการ BTC-USD) และกับไม้ SET เก่าที่ไม่มี .BK
    ตรรกะชุดนี้ให้ผลเดียวกับ _port_fetch_map ในหน้าพอร์ต
    """
    sym = item.symbol
    if item.market == MarketType.SET and not sym.endswith('.BK'):
        return f"{sym}.BK"
    if item.market == MarketType.CRYPTO and '-' not in sym:
        return f"{sym}-USD"
    return sym


class Command(BaseCommand):
    help = 'Scan portfolio prices and send notifications for DCA and Trailing Stop targets.'

    def send_line_notify(self, message):
        """
        เดิมยิง LINE Notify ซึ่งปิดบริการถาวรไปแล้วเมื่อ 31 มี.ค. 2025
        endpoint notify-api.line.me ไม่มีอยู่จริงอีกต่อไป คำสั่งนี้จึงส่งอะไรไม่ได้
        เก็บโค้ดไว้เพื่อบอกให้ชัดว่าช่องทางแจ้งเตือนตายแล้ว ไม่ใช่ทำเงียบๆ เหมือนเดิม
        ถ้าต้องการแจ้งเตือนจริง ต้องย้ายไป LINE Messaging API (push message)
        """
        token = os.environ.get('LINE_NOTIFY_TOKEN')
        if not token:
            self.stdout.write(self.style.WARNING(
                "LINE_NOTIFY_TOKEN is not set. Skipping LINE notification."))
            return

        self.stdout.write(self.style.ERROR(
            "LINE Notify ปิดบริการถาวรตั้งแต่ 31 มี.ค. 2025 — ส่งแจ้งเตือนไม่ได้ "
            "ต้องย้ายไป LINE Messaging API ก่อน (ข้อความถูกพิมพ์ออก stdout แทน)"))

        url = 'https://notify-api.line.me/api/notify'
        headers = {'Authorization': f'Bearer {token}'}
        data = {'message': message}
        try:
            response = requests.post(url, headers=headers, data=data, timeout=10)
            if response.status_code == 200:
                self.stdout.write(self.style.SUCCESS("Line notification sent successfully."))
            else:
                self.stdout.write(self.style.ERROR(
                    f"Failed to send Line notification: {response.text}"))
        except Exception as e:
            self.stdout.write(self.style.ERROR(f"Error sending Line notification: {str(e)}"))

    def handle(self, *args, **kwargs):
        self.stdout.write("Starting Portfolio Scan...")

        items = Portfolio.objects.select_related('user').all()
        if not items.exists():
            self.stdout.write("No items in portfolio to scan.")
            return

        # แยก alert ตามเจ้าของพอร์ต — เดิมรวมทุก user เข้าข้อความเดียวแล้วส่งออกไป
        # ทีเดียว ซึ่งทำให้ข้อมูลพอร์ตของแต่ละคนรั่วข้ามกันถ้าระบบมีผู้ใช้มากกว่าหนึ่งคน
        alerts_by_user = defaultdict(list)

        for item in items:
            try:
                fetch_sym = _yf_symbol(item)
                t = yf.Ticker(fetch_sym)
                try:
                    info = t.info
                    if not isinstance(info, dict):
                        info = {}
                except Exception:
                    info = {}

                current_price = (info.get('currentPrice')
                                 or info.get('regularMarketPrice')
                                 or info.get('previousClose'))

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
                ccy = _CURRENCY.get(item.market, '')

                self.stdout.write(f"Scanned {item.symbol}: P/L {gain_loss_pct:.2f}%")

                # 1. DCA Planner Logic (Loss > 20%)
                if gain_loss_pct <= -20:
                    target_cost = curr_p / 0.90  # Target adjusting average cost to just 10% loss
                    if curr_p < target_cost < entry_p:
                        dca_qty = qty * (entry_p - target_cost) / (target_cost - curr_p)
                        dca_amount = dca_qty * curr_p
                        alerts_by_user[item.user_id].append(
                            f"\n[DCA ALERT] {item.symbol}"
                            f"\nสถานะ: ขาดทุน {gain_loss_pct:.2f}% (ทุน {entry_p}, ราคาปัจจุบัน {curr_p})"
                            f"\nคำแนะนำ: ซื้อเพิ่ม {dca_qty:.0f} หน่วย (ใช้เงิน {dca_amount:,.2f} {ccy}) "
                            f"\nเพื่อลดต้นทุนเฉลี่ยมาที่ {target_cost:.2f} (พอร์ตจะติดลบเพียง -10%)"
                        )

                # 2. Trailing Stop Logic (Gain > 10%)
                if gain_loss_pct >= 10:
                    trailing_stop = curr_p * 0.95
                    alerts_by_user[item.user_id].append(
                        f"\n[PROFIT ALERT] {item.symbol}"
                        f"\nสถานะ: กำไร {gain_loss_pct:.2f}% (ทุน {entry_p}, ราคาปัจจุบัน {curr_p})"
                        f"\nคำแนะนำ: ขยับ Trailing Stop ล็อกกำไรที่ {trailing_stop:.2f}"
                        f"\nหากราคาหลุดเส้นนี้ ระบบแนะนำให้แบ่งขายเพื่อทำกำไร"
                    )

            except Exception as e:
                self.stdout.write(self.style.ERROR(f"Error processing {item.symbol}: {str(e)}"))

        total = sum(len(a) for a in alerts_by_user.values())
        if total:
            self.stdout.write(self.style.SUCCESS(
                f"Found {total} alerts across {len(alerts_by_user)} user(s). Sending notifications..."))
            for user_id, alerts in alerts_by_user.items():
                full_message = "📊 แจ้งเตือน AI Portfolio Scanner 🤖" + "".join(alerts)
                self.stdout.write(f"--- user_id={user_id} ---")
                self.stdout.write(full_message)
                self.send_line_notify(full_message)
        else:
            self.stdout.write("No critical alerts triggered in this scan.")

        self.stdout.write(self.style.SUCCESS("Portfolio Scan Completed."))
