# Migration for ROIC/WACC on the US value scanner

from django.db import migrations, models


class Migration(migrations.Migration):

    dependencies = [
        ('stocks', '0092_bo_abcd_convergence_check'),
    ]

    operations = [
        migrations.AddField(
            model_name='valuescancandidate',
            name='roic',
            field=models.FloatField(
                blank=True,
                null=True,
                help_text='Return on Invested Capital (%) — NOPAT / (debt + equity - cash)'
            ),
        ),
        migrations.AddField(
            model_name='valuescancandidate',
            name='wacc',
            field=models.FloatField(
                blank=True,
                null=True,
                help_text='Weighted Average Cost of Capital (%) — per-company, from beta and capital structure'
            ),
        ),
        migrations.AddField(
            model_name='valuescancandidate',
            name='roic_spread',
            field=models.FloatField(
                blank=True,
                null=True,
                help_text='ROIC - WACC (%). Positive creates value, negative destroys it.'
            ),
        ),
    ]
