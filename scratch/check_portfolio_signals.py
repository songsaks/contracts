import os
import sys
import django

# Set up Django environment
sys.path.append(os.path.dirname(os.path.dirname(os.path.abspath(__file__))))
os.environ.setdefault('DJANGO_SETTINGS_MODULE', 'config.settings')
django.setup()

from stocks.models import PrecisionScanCandidate, CupHandleCandidate
from django.db.models import Max
from stocks.views import _compute_signals

symbols = ["BLA", "DELTA", "EPG", "SCGP", "STGT", "TCAP", "WHAUP"]

# Find latest runs
latest_prec_run = PrecisionScanCandidate.objects.filter(market='SET').aggregate(Max('scan_run'))['scan_run__max']
latest_ch_run = CupHandleCandidate.objects.filter(market='SET').aggregate(Max('scan_run'))['scan_run__max']

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

print("=== PORTFOLIO ANALYSIS & EXIT SIGNALS ===")
print(f"Latest Scan Run: {latest_prec_run}")
print("-" * 60)

for sym in symbols:
    cand = prec_cands.get(sym)
    if not cand:
        print(f"STOCK: {sym} - NO CURRENT DATA IN SCANNER")
        print("-" * 60)
        continue
    
    # Compute signals
    sig_result = _compute_signals(cand, current_price=cand.price)
    
    print(f"STOCK: {sym} (Price: {cand.price})")
    
    # Signals
    exit_sig = sig_result.get('exit_signal')
    rev_alert = sig_result.get('reversal_alert')
    rev_reasons = sig_result.get('reversal_reasons')
    stage = sig_result.get('stage_label')
    sell_sc = sig_result.get('sell_score')
    
    status_str = "OK (HOLD) ✅"
    if exit_sig == 'STRONG EXIT':
        status_str = "🚨 STRONG EXIT! (SELL NOW)"
    elif exit_sig == 'EXIT':
        status_str = "⚠️ EXIT (SELL/TAKE PROFIT)"
    elif exit_sig == 'WATCH':
        status_str = "👁 WATCH (CAUTION)"
        
    print(f"  Action Status: {status_str}")
    print(f"  Sell Score: {sell_sc}/100 | Exit Signal: '{exit_sig}'")
    print(f"  Stage: {stage}")
    print(f"  Reversal Alert: {rev_alert or 'None'} (Score: {sig_result.get('reversal_score')}/5)")
    if rev_reasons:
        print(f"  Reversal Reasons: {', '.join(rev_reasons)}")
    
    # Check is_medium_term
    is_medium = cand.is_medium_term or sym in ch_symbols
    print(f"  Still in Medium-Term Scanner List: {is_medium}")
    
    # Why is it or isn't it in Medium-Term?
    reasons = []
    if cand.is_canslim: reasons.append("CAN SLIM")
    if cand.vcp_setup: reasons.append("VCP Setup")
    if cand.is_52w_breakout: reasons.append("52w Breakout")
    if sym in ch_symbols: reasons.append("Cup & Handle")
    
    if is_medium:
        print(f"    - Reasons: {', '.join(reasons)}")
    else:
        print(f"    - Reasons: None of the criteria are met.")
        
    print("-" * 60)
