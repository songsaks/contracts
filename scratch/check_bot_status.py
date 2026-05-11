import os
import django
import sys

# Set up Django environment
sys.path.append(os.getcwd())
os.environ.setdefault('DJANGO_SETTINGS_MODULE', 'contracts.settings')
django.setup()

from stocks.models import BotActivity
from django.utils import timezone

activities = BotActivity.objects.all()
print(f"Total Activities: {activities.count()}")
for a in activities:
    diff = (timezone.now() - a.last_heartbeat).total_seconds()
    print(f"Bot: {a.bot_name} | Status: {a.status} | Last: {diff:.1f}s ago | Msg: {a.message}")
