import asyncio
import websockets
import json

TOKEN = "1d399e69d1c6e697a53a16a37820bcf73a46ae9de244c7d5"
URL = "ws://72.60.197.71:18789/"

async def test_operator():
    headers = {"Authorization": f"Bearer {TOKEN}"}
    try:
        async with websockets.connect(URL, additional_headers=headers) as ws:
            # Wait for challenge
            async for msg in ws:
                data = json.loads(msg)
                if data.get("event") == "connect.challenge":
                    nonce = data["payload"]["nonce"]
                    # Try operator connect
                    payload = {
                        "type": "connect",
                        "params": {
                            "auth": {"token": TOKEN},
                            "deviceId": "operator",
                            "nonce": nonce
                        }
                    }
                    print(f"Sending operator connect: {payload}")
                    await ws.send(json.dumps(payload))
                elif "success" in msg:
                    print(f"SUCCESS: {msg}")
                    break
    except Exception as e:
        print(f"Operator failed: {str(e)}")

if __name__ == "__main__":
    asyncio.run(test_operator())
