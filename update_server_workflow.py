import os
import django
import sys

# Setup Django environment
sys.path.append(os.getcwd())
os.environ.setdefault('DJANGO_SETTINGS_MODULE', 'contracts.settings') # ปรับตามชื่อโปรเจคจริงถ้าไม่ใช่ contracts
django.setup()

from pms.models import JobStatus, Project
from django.db import transaction

def update_workflow_to_standard():
    print("🚀 Starting Workflow Update to Standard...")
    
    # กำหนดค่ามาตรฐานตามที่ User ต้องการ (5 มี.ค. 2026)
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
            
            print(f"\n✅ SUCCESS: Updated {total_updated} workflow steps total.")
    except Exception as e:
        print(f"\n❌ ERROR: {e}")

if __name__ == "__main__":
    update_workflow_to_standard()
