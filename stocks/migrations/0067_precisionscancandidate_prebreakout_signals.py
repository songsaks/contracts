from django.db import migrations, models


class Migration(migrations.Migration):

    dependencies = [
        ('stocks', '0066_dailyagentreport'),
    ]

    operations = [
        migrations.AddField(
            model_name='precisionscancandidate',
            name='inside_bar',
            field=models.BooleanField(default=False),
        ),
        migrations.AddField(
            model_name='precisionscancandidate',
            name='acc_days',
            field=models.IntegerField(default=0),
        ),
        migrations.AddField(
            model_name='precisionscancandidate',
            name='dist_days',
            field=models.IntegerField(default=0),
        ),
        migrations.AddField(
            model_name='precisionscancandidate',
            name='base_length_weeks',
            field=models.IntegerField(default=0),
        ),
    ]
