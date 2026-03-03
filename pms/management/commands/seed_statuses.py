from django.core.management.base import BaseCommand
from pms.models import JobStatus, Project

class Command(BaseCommand):
    help = 'Seed default JobStatus for the PMS app'

    def handle(self, *args, **options):
        # Service Workflow
        service_statuses = [
            (Project.Status.SOURCING, 'จัดหา', 10),
            (Project.Status.QUOTED, 'เสนอราคา', 20),
            (Project.Status.ORDERING, 'สั่งซื้อ', 30),
            (Project.Status.RECEIVED_QC, 'รับของ/QC', 40),
            (Project.Status.DELIVERY, 'ส่งมอบ', 50),
            (Project.Status.ACCEPTED, 'ตรวจรับ', 60),
            (Project.Status.CLOSED, 'ปิดจบ', 70),
        ]
        
        # Repair Workflow
        repair_statuses = [
            (Project.Status.SOURCING, 'รับแจ้งซ่อม', 10),
            (Project.Status.SUPPLIER_CHECK, 'เช็คราคา', 20),
            (Project.Status.ORDERING, 'จัดคิวซ่อม', 30),
            (Project.Status.DELIVERY, 'ซ่อม', 40),
            (Project.Status.CLOSED, 'ปิดงานซ่อม', 50),
        ]

        # Rental Workflow
        rental_statuses = [
            (Project.Status.SOURCING, 'จัดหา', 10),
            (Project.Status.CONTRACTED, 'ทำสัญญา', 20),
            (Project.Status.RENTING, 'เช่า', 30),
            (Project.Status.CLOSED, 'ปิดจบ', 40),
        ]

        # Project Workflow
        project_statuses = [
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
        ]

        all_types = [
            (Project.JobType.PROJECT, project_statuses),
            (Project.JobType.SERVICE, service_statuses),
            (Project.JobType.REPAIR, repair_statuses),
            (Project.JobType.RENTAL, rental_statuses),
        ]

        count = 0
        for jt, statuses in all_types:
            for key, label, sort in statuses:
                obj, created = JobStatus.objects.get_or_create(
                    job_type=jt,
                    status_key=key,
                    defaults={'label': label, 'sort_order': sort}
                )
                if created:
                    count += 1
        
        self.stdout.write(self.style.SUCCESS(f'Successfully seeded {count} job statuses!'))
