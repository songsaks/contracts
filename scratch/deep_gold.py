import yfinance as yf
import pandas_ta as ta

def deep_analyze_gold():
    df = yf.download('GC=F', period='6mo', auto_adjust=True)
    # Simplify columns if multi-index
    if isinstance(df.columns, pd.MultiIndex):
        df.columns = df.columns.get_level_values(0)
    
    df['RSI'] = ta.rsi(df['Close'], length=14)
    df['EMA200'] = ta.ema(df['Close'], length=200)
    
    last = df.iloc[-1]
    print(f"Current Price: {float(last['Close']):.2f}")
    print(f"RSI: {float(last['RSI']):.2f}")
    print(f"EMA200: {float(last['EMA200']):.2f}")
    
import pandas as pd
deep_analyze_gold()
