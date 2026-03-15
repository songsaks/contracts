import yfinance as yf
ticker = yf.Ticker("CPALL.BK")
info = ticker.info
print(f"Current Assets: {info.get('totalCurrentAssets')}")
print(f"Total Liabilities: {info.get('totalLiabilities')}")
print(f"Market Cap: {info.get('marketCap')}")
print(f"Free Cash Flow: {info.get('freeCashflow')}")
print(f"EBITDA: {info.get('ebitda')}")
print(f"Enterprise Value: {info.get('enterpriseValue')}")
print(f"PEG Ratio: {info.get('pegRatio')}")
print(f"EPS Growth: {info.get('earningsGrowth')}")
print(f"Earnings Yield: {info.get('ebitda') / info.get('enterpriseValue') if info.get('enterpriseValue') else 'N/A'}")
