import asyncio
import json
import logging
import aiohttp

logging.basicConfig(level=logging.INFO)
logger = logging.getLogger("TestOpenClaw")

GATEWAY_URL = "ws://72.60.197.71:18789/"
TOKEN = "1d399e69d1c6e697a53a16a37820bcf73a46ae9de244c7d5"

async def test_handshake():
    headers = {"Authorization": f"Bearer {TOKEN}"}
    async with aiohttp.ClientSession(headers=headers) as session:
        async with session.ws_connect(GATEWAY_URL) as ws:
            logger.info("Connected.")
            
            async for msg in ws:
                if msg.type == aiohttp.WSMsgType.TEXT:
                    logger.info(f"RECEIVED: {msg.data}")
                    data = json.loads(msg.data)
                    
                    if data.get("event") == "connect.challenge":
                        nonce = data["payload"]["nonce"]
                        logger.info(f"Got challenge nonce: {nonce}")
                        
                        # Try to respond with connect frame including nonce
                        connect_frame = {
                            "type": "connect",
                            "params": {
                                "auth": {"token": TOKEN},
                                "nonce": nonce,
                                "device": {
                                    "id": "pms-server-node",
                                    "name": "PMS Django Server"
                                }
                            }
                        }
                        logger.info(f"Responding with: {connect_frame}")
                        await ws.send_str(json.dumps(connect_frame))
                    
                    elif data.get("type") == "connect:success" or "success" in msg.data:
                        logger.info("WE ARE IN! Testing agent run...")
                        run_cmd = {
                            "type": "agent:run",
                            "params": {"agentId": "main", "input": "ทดสอบหน่อยครับ", "stream": True}
                        }
                        await ws.send_str(json.dumps(run_cmd))
                    
                    elif data.get("type") == "agent:output" or "output" in msg.data:
                         logger.info(f"AGENT OUTPUT: {msg.data}")

                elif msg.type == aiohttp.WSMsgType.CLOSED:
                    logger.info(f"Closed: {ws.close_code}")
                    break

if __name__ == "__main__":
    asyncio.run(test_handshake())
