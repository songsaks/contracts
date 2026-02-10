import django, os
os.environ['DJANGO_SETTINGS_MODULE'] = 'config.settings'
django.setup()
from pms.models import Project, ServiceQueueItem

# ค้นหางาน Solar cells
projects = Project.objects.filter(name__icontains='Solar')
print(f"พบงานที่ชื่อมีคำว่า Solar: {projects.count()} รายการ")

for p in projects:
    print(f"\n--- Project: {p.name} ---")
    print(f"ID: {p.id}")
    print(f"Job Type: {p.job_type}")
    print(f"Status (Value): {p.status}")
    print(f"Status (Display): {p.get_status_display()}")
    
    # ตรวจสอบงานในคิวที่มีอยู่
    q_items = p.service_tasks.all()
    print(f"งานในคิว AI ที่มีอยู่: {q_items.count()} รายการ")
    for q in q_items:
        print(f"  - [{q.status}] {q.title} (ID: {q.id})")

    # จำลองการตรวจสอบเงื่อนไข sync_projects_to_queue
    from django.db.models import Q
    is_ready = Project.objects.filter(id=p.id).filter(
        Q(job_type='REPAIR', status='ORDERING') |
        Q(job_type='SERVICE', status='DELIVERY') |
        Q(job_type='PROJECT', status='INSTALLATION')
    ).exclude(
        service_tasks__status__in=['PENDING', 'SCHEDULED', 'IN_PROGRESS', 'COMPLETED']
    ).exists()
    
    print(f"ผ่านเงื่อนไขการดึงเข้าคิวหรือไม่: {'✅ ผ่าน' if is_ready else '❌ ไม่ผ่าน'}")
    
    if not is_ready:
        if p.status != 'INSTALLATION' and p.job_type == 'PROJECT':
            print(f"  -> สาเหตุ: สถานะคือ '{p.status}' ไม่ใช่ 'INSTALLATION'")
        if p.service_tasks.filter(status='COMPLETED').exists():
            print(f"  -> สาเหตุ: มีงานในคิวที่สถานะ 'COMPLETED' (เสร็จสิ้น) อยู่แล้ว ระบบจึงไม่ดึงซ้ำ")
