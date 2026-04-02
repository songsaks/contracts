from django.core.management.base import BaseCommand
from pms.models import JobStatus, Project


class Command(BaseCommand):
    help = 'Seed/force-update JobStatus for all PMS job types (PROJECT/SERVICE/REPAIR/RENTAL/SURVEY)'

    def add_arguments(self, parser):
        parser.add_argument(
            '--force',
            action='store_true',
            help='Force update label and sort_order of existing records (default: only insert missing)',
        )
        parser.add_argument(
            '--dry-run',
            action='store_true',
            help='Show what would be done without making changes',
        )

    def handle(self, *args, **options):
        force   = options['force']
        dry_run = options['dry_run']

        # ── Master seed data ─────────────────────────────────────────────────
        SEED = {
            Project.JobType.PROJECT: [
                (Project.Status.DRAFT,               'รวบรวม',        10),
                (Project.Status.SOURCING,             'จัดหา',         20),
                (Project.Status.QUOTED,               'เสนอราคา',      30),
                (Project.Status.CONTRACTED,           'ทำสัญญา',       40),
                (Project.Status.ORDERING,             'สั่งซื้อ',      50),
                (Project.Status.RECEIVED_QC,          'รับของ/QC',     60),
                (Project.Status.INSTALLATION,         'ติดตั้ง',       70),
                (Project.Status.ACCEPTED,             'ตรวจรับ',       80),
                (Project.Status.BILLING,              'วางบิล',        90),
                (Project.Status.WAITING_FOR_SALE_KEY, 'รอคีย์ขาย',    100),
                (Project.Status.CLOSED,               'ปิดจบ',         110),
                (Project.Status.CANCELLED,            'ยกเลิก',        120),
            ],
            Project.JobType.SERVICE: [
                (Project.Status.SOURCING,             'จัดหา',         10),
                (Project.Status.QUOTED,               'เสนอราคา',      20),
                (Project.Status.ORDERING,             'สั่งซื้อ',      30),
                (Project.Status.RECEIVED_QC,          'รับของ/QC',     40),
                (Project.Status.DELIVERY,             'ส่งมอบ',        50),
                (Project.Status.ACCEPTED,             'ตรวจรับ',       60),
                (Project.Status.WAITING_FOR_SALE_KEY, 'รอคีย์ขาย',    65),
                (Project.Status.CLOSED,               'ปิดจบ',         70),
                (Project.Status.CANCELLED,            'ยกเลิก',        80),
            ],
            Project.JobType.REPAIR: [
                (Project.Status.SOURCING,             'รับแจ้งซ่อม',   10),
                (Project.Status.SUPPLIER_CHECK,       'เช็คราคา',      20),
                (Project.Status.ORDERING,             'จัดคิวซ่อม',    30),
                (Project.Status.DELIVERY,             'ซ่อม',          40),
                (Project.Status.WAITING_FOR_SALE_KEY, 'รอคีย์ขาย',    45),
                (Project.Status.CLOSED,               'ปิดงานซ่อม',   50),
                (Project.Status.CANCELLED,            'ยกเลิก',        60),
            ],
            Project.JobType.RENTAL: [
                (Project.Status.SOURCING,             'จัดหา',         10),
                (Project.Status.CONTRACTED,           'ทำสัญญา',       20),
                (Project.Status.RENTING,              'เช่า',          30),
                (Project.Status.WAITING_FOR_SALE_KEY, 'รอคีย์ขาย',    35),
                (Project.Status.CLOSED,               'ปิดจบ',         40),
                (Project.Status.CANCELLED,            'ยกเลิก',        50),
            ],
            Project.JobType.SURVEY: [
                ('QUEUE_SURVEY',                      'ดูหน้างาน',     10),
                (Project.Status.CLOSED,               'ปิดจบ',         20),
                (Project.Status.CANCELLED,            'ยกเลิก',        30),
            ],
        }

        created_count = 0
        updated_count = 0
        deleted_count = 0

        for jt, steps in SEED.items():
            seed_keys = [key for key, _, _ in steps]

            # ── Remove keys no longer in seed ──────────────────────────────
            obsolete = JobStatus.objects.filter(job_type=jt).exclude(status_key__in=seed_keys)
            if obsolete.exists():
                obs_labels = list(obsolete.values_list('status_key', flat=True))
                if dry_run:
                    self.stdout.write(self.style.WARNING(
                        f'  [DRY-RUN] Would delete {jt}: {obs_labels}'
                    ))
                else:
                    cnt, _ = obsolete.delete()
                    deleted_count += cnt
                    self.stdout.write(self.style.WARNING(
                        f'  Deleted obsolete [{jt}]: {obs_labels}'
                    ))

            # ── Upsert each step ────────────────────────────────────────────
            for key, label, sort in steps:
                existing = JobStatus.objects.filter(job_type=jt, status_key=key).first()

                if existing:
                    if force and (existing.label != label or existing.sort_order != sort):
                        if dry_run:
                            self.stdout.write(
                                f'  [DRY-RUN] Would update [{jt}] {key}: '
                                f'label="{existing.label}"→"{label}" sort={existing.sort_order}→{sort}'
                            )
                        else:
                            existing.label      = label
                            existing.sort_order = sort
                            existing.is_active  = True
                            existing.save()
                            updated_count += 1
                            self.stdout.write(f'  Updated [{jt}] {key}: "{label}" sort={sort}')
                else:
                    if dry_run:
                        self.stdout.write(
                            f'  [DRY-RUN] Would create [{jt}] {key}: "{label}" sort={sort}'
                        )
                    else:
                        JobStatus.objects.create(
                            job_type=jt, status_key=key,
                            label=label, sort_order=sort, is_active=True
                        )
                        created_count += 1
                        self.stdout.write(f'  Created [{jt}] {key}: "{label}" sort={sort}')

        # ── Ensure JobStatusAssignment row exists for every status ──────────
        from pms.models import JobStatusAssignment
        for js in JobStatus.objects.all():
            JobStatusAssignment.objects.get_or_create(job_status=js)

        if dry_run:
            self.stdout.write(self.style.SUCCESS('\n[DRY-RUN] No changes made.'))
        else:
            self.stdout.write(self.style.SUCCESS(
                f'\nDone — created: {created_count}, updated: {updated_count}, deleted: {deleted_count}'
            ))
