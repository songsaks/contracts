import os
import django
os.environ.setdefault('DJANGO_SETTINGS_MODULE', 'contracts.settings')
django.setup()

from stocks.views import _process_precision_scan

res = _process_precision_scan('RBF')
if res:
    import json
    print(json.dumps({
        'symbol': res.symbol,
        'buy_score': res.buy_score,
        'rs_rating': res.rs_rating,
        'adx': res.adx_14,
        'rsi': res.rsi_14_val,
        'rvol': res.rvol,
        'rr': res.risk_reward_ratio,
        'reasons': res.top_reasons
    }, indent=2, ensure_ascii=False))
else:
    print("RBF returned None")
