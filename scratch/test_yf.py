import yfinance as yf
import pandas as pd

symbols = ["PTT.BK", "CPALL.BK", "AOT.BK"]
try:
    data = yf.download(symbols, period="1y", interval="1d", progress=False, group_by='ticker')
    print(f"Data received: {not data.empty}")
    for s in symbols:
        if s in data:
            print(f"{s}: {len(data[s])} rows")
        else:
            print(f"{s} not in data")
except Exception as e:
    print(f"Error: {e}")
