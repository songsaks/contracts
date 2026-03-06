import asyncio
import websockets
import json

TOKEN = "1d399e69d1c6e697a53a16a37820bcf73a46ae9de244c7d5"
URL = "ws://72.60.197.71:18789/"

async def test_flat_token():
    print(f"Testing flat token...")
    try:
        async with websockets.connect(URL) as ws:
            print("Connected.")
            # Send immediate connect with flat token
            payload = {"type": "connect", "params": {"token": TOKEN}}
            print(f"Sending: {payload}")
            await ws.send(json.dumps(payload))
            
            async for msg in ws:
                print(f"MSG: {msg}")
                if "success" in msg:
                    print("SUCCESS!")
                    break
    except Exception as e:
        print(f"Flat token failed: {str(e)}")

async def test_root_token():
    print(f"\nTesting root token...")
    try:
        async with websockets.connect(URL) as ws:
            print("Connected.")
            # Send immediate connect with root token
            payload = {"type": "connect", "token": TOKEN}
            print(f"Sending: {payload}")
            await ws.send(json.dumps(payload))
            
            async for msg in ws:
                print(f"MSG: {msg}")
                if "success" in msg:
                    print("SUCCESS!")
                    break
    except Exception as e:
        print(f"Root token failed: {str(e)}")

async def main():
    await test_flat_token()
    await test_root_token()

if __name__ == "__main__":
    asyncio.run(main())
