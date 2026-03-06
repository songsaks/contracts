import asyncio
import websockets
import json

TOKEN = "1d399e69d1c6e697a53a16a37820bcf73a46ae9de244c7d5"
URL = "ws://72.60.197.71:18789/"

async def test_rpc_sub():
    print(f"Testing subprotocol 'rpc'...")
    headers = {"Authorization": f"Bearer {TOKEN}"}
    try:
        async with websockets.connect(URL, subprotocols=["rpc"], additional_headers=headers) as ws:
            print(f"Connected. Sub: {ws.subprotocol}")
            # Try to send a simple auth message if requested
            async for msg in ws:
                print(f"MSG: {msg}")
                if "challenge" in msg:
                    # In RPC mode, can we send auth?
                    auth_msg = {"type": "gateway:auth", "params": {"token": TOKEN}}
                    print(f"Sending: {auth_msg}")
                    await ws.send(json.dumps(auth_msg))
    except Exception as e:
        print(f"RPC Sub failed: {str(e)}")

if __name__ == "__main__":
    asyncio.run(test_rpc_sub())
