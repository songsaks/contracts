import os
import sys
import django

# Set up Django environment
sys.path.append(os.path.dirname(os.path.dirname(os.path.abspath(__file__))))
os.environ.setdefault('DJANGO_SETTINGS_MODULE', 'config.settings')
django.setup()

from stocks.models import PrecisionScanCandidate, CupHandleCandidate, TurtleScanCandidate
from django.utils import timezone
from django.db.models import Max

symbols = ["BLA", "DELTA", "EPG", "SCGP", "STGT", "TCAP", "WHAUP"]

print(f"Checking latest status for symbols: {symbols}")

# Find latest runs
latest_prec_run = PrecisionScanCandidate.objects.filter(market='SET').aggregate(Max('scan_run'))['scan_run__max']
latest_ch_run = CupHandleCandidate.objects.filter(market='SET').aggregate(Max('scan_run'))['scan_run__max']
latest_turtle_run = TurtleScanCandidate.objects.filter(market='SET').aggregate(Max('scan_run'))['scan_run__max']

print(f"Latest Precision Run: {latest_prec_run}")
print(f"Latest Cup & Handle Run: {latest_ch_run}")
print(f"Latest Turtle Run: {latest_turtle_run}")
print("-" * 50)

# Check precision candidates
prec_cands = {}
if latest_prec_run:
    qs = PrecisionScanCandidate.objects.filter(market='SET', scan_run=latest_prec_run, symbol__in=symbols)
    for c in qs:
        prec_cands[c.symbol] = c

# Check cup & handle
ch_symbols = set()
if latest_ch_run:
    ch_symbols = set(CupHandleCandidate.objects.filter(market='SET', scan_run=latest_ch_run, symbol__in=symbols).values_list('symbol', flat=True))

for sym in symbols:
    print(f"STOCK: {sym}")
    cand = prec_cands.get(sym)
    if not cand:
        # Check if symbol exists in any run
        last_any = PrecisionScanCandidate.objects.filter(market='SET', symbol=sym).order_by('-scan_run').first()
        if last_any:
            print(f"  * Warning: Not in the latest scan run. Last seen in scan run {last_any.scan_run} with price {last_any.price}")
        else:
            print(f"  * No scan data found in database for {sym}")
        print("-" * 50)
        continue
    
    # We have candidate data
    print(f"  Current Price: {cand.price}")
    print(f"  RSI: {cand.rsi:.1f} | ADX: {cand.adx:.1f} | RVOL: {cand.rvol:.2f} (Bullish: {cand.rvol_bullish})")
    print(f"  Technical Score: {cand.technical_score}/100 | CMF: {cand.cmf if cand.cmf is not None else 'N/A'}")
    
    # Portfolio classifications
    print(f"  Portfolios:")
    print(f"    - Short-Term: {cand.is_short_term}")
    print(f"    - Medium-Term: {cand.is_medium_term or sym in ch_symbols} (is_medium_term field: {cand.is_medium_term}, in CupHandle: {sym in ch_symbols})")
    print(f"    - Long-Term: {cand.is_long_term}")
    
    # Detailed Medium-Term reasons
    print(f"    [Medium-Term Breakdown]:")
    print(f"      - CAN SLIM: {cand.is_canslim} (Stage2: {cand.stage2}, RS Rating: {cand.rs_rating}, Growth(EPS/Rev): {cand.eps_growth:.1f}%/{cand.rev_growth:.1f}%, CMF/PP: {cand.cmf}/{cand.pocket_pivot})")
    print(f"      - VCP Setup: {cand.vcp_setup}")
    print(f"      - 52w Breakout: {cand.is_52w_breakout} (Year High: {cand.year_high}, Upside to High: {cand.upside_to_high:.1f}%)")
    print(f"      - Cup & Handle: {sym in ch_symbols}")
    
    # Let's import the exit signal logic to see what it is
    try:
        from stocks.views import _compute_signals
        # We need to construct arguments for _compute_signals
        # Let's see what _compute_signals expects
        import inspect
        sig = inspect.signature(_compute_signals)
        print(f"  _compute_signals signature: {sig}")
    except Exception as e:
        print(f"  Could not inspect signature: {e}")
        
    print("-" * 50)
