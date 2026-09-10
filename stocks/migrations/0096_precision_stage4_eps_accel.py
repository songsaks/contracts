# Stage 4 (distribution) and EPS acceleration on the precision scan,
# so the SET path has the Minervini signals the US SEPA model already carried.

from django.db import migrations, models


class Migration(migrations.Migration):

    dependencies = [
        ('stocks', '0095_sync_field_help_text'),
    ]

    operations = [
        migrations.AddField(
            model_name='precisionscancandidate',
            name='stage4',
            field=models.BooleanField(default=False),
        ),
        migrations.AddField(
            model_name='precisionscancandidate',
            name='eps_accel',
            field=models.BooleanField(default=False),
        ),
    ]
