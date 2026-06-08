import os
import sys

project_root = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
sys.path.append(project_root)

import django
os.environ.setdefault('DJANGO_SETTINGS_MODULE', 'config.settings')
django.setup()

from stocks.models import AIManualScanResult

results = AIManualScanResult.objects.filter(scan_run__isnull=True)
print(f"Found {results.count()} legacy records to update.")

updated = 0
for r in results:
    r.scan_run = r.created_at
    r.save()
    updated += 1

print(f"Successfully backpopulated scan_run for {updated} records.")
