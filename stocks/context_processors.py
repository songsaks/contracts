from django.contrib import messages
from django.core.cache import cache
from django.utils.html import escape
from django.utils.safestring import mark_safe
from stocks.models import StockAlertConfig, StockAlertEvent
from stocks.alert_engine import evaluate_user_alerts


def stock_alerts_processor(request):
    """
    Context processor ที่ตรวจสอบการแจ้งเตือนสำคัญของหุ้นแบบ Realtime
    หากมีแจ้งเตือนใหม่ที่ยังไม่ได้อ่าน จะนำข้อความแจ้งเตือนฉบับเต็ม (message)
    ใส่เข้าสู่ django.contrib.messages เพื่อให้แสดงผลบนแถบ Message ด้านบนของทุกหน้าทันที!
    """
    if not hasattr(request, 'user') or not request.user.is_authenticated:
        return {}

    try:
        config = StockAlertConfig.objects.get(user=request.user)
        if not config.enabled:
            return {}
    except StockAlertConfig.DoesNotExist:
        return {}

    # Throttled evaluation (ทุกๆ 3 นาที) เพื่อประเมิน alert ใหม่
    cache_key = f"stockalert_cp_lastrun_{request.user.id}"
    if not cache.get(cache_key):
        try:
            evaluate_user_alerts(request.user, config)
            cache.set(cache_key, True, timeout=min(config.check_interval_minutes * 60, 180))
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
                else:
                    messages.info(request, mark_safe(f"🔔 <strong>{safe_type_label}</strong>: {msg_html}"))

            cache.set(msg_cache_key, True, timeout=120)

    unread_count = StockAlertEvent.objects.filter(user=request.user, is_read=False).count()
    return {
        'unread_stock_alerts_count': unread_count
    }
