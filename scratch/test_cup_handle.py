import os
import sys
import django
import pandas as pd
import yfinance as yf
from datetime import datetime, timedelta

# Add current directory to path
sys.path.append(os.getcwd())

os.environ.setdefault('DJANGO_SETTINGS_MODULE', 'config.settings')
django.setup()

from stocks.utils import detect_cup_and_handle

symbols = ['KCE.BK', 'HANA.BK', 'DELTA.BK', 'GLOBAL.BK', 'JMT.BK']
end_date = datetime.now()
start_date = end_date - timedelta(days=600)

for sym in symbols:
    print(f"Testing {sym}...")
    try:
        df = yf.download(sym, start=start_date, end=end_date, progress=False)
        if df.empty:
            print(f"  No data for {sym}")
            continue
        
        # Flatten MultiIndex if yfinance > 0.2.0
        if isinstance(df.columns, pd.MultiIndex):
            df.columns = df.columns.droplevel(1)
            
        res = detect_cup_and_handle(df)
        if res:
            print(f"  Found pattern: {res['stage']} (Conf: {res['confidence_score']})")
        else:
            print(f"  No pattern found.")
    except Exception as e:
        print(f"  Error testing {sym}: {e}")
