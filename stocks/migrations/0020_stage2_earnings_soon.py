from django.db import migrations, models


class Migration(migrations.Migration):

    dependencies = [
        ('stocks', '0019_us_precision_scanner'),
    ]

    operations = [
        migrations.AddField(
            model_name='precisionscancandidate',
            name='stage2',
            field=models.BooleanField(default=False),
        ),
        migrations.AddField(
            model_name='precisionscancandidate',
            name='earnings_soon',
            field=models.BooleanField(default=False),
        ),
    ]
