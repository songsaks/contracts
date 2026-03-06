import asyncio
import websockets
import json

TOKEN = "1d399e69d1c6e697a53a16a37820bcf73a46ae9de244c7d5"
URL = "ws://72.60.197.71:18789/v1/chat/completions"

async def test_ws_openai():
    headers = {"Authorization": f"Bearer {TOKEN}"}
    print(f"Testing WS on OpenAI path: {URL}")
    try:
        async with websockets.connect(URL, additional_headers=headers) as ws:
            print("Connected.")
            # Send OpenAI payload
            payload = {
                "model": "main",
                "messages": [{"role": "user", "content": "hi"}],
                "stream": True
            }
            await ws.send(json.dumps(payload))
            async for msg in ws:
                print(f"MSG: {msg}")
    except Exception as e:
        print(f"WS OpenAI failed: {str(e)}")

if __name__ == "__main__":
    asyncio.run(test_ws_openai())
