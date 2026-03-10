import os
import django
import sys

# Add current directory to path
sys.path.append(os.getcwd())

os.environ.setdefault('DJANGO_SETTINGS_MODULE', 'config.settings')
django.setup()

from pms.models import Project, ProjectStatusLog, CustomerRequest, RequestStatusLog

try:
    print("Testing Project Logging...")
    # Fetch a fresh instance
    p = Project.objects.first()
    if p:
        print(f"Project ID {p.id}")
        old_val_internal = getattr(p, '_old_status', 'NOT FOUND')
        print(f"Internal _old_status: {old_val_internal}")
        
        old_status = p.status
        print(f"Current status property: {old_status}")
        
        new_status = 'NEW' if old_status != 'NEW' else 'DRAFT'
        print(f"Changing to: {new_status}")
        p.status = new_status
        
        # Set dummy user flag
        p._changed_by_user = None
        p.save()
        
        print("Save completed.")
        
        last_log = ProjectStatusLog.objects.filter(project=p).order_by('-changed_at').first()
        if last_log:
            print(f"Log found: {last_log.old_status} -> {last_log.new_status}")
        else:
            print("Log NOT found!")
    else:
        print("No projects found.")

except Exception as e:
    import traceback
    print(f"An error occurred: {e}")
    traceback.print_exc()
