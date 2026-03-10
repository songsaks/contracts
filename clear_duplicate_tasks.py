import os
import django

# Set up Django environment
os.environ.setdefault('DJANGO_SETTINGS_MODULE', 'config.settings')
django.setup()

from pms.models import ServiceQueueItem, Project

def clear_duplicate_tasks():
    """
    Finds Projects that have multiple active ServiceQueueItem records
    and keeps only the most recently updated one.
    """
    active_statuses = ['PENDING', 'SCHEDULED', 'IN_PROGRESS', 'INCOMPLETE']
    
    # Get all projects that have at least one active task
    projects_with_tasks = Project.objects.filter(
        service_tasks__status__in=active_statuses
    ).distinct()

    total_cleared = 0
    print(f"Checking {projects_with_tasks.count()} projects for duplicate active tasks...")

    for project in projects_with_tasks:
        # Get all active tasks for this project, newest first
        active_tasks = ServiceQueueItem.objects.filter(
            project=project,
            status__in=active_statuses
        ).order_by('-updated_at')

        if active_tasks.count() > 1:
            print(f"Found {active_tasks.count()} active tasks for project: {project.name}")
            # Keep the newest one (index 0)
            to_keep = active_tasks[0]
            to_delete = active_tasks[1:]

            for task in to_delete:
                print(f"  --> Deleting duplicate task: ID={task.id}, Status={task.status}, Title={task.title}")
                task.delete()
                total_cleared += 1

    # Also check for orphaned tasks or tasks in trigger statuses that might be duplicates
    # and were somehow created without a linked project (though unlikely based on current schema)
    
    print("-" * 50)
    print(f"Cleanup finished: Total {total_cleared} duplicate tasks removed.")

if __name__ == "__main__":
    clear_duplicate_tasks()
