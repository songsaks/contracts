import yfinance as yf
import pandas as pd

def compare_vcp_top(symbols):
    results = []
    for sym in symbols:
        t = yf.Ticker(sym)
        info = t.info
        
        # Financials
        eps_growth = info.get('earningsQuarterlyGrowth')
        rev_growth = info.get('revenueGrowth')
        forward_pe = info.get('forwardPE')
        
        # Technicals (SMA check)
        df = t.history(period='1y')
        df['SMA50'] = df['Close'].rolling(50).mean()
        df['SMA200'] = df['Close'].rolling(200).mean()
        last = df.iloc[-1]
        
        results.append({
            'Symbol': sym,
            'Name': info.get('longName'),
            'EPS Growth': f"{eps_growth*100:.1f}%" if eps_growth else "N/A",
            'Rev Growth': f"{rev_growth*100:.1f}%" if rev_growth else "N/A",
            'Forward P/E': forward_pe,
            'Above SMA200': last['Close'] > last['SMA200'],
            'Price': round(last['Close'], 2)
        })
    
    return pd.DataFrame(results)

print(compare_vcp_top(['SLB', 'FDX']))
