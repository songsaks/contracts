import os
import django
from django.template.loader import get_template

os.environ.setdefault('DJANGO_SETTINGS_MODULE', 'config.settings')
django.setup()

try:
    t = get_template('repairs/repair_list.html')
    print(f"SUCCESS: Found template: {t.origin.name}")
except Exception as e:
    print(f"FAILURE: {e}")
    
    from django.apps import apps
    print("Installed apps:")
    for app in apps.get_app_configs():
        print(f"- {app.name}: {app.path}")
