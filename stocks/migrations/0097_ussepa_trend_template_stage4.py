# Trend Template and Stage 4 on the US SEPA scanner, matching what the
# SET SEPA page gained in 0096.

from django.db import migrations, models


class Migration(migrations.Migration):

    dependencies = [
        ('stocks', '0096_precision_stage4_eps_accel'),
    ]

    operations = [
        migrations.AddField(
            model_name='ussepacandidate',
            name='stage4',
            field=models.BooleanField(default=False),
        ),
        migrations.AddField(
            model_name='ussepacandidate',
            name='trend_template_score',
            field=models.IntegerField(default=0),
        ),
    ]
