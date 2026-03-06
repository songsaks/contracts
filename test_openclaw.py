import asyncio
import json
import logging
import aiohttp
import sys

# Logging setup
logging.basicConfig(level=logging.INFO, format="%(asctime)s - %(name)s - %(levelname)s - %(message)s")
logger = logging.getLogger("TestOpenClaw")

GATEWAY_URL = "http://72.60.197.71:18789"
TOKEN = "1d399e69d1c6e697a53a16a37820bcf73a46ae9de244c7d5"

async def test_aiohttp():
    ws_url = GATEWAY_URL.replace("http", "ws") + "/"
    logger.info(f"Connecting to {ws_url} using aiohttp...")
    headers = {"Authorization": f"Bearer {TOKEN}"}
    
    try:
        async with aiohttp.ClientSession(headers=headers) as session:
            async with session.ws_connect(ws_url, timeout=10) as ws:
                logger.info("Successfully connected!")
                
                # Send auth frame
                # Pattern connect.params.auth.token
                connect_payload = {"type": "connect", "params": {"auth": {"token": TOKEN}}}
                logger.info(f"Sending 'connect' frame: {connect_payload}")
                await ws.send_str(json.dumps(connect_payload))
                
                # Wait for response
                async for msg in ws:
                    if msg.type == aiohttp.WSMsgType.TEXT:
                        logger.info(f"RECEIVED RAW: {msg.data}")
                        data = json.loads(msg.data)
                        if "connect:success" in msg.data or "gateway:auth:success" in msg.data:
                            logger.info("AUTH SUCCESS! Sending test agent run...")
                            run_cmd = {
                                "type": "agent:run",
                                "params": {"agentId": "main", "input": "hi", "stream": True}
                            }
                            await ws.send_str(json.dumps(run_cmd))
                        elif "error" in msg.data.lower():
                             logger.error(f"Server Error Message: {msg.data}")
                    elif msg.type == aiohttp.WSMsgType.CLOSED:
                        logger.info(f"WebSocket closed. Code={ws.close_code}, Extra={ws.exception()}")
                        break
                    elif msg.type == aiohttp.WSMsgType.CLOSING:
                        logger.info("WebSocket is closing...")
                    elif msg.type == aiohttp.WSMsgType.ERROR:
                        logger.error(f"WebSocket Error: {ws.exception()}")
                        break

    except Exception as e:
        logger.error(f"Test Crashed: {str(e)}")

if __name__ == "__main__":
    asyncio.run(test_aiohttp())
