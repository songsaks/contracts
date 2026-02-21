from django.db import migrations, models

def populate_closed_at(apps, schema_editor):
    RepairItem = apps.get_model('repairs', 'RepairItem')
    RepairItem.objects.filter(
        status__in=['FINISHED', 'COMPLETED'], 
        closed_at__isnull=True
    ).update(closed_at=models.F('updated_at'))

class Migration(migrations.Migration):

    dependencies = [
        ('repairs', '0006_repairitem_closed_at'),
    ]

    operations = [
        migrations.RunPython(populate_closed_at),
    ]
