import yfinance as yf
ticker = yf.Ticker("ROJNA.BK")
print(f"Dividend Yield: {ticker.info.get('dividendYield')}")
print(f"ROE: {ticker.info.get('returnOnEquity')}")
print(f"Book Value: {ticker.info.get('bookValue')}")
print(f"P/E: {ticker.info.get('trailingPE')}")
print(f"P/BV: {ticker.info.get('priceToBook')}")
