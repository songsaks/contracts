import asyncio
import websockets
import json

TOKEN = "1d399e69d1c6e697a53a16a37820bcf73a46ae9de244c7d5"
URL = "ws://72.60.197.71:18789/"

async def test_role():
    headers = {"Authorization": f"Bearer {TOKEN}"}
    try:
        async with websockets.connect(URL, additional_headers=headers) as ws:
            async for msg in ws:
                data = json.loads(msg)
                if data.get("event") == "connect.challenge":
                    nonce = data["payload"]["nonce"]
                    payload = {
                        "type": "connect",
                        "params": {
                            "auth": {"token": TOKEN},
                            "role": "operator",
                            "nonce": nonce,
                            "deviceId": "operator-node"
                        }
                    }
                    print(f"Sending operator role connect: {payload}")
                    await ws.send(json.dumps(payload))
                elif "success" in msg:
                    print(f"SUCCESS: {msg}")
                    break
    except Exception as e:
        print(f"Role failed: {str(e)}")

if __name__ == "__main__":
    asyncio.run(test_role())
