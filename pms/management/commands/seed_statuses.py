from django.core.management.base import BaseCommand
from pms.models import JobStatus, Project

class Command(BaseCommand):
    help = 'Seed default JobStatus for the PMS app'

    def handle(self, *args, **options):
        # Service Workflow (งานขาย)
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
        
        # Repair Workflow (งานซ่อม)
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

        # Project Workflow (งานโครงการ)
        project_statuses = [
            (Project.Status.DRAFT, 'รวบรวม', 10),
            (Project.Status.QUOTED, 'เสนอราคา', 20),
            (Project.Status.CONTRACTED, 'ทำสัญญา', 30),
            (Project.Status.ORDERING, 'สั่งซื้อ', 40),
            (Project.Status.RECEIVED_QC, 'รับของ/QC', 50),
            (Project.Status.REQUESTING_ACTION, 'ขอดำเนินการ', 60),
            (Project.Status.INSTALLATION, 'คิว', 70),
            (Project.Status.WAITING_FOR_SALE_KEY, 'รอคีย์ขาย', 80),
            (Project.Status.CLOSED, 'ปิดจบ', 90),
            (Project.Status.CANCELLED, 'ยกเลิก', 100),
        ]

        all_types = [
            (Project.JobType.PROJECT, project_statuses),
            (Project.JobType.SERVICE, service_statuses),
            (Project.JobType.REPAIR, repair_statuses),
        ]

        count = 0
        for jt, statuses in all_types:
            # Keep track of active keys to disable others
            active_keys = [s[0] for s in statuses]
            
            # Deactivate statuses not in the list for this type
            JobStatus.objects.filter(job_type=jt).exclude(status_key__in=active_keys).delete()

            for key, label, sort in statuses:
                obj, created = JobStatus.objects.update_or_create(
                    job_type=jt,
                    status_key=key,
                    defaults={'label': label, 'sort_order': sort, 'is_active': True}
                )
                count += 1
        
        self.stdout.write(self.style.SUCCESS(f'Successfully seeded {count} job statuses!'))

        # Ensure JobStatusAssignment exists for each
        from pms.models import JobStatusAssignment
        for js in JobStatus.objects.all():
            JobStatusAssignment.objects.get_or_create(job_status=js)
