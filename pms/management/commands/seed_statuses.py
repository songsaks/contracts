from django.core.management.base import BaseCommand
from pms.models import JobStatus, Project

class Command(BaseCommand):
    help = 'Seed default JobStatus for the PMS app'

    def handle(self, *args, **options):
        # 1. Project Workflow
        # รวบรวม->เสนอราคา->ทำสัญญา->สั่งซื้อ->รับของ/QC->ขอดำเนิการ->คิว->รอคีย์ขาย->ปิดจบ->ยกเลิก
        project_statuses = [
            (Project.Status.DRAFT, 'รวบรวม', 10),
            (Project.Status.QUOTED, 'เสนอราคา', 20),
            (Project.Status.CONTRACTED, 'ทำสัญญา', 30),
            (Project.Status.ORDERING, 'สั่งซื้อ', 40),
            (Project.Status.RECEIVED_QC, 'รับของ/QC', 50),
            (Project.Status.REQUESTING, 'ขอดำเนินการ', 60),
            (Project.Status.INSTALLATION, 'คิว', 70),
            (Project.Status.WAITING_FOR_SALE_KEY, 'รอคีย์ขาย', 80),
            (Project.Status.CLOSED, 'ปิดจบ', 90),
            (Project.Status.CANCELLED, 'ยกเลิก', 100),
        ]

        # 2. Service/Sale Workflow
        # รวบรวม->เสนอราคา->สั่งซื้อ->รับของ/QC->คิว->รอคีย์ขาย->ปิดจบ->ยกเลิก
        service_statuses = [
            (Project.Status.DRAFT, 'รวบรวม', 10),
            (Project.Status.QUOTED, 'เสนอราคา', 20),
            (Project.Status.ORDERING, 'สั่งซื้อ', 30),
            (Project.Status.RECEIVED_QC, 'รับของ/QC', 40),
            (Project.Status.DELIVERY, 'คิว', 50),
            (Project.Status.WAITING_FOR_SALE_KEY, 'รอคีย์ขาย', 60),
            (Project.Status.CLOSED, 'ปิดจบ', 70),
            (Project.Status.CANCELLED, 'ยกเลิก', 80),
        ]
        
        # 3. Repair Workflow
        # รวบรวม->เสนอราคา->สั่งซื้อ->รับของ/QC->ซ่อม->คิว->รอคีย์ขาย->ปิดจบ->ยกเลิก
        repair_statuses = [
            (Project.Status.DRAFT, 'รวบรวม', 10),
            (Project.Status.QUOTED, 'เสนอราคา', 20),
            (Project.Status.ORDERING, 'สั่งซื้อ', 30),
            (Project.Status.RECEIVED_QC, 'รับของ/QC', 40),
            (Project.Status.REPAIRING, 'ซ่อม', 50),
            (Project.Status.DELIVERY, 'คิว', 60),
            (Project.Status.WAITING_FOR_SALE_KEY, 'รอคีย์ขาย', 70),
            (Project.Status.CLOSED, 'ปิดจบ', 80),
            (Project.Status.CANCELLED, 'ยกเลิก', 90),
        ]

        # 4. Rental Workflow (Keep as is or similar)
        rental_statuses = [
            (Project.Status.DRAFT, 'รวบรวม', 10),
            (Project.Status.CONTRACTED, 'ทำสัญญา', 20),
            (Project.Status.RENTING, 'เช่า', 30),
            (Project.Status.CLOSED, 'ปิดจบ', 40),
            (Project.Status.CANCELLED, 'ยกเลิก', 50),
        ]

        all_types = [
            (Project.JobType.PROJECT, project_statuses),
            (Project.JobType.SERVICE, service_statuses),
            (Project.JobType.REPAIR, repair_statuses),
            (Project.JobType.RENTAL, rental_statuses),
        ]

        # Clear existing to ensure clean sort order and steps
        JobStatus.objects.all().delete()

        count = 0
        for jt, statuses in all_types:
            for key, label, sort in statuses:
                JobStatus.objects.create(
                    job_type=jt,
                    status_key=key,
                    label=label,
                    sort_order=sort
                )
                count += 1
        
        self.stdout.write(self.style.SUCCESS(f'Successfully re-seeded {count} job statuses!'))
