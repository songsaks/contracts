from django.db import migrations, models


class Migration(migrations.Migration):

    dependencies = [
        ('stocks', '0020_stage2_earnings_soon'),
    ]

    operations = [
        migrations.AddField(
            model_name='precisionscancandidate',
            name='pocket_pivot',
            field=models.BooleanField(default=False),
        ),
        migrations.AddField(
            model_name='precisionscancandidate',
            name='vdu_near_zone',
            field=models.BooleanField(default=False),
        ),
    ]
