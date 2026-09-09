# Migration for BO + B (ABCD) Convergence Check

from django.db import migrations, models


class Migration(migrations.Migration):

    dependencies = [
        ('stocks', '0091_abcd_thin_retracement_improvements'),
    ]

    operations = [
        migrations.AddField(
            model_name='precisionscancandidate',
            name='convergence_gap_pct',
            field=models.FloatField(
                default=0.0,
                help_text='% difference between BO and B (ABCD) entry prices (0-5% = strong, 5-8% = fair, 8-15% = risky, >15% = diverge)'
            ),
        ),
        migrations.AddField(
            model_name='precisionscancandidate',
            name='convergence_status',
            field=models.CharField(
                blank=True,
                default='none',
                help_text='Convergence status: strong/fair/risky/diverge/none',
                max_length=10
            ),
        ),
    ]
