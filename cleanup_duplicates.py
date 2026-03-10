import os
import django
import sys

# Add current directory to path
sys.path.append(os.getcwd())

os.environ.setdefault('DJANGO_SETTINGS_MODULE', 'config.settings')
django.setup()

from pms.models import ServiceQueueItem

print("Cleaning up duplicated service queue tasks...")

# Find projects that have both PENDING and INCOMPLETE tasks
# These are the duplicates caused by the bug
incomplete_tasks = ServiceQueueItem.objects.filter(status='INCOMPLETE')

deleted_count = 0
for inc_task in incomplete_tasks:
    if inc_task.project:
        # Check if there's a PENDING task for the same project
        duplicates = ServiceQueueItem.objects.filter(
            project=inc_task.project,
            status='PENDING'
        )
        if duplicates.exists():
            print(f"Found Duplicate for project: {inc_task.project.name}")
            for d in duplicates:
                print(f"  Deleting PENDING task ID: {d.id}")
                d.delete()
                deleted_count += 1
    
    if inc_task.repair_job:
        # Also check repair jobs
        duplicates = ServiceQueueItem.objects.filter(
            repair_job=inc_task.repair_job,
            status='PENDING'
        )
        if duplicates.exists():
            print(f"Found Duplicate for repair: {inc_task.repair_job.id}")
            for d in duplicates:
                print(f"  Deleting PENDING task ID: {d.id}")
                d.delete()
                deleted_count += 1

print(f"Done. Deleted {deleted_count} duplicate tasks.")
