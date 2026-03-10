from .models import CustomerRequirement, CustomerRequest, UserNotification
from django.conf import settings

# เพิ่มตัวแปรส่วนกลางสำหรับใช้ใน Template ของ PMS (เช่น จำนวนการแจ้งเตือน, จำนวน Lead ใหม่)
def pms_context(request):
    context = {
        'CHATBOT_ENABLED': getattr(settings, 'CHATBOT_ENABLED', True)
    }
    if request.user.is_authenticated:
        unconverted_leads_count = CustomerRequirement.objects.filter(is_converted=False).count()
        new_requests_count = CustomerRequest.objects.filter(status=CustomerRequest.Status.RECEIVED).count()
        unread_notifications_count = UserNotification.objects.filter(user=request.user, is_read=False).count()
        context.update({
            'unconverted_leads_count': unconverted_leads_count,
            'new_requests_count': new_requests_count,
            'unread_notifications_count': unread_notifications_count,
        })
    return context
