import django, os
os.environ['DJANGO_SETTINGS_MODULE'] = 'config.settings'
django.setup()
from pms.models import ServiceQueueItem

# ลบงานที่ไม่ได้ผูกกับ Project (งานที่สร้างมือ) 
# และงานที่ไม่เข้าข่ายสถานะที่กำหนดเพื่อเริ่มต้นใหม่แบบสะอาด
to_delete = ServiceQueueItem.objects.filter(project__isnull=True)
count = to_delete.count()
to_delete.delete()

print(f"ลบงานสร้างมือ/ขยะออก: {count} รายการ")
print("ระบบจะทำการดึงงานจากสถานะจริงในการโหลดหน้า Dashboard ครั้งต่อไป")
