"""
Management command: export_seed_statuses
========================================
อ่าน JobStatus ทั้งหมดที่มีอยู่ใน DB แล้วเขียนทับ seed_statuses.py ให้อัตโนมัติ

วิธีใช้ (รันที่ server production):
    python manage.py export_seed_statuses

ผลลัพธ์:
    - แสดงข้อมูลที่จะ export บน console
    - เขียนทับ pms/management/commands/seed_statuses.py ด้วยข้อมูล production จริง
    - commit ไฟล์นี้เข้า git แล้ว deploy ไป local/staging ได้เลย
"""
import os
from django.core.management.base import BaseCommand
from pms.models import JobStatus, Project


class Command(BaseCommand):
    help = 'Export current DB JobStatus rows into seed_statuses.py (overwrites the file)'

    def handle(self, *args, **options):
        # ── 1. Read all active statuses grouped by job_type ─────────────────
        statuses = (
            JobStatus.objects
            .all()
            .order_by('job_type', 'sort_order', 'status_key')
        )

        if not statuses.exists():
            self.stdout.write(self.style.ERROR('No JobStatus records found in DB. Nothing exported.'))
            return

        # Group by job_type
        grouped = {}
        for js in statuses:
            grouped.setdefault(js.job_type, []).append(js)

        # ── 2. Print summary ─────────────────────────────────────────────────
        self.stdout.write(self.style.SUCCESS('\n=== JobStatus export from DB ==='))
        for jt, rows in grouped.items():
            self.stdout.write(f'\n  [{jt}]')
            for js in rows:
                active_flag = '' if js.is_active else '  ← INACTIVE'
                self.stdout.write(f'    sort={js.sort_order:3d}  key={js.status_key:<30s}  label={js.label}{active_flag}')

        # ── 3. Build Python source ───────────────────────────────────────────
        jt_var_map = {
            Project.JobType.PROJECT: 'Project.JobType.PROJECT',
            Project.JobType.SERVICE: 'Project.JobType.SERVICE',
            Project.JobType.REPAIR:  'Project.JobType.REPAIR',
            Project.JobType.RENTAL:  'Project.JobType.RENTAL',
            Project.JobType.SURVEY:  'Project.JobType.SURVEY',
        }

        # Build a reverse map: status_key → Project.Status.XXX or 'raw_string'
        status_key_map = {v: f'Project.Status.{k}' for k, v in Project.Status.choices}
        # Also map by attribute name
        for attr in dir(Project.Status):
            if not attr.startswith('_'):
                val = getattr(Project.Status, attr, None)
                if isinstance(val, str) and val not in status_key_map:
                    status_key_map[val] = f'Project.Status.{attr}'

        def key_repr(key):
            """Return Python expression for the status key."""
            if key in status_key_map:
                return status_key_map[key]
            return f"'{key}'"

        lines = []
        lines.append('from django.core.management.base import BaseCommand')
        lines.append('from pms.models import JobStatus, Project')
        lines.append('')
        lines.append('')
        lines.append('class Command(BaseCommand):')
        lines.append("    help = 'Seed/force-update JobStatus for all PMS job types (exported from production DB)'")
        lines.append('')
        lines.append('    def add_arguments(self, parser):')
        lines.append('        parser.add_argument(')
        lines.append("            '--force',")
        lines.append('            action=\'store_true\',')
        lines.append("            help='Force update label and sort_order of existing records',")
        lines.append('        )')
        lines.append('        parser.add_argument(')
        lines.append("            '--dry-run',")
        lines.append('            action=\'store_true\',')
        lines.append("            help='Show what would be done without making changes',")
        lines.append('        )')
        lines.append('')
        lines.append('    def handle(self, *args, **options):')
        lines.append('        force   = options[\'force\']')
        lines.append('        dry_run = options[\'dry_run\']')
        lines.append('')
        lines.append('        SEED = {')

        for jt, rows in grouped.items():
            jt_expr = jt_var_map.get(jt, f"'{jt}'")
            lines.append(f'            {jt_expr}: [')
            for js in rows:
                k_expr = key_repr(js.status_key)
                label_escaped = js.label.replace("'", "\\'")
                active_comment = '' if js.is_active else '  # INACTIVE — kept for reference'
                lines.append(f"                ({k_expr}, '{label_escaped}', {js.sort_order}),{active_comment}")
            lines.append('            ],')

        lines.append('        }')
        lines.append('')
        lines.append('        created_count = 0')
        lines.append('        updated_count = 0')
        lines.append('        deleted_count = 0')
        lines.append('')
        lines.append('        for jt, steps in SEED.items():')
        lines.append('            seed_keys = [key for key, _, _ in steps]')
        lines.append('')
        lines.append('            obsolete = JobStatus.objects.filter(job_type=jt).exclude(status_key__in=seed_keys)')
        lines.append('            if obsolete.exists():')
        lines.append('                obs_labels = list(obsolete.values_list(\'status_key\', flat=True))')
        lines.append('                if dry_run:')
        lines.append('                    self.stdout.write(self.style.WARNING(f\'  [DRY-RUN] Would delete {jt}: {obs_labels}\'))')
        lines.append('                else:')
        lines.append('                    cnt, _ = obsolete.delete()')
        lines.append('                    deleted_count += cnt')
        lines.append('                    self.stdout.write(self.style.WARNING(f\'  Deleted obsolete [{jt}]: {obs_labels}\'))')
        lines.append('')
        lines.append('            for key, label, sort in steps:')
        lines.append('                existing = JobStatus.objects.filter(job_type=jt, status_key=key).first()')
        lines.append('                if existing:')
        lines.append('                    if force and (existing.label != label or existing.sort_order != sort):')
        lines.append('                        if dry_run:')
        lines.append('                            self.stdout.write(f\'  [DRY-RUN] Would update [{jt}] {key}: "{existing.label}"→"{label}" sort={existing.sort_order}→{sort}\')')
        lines.append('                        else:')
        lines.append('                            existing.label      = label')
        lines.append('                            existing.sort_order = sort')
        lines.append('                            existing.is_active  = True')
        lines.append('                            existing.save()')
        lines.append('                            updated_count += 1')
        lines.append('                else:')
        lines.append('                    if dry_run:')
        lines.append('                        self.stdout.write(f\'  [DRY-RUN] Would create [{jt}] {key}: "{label}" sort={sort}\')')
        lines.append('                    else:')
        lines.append('                        JobStatus.objects.create(job_type=jt, status_key=key, label=label, sort_order=sort, is_active=True)')
        lines.append('                        created_count += 1')
        lines.append('')
        lines.append('        from pms.models import JobStatusAssignment')
        lines.append('        for js in JobStatus.objects.all():')
        lines.append('            JobStatusAssignment.objects.get_or_create(job_status=js)')
        lines.append('')
        lines.append('        if dry_run:')
        lines.append('            self.stdout.write(self.style.SUCCESS(\'\\n[DRY-RUN] No changes made.\'))')
        lines.append('        else:')
        lines.append('            self.stdout.write(self.style.SUCCESS(')
        lines.append('                f\'\\nDone — created: {created_count}, updated: {updated_count}, deleted: {deleted_count}\'')
        lines.append('            ))')

        source = '\n'.join(lines) + '\n'

        # ── 4. Write to seed_statuses.py ─────────────────────────────────────
        out_path = os.path.join(os.path.dirname(__file__), 'seed_statuses.py')
        with open(out_path, 'w', encoding='utf-8') as f:
            f.write(source)

        self.stdout.write(self.style.SUCCESS(f'\n✓ Written to: {out_path}'))
        self.stdout.write('  Now commit seed_statuses.py and deploy to other environments.')
