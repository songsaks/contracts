import requests
from bs4 import BeautifulSoup

def get_set100_symbols():
    url = "https://classic.set.or.th/mkt/sectorquotation.do?sector=SET100&language=th&country=TH"
    try:
        response = requests.get(url, timeout=10)
        if response.status_code == 200:
            soup = BeautifulSoup(response.text, 'html.parser')
            # The symbols are usually in <a> tags within a specific <td> or table
            symbols = []
            for a in soup.find_all('a', href=True):
                if 'stockquotation.do?symbol=' in a['href']:
                    symbol = a.text.strip()
                    if symbol and symbol not in symbols:
                        symbols.append(symbol)
            return symbols
    except Exception as e:
        print(f"Error: {e}")
    return []

if __name__ == "__main__":
    symbols = get_set100_symbols()
    print(f"Found {len(symbols)} symbols")
    print(symbols[:10])
