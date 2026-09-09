# Adds the market split to the value scanner so SET and US candidates
# no longer share one listing. Existing rows are all US.

from django.db import migrations, models


class Migration(migrations.Migration):

    dependencies = [
        ('stocks', '0093_valuescancandidate_roic_wacc'),
    ]

    operations = [
        migrations.AddField(
            model_name='valuescancandidate',
            name='market',
            field=models.CharField(
                db_index=True,
                default='US',
                max_length=4,
                help_text='US or SET. Existing rows predate the Thai scanner and are all US.'
            ),
        ),
    ]
