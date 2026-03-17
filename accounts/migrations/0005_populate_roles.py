from django.db import migrations


INITIAL_ROLES = [
    {
        'code': 'admin',
        'name': 'ผู้ดูแลระบบ (Admin)',
        'is_staff_role': True,
        'is_technician_role': False,
        'badge_color': 'bg-red-100 text-red-800 border-red-200',
        'order': 1,
    },
    {
        'code': 'manager',
        'name': 'ผู้บริหาร (Manager)',
        'is_staff_role': True,
        'is_technician_role': False,
        'badge_color': 'bg-purple-100 text-purple-800 border-purple-200',
        'order': 2,
    },
    {
        'code': 'reception',
        'name': 'แอดมินรับงาน (Reception)',
        'is_staff_role': False,
        'is_technician_role': False,
        'badge_color': 'bg-pink-100 text-pink-800 border-pink-200',
        'order': 3,
    },
    {
        'code': 'technician_lead',
        'name': 'หัวหน้าช่าง (Lead Technician)',
        'is_staff_role': False,
        'is_technician_role': True,
        'badge_color': 'bg-blue-100 text-blue-800 border-blue-200',
        'order': 4,
    },
    {
        'code': 'technician',
        'name': 'ช่างเทคนิค (Technician)',
        'is_staff_role': False,
        'is_technician_role': True,
        'badge_color': 'bg-cyan-100 text-cyan-800 border-cyan-200',
        'order': 5,
    },
    {
        'code': 'sale',
        'name': 'พนักงานขาย (Sale)',
        'is_staff_role': False,
        'is_technician_role': False,
        'badge_color': 'bg-green-100 text-green-800 border-green-200',
        'order': 6,
    },
    {
        'code': 'hr_payroll',
        'name': 'ฝ่ายบุคคล/เงินเดือน (HR/Payroll)',
        'is_staff_role': False,
        'is_technician_role': False,
        'badge_color': 'bg-orange-100 text-orange-800 border-orange-200',
        'order': 7,
    },
]


def populate_roles(apps, schema_editor):
    Role = apps.get_model('accounts', 'Role')
    for data in INITIAL_ROLES:
        Role.objects.get_or_create(code=data['code'], defaults=data)


def remove_roles(apps, schema_editor):
    Role = apps.get_model('accounts', 'Role')
    Role.objects.filter(code__in=[r['code'] for r in INITIAL_ROLES]).delete()


class Migration(migrations.Migration):

    dependencies = [
        ('accounts', '0004_role_model'),
    ]

    operations = [
        migrations.RunPython(populate_roles, remove_roles),
    ]
