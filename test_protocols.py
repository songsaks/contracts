import asyncio
import websockets
import json

TOKEN = "1d399e69d1c6e697a53a16a37820bcf73a46ae9de244c7d5"
URL = "ws://72.60.197.71:18789/"

async def test_subprotocol():
    print(f"Testing subprotocol with token...")
    try:
        # Some OpenClaw versions use 'token-<token>' as a subprotocol
        async with websockets.connect(URL, subprotocols=[f"token-{TOKEN}"]) as ws:
            print(f"Connected with subprotocol: {ws.subprotocol}")
            
            # Send ping or connect
            await ws.send(json.dumps({"type": "connect"}))
            
            async for msg in ws:
                print(f"MSG: {msg}")
                if "success" in msg:
                    break
    except Exception as e:
        print(f"Subprotocol failed: {str(e)}")

async def test_headers():
    print(f"\nTesting additional_headers...")
    headers = {"Authorization": f"Bearer {TOKEN}"}
    try:
        async with websockets.connect(URL, additional_headers=headers) as ws:
            print("Connected with headers.")
            # Send immediate connect frame
            await ws.send(json.dumps({"type": "connect", "params": {"auth": {"token": TOKEN}}}))
            
            async for msg in ws:
                print(f"MSG: {msg}")
                if "challenge" in msg:
                    print("Received challenge. Handshake still required.")
                if "success" in msg:
                    print("SUCCESS!")
                    break
    except Exception as e:
        print(f"Headers failed: {str(e)}")

async def main():
    await test_subprotocol()
    await test_headers()

if __name__ == "__main__":
    asyncio.run(main())
