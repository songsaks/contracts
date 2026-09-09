# Generated migration for ABCD thin retracement detection improvements

from django.db import migrations, models


class Migration(migrations.Migration):

    dependencies = [
        ('stocks', '0090_precisionscancandidate_abcd_pattern'),
    ]

    operations = [
        migrations.AddField(
            model_name='precisionscancandidate',
            name='abcd_quality',
            field=models.CharField(
                blank=True,
                default='medium',
                help_text='Quality flag for ABCD patterns: high/medium/low (especially for thin retracements)',
                max_length=10
            ),
        ),
        migrations.AddField(
            model_name='precisionscancandidate',
            name='abcd_is_thin',
            field=models.BooleanField(
                default=False,
                help_text='True when retracement is thin (15-30% vs normal 30-78.6%)'
            ),
        ),
    ]
