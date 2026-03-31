from django.db import migrations


class Migration(migrations.Migration):

    dependencies = [
        ('pms', '0036_jobstatus_triggers_ai_queue'),
    ]

    operations = [
        migrations.RemoveField(
            model_name='jobstatus',
            name='triggers_ai_queue',
        ),
    ]
