import yfinance as yf

for sym in ['WHA.BK', 'WHAUP.BK']:
    ticker = yf.Ticker(sym)
    
    # Method 1: history
    hist = ticker.history(period='5d')
    close_price = hist['Close'].iloc[-1] if not hist.empty else None
    
    # Method 2: fast_info
    try:
        fast_price = ticker.fast_info.last_price
    except Exception as e:
        fast_price = f"Error: {e}"
        
    print(f"Symbol: {sym}")
    print(f"  history Close: {close_price}")
    print(f"  fast_info last_price: {fast_price}")
    print("-" * 30)
