import os
import django
import sys
import pandas as pd

sys.path.append(os.path.abspath('.'))
os.environ.setdefault('DJANGO_SETTINGS_MODULE', 'config.settings')
django.setup()

import yfinance as yf
import pandas_ta as ta

def analyze_wha():
    print("Downloading WHA.BK data...")
    ticker = yf.Ticker("WHA.BK")
    df = ticker.history(period="1y")
    if df.empty:
        print("Failed to download WHA.BK data")
        return
        
    current_price = float(df['Close'].iloc[-1])
    
    # Calculate indicators
    df['EMA20'] = ta.ema(df['Close'], length=20)
    df['EMA50'] = ta.ema(df['Close'], length=50)
    df['EMA200'] = ta.ema(df['Close'], length=200)
    df['RSI'] = ta.rsi(df['Close'], length=14)
    df['ATR'] = ta.atr(df['High'], df['Low'], df['Close'], length=14)
    
    # Resistance / 52w High
    high_52w = float(df['High'].tail(252).max())
    low_20d = float(df['Low'].tail(20).min())
    low_10d = float(df['Low'].tail(10).min())
    
    latest = df.iloc[-1]
    atr_val = float(latest['ATR'])
    
    print("\n--- WHA.BK Technical Stats ---")
    print(f"Current Price: {current_price} Baht")
    print(f"52-Week High (Ultimate Resistance): {high_52w} Baht")
    print(f"EMA20: {latest['EMA20']:.2f} Baht")
    print(f"EMA50: {latest['EMA50']:.2f} Baht")
    print(f"EMA200: {latest['EMA200']:.2f} Baht")
    print(f"RSI (14): {latest['RSI']:.1f}")
    print(f"ATR (14): {atr_val:.3f} Baht")
    print(f"10-Day Low (Turtle S1 Exit): {low_10d:.2f} Baht")
    print(f"20-Day Low (Turtle S2 Exit): {low_20d:.2f} Baht")
    
    # Base Depth Calculation
    # Let's find the low of the consolidation base in the last 3-4 months
    recent_low = float(df['Low'].tail(90).min())
    base_depth = high_52w - recent_low
    projected_target = high_52w + base_depth
    print(f"Consolidation Base Low (90d): {recent_low} Baht")
    print(f"Consolidation Base Depth: {base_depth:.2f} Baht")
    print(f"Projected Breakout Target (Base Depth projection): {projected_target:.2f} Baht")

if __name__ == "__main__":
    analyze_wha()
