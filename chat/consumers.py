import json
from channels.generic.websocket import AsyncWebsocketConsumer
from channels.db import database_sync_to_async
from django.utils import timezone
from .models import ChatRoom, ChatMessage

# ตัวแปรสำหรับเก็บสถานะผู้ที่ออนไลน์อยู่ในแต่ละห้อง (In-memory storage)
online_users_by_room = {}

# คอมซูมเมอร์สำหรับการจัดการแชทผ่าน WebSocket
class ChatConsumer(AsyncWebsocketConsumer):
    # เมื่อพยายามเชื่อมต่อ WebSocket
    async def connect(self):
        # ดึงไอดีห้องจาก URL parameter
        self.room_id = self.scope['url_route']['kwargs']['room_id']
        self.room_group_name = f'chat_{self.room_id}'

        # ตรวจสอบตัวตนผู้ใช้
        if self.scope["user"].is_anonymous:
            await self.close()
        else:
            # เข้าร่วมกลุ่ม (Channel Group) ของห้องแชทนี้
            await self.channel_layer.group_add(
                self.room_group_name,
                self.channel_name
            )
            await self.accept()

            # บันทึกผู้ใช้เข้าสู่รายชื่อออนไลน์
            if self.room_id not in online_users_by_room:
                online_users_by_room[self.room_id] = {}
            
            online_users_by_room[self.room_id][self.channel_name] = {
                'id': self.scope["user"].id,
                'username': self.scope["user"].username
            }
            
            # แจ้งให้ทุกคนในห้องทราบว่ามีคนออนไลน์เพิ่ม
            await self.broadcast_online_users()

    # เมื่อเลิกเชื่อมต่อ WebSocket
    async def disconnect(self, close_code):
        # ลบผู้ใช้ออกจากรายชื่อออนไลน์และแจ้งทุกคน
        if self.room_id in online_users_by_room and self.channel_name in online_users_by_room[self.room_id]:
            del online_users_by_room[self.room_id][self.channel_name]
            await self.broadcast_online_users()

        # ออกจากกลุ่ม (Channel Group) ของห้องแชท
        await self.channel_layer.group_discard(
            self.room_group_name,
            self.channel_name
        )

    # เมื่อได้รับข้อมูลจาก WebSocket (ผู้ใช้ส่งข้อความมา)
    async def receive(self, text_data):
        # แปลงข้อมูล JSON ที่รับเข้ามา
        data = json.loads(text_data)
        message_text = data.get('message', '').strip()
        is_stt = data.get('is_stt', False)
        
        # ข้อมูลเพิ่มเติม: รูปภาพ, ไฟล์, และพิกัด
        image_url = data.get('image_url', None)
        file_url = data.get('file_url', None)
        latitude = data.get('latitude', None)
        longitude = data.get('longitude', None)
        location_name = data.get('location_name', '')

        if message_text or image_url or file_url or (latitude and longitude):
            user = self.scope["user"]
            # บันทึกข้อความพร้อมข้อมูลพิกัด (ถ้ามี)
            await self.save_message(user, self.room_id, message_text, is_stt, latitude, longitude, location_name)

            # ส่งต่อข้อความไปยังทุกคนในกลุ่ม (Broadcast)
            await self.channel_layer.group_send(
                self.room_group_name,
                {
                    'type': 'chat_message',
                    'message': message_text,
                    'username': user.username,
                    'user_id': user.id,
                    'is_stt': is_stt,
                    'image_url': image_url,
                    'file_url': file_url,
                    'latitude': latitude,
                    'longitude': longitude,
                    'location_name': location_name,
                    'timestamp': timezone.localtime(timezone.now()).strftime('%H:%M')
                }
            )

    # ฟังเรียกจากกลุ่ม
    async def chat_message(self, event):
        # ส่งข้อมูลกลับไปยัง WebSocket
        await self.send(text_data=json.dumps({
            'type': 'chat_message',
            'message': event['message'],
            'username': event['username'],
            'user_id': event['user_id'],
            'is_stt': event['is_stt'],
            'image_url': event.get('image_url'),
            'file_url': event.get('file_url'),
            'latitude': event.get('latitude'),
            'longitude': event.get('longitude'),
            'location_name': event.get('location_name'),
            'timestamp': event['timestamp']
        }))

    # ส่งรายชื่อคนออนไลน์ทั้งหมด
    async def broadcast_online_users(self):
        if self.room_id in online_users_by_room:
            # คัดกรองผู้ใช้ที่ซ้ำกันออก (1 คนเปิดหลายหน้าจอ)
            unique_users = {}
            for channel, user_info in online_users_by_room[self.room_id].items():
                unique_users[user_info['id']] = user_info
            online_list = list(unique_users.values())
        else:
            online_list = []
            
        await self.channel_layer.group_send(
            self.room_group_name,
            {
                'type': 'online_users_update',
                'users': online_list
            }
        )

    # ฟังเรียกสำหรับรายชื่อคนออนไลน์
    async def online_users_update(self, event):
        await self.send(text_data=json.dumps({
            'type': 'online_users',
            'users': event['users']
        }))

    # ฟังก์ชันช่วยบันทึกข้อความลงฐานข้อมูล
    @database_sync_to_async
    def save_message(self, user, room_id, content, is_stt, lat=None, lon=None, loc_name=''):
        room = ChatRoom.objects.get(id=room_id)
        ChatMessage.objects.create(
            room=room,
            user=user,
            content=content,
            is_speech_to_text=is_stt,
            latitude=lat,
            longitude=lon,
            location_name=loc_name
        )
