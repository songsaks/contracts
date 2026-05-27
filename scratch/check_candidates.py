import os
import sys
import django

sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))
os.environ.setdefault('DJANGO_SETTINGS_MODULE', 'config.settings')
django.setup()

from stocks.models import CupHandleCandidate, PrecisionScanCandidate, MorningBriefing

print("--- Cup & Handle Candidates ---")
ch_runs = CupHandleCandidate.objects.values_list('scan_run', flat=True).distinct().order_by('-scan_run')[:3]
for run in ch_runs:
    count = CupHandleCandidate.objects.filter(scan_run=run).count()
    symbols = list(CupHandleCandidate.objects.filter(scan_run=run).values_list('symbol', flat=True)[:10])
    print(f"Run: {run}, Count: {count}, Symbols: {symbols}")

print("\n--- Precision Scan Candidates ---")
pr_runs = PrecisionScanCandidate.objects.values_list('scan_run', flat=True).distinct().order_by('-scan_run')[:3]
for run in pr_runs:
    count = PrecisionScanCandidate.objects.filter(scan_run=run).count()
    symbols = list(PrecisionScanCandidate.objects.filter(scan_run=run).values_list('symbol', flat=True)[:10])
    print(f"Run: {run}, Count: {count}, Symbols: {symbols}")

print("\n--- Morning Briefings in DB ---")
briefings = MorningBriefing.objects.all().order_by('-created_at')[:3]
for b in briefings:
    print(f"ID: {b.id}, Created at: {b.created_at}, Report prefix: {b.report_md[:150]}")
