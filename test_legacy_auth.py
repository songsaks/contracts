import asyncio
import json
import logging
import aiohttp

logging.basicConfig(level=logging.INFO)
logger = logging.getLogger("TestLegacy")

TOKEN = "1d399e69d1c6e697a53a16a37820bcf73a46ae9de244c7d5"
URL = "ws://72.60.197.71:18789/"

async def test_legacy():
    # Legacy Moltbot/Clawdbot used 'token' as query and 'gateway:auth'
    ws_url = f"{URL}?token={TOKEN}"
    async with aiohttp.ClientSession() as session:
        async with session.ws_connect(ws_url) as ws:
            logger.info("Connected via query. Sending 'gateway:auth'...")
            auth_frame = {"type": "gateway:auth", "params": {"token": TOKEN}}
            await ws.send_str(json.dumps(auth_frame))
            
            async for msg in ws:
                if msg.type == aiohttp.WSMsgType.TEXT:
                    logger.info(f"RECEIVED: {msg.data}")
                    if "success" in msg.data:
                        logger.info("LEGACY AUTH SUCCESS!")
                        return
                    if "challenge" in msg.data:
                        logger.info("Still got challenge. Sending 'connect' response...")
                        nonce = json.loads(msg.data)["payload"]["nonce"]
                        # Some versions use root token
                        await ws.send_str(json.dumps({"type": "connect", "token": TOKEN, "nonce": nonce}))

if __name__ == "__main__":
    asyncio.run(test_legacy())
