import os
import django
import sys

# Set up Django environment
sys.path.append('d:\\DjangoProjects\\contracts')
os.environ.setdefault('DJANGO_SETTINGS_MODULE', 'config.settings')
django.setup()

from stocks.models import BotActivity

activity = BotActivity.objects.filter(bot_name="Gold Server Bot").first()
if activity:
    print(f"Status: {activity.status}")
    print(f"Message: {activity.message}")
    print(f"Last Heartbeat: {activity.last_heartbeat}")
else:
    print("No BotActivity record found.")
