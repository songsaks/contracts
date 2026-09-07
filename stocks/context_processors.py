from django.contrib import messages
from django.core.cache import cache
from django.utils.html import escape
from django.utils.safestring import mark_safe
from stocks.models import StockAlertConfig, StockAlertEvent
from stocks.alert_engine import evaluate_user_alerts, effective_check_interval_seconds


def stock_alerts_processor(request):
    """
    Context processor ที่ตรวจสอบการแจ้งเตือนสำคัญของหุ้นแบบ Realtime
    หากมีแจ้งเตือนใหม่ที่ยังไม่ได้อ่าน จะนำข้อความแจ้งเตือนฉบับเต็ม (message)
    ใส่เข้าสู่ django.contrib.messages เพื่อให้แสดงผลบนแถบ Message ด้านบนของทุกหน้าทันที!
    """
    if not hasattr(request, 'user') or not request.user.is_authenticated:
        return {}

    # แสดงข้อความแจ้งเตือนหุ้นเฉพาะหน้าในระบบ /stocks/ เท่านั้น
    # ไม่ให้ไปโผล่ในแอปอื่น (repairs, payroll, rentals, chat ฯลฯ) ที่ใช้ base.html ร่วมกัน
    if not request.path.startswith('/stocks/'):
        return {}

    try:
        config = StockAlertConfig.objects.get(user=request.user)
        if not config.enabled:
            return {}
    except StockAlertConfig.DoesNotExist:
        return {}

    # Throttled evaluation — รอบเช็คตาม effective_check_interval_seconds
    # (ตลาดเปิด ≤ 90 วินาที, ตลาดปิด = ค่าที่ user ตั้ง)
    cache_key = f"stockalert_cp_lastrun_{request.user.id}"
    if not cache.get(cache_key):
        try:
            evaluate_user_alerts(request.user, config)
            cache.set(cache_key, True, timeout=effective_check_interval_seconds(config))
        except Exception:
            pass

    # ดึง Unread Events เพื่อแสดงใน django.contrib.messages (ใช่วงเวลาสั้นป้องกันสแปมข้อความซ้ำจากการรีเฟรชถี่)
    msg_cache_key = f"stockalert_cp_msg_shown_{request.user.id}"
    if not cache.get(msg_cache_key):
        unread_events = list(
            StockAlertEvent.objects.filter(user=request.user, is_read=False)
            .order_by('-created_at')[:3]
        )
        if unread_events:
            for event in unread_events:
                # escape ข้อมูลที่ผู้ใช้กรอกเอง (symbol, message มี p.symbol ผสมอยู่) ก่อนประกอบกับ
                # <strong> ที่เราควบคุมเอง แล้วค่อย mark_safe ทั้งก้อน — กัน stored XSS ถ้ามีคนตั้งชื่อ
                # symbol ในพอร์ตเป็น payload (เช่น <script>) ป้องกันไม่ให้ไปโดน render เป็น HTML จริง
                safe_symbol = escape(event.symbol)
                safe_message = escape(event.message)
                safe_type_label = escape(event.get_alert_type_display())
                msg_html = f"<strong>[{safe_symbol}]</strong> {safe_message}"
                if event.alert_type in (StockAlertEvent.AlertType.STOP_LOSS, StockAlertEvent.AlertType.TRAILING_EXIT):
                    messages.error(request, mark_safe(f"🩸 <strong>{safe_type_label}</strong>: {msg_html}"))
                elif event.alert_type == StockAlertEvent.AlertType.DISTRIBUTION_WARNING:
                    messages.warning(request, mark_safe(f"⚠️ <strong>{safe_type_label}</strong>: {msg_html}"))
                elif event.alert_type in (StockAlertEvent.AlertType.TP_PARTIAL, StockAlertEvent.AlertType.TAKE_PROFIT):
                    messages.success(request, mark_safe(f"💵 <strong>{safe_type_label}</strong>: {msg_html}"))
                elif event.alert_type == StockAlertEvent.AlertType.BREAKOUT:
                    messages.success(request, mark_safe(f"🚀 <strong>{safe_type_label}</strong>: {msg_html}"))
                elif event.alert_type == StockAlertEvent.AlertType.REALLOCATE:
                    messages.info(request, mark_safe(f"🔄 <strong>{safe_type_label}</strong>: {msg_html}"))
                elif event.alert_type == StockAlertEvent.AlertType.MARKET_TIMING:
                    messages.warning(request, mark_safe(f"🌐 <strong>{safe_type_label}</strong>: {msg_html}"))
                elif event.alert_type == StockAlertEvent.AlertType.SECTOR_ROTATION:
                    messages.info(request, mark_safe(f"🔁 <strong>{safe_type_label}</strong>: {msg_html}"))
                else:
                    messages.info(request, mark_safe(f"🔔 <strong>{safe_type_label}</strong>: {msg_html}"))

            cache.set(msg_cache_key, True, timeout=120)

    # แจ้งเตือนที่ยังไม่อ่านล่าสุด — ใช้แสดงใน dropdown ของ nav (hover บน desktop / แตะบน tablet)
    recent_unread = list(
        StockAlertEvent.objects.filter(user=request.user, is_read=False)
        .order_by('-created_at')[:8]
    )
    unread_count = StockAlertEvent.objects.filter(user=request.user, is_read=False).count()
    return {
        'unread_stock_alerts_count': unread_count,
        'recent_stock_alerts': recent_unread,
    }
