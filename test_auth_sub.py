import asyncio
import websockets
import json

TOKEN = "1d399e69d1c6e697a53a16a37820bcf73a46ae9de244c7d5"
URL = "ws://72.60.197.71:18789/"

async def test_auth_sub():
    print(f"Testing subprotocol 'auth-<token>'...")
    try:
        # dashboard uses 'auth-<token>' often or just tokens?
        # let's try 'auth-<token>'
        async with websockets.connect(URL, subprotocols=[f"auth-{TOKEN}"]) as ws:
            print(f"Connected. Sub: {ws.subprotocol}")
            async for msg in ws:
                print(f"MSG: {msg}")
                if "challenge" in msg:
                    # respond simple
                    await ws.send(json.dumps({"type": "connect", "params": {"auth": {"token": TOKEN}}}))
    except Exception as e:
        print(f"Auth Sub failed: {str(e)}")

if __name__ == "__main__":
    asyncio.run(test_auth_sub())
