import os
import django
import sys

# Add current directory to path
sys.path.append(os.getcwd())

os.environ.setdefault('DJANGO_SETTINGS_MODULE', 'config.settings')
django.setup()

from pms.models import Project, JobStatus

types = Project.JobType.choices
for jt_code, jt_label in types:
    print(f"\n--- {jt_label} ({jt_code}) ---")
    statuses = JobStatus.objects.filter(job_type=jt_code, is_active=True).order_by('sort_order')
    for s in statuses:
        print(f"  {s.status_key}: {s.label} ({s.sort_order})")
