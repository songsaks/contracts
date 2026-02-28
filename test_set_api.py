import requests

def test_set_api():
    # Newer SET API endpoint
    url = "https://www.set.or.th/api/set/index/set100/constituents?lang=th"
    headers = {
        "User-Agent": "Mozilla/5.0 (Windows NT 10.0; Win64; x64) AppleWebKit/537.36 (KHTML, like Gecko) Chrome/91.0.4472.124 Safari/537.36",
        "Referer": "https://www.set.or.th/th/market/index/set100/overview"
    }
    try:
        response = requests.get(url, headers=headers, timeout=10)
        print(f"Status: {response.status_code}")
        if response.status_code == 200:
            data = response.json()
            # print(data)
            # The structure might be {'constituents': [{'symbol': '...', ...}, ...]}
            symbols = [item['symbol'] for item in data.get('constituents', [])]
            return symbols
    except Exception as e:
        print(f"Error: {e}")
    return []

if __name__ == "__main__":
    symbols = test_set_api()
    print(f"Found {len(symbols)} symbols")
    print(symbols[:10])
