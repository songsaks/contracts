import os
import django

os.environ.setdefault('DJANGO_SETTINGS_MODULE', 'config.settings')
django.setup()

from repairs.models import RepairType

types = [
    ('Outsourcing', 'งานรับจากภายนอก/ตัวแทน'),
    ('Other Departments', 'งานจากแผนก/หน่วยงานอื่นภายใน')
]

for name, desc in types:
    obj, created = RepairType.objects.get_or_create(name=name, defaults={'description': desc})
    if created:
        print(f"Created RepairType: {name}")
    else:
        print(f"RepairType already exists: {name}")
