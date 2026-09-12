from django.conf import settings
from django.db import migrations, models
import django.db.models.deletion


class Migration(migrations.Migration):
    dependencies = [
        ('stocks', '0097_ussepa_trend_template_stage4'),
        migrations.swappable_dependency(settings.AUTH_USER_MODEL),
    ]
    operations = [migrations.CreateModel(
        name='PrecisionScanRun',
        fields=[
            ('id', models.BigAutoField(auto_created=True, primary_key=True, serialize=False, verbose_name='ID')),
            ('market', models.CharField(default='SET', max_length=10)),
            ('started_at', models.DateTimeField()),
            ('status', models.CharField(default='running', max_length=16)),
            ('total_symbols', models.PositiveIntegerField(default=0)),
            ('rs_count', models.PositiveIntegerField(default=0)),
            ('candidate_count', models.PositiveIntegerField(default=0)),
            ('message', models.CharField(blank=True, max_length=255)),
            ('user', models.ForeignKey(on_delete=django.db.models.deletion.CASCADE, to=settings.AUTH_USER_MODEL)),
        ],
        options={'ordering': ['-started_at']},
    )]
