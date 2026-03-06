import asyncio
import json
import logging
import aiohttp

logging.basicConfig(level=logging.INFO)
logger = logging.getLogger("TestImmediateAuth")

TOKEN = "1d399e69d1c6e697a53a16a37820bcf73a46ae9de244c7d5"
URL = "ws://72.60.197.71:18789/"

async def test_immediate_auth():
    headers = {"Authorization": f"Bearer {TOKEN}"}
    async with aiohttp.ClientSession(headers=headers) as session:
        async with session.ws_connect(URL) as ws:
            logger.info("Connected. Sending initial connect...")
            await ws.send_str(json.dumps({"type": "connect", "params": {"auth": {"token": TOKEN}}}))
            
            async for msg in ws:
                if msg.type == aiohttp.WSMsgType.TEXT:
                    logger.info(f"RECEIVED: {msg.data}")
                    data = json.loads(msg.data)
                    
                    if data.get("event") == "connect.challenge":
                        nonce = data["payload"]["nonce"]
                        # Just send gateway:auth directly
                        auth_frame = {
                            "type": "gateway:auth",
                            "params": {"token": TOKEN, "nonce": nonce}
                        }
                        logger.info(f"Sending Gateway Auth: {auth_frame}")
                        await ws.send_str(json.dumps(auth_frame))

                    elif "success" in msg.data or "hello-ok" in msg.data:
                        logger.info("WE ARE IN!")
                        return
                    elif "error" in msg.data:
                         logger.error(f"Error: {msg.data}")
                elif msg.type == aiohttp.WSMsgType.CLOSED:
                    logger.info(f"Closed: {ws.close_code}")
                    break

if __name__ == "__main__":
    asyncio.run(test_immediate_auth())
