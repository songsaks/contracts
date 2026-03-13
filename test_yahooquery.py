
import os
import sys
import pandas as pd
from yahooquery import Ticker

symbol = 'ICHI.BK'
print(f"Testing {symbol} with yahooquery...")

t = Ticker(symbol)
hist = t.history(period='1y')

if isinstance(hist, pd.DataFrame):
     print(f"Hist shape: {hist.shape}")
     if not hist.empty:
         # yahooquery hist usually has MultiIndex (symbol, date)
         if 'adjclose' in hist.columns:
             price = hist['adjclose'].iloc[-1]
             print(f"Latest adjclose: {price}")
         elif 'close' in hist.columns:
             price = hist['close'].iloc[-1]
             print(f"Latest close: {price}")
else:
     print(f"Hist is not a DataFrame: {type(hist)}")
     print(hist)

print("\n--- Done ---")
