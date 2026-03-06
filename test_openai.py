import asyncio
import aiohttp
import json

URL = "http://72.60.197.71:18789/v1/chat/completions"
TOKEN = "1d399e69d1c6e697a53a16a37820bcf73a46ae9de244c7d5"

async def test_openai_stream():
    headers = {
        "Authorization": f"Bearer {TOKEN}",
        "Content-Type": "application/json"
    }
    payload = {
        "model": "main", # OpenClaw uses agent ID as model
        "messages": [{"role": "user", "content": "hi"}],
        "stream": True
    }
    
    print(f"Connecting to {URL}...")
    async with aiohttp.ClientSession() as session:
        async with session.post(URL, headers=headers, json=payload) as response:
            print(f"Status: {response.status}")
            if response.status == 200:
                async for line in response.content:
                    line = line.decode('utf-8').strip()
                    if line.startswith("data: "):
                        data_str = line[6:]
                        if data_str == "[DONE]":
                            print("\n[DONE]")
                            break
                        try:
                            data = json.loads(data_str)
                            chunk = data['choices'][0]['delta'].get('content', '')
                            print(chunk, end='', flush=True)
                        except:
                            pass
            else:
                print(await response.text())

if __name__ == "__main__":
    asyncio.run(test_openai_stream())
