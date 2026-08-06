# ====== check_web_alerts.py — เช็คแจ้งเตือน Action ของหุ้น (SL/TP/Breakout/Watchlist) ======
# ให้ทุก user ที่เปิดใช้งานไว้ (StockAlertConfig.enabled=True) โดยไม่ยุ่งกับช่องทางภายนอกใดๆ
# (ไม่ส่ง Telegram/LINE/Email) แค่บันทึกลง StockAlertEvent ให้ขึ้นในหน้าเว็บ /stocks/alerts/history/
#
# ใช้ evaluate_user_alerts() ตัวเดียวกับที่ AJAX endpoint check_stock_alerts เรียกตอนเปิดหน้าเว็บ
# และใช้ cache key เดียวกัน (_LAST_RUN_CACHE_KEY) เพื่อให้ throttle ตาม check_interval_minutes
# ของแต่ละ user ทำงานร่วมกันได้ ไม่ว่าจะถูกเรียกจาก cron หรือจากเบราว์เซอร์
#
# นอกจากนี้ยังลบประวัติแจ้งเตือนเก่ากว่า alert_retention_days ของแต่ละ user ทิ้งด้วย (เช็ควันละครั้ง)
# เพื่อไม่ให้ตาราง StockAlertEvent โตไม่มีที่สิ้นสุด
#
# ตั้ง cron ให้รันคำสั่งนี้เป็นระยะ (เช่นทุก 5 นาที) — ไม่ต้องกังวลเรื่องเวลาตลาดปิด เพราะ
# evaluate_user_alerts() เช็ค is_market_open() ต่อ position ในพอร์ตอยู่แล้วก่อนสร้าง SL/TP/Breakout alert

from datetime import timedelta

from django.core.cache import cache
from django.core.management.base import BaseCommand
from django.utils import timezone

from stocks.alert_engine import evaluate_user_alerts
from stocks.models import StockAlertConfig, StockAlertEvent
from stocks.views.alerts import _LAST_RUN_CACHE_KEY

_CLEANUP_CACHE_KEY = 'stockalert_cleanup_lastrun_{user_id}'
_CLEANUP_INTERVAL_SECONDS = 24 * 60 * 60  # เช็คลบวันละครั้งต่อ user ก็พอ ไม่ต้องทุกรอบ cron


class Command(BaseCommand):
    help = (
        'เช็คแจ้งเตือน Action ของหุ้นในพอร์ต/Watchlist ให้ทุก user ที่เปิดใช้งาน '
        '(บันทึกลง StockAlertEvent เท่านั้น ไม่ส่งข้อความออกช่องทางภายนอก) '
        'พร้อมลบประวัติแจ้งเตือนเก่ากว่าที่ตั้งไว้ทิ้งด้วย — สำหรับตั้ง cron รันเป็นระยะ'
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

        # ── ลบประวัติแจ้งเตือนเก่าทิ้งตามที่แต่ละ user ตั้งไว้ (ไม่ผูกกับ enabled — ปิดแจ้งเตือนไว้ก็ยังเก็บกวาดให้) ──
        deleted_total = 0
        for config in StockAlertConfig.objects.all().select_related('user'):
            cleanup_key = _CLEANUP_CACHE_KEY.format(user_id=config.user.id)
            if cache.get(cleanup_key):
                continue  # เช็คไปแล้ววันนี้

            cutoff = timezone.now() - timedelta(days=config.alert_retention_days)
            deleted, _ = StockAlertEvent.objects.filter(user=config.user, created_at__lt=cutoff).delete()
            cache.set(cleanup_key, True, timeout=_CLEANUP_INTERVAL_SECONDS)

            if deleted:
                deleted_total += deleted
                self.stdout.write(self.style.WARNING(
                    f"[{config.user.username}] ลบแจ้งเตือนที่เก่ากว่า {config.alert_retention_days} วัน จำนวน {deleted} รายการ"
                ))

        if deleted_total:
            self.stdout.write(self.style.SUCCESS(f"ลบประวัติแจ้งเตือนเก่ารวม {deleted_total} รายการ"))
