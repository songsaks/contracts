import asyncio
import json
import logging
import aiohttp

logging.basicConfig(level=logging.INFO)
logger = logging.getLogger("TestTwoStep")

TOKEN = "1d399e69d1c6e697a53a16a37820bcf73a46ae9de244c7d5"
URL = "ws://72.60.197.71:18789/"

async def test_twostep():
    headers = {"Authorization": f"Bearer {TOKEN}"}
    async with aiohttp.ClientSession(headers=headers) as session:
        async with session.ws_connect(URL) as ws:
            logger.info("Connected. Sending Step 1: Connect")
            # Step 1: Immediate connect frame
            hello = {"type": "connect", "params": {"auth": {"token": TOKEN}}}
            await ws.send_str(json.dumps(hello))
            
            async for msg in ws:
                if msg.type == aiohttp.WSMsgType.TEXT:
                    logger.info(f"RECEIVED: {msg.data}")
                    data = json.loads(msg.data)
                    
                    if data.get("event") == "connect.challenge":
                        nonce = data["payload"]["nonce"]
                        logger.info(f"Got challenge: {nonce}. Sending Step 2: Response")
                        # Step 2: Connect again with nonce
                        response = {
                            "type": "connect",
                            "params": {
                                "auth": {"token": TOKEN},
                                "nonce": nonce
                            }
                        }
                        await ws.send_str(json.dumps(response))
                    
                    elif "success" in msg.data or "hello-ok" in msg.data:
                        logger.info("SUCCESS!")
                        return
                elif msg.type == aiohttp.WSMsgType.CLOSED:
                    logger.info(f"Closed: {ws.close_code}")
                    break

if __name__ == "__main__":
    asyncio.run(test_twostep())
