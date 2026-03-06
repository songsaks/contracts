import asyncio
import json
import logging
import aiohttp

logging.basicConfig(level=logging.INFO)
logger = logging.getLogger("TestLocalOpenClaw")

TOKEN = "1d399e69d1c6e697a53a16a37820bcf73a46ae9de244c7d5"
URLS = ["ws://127.0.0.1:18791/", "ws://127.0.0.1:18792/"]

async def test_url(url):
    logger.info(f"Connecting to {url}...")
    try:
        async with aiohttp.ClientSession() as session:
            async with session.ws_connect(url, timeout=5) as ws:
                logger.info("Connected!")
                async for msg in ws:
                    if msg.type == aiohttp.WSMsgType.TEXT:
                        logger.info(f"RECEIVED: {msg.data}")
                        if "challenge" in msg.data:
                             nonce = json.loads(msg.data)["payload"]["nonce"]
                             # Try connect with nonce
                             await ws.send_str(json.dumps({
                                 "type": "connect",
                                 "params": {"auth": {"token": TOKEN}, "nonce": nonce}
                             }))
                        elif "success" in msg.data or "hello-ok" in msg.data:
                             logger.info("SUCCESS!")
                             return True
                    elif msg.type == aiohttp.WSMsgType.CLOSED:
                        break
    except Exception as e:
        logger.error(f"Failed on {url}: {str(e)}")
    return False

async def main():
    for url in URLS:
        if await test_url(url):
            logger.info(f"--- GOT IT: {url} works! ---")
            break

if __name__ == "__main__":
    asyncio.run(main())
