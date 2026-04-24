import yfinance as yf
import pandas as pd

def analyze_etsy():
    t = yf.Ticker('ETSY')
    
    # 1. Fundamentals
    info = t.info
    print(f"Name: {info.get('longName')}")
    print(f"Sector: {info.get('sector')}")
    print(f"Market Cap: {info.get('marketCap')/1e9:.2f}B USD")
    print(f"Trailing P/E: {info.get('trailingPE')}")
    print(f"Forward P/E: {info.get('forwardPE')}")
    print(f"Revenue Growth (YoY): {info.get('revenueGrowth')}")
    print(f"Profit Margin: {info.get('profitMargins')}")
    
    # 2. Earnings Growth (Crucial for CAN SLIM / Cup & Handle)
    try:
        financials = t.quarterly_financials
        # Get Net Income growth for last few quarters
        net_income = financials.loc['Net Income']
        print("\nQuarterly Net Income (Last 4):")
        for i, val in enumerate(net_income[:4]):
            print(f"Q{i+1}: {val/1e6:.2f}M")
    except:
        print("Could not fetch quarterly income growth")

    # 3. Technicals
    df = t.history(period='1y')
    df['SMA50'] = df['Close'].rolling(50).mean()
    df['SMA200'] = df['Close'].rolling(200).mean()
    
    last = df.iloc[-1]
    print(f"\nCurrent Price: {last['Close']:.2f}")
    print(f"50-Day SMA: {last['SMA50']:.2f}")
    print(f"200-Day SMA: {last['SMA200']:.2f}")
    
    # Check if price is above SMAs
    if last['Close'] > last['SMA50'] and last['Close'] > last['SMA200']:
        print("Trend: Bullish (Price > 50 & 200 SMA)")
    else:
        print("Trend: Neutral/Weak (Price below key SMAs)")

analyze_etsy()
