import os
import django

os.environ.setdefault('DJANGO_SETTINGS_MODULE', 'config.settings')
django.setup()

from pms.models import ServiceQueueItem

def list_queue():
    items = ServiceQueueItem.objects.filter(
        status__in=['PENDING', 'SCHEDULED', 'IN_PROGRESS', 'INCOMPLETE', 'COMPLETED']
    ).select_related('project', 'project__customer').order_by('project_id', 'created_at')
    
    print(f"{'ID':<5} | {'ProjID':<7} | {'Status':<12} | {'Project Name':<40} | {'Customer'}")
    print("-" * 100)
    for item in items:
        p_id = item.project.id if item.project else "None"
        p_name = item.project.name if item.project else "No Project"
        c_name = item.project.customer.name if item.project and item.project.customer else "No Customer"
        print(f"{item.id:<5} | {p_id:<7} | {item.status:<12} | {p_name[:38]:<40} | {c_name}")

if __name__ == "__main__":
    list_queue()
