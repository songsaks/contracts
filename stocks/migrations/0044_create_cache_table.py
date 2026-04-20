from django.db import migrations, connection

def create_cache_table(apps, schema_editor):
    from django.core.management import call_command
    # Check if table already exists to avoid errors
    with connection.cursor() as cursor:
        cursor.execute("SELECT 1 FROM information_schema.tables WHERE table_name = 'django_cache'")
        exists = cursor.fetchone()
        if not exists:
            call_command('createcachetable')

class Migration(migrations.Migration):

    dependencies = [
        ('stocks', '0043_scanwatchlistitem_strategy'),
    ]

    operations = [
        migrations.RunPython(create_cache_table),
    ]
