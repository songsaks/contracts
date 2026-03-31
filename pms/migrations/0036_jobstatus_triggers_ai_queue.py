from django.db import migrations, models


def set_initial_queue_triggers(apps, schema_editor):
    """Mark existing INSTALLATION (PROJECT) and DELIVERY (SERVICE/REPAIR) as AI queue triggers."""
    JobStatus = apps.get_model('pms', 'JobStatus')
    JobStatus.objects.filter(
        job_type='PROJECT', status_key='INSTALLATION'
    ).update(triggers_ai_queue=True)
    JobStatus.objects.filter(
        job_type__in=['SERVICE', 'REPAIR'], status_key='DELIVERY'
    ).update(triggers_ai_queue=True)


class Migration(migrations.Migration):

    dependencies = [
        ('pms', '0035_jobstatus_preparing_docs'),
    ]

    operations = [
        migrations.AddField(
            model_name='jobstatus',
            name='triggers_ai_queue',
            field=models.BooleanField(
                default=False,
                verbose_name='ส่งเข้า AI Queue',
                help_text='เมื่อโครงการเข้าสถานะนี้ ระบบจะสร้างคิวงานอัตโนมัติ (AI Service Queue)',
            ),
        ),
        migrations.RunPython(set_initial_queue_triggers, migrations.RunPython.noop),
    ]
