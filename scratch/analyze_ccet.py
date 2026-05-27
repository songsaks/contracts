import os
import django
import sys
import pandas as pd
import numpy as np

sys.path.append(os.path.abspath('.'))
os.environ.setdefault('DJANGO_SETTINGS_MODULE', 'config.settings')
django.setup()

import yfinance as yf
import pandas_ta as ta
from stocks.utils import analyze_momentum_technical_v2

def analyze_ccet():
    print("Downloading CCET.BK data...")
    ticker = yf.Ticker("CCET.BK")
    df = ticker.history(period="1y")
    if df.empty:
        print("Failed to download CCET.BK data")
        return
        
    print(f"Downloaded {len(df)} rows of data.")
    
    # Calculate indicators like in analyze_momentum_technical_v2
    df['EMA200'] = ta.ema(df['Close'], length=200)
    df['EMA50']  = ta.ema(df['Close'], length=50)
    df['EMA20']  = ta.ema(df['Close'], length=20)
    df['RSI']    = ta.rsi(df['Close'], length=14)
    
    # RVOL
    df['Avg_Vol_20'] = df['Volume'].rolling(window=20).mean()
    df['RVOL'] = df['Volume'] / df['Avg_Vol_20']
    
    # Turtle Distance (Distance to 20-day High)
    df['High_20'] = df['High'].rolling(window=20).max()
    df['Turtle_Dist'] = ((df['High_20'] - df['Close']) / df['Close'] * 100)
    
    # CMF
    cmf_vals = []
    for i in range(len(df)):
        if i < 20:
            cmf_vals.append(np.nan)
            continue
        sub_df = df.iloc[i-19:i+1]
        hi = sub_df['High']
        lo = sub_df['Low']
        cl = sub_df['Close']
        vo = sub_df['Volume'].astype(float)
        rng = (hi - lo).replace(0, float('nan'))
        mfv = ((cl - lo) - (hi - cl)) / rng * vo
        sum_vol = vo.sum()
        if sum_vol > 0:
            cmf_vals.append(mfv.sum() / sum_vol)
        else:
            cmf_vals.append(0.0)
    df['CMF'] = cmf_vals

    # Identify setups
    df['EMA_Aligned'] = (df['Close'] > df['EMA20']) & (df['EMA20'] > df['EMA50']) & (df['EMA50'] > df['EMA200'])
    
    # Let's print out the latest 40 trading days of CCET to see its current state
    print("\n--- Latest 40 trading days for CCET ---")
    print(f"{'Date':<12} | {'Close':<6} | {'EMA20':<6} | {'EMA50':<6} | {'EMA200':<6} | {'EMA_Align':<9} | {'RVOL':<5} | {'TurtleDist':<10} | {'CMF':<6}")
    print("-" * 90)
    
    latest_40 = df.tail(40)
    for idx, row in latest_40.iterrows():
        date_str = idx.strftime('%Y-%m-%d')
        ema_align_str = "YES" if row['EMA_Aligned'] else "NO"
        print(f"{date_str:<12} | {row['Close']:<6.2f} | {row['EMA20']:<6.2f} | {row['EMA50']:<6.2f} | {row['EMA200']:<6.2f} | {ema_align_str:<9} | {row['RVOL']:<5.2f} | {row['Turtle_Dist']:<10.2f} | {row['CMF']:<6.2f}")

    # Let's find dates where CCET broke out (e.g. price went up significantly or had big volume)
    print("\n--- CCET Big Move Days (Close Change > 5% or RVOL > 2.0) ---")
    df['Prev_Close'] = df['Close'].shift(1)
    df['Pct_Change'] = (df['Close'] - df['Prev_Close']) / df['Prev_Close'] * 100
    big_moves = df[(df['Pct_Change'] > 5.0) | (df['RVOL'] > 2.0)].tail(20)
    print(f"{'Date':<12} | {'Close':<6} | {'% Change':<8} | {'RVOL':<5} | {'EMA_Align':<9} | {'TurtleDist':<10} | {'CMF':<6}")
    print("-" * 75)
    for idx, row in big_moves.iterrows():
        date_str = idx.strftime('%Y-%m-%d')
        ema_align_str = "YES" if row['EMA_Aligned'] else "NO"
        print(f"{date_str:<12} | {row['Close']:<6.2f} | {row['Pct_Change']:<+8.1f}% | {row['RVOL']:<5.2f} | {ema_align_str:<9} | {row['Turtle_Dist']:<10.2f} | {row['CMF']:<6.2f}")

if __name__ == "__main__":
    analyze_ccet()
