import os
import django

os.environ.setdefault('DJANGO_SETTINGS_MODULE', 'config.settings')
django.setup()

from repairs.models import RepairType

updates = {
    'Outsourcing': {'color': '#a855f7', 'icon': 'fas fa-external-link-alt'}, # Purple
    'Other Departments': {'color': '#0ea5e9', 'icon': 'fas fa-building'},   # Sky Blue
}

for name, data in updates.items():
    rt = RepairType.objects.filter(name=name).first()
    if rt:
        rt.color = data['color']
        rt.icon = data['icon']
        rt.save()
        print(f"Updated {name}: {data['color']}")
