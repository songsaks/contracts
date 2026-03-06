import requests
import json

def test_openclaw():
    openclaw_url = 'http://72.60.197.71:18789/v1/chat/completions'
    headers = {
        'Authorization': 'Bearer 1d399e69d1c6e697a53a16a37820bcf73a46ae9de244c7d5',
        'Content-Type': 'application/json'
    }
    payload = {
        "model": "google/gemini-2.0-flash",
        "messages": [{"role": "user", "content": "Hello"}]
    }

    try:
        print(f"Testing URL: {openclaw_url}")
        response = requests.post(openclaw_url, headers=headers, json=payload, timeout=10)
        print(f"Status Code: {response.status_code}")
        print(f"Headers: {response.headers}")
        print(f"Text Preview: {response.text[:200]}")
        try:
            print(f"JSON: {response.json()}")
        except:
            print("Failed to parse JSON")
    except Exception as e:
        print(f"Error: {e}")

if __name__ == "__main__":
    test_openclaw()
