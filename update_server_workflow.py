import os
import django
import sys

# Setup Django environment
sys.path.append(os.getcwd())
os.environ.setdefault('DJANGO_SETTINGS_MODULE', 'config.settings')
django.setup()

from pms.models import JobStatus, Project
from django.db import transaction

def update_workflow_to_standard():
    print("🚀 Starting Workflow Sync to Standard (Updated: 9 Mar 2026)...")
    
    # 1. กำหนดค่ามาตรฐานล่าสุด
    defaults = {
        Project.JobType.SERVICE: [
            (Project.Status.SOURCING, 'จัดหา', 10),
            (Project.Status.QUOTED, 'เสนอราคา', 20),
            (Project.Status.ORDERING, 'สั่งซื้อ', 30),
            (Project.Status.RECEIVED_QC, 'รับของ/QC', 40),
            (Project.Status.DELIVERY, 'ส่งมอบ', 50),
            (Project.Status.ACCEPTED, 'ตรวจรับ', 60),
            (Project.Status.WAITING_FOR_SALE_KEY, 'รอคีย์ขาย', 65),
            (Project.Status.CLOSED, 'ปิดจบ', 70),
            (Project.Status.CANCELLED, 'ยกเลิก', 80),
        ],
        Project.JobType.REPAIR: [
            (Project.Status.SOURCING, 'รับแจ้งซ่อม', 10),
            (Project.Status.SUPPLIER_CHECK, 'เช็คราคา', 20),
            (Project.Status.ORDERING, 'จัดคิวซ่อม', 30),
            (Project.Status.DELIVERY, 'ซ่อม', 40),
            (Project.Status.WAITING_FOR_SALE_KEY, 'รอคีย์ขาย', 45),
            (Project.Status.CLOSED, 'ปิดงานซ่อม', 50),
            (Project.Status.CANCELLED, 'ยกเลิก', 60),
        ],
        Project.JobType.RENTAL: [
            (Project.Status.SOURCING, 'จัดหา', 10),
            (Project.Status.CONTRACTED, 'ทำสัญญา', 20),
            (Project.Status.RENTING, 'เช่า', 30),
            (Project.Status.WAITING_FOR_SALE_KEY, 'รอคีย์ขาย', 35),
            (Project.Status.CLOSED, 'ปิดจบ', 40),
            (Project.Status.CANCELLED, 'ยกเลิก', 50),
        ],
        Project.JobType.PROJECT: [
            (Project.Status.DRAFT, 'รวบรวม', 10),
            (Project.Status.SOURCING, 'จัดหา', 20),
            (Project.Status.QUOTED, 'เสนอราคา', 30),
            (Project.Status.CONTRACTED, 'ทำสัญญา', 40),
            (Project.Status.ORDERING, 'สั่งซื้อ', 50),
            (Project.Status.RECEIVED_QC, 'รับของ/QC', 60),
            (Project.Status.INSTALLATION, 'ติดตั้ง', 70),
            (Project.Status.ACCEPTED, 'ตรวจรับ', 80),
            (Project.Status.BILLING, 'วางบิล', 90),
            (Project.Status.WAITING_FOR_SALE_KEY, 'รอคีย์ขาย', 100),
            (Project.Status.CLOSED, 'ปิดจบ', 110),
            (Project.Status.CANCELLED, 'ยกเลิก', 120),
        ]
    }

    try:
        with transaction.atomic():
            # 2. ปิดการใช้งานของเก่าทั้งหมดก่อน (is_active=False) 
            print("🧹 Deactivating old workflow steps...")
            JobStatus.objects.all().update(is_active=False)
            
            total_updated = 0
            for jt, steps in defaults.items():
                print(f"\n📦 Processing Job Type: {jt}")
                for key, label, sort in steps:
                    obj, created = JobStatus.objects.update_or_create(
                        job_type=jt,
                        status_key=key,
                        defaults={
                            'label': label,
                            'sort_order': sort,
                            'is_active': True
                        }
                    )
                    action = "Created" if created else "Updated"
                    print(f"  - [{action}] {key}: {label} (Sort: {sort})")
                    total_updated += 1
            
            print(f"\n✅ SUCCESS: Created/Updated {total_updated} workflow steps total.")
            
            # 3. ตรวจสอบงานที่ค้างสถานะที่ไม่ได้ใช้งานแล้ว
            print("\n🔍 Checking for projects in inactive statuses...")
            active_statuses_per_type = {jt: [s[0] for s in steps] for jt, steps in defaults.items()}
            
            for project in Project.objects.exclude(status__in=[Project.Status.CLOSED, Project.Status.CANCELLED]):
                valid_statuses = active_statuses_per_type.get(project.job_type, [])
                if project.status not in valid_statuses:
                    new_default = valid_statuses[0] if valid_statuses else project.status
                    print(f"  ⚠️ Project '{project.name}' (ID: {project.pk}) is in inactive status '{project.status}'.")
                    print(f"     -> Auto-migrating to '{new_default}'")
                    project.status = new_default
                    project._changed_by_ai = True
                    project.save()

    except Exception as e:
        print(f"\n❌ ERROR: {e}")

if __name__ == "__main__":
    update_workflow_to_standard()
