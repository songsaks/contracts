import os, django
os.environ.setdefault('DJANGO_SETTINGS_MODULE', 'config.settings')
django.setup()
from stocks.models import PrecisionScanCandidate, CupHandleCandidate, TurtleScanCandidate
from django.db.models import Max

sym = 'WHA'
market = 'SET'

latest_prec = PrecisionScanCandidate.objects.filter(market=market).aggregate(Max('scan_run'))['scan_run__max']
latest_ch = CupHandleCandidate.objects.filter(market=market).aggregate(Max('scan_run'))['scan_run__max']
latest_turtle = TurtleScanCandidate.objects.filter(market=market).aggregate(Max('scan_run'))['scan_run__max']

p = PrecisionScanCandidate.objects.filter(symbol=sym, scan_run=latest_prec).first()
ch = CupHandleCandidate.objects.filter(symbol=sym, scan_run=latest_ch).first()
t = TurtleScanCandidate.objects.filter(symbol=sym, scan_run=latest_turtle).first()

print(f"--- {sym} Analysis ---")
print(f"Latest Scan Run (Precision): {latest_prec}")
print(f"Latest Scan Run (C&H): {latest_ch}")
print(f"Latest Scan Run (Turtle): {latest_turtle}")
print(f"In Precision Scan: {p is not None}")
print(f"In Cup & Handle Scan: {ch is not None}")
print(f"In Turtle Scan: {t is not None}")

if p:
    print(f"Technical Score: {p.technical_score}")
    print(f"RS Rating: {p.rs_rating}")

# Check TOP 5 to compare
top_5 = PrecisionScanCandidate.objects.filter(market=market, scan_run=latest_prec).order_by('-technical_score')[:5]
print("\n--- Current Top 5 Precision ---")
for s in top_5:
    print(f"{s.symbol}: Score={s.technical_score}, RS={s.rs_rating}")
