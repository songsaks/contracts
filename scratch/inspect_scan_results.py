import os
import sys

project_root = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
sys.path.append(project_root)

import django
os.environ.setdefault('DJANGO_SETTINGS_MODULE', 'config.settings')
django.setup()

from django.contrib.auth import get_user_model
from stocks.models import AIManualScanResult

User = get_user_model()
user = User.objects.first()

print(f"User: {user.username}")
results = AIManualScanResult.objects.filter(user=user)
print(f"Total results: {results.count()}")
for r in results:
    print(f"ID: {r.id}, Symbol: {r.symbol}, Grade: {r.grade}, Created At: {r.created_at}, Scan Run: {r.scan_run}")
