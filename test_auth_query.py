import asyncio
import websockets
import json

TOKEN = "1d399e69d1c6e697a53a16a37820bcf73a46ae9de244c7d5"

async def test_auth_query():
    url = f"ws://72.60.197.71:18789/?auth={TOKEN}"
    print(f"Testing ?auth=: {url}")
    try:
        async with websockets.connect(url) as ws:
            print("Connected.")
            # Don't send any immediate frame, just wait
            async for msg in ws:
                print(f"MSG: {msg}")
                if "challenge" in msg:
                    # Try to respond with a connect frame that doesn't have params
                    await ws.send(json.dumps({"type": "connect", "token": TOKEN}))
                if "success" in msg:
                    break
    except Exception as e:
        print(f"Auth query failed: {str(e)}")

if __name__ == "__main__":
    asyncio.run(test_auth_query())
