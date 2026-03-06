import asyncio
import websockets
import json

TOKEN = "1d399e69d1c6e697a53a16a37820bcf73a46ae9de244c7d5"

async def test_query_param():
    url = f"ws://72.60.197.71:18789/?token={TOKEN}"
    print(f"Testing query param: {url}")
    try:
        async with websockets.connect(url) as ws:
            print("Connected.")
            # Send immediate connect
            await ws.send(json.dumps({"type": "connect"}))
            async for msg in ws:
                print(f"MSG: {msg}")
                if "success" in msg:
                    print("SUCCESS!")
                    break
    except Exception as e:
        print(f"Query param failed: {str(e)}")

if __name__ == "__main__":
    asyncio.run(test_query_param())
