import yfinance as yf
import pandas as pd

symbols = ['^GSPC', '^IXIC', 'BTC-USD', 'ETH-USD', 'GC=F']
for sym in symbols:
    try:
        t = yf.Ticker(sym)
        price = t.fast_info.last_price
        print(f"{sym}: {price}")
    except:
        print(f"Failed {sym}")
