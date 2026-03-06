import asyncio
import aiohttp
import json
import logging

logging.basicConfig(level=logging.INFO)
logger = logging.getLogger("TestRPC")

TOKEN = "1d399e69d1c6e697a53a16a37820bcf73a46ae9de244c7d5"
URLS = [
    "ws://72.60.197.71:18789/",
    "ws://72.60.197.71:18789/ws",
    "ws://72.60.197.71:18789/rpc"
]

async def test_url(url):
    logger.info(f"--- Testing {url} ---")
    headers = {"Authorization": f"Bearer {TOKEN}"}
    try:
        async with aiohttp.ClientSession(headers=headers) as session:
            async with session.ws_connect(url, timeout=5) as ws:
                logger.info("Connected.")
                # Send immediate connect
                payload = {"type": "connect", "params": {"auth": {"token": TOKEN}}}
                await ws.send_str(json.dumps(payload))
                
                async for msg in ws:
                    if msg.type == aiohttp.WSMsgType.TEXT:
                        logger.info(f"RECEIVED: {msg.data}")
                        if "success" in msg.data:
                            logger.info("SUCCESS!")
                            return True
                    elif msg.type == aiohttp.WSMsgType.CLOSED:
                        logger.info(f"Closed: {ws.close_code}")
                        break
    except Exception as e:
        logger.error(f"Error on {url}: {str(e)}")
    return False

async def main():
    for url in URLS:
        if await test_url(url):
            break

if __name__ == "__main__":
    asyncio.run(main())
