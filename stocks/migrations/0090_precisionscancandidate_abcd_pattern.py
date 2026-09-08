# ABCD swing pattern fields (day-trade style) — non-scoring, additive only

from django.db import migrations, models


class Migration(migrations.Migration):

    dependencies = [
        ('stocks', '0089_stockalertconfig_alert_market_timing_and_more'),
    ]

    operations = [
        migrations.AddField(
            model_name='precisionscancandidate',
            name='abcd_setup',
            field=models.BooleanField(default=False),
        ),
        migrations.AddField(
            model_name='precisionscancandidate',
            name='abcd_stage',
            field=models.CharField(blank=True, default='', max_length=10),
        ),
        migrations.AddField(
            model_name='precisionscancandidate',
            name='abcd_a_price',
            field=models.FloatField(blank=True, null=True),
        ),
        migrations.AddField(
            model_name='precisionscancandidate',
            name='abcd_b_price',
            field=models.FloatField(blank=True, null=True),
        ),
        migrations.AddField(
            model_name='precisionscancandidate',
            name='abcd_c_price',
            field=models.FloatField(blank=True, null=True),
        ),
        migrations.AddField(
            model_name='precisionscancandidate',
            name='abcd_entry',
            field=models.FloatField(blank=True, null=True),
        ),
        migrations.AddField(
            model_name='precisionscancandidate',
            name='abcd_stop',
            field=models.FloatField(blank=True, null=True),
        ),
        migrations.AddField(
            model_name='precisionscancandidate',
            name='abcd_target',
            field=models.FloatField(blank=True, null=True),
        ),
        migrations.AddField(
            model_name='precisionscancandidate',
            name='abcd_rr',
            field=models.FloatField(blank=True, null=True),
        ),
    ]
