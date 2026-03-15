import yfinance as yf
ticker = yf.Ticker("CPALL.BK")
print("Balance Sheet:")
print(ticker.balance_sheet)
print("\nCashflow:")
print(ticker.cashflow)
