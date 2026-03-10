import os
import django

os.environ.setdefault('DJANGO_SETTINGS_MODULE', 'config.settings')
django.setup()

from pms.models import Project, ServiceQueueItem
from django.db.models import Count
from django.utils import timezone

def cleanup_duplicates():
    print("--- Starting ServiceQueueItem Cleanup ---")
    
    # 1. Find projects that have more than one "Active" task in the queue
    # Active statuses: PENDING, SCHEDULED, IN_PROGRESS, INCOMPLETE
    active_statuses = ['PENDING', 'SCHEDULED', 'IN_PROGRESS', 'INCOMPLETE']
    
    # We group by project ID and count how many active tasks they have
    duplicate_groups = ServiceQueueItem.objects.filter(
        project__isnull=False,
        status__in=active_statuses
    ).values('project').annotate(task_count=Count('id')).filter(task_count__gt=1)
    
    total_deleted = 0
    
    for group in duplicate_groups:
        proj_id = group['project']
        # Use select_related to avoid multiple queries
        tasks = ServiceQueueItem.objects.filter(
            project_id=proj_id,
            status__in=active_statuses
        ).order_by('-updated_at') # Keep the most recently updated one
        
        keep_task = tasks[0]
        delete_tasks = tasks[1:]
        
        print(f"Project ID {proj_id}: Keeping task {keep_task.id} (Status: {keep_task.status}), deleting {len(delete_tasks)} duplicates.")
        
        for t in delete_tasks:
            t.delete()
            total_deleted += 1
            
    # 2. Also find tasks that might have been created for projects that are ALREADY in a successful end state
    # i.e. Project is CLOSED or CANCELLED but somehow there's still an active task in the queue
    finished_proj_tasks = ServiceQueueItem.objects.filter(
        project__status__in=[Project.Status.CLOSED, Project.Status.CANCELLED],
        status__in=active_statuses
    )
    
    for t in finished_proj_tasks:
        print(f"Deleting orphaned task {t.id} for finished project {t.project.id} ({t.project.status})")
        t.delete()
        total_deleted += 1

    print(f"--- Cleanup Complete. Total duplicates/orphans removed: {total_deleted} ---")

if __name__ == "__main__":
    cleanup_duplicates()
