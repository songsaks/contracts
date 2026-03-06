import asyncio
import websockets
import json

TOKEN = "1d399e69d1c6e697a53a16a37820bcf73a46ae9de244c7d5"
URL = "ws://72.60.197.71:18789/"

async def test_ignore():
    headers = {"Authorization": f"Bearer {TOKEN}"}
    print("Connecting...")
    try:
        async with websockets.connect(URL, additional_headers=headers) as ws:
            print("Connected. Ignoring challenge if any.")
            
            run_cmd = {
                "type": "agent:run",
                "params": {
                    "agentId": "main",
                    "input": "hi",
                    "stream": True,
                    "sessionId": "test-session"
                }
            }
            print(f"Sending run command immediately: {run_cmd}")
            await ws.send(json.dumps(run_cmd))
            
            async for msg in ws:
                print(f"MSG: {msg}")
                if "output" in msg:
                    print("IT WORKS!")
                    break
    except Exception as e:
        print(f"Ignore failed: {str(e)}")

if __name__ == "__main__":
    asyncio.run(test_ignore())
