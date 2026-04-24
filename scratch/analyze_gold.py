import yfinance as yf
import pandas as pd
import numpy as np

def analyze_gold():
    t = yf.Ticker('GC=F')
    df = t.history(period='1y')
    if df.empty:
        print("No data")
        return

    # Donchian Channels
    df['dc20_upper'] = df['High'].rolling(20).max()
    df['dc55_upper'] = df['High'].rolling(55).max()
    df['dc20_lower'] = df['Low'].rolling(20).min()
    
    last = df.iloc[-1]
    prev = df.iloc[-2]
    
    print(f"Current Price: {last['Close']:.2f}")
    print(f"DC20 Upper (20D High): {prev['dc20_upper']:.2f}")
    print(f"DC55 Upper (55D High): {prev['dc55_upper']:.2f}")
    print(f"DC20 Lower (20D Low): {prev['dc20_lower']:.2f}")
    
    if last['Close'] >= prev['dc20_upper']:
        print("Status: Breakout System 1 (20D) detected!")
    elif last['Close'] >= prev['dc55_upper']:
        print("Status: Breakout System 2 (55D) detected!")
    else:
        dist_s1 = ((prev['dc20_upper'] - last['Close']) / last['Close']) * 100
        print(f"Status: Waiting for Breakout. Dist to S1: {dist_s1:.2f}%")

analyze_gold()
