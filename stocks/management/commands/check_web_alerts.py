# ====== check_web_alerts.py — เช็คแจ้งเตือน Action ของหุ้น (SL/TP/Breakout/Watchlist) ======
# ให้ทุก user ที่เปิดใช้งานไว้ (StockAlertConfig.enabled=True) โดยไม่ยุ่งกับช่องทางภายนอกใดๆ
# (ไม่ส่ง Telegram/LINE/Email) แค่บันทึกลง StockAlertEvent ให้ขึ้นในหน้าเว็บ /stocks/alerts/history/
#
# ใช้ evaluate_user_alerts() ตัวเดียวกับที่ AJAX endpoint check_stock_alerts เรียกตอนเปิดหน้าเว็บ
# และใช้ cache key เดียวกัน (_LAST_RUN_CACHE_KEY) เพื่อให้ throttle ตาม check_interval_minutes
# ของแต่ละ user ทำงานร่วมกันได้ ไม่ว่าจะถูกเรียกจาก cron หรือจากเบราว์เซอร์
#
# ตั้ง cron ให้รันคำสั่งนี้เป็นระยะ (เช่นทุก 5 นาที) — ไม่ต้องกังวลเรื่องเวลาตลาดปิด เพราะ
# evaluate_user_alerts() เช็ค is_market_open() ต่อ position ในพอร์ตอยู่แล้วก่อนสร้าง SL/TP/Breakout alert

from django.core.cache import cache
from django.core.management.base import BaseCommand

from stocks.alert_engine import evaluate_user_alerts
from stocks.models import StockAlertConfig
from stocks.views.alerts import _LAST_RUN_CACHE_KEY


class Command(BaseCommand):
    help = (
        'เช็คแจ้งเตือน Action ของหุ้นในพอร์ต/Watchlist ให้ทุก user ที่เปิดใช้งาน '
        '(บันทึกลง StockAlertEvent เท่านั้น ไม่ส่งข้อความออกช่องทางภายนอก) — สำหรับตั้ง cron รันเป็นระยะ'
    )

    def handle(self, *args, **kwargs):
        configs = StockAlertConfig.objects.filter(enabled=True).select_related('user')
        checked = 0
        total_events = 0

        for config in configs:
            cache_key = _LAST_RUN_CACHE_KEY.format(user_id=config.user.id)
            if cache.get(cache_key):
                continue  # ยังไม่ถึงรอบเช็คของ user นี้ตาม check_interval_minutes

            checked += 1
            try:
                events = evaluate_user_alerts(config.user, config)
            except Exception as e:
                self.stdout.write(self.style.ERROR(f"[{config.user.username}] error: {e}"))
                continue

            cache.set(cache_key, True, timeout=config.check_interval_minutes * 60)
            total_events += len(events)
            if events:
                summary = ', '.join(f"{e.symbol}({e.alert_type})" for e in events)
                self.stdout.write(self.style.SUCCESS(f"[{config.user.username}] {len(events)} alert(s): {summary}"))

        self.stdout.write(self.style.SUCCESS(
            f"เช็คแล้ว {checked}/{configs.count()} user(s) (ที่เหลือยังไม่ถึงรอบ), สร้าง {total_events} alert(s) ใหม่"
        ))
