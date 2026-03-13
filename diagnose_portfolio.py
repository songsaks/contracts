
import os
import sys
import django
import pandas as pd
import yfinance as yf
import pandas_ta as ta

# Setup Django
os.environ.setdefault('DJANGO_SETTINGS_MODULE', 'config.settings')
sys.path.insert(0, r'd:\DjangoProjects\contracts')
django.setup()

from django.contrib.auth.models import User
from stocks.models import Portfolio, MomentumCandidate
from stocks.utils import calculate_trailing_stop, analyze_momentum_technical

user = User.objects.get(username='songsak')
portfolio_items = Portfolio.objects.filter(user=user)

print(f"Total items for songsak: {portfolio_items.count()}")

for item in portfolio_items:
    print(f"\n--- Testing {item.symbol} ---")
    try:
        t = yf.Ticker(item.symbol)
        hist = t.history(period="1y")
        
        if hist.empty:
            alt_sym = f"{item.symbol}.BK" if ".BK" not in item.symbol else item.symbol.replace(".BK", "")
            print(f"  Hist empty, trying {alt_sym}...")
            t = yf.Ticker(alt_sym)
            hist = t.history(period="1y")

        if hist.empty:
            print(f"  FAILED: No data found for {item.symbol}")
            continue
            
        if isinstance(hist.columns, pd.MultiIndex):
            hist.columns = [col[0] if isinstance(col, tuple) else col for col in hist.columns]
        hist = hist.loc[:, ~hist.columns.duplicated()]
        
        current_price = float(hist['Close'].iloc[-1])
        print(f"  Current Price from hist: {current_price}")
        
        rsi_series = ta.rsi(hist['Close'], length=14)
        rsi_val = rsi_series.iloc[-1] if (rsi_series is not None and not rsi_series.empty) else None
        print(f"  RSI: {rsi_val}")
        
        tech_analysis = analyze_momentum_technical(hist)
        print(f"  Tech Score: {tech_analysis['score'] if tech_analysis else 'N/A'}")
        
    except Exception as e:
        import traceback
        print(f"  ERROR for {item.symbol}: {e}")
        traceback.print_exc()

print("\n--- End of Test ---")
