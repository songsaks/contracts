import asyncio
import websockets
import json

TOKEN = "1d399e69d1c6e697a53a16a37820bcf73a46ae9de244c7d5"
URL = "ws://72.60.197.71:18789/"

async def test_id():
    headers = {"Authorization": f"Bearer {TOKEN}"}
    try:
        async with websockets.connect(URL, additional_headers=headers) as ws:
            async for msg in ws:
                data = json.loads(msg)
                if data.get("event") == "connect.challenge":
                    nonce = data["payload"]["nonce"]
                    # Add 'id' field
                    payload = {
                        "type": "connect",
                        "id": "1",
                        "params": {
                            "auth": {"token": TOKEN},
                            "nonce": nonce
                        }
                    }
                    print(f"Sending connect with id: {payload}")
                    await ws.send(json.dumps(payload))
                elif "success" in msg:
                    print(f"SUCCESS: {msg}")
                    break
    except Exception as e:
        print(f"ID failed: {str(e)}")

if __name__ == "__main__":
    asyncio.run(test_id())
