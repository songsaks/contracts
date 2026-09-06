from .models import CustomerRequirement, CustomerRequest, UserNotification
from django.conf import settings

# ฟังก์ชันสำหรับส่งตัวแปร (Variables) ทั่วไปเข้าไปยังหน้าจอ Template ในทุกๆ หน้าของระบบ PMS
# ใช้เพื่อแสดงสถิติล่าสุด เช่น จำนวนรายการที่ยังไม่ได้ซิงค์ และการแจ้งเตือนแบบด่วน
def pms_context(request):
    """รวบรวมข้อมูลสถานะกลางเพื่อแสดงผลบนแถบนำทางหรือแดชบอร์ด"""
    context = {
        'CHATBOT_ENABLED': getattr(settings, 'CHATBOT_ENABLED', True)
    }
    if request.user.is_authenticated:
        # นับจำนวนความต้องการลูกค้า (Leads) ที่ยังไม่ได้แปลงไปเป็นโครงการจริง
        unconverted_leads_count = CustomerRequirement.objects.filter(is_converted=False).count()
        # นับจำนวนคำขอลูกค้า (Requests) ใหม่ที่เพิ่งได้รับเข้ามาและยังไม่ดำเนินการ
        new_requests_count = CustomerRequest.objects.filter(status=CustomerRequest.Status.RECEIVED).count()
        # นับจำนวนการแจ้งเตือนงานที่ได้รับมอบหมายล่าสุดแต่ยังไม่ได้เปิดอ่าน
        unread_notifications_count = UserNotification.objects.filter(user=request.user, is_read=False).count()

        # ตัวนับฝั่งหุ้น (DailyAgentReport / StockAlertEvent) ใช้เฉพาะ navbar ของ base_stocks.html
        # จึง query เฉพาะเมื่ออยู่ในหน้า /stocks/ เท่านั้น ไม่ต้องยิงทุก request ของแอปอื่น
        unread_reports_count = 0
        unread_stock_alerts_count = 0
        if request.path.startswith('/stocks/'):
            try:
                from stocks.models import DailyAgentReport
                unread_reports_count = DailyAgentReport.objects.filter(user=request.user, is_read=False).count()
            except Exception:
                unread_reports_count = 0
            try:
                from stocks.models import StockAlertEvent
                unread_stock_alerts_count = StockAlertEvent.objects.filter(user=request.user, is_read=False).count()
            except Exception:
                unread_stock_alerts_count = 0

        context.update({
            'unconverted_leads_count': unconverted_leads_count,
            'new_requests_count': new_requests_count,
            'unread_notifications_count': unread_notifications_count,
            'unread_reports_count': unread_reports_count,
            'unread_stock_alerts_count': unread_stock_alerts_count,
        })
    return context

