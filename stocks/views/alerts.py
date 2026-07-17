# ====== alerts.py — แจ้งเตือน Action ของหุ้นในหน้าเว็บ (SL/TP/Breakout/Watchlist) ======

from django.contrib import messages
from django.contrib.auth.decorators import login_required
from django.core.cache import cache
from django.http import JsonResponse
from django.shortcuts import get_object_or_404, redirect, render
from django.utils import timezone
from django.views.decorators.http import require_POST

from stocks.alert_engine import evaluate_user_alerts
from stocks.forms import StockAlertConfigForm
from stocks.models import StockAlertConfig, StockAlertEvent

_LAST_RUN_CACHE_KEY = 'stockalert_lastrun_{user_id}'


@login_required
def check_stock_alerts(request):
    """
    AJAX endpoint ที่ฝั่ง client เรียกเป็นระยะ (ตอนเปิดหน้าเว็บ + ทุกๆ ไม่กี่นาที)
    เซิร์ฟเวอร์เป็นคนคุมจริงๆ ว่าถึงรอบเช็คราคาหรือยัง ตาม check_interval_minutes ของ user
    """
    config, _ = StockAlertConfig.objects.get_or_create(user=request.user)
    if not config.enabled:
        return JsonResponse({'alerts': []})

    cache_key = _LAST_RUN_CACHE_KEY.format(user_id=request.user.id)
    if cache.get(cache_key):
        return JsonResponse({'alerts': [], 'skipped': True})

    events = evaluate_user_alerts(request.user, config)
    cache.set(cache_key, True, timeout=config.check_interval_minutes * 60)

    return JsonResponse({
        'alerts': [
            {
                'type': e.alert_type,
                'symbol': e.symbol,
                'strategy': e.strategy,
                'message': e.message,
                'price': e.price,
                'created_at': e.created_at.isoformat() if e.created_at else None,
            }
            for e in events
        ]
    })


@login_required
def stock_alert_config_view(request):
    """หน้าตั้งค่าแจ้งเตือน Action ของหุ้นในพอร์ต"""
    config, _ = StockAlertConfig.objects.get_or_create(user=request.user)

    if request.method == 'POST':
        form = StockAlertConfigForm(request.POST, instance=config)
        if form.is_valid():
            form.save()
            messages.success(request, 'บันทึกการตั้งค่าแจ้งเตือนเรียบร้อยแล้ว')
            return redirect('stocks:stock_alert_config')
    else:
        form = StockAlertConfigForm(instance=config)

    return render(request, 'stocks/alert_config.html', {'form': form})


@login_required
def stock_alert_history(request):
    """ประวัติการแจ้งเตือน Action ของหุ้นทั้งหมด (ใหม่ไปเก่า) จัดกลุ่มตามวันที่"""
    events = list(StockAlertEvent.objects.filter(user=request.user)[:100])
    today = timezone.localdate()

    day_groups = []
    current_day, current_bucket = None, None
    for e in events:
        e_day = timezone.localtime(e.created_at).date()
        if e_day != current_day:
            current_day = e_day
            current_bucket = {'day': e_day, 'events': []}
            day_groups.append(current_bucket)
        current_bucket['events'].append(e)

    unread_count = sum(1 for e in events if not e.is_read)

    return render(request, 'stocks/alert_history.html', {
        'day_groups': day_groups,
        'today': today,
        'yesterday': today - timezone.timedelta(days=1),
        'unread_count': unread_count,
        'has_events': bool(events),
    })


@require_POST
@login_required
def mark_stock_alerts_read(request):
    """ทำเครื่องหมายอ่านแล้วทั้งหมด ผ่าน AJAX"""
    StockAlertEvent.objects.filter(user=request.user, is_read=False).update(is_read=True)
    return JsonResponse({'success': True, 'unread_count': 0})


@require_POST
@login_required
def mark_stock_alert_read(request, pk):
    """สลับสถานะอ่านแล้ว/ยังไม่อ่านของแจ้งเตือนรายการเดียว ผ่าน AJAX"""
    event = get_object_or_404(StockAlertEvent, pk=pk, user=request.user)
    event.is_read = not event.is_read
    event.save(update_fields=['is_read'])
    unread_count = StockAlertEvent.objects.filter(user=request.user, is_read=False).count()
    return JsonResponse({'success': True, 'is_read': event.is_read, 'unread_count': unread_count})
