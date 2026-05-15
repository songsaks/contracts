import yfinance as yf
import pandas as pd

def check_data():
    symbols = ["^SET", "TDEX.BK", "SET50.BK"]
    for symbol in symbols:
        print(f"Checking data for {symbol}...")
        try:
            t = yf.Ticker(symbol)
            df = t.history(period="100d")
            if df is None or df.empty:
                print(f"{symbol}: Data is EMPTY")
            else:
                print(f"{symbol}: Data found: {len(df)} rows")
        except Exception as e:
            print(f"{symbol}: Error: {e}")

if __name__ == "__main__":
    check_data()
