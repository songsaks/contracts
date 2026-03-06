import asyncio
import json
import logging
import aiohttp

logging.basicConfig(level=logging.INFO)
logger = logging.getLogger("TestOperatorDirect")

TOKEN = "1d399e69d1c6e697a53a16a37820bcf73a46ae9de244c7d5"
URL = "ws://72.60.197.71:18789/"

async def test_operator_direct():
    headers = {"Authorization": f"Bearer {TOKEN}"}
    async with aiohttp.ClientSession(headers=headers) as session:
        async with session.ws_connect(URL) as ws:
            logger.info("Connected. Sending Connect as Operator...")
            # Some systems allow bypassing challenge if correct deviceId/role + token is sent
            payload = {
                "type": "connect",
                "params": {
                    "auth": {"token": TOKEN},
                    "role": "operator",
                    "deviceId": "pms-server-operator"
                }
            }
            await ws.send_str(json.dumps(payload))
            
            async for msg in ws:
                if msg.type == aiohttp.WSMsgType.TEXT:
                    logger.info(f"RECEIVED: {msg.data}")
                    if "success" in msg.data or "hello-ok" in msg.data:
                        logger.info("WE ARE IN!")
                        return
                    if "challenge" in msg.data:
                        logger.info("Still got challenge. Sending response with same params + nonce...")
                        nonce = json.loads(msg.data)["payload"]["nonce"]
                        payload["params"]["nonce"] = nonce
                        await ws.send_str(json.dumps(payload))
                elif msg.type == aiohttp.WSMsgType.CLOSED:
                    logger.info(f"Closed: {ws.close_code}")
                    break

if __name__ == "__main__":
    asyncio.run(test_operator_direct())
