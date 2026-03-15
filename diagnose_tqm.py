import yfinance as yf
import pandas as pd
import pandas_ta as ta
import os
import django

# Setup Django environment
os.environ.setdefault('DJANGO_SETTINGS_MODULE', 'config.settings')
django.setup()

def scale_to_percent(val):
    if not isinstance(val, (int, float)): return val
    if abs(val) < 1.0:
        return val * 100
    return val

def check_stock(sym):
    print(f"Checking {sym}...")
    try:
        t = yf.Ticker(sym)
        inf = t.info
        hist_short = t.history(period="6mo")
        rsi_val = 'N/A'
        rvol = 1.0
        if not hist_short.empty:
            rsi_series = ta.rsi(hist_short['Close'], length=14)
            if rsi_series is not None and not rsi_series.empty:
                rsi_val = float(rsi_series.iloc[-1])
            current_vol = float(hist_short['Volume'].iloc[-1])
            avg_vol_20 = float(hist_short['Volume'].tail(20).mean())
            rvol = current_vol / avg_vol_20 if avg_vol_20 > 0 else 1.0

        # Quality
        de = inf.get('debtToEquity', 'N/A')
        roe = scale_to_percent(inf.get('returnOnEquity'))
        
        # Value
        pe = inf.get('trailingPE')
        pb = inf.get('priceToBook')
        peg = inf.get('pegRatio')
        dy = scale_to_percent(inf.get('dividendYield'))
        
        print(f"Metrics: PE={pe}, PB={pb}, ROE={roe}, DY={dy}, DE={de}, RSI={rsi_val}")

        # Scoring Logic
        pillar_scores = [0, 0, 0]
        # Quality
        q_metrics = 0
        if isinstance(roe, (int, float)):
            if roe > 15: pillar_scores[0] += 50
            elif roe > 10: pillar_scores[0] += 30
            q_metrics += 1
        if isinstance(de, (int, float)):
            de_scaled = de / 100 if de > 5 else de # yfinance quirk
            if de_scaled < 1.0: pillar_scores[0] += 50
            elif de_scaled < 1.5: pillar_scores[0] += 30
            q_metrics += 1
        if q_metrics == 1: pillar_scores[0] *= 2

        # Value
        v_metrics = 0
        if isinstance(pe, (int, float)):
            if pe < 15: pillar_scores[1] += 25
            elif pe < 25: pillar_scores[1] += 15
            v_metrics += 1
        if isinstance(pb, (int, float)):
            if pb < 1.5: pillar_scores[1] += 25
            elif pb < 2.0: pillar_scores[1] += 15
            v_metrics += 1
        if isinstance(dy, (int, float)):
            if dy >= 3.0: pillar_scores[1] += 25
            elif dy >= 1.0: pillar_scores[1] += 15
            v_metrics += 1
        if isinstance(peg, (int, float)):
            if peg < 1.0: pillar_scores[1] += 25
            elif peg < 1.5: pillar_scores[1] += 15
            v_metrics += 1
        if 0 < v_metrics < 4: pillar_scores[1] = (pillar_scores[1] / v_metrics) * 4

        # Timing
        if isinstance(rsi_val, (int, float)):
            if 30 <= rsi_val <= 45: pillar_scores[2] += 60
            elif 45 < rsi_val <= 60: pillar_scores[2] += 40
        if rvol > 1.5: pillar_scores[2] += 40
        elif rvol > 1.0: pillar_scores[2] += 20

        final_score = (pillar_scores[0] * 0.40) + (pillar_scores[1] * 0.40) + (pillar_scores[2] * 0.20)
        print(f"Scores: Quality={pillar_scores[0]}, Value={pillar_scores[1]}, Timing={pillar_scores[2]}")
        print(f"Final Score: {final_score}")

    except Exception as e:
        print(f"Error: {e}")

if __name__ == "__main__":
    check_stock("TQM.BK")
