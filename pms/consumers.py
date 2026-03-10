import json
import logging
import asyncio
from channels.generic.websocket import AsyncWebsocketConsumer
from django.conf import settings
from chatbot.services.gemini import gemini_chat_sync
from asgiref.sync import sync_to_async

logger = logging.getLogger(__name__)

class PmsChatConsumer(AsyncWebsocketConsumer):
    # จัดการการเชื่อมต่อ WebSocket จากผู้ใช้งาน (Frontend)
    async def connect(self):
        # ตรวจสอบว่าระบบ Chatbot ถูกปิดใช้งานทั่วโลกหรือไม่
        if not getattr(settings, 'CHATBOT_ENABLED', True):
            await self.close()
            return

        # รับการเชื่อมต่อจากหน้าจอ PMS UI
        print(f"DEBUG: WebSocket connection attempt from {self.scope.get('user')}")
        await self.accept()
        user = self.scope.get('user', 'Anonymous')
        print(f"DEBUG: WebSocket accepted for {user}")
        logger.info(f"Client connected to PMS Chat: {user}")

    # จัดการเมื่อมีการปิดการเชื่อมต่อ WebSocket
    async def disconnect(self, close_code):
        print(f"DEBUG: WebSocket disconnected. Close code: {close_code}")
        logger.info(f"Chat socket disconnected: {close_code}")
        pass

    # รับข้อความจากผู้ใช้งาน และส่งไปประมวลผลผ่านระบบ Gemini AI แบบ Synchronous
    async def receive(self, text_data):
        # 3. Receive message from User (Frontend)
        print(f"DEBUG: Message received: {text_data}")
        try:
            data = json.loads(text_data)
            message = data.get('message', '').strip()
            if not message: return

            user_obj = self.scope.get("user") if self.scope.get("user") and self.scope["user"].is_authenticated else None
            
            # Since Gemini with tools needs a sync context for Django models,
            # we run it in a thread using sync_to_async.
            # Non-streaming for reliability with tool calls.
            
            answer = await sync_to_async(gemini_chat_sync)(message, user=user_obj)
            
            if answer:
                await self.send(json.dumps({
                    'type': 'ai_reply_chunk',
                    'text': answer
                }))
            
            # Send done signal
            await self.send(json.dumps({'type': 'ai_reply_done'}))
            
        except Exception as e:
            logger.error(f"Error in Gemini Chat receive: {str(e)}")
            await self.send(json.dumps({'type': 'error', 'message': str(e)}))
