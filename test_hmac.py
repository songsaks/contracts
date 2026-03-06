import asyncio
import json
import logging
import aiohttp
import hmac
import hashlib

logging.basicConfig(level=logging.INFO)
logger = logging.getLogger("TestHMAC")

TOKEN = "1d399e69d1c6e697a53a16a37820bcf73a46ae9de244c7d5"
URL = "ws://72.60.197.71:18789/"

async def test_hmac():
    headers = {"Authorization": f"Bearer {TOKEN}"}
    async with aiohttp.ClientSession(headers=headers) as session:
        async with session.ws_connect(URL) as ws:
            logger.info("Connected.")
            async for msg in ws:
                if msg.type == aiohttp.WSMsgType.TEXT:
                    logger.info(f"RECEIVED: {msg.data}")
                    data = json.loads(msg.data)
                    
                    if data.get("event") == "connect.challenge":
                        nonce = data["payload"]["nonce"]
                        # Generate HMAC-SHA256 signature
                        sig = hmac.new(TOKEN.encode(), nonce.encode(), hashlib.sha256).hexdigest()
                        
                        connect_frame = {
                            "type": "connect",
                            "params": {
                                "auth": {"token": TOKEN},
                                "device": {
                                    "id": "pms-server",
                                    "signature": sig,
                                    "nonce": nonce
                                }
                            }
                        }
                        logger.info(f"Sending HMAC connect: {connect_frame}")
                        await ws.send_str(json.dumps(connect_frame))
                    
                    elif "success" in msg.data or "hello-ok" in msg.data:
                        logger.info("SUCCESS!")
                        return

if __name__ == "__main__":
    asyncio.run(test_hmac())
