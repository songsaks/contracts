import json
from channels.generic.websocket import AsyncWebsocketConsumer
from channels.db import database_sync_to_async
from django.utils import timezone
from .models import ChatRoom, ChatMessage

# ====== WebSocket Consumer สำหรับระบบแชทแบบ Real-time ======

# ตัวแปร in-memory เก็บสถานะผู้ใช้ที่ออนไลน์อยู่ในแต่ละห้อง
# โครงสร้าง: { room_id: { channel_name: { 'id': user_id, 'username': ... } } }
# หมายเหตุ: ข้อมูลนี้จะหายเมื่อ Server รีสตาร์ท เนื่องจากเก็บใน RAM เท่านั้น
online_users_by_room = {}


class ChatConsumer(AsyncWebsocketConsumer):
    """
    WebSocket Consumer หลักสำหรับระบบแชท
    ทำงานแบบ Asynchronous โดยใช้ Django Channels (ASGI)

    หน้าที่หลัก:
    - รับและส่งข้อความแบบ Real-time ระหว่างผู้ใช้ในห้องเดียวกัน
    - จัดการรายชื่อผู้ใช้ที่ออนไลน์ (Online Presence)
    - บันทึกข้อความลงฐานข้อมูลทุกครั้งที่มีการส่ง
    - รองรับทั้งข้อความตัวอักษร รูปภาพ ไฟล์แนบ และพิกัด GPS
    """

    # ====== การเชื่อมต่อ WebSocket (Connection Lifecycle) ======

    async def connect(self):
        """
        เรียกทันทีเมื่อ Client พยายามเชื่อมต่อ WebSocket
        - ดึง room_id จาก URL
        - ปฏิเสธการเชื่อมต่อถ้าผู้ใช้ไม่ได้ Login
        - เข้าร่วม Channel Group ของห้องแชทนั้น
        - เพิ่มชื่อเข้ารายชื่อออนไลน์ และแจ้งทุกคนในห้อง
        """
        # ดึงไอดีห้องจาก URL parameter ที่กำหนดไว้ใน routing.py
        self.room_id = self.scope['url_route']['kwargs']['room_id']
        # ชื่อ Group ต้องตรงกับที่ใช้ใน views.py (upload_file)
        self.room_group_name = f'chat_{self.room_id}'

        # ตรวจสอบตัวตนผู้ใช้: ถ้าเป็น Anonymous ให้ปิดการเชื่อมต่อทันที
        if self.scope["user"].is_anonymous:
            await self.close()
        else:
            # เข้าร่วม Channel Group ของห้องแชทนี้ เพื่อรับ Broadcast จากทุกคนในห้อง
            await self.channel_layer.group_add(
                self.room_group_name,
                self.channel_name
            )
            # ยืนยันการเชื่อมต่อ (ถ้าไม่เรียก accept() WebSocket จะถูกปฏิเสธ)
            await self.accept()

            # บันทึกข้อมูลผู้ใช้เข้าสู่รายชื่อออนไลน์ (keyed by channel_name)
            if self.room_id not in online_users_by_room:
                online_users_by_room[self.room_id] = {}

            online_users_by_room[self.room_id][self.channel_name] = {
                'id': self.scope["user"].id,
                'username': self.scope["user"].username
            }

            # แจ้งให้ทุกคนในห้องทราบว่ามีคนออนไลน์เพิ่มขึ้น
            await self.broadcast_online_users()

    async def disconnect(self, close_code):
        """
        เรียกเมื่อ Client ตัดการเชื่อมต่อ WebSocket (ปิดแท็บ, ออกจากหน้า, หลุด)
        - ลบผู้ใช้ออกจากรายชื่อออนไลน์
        - แจ้งผู้ใช้ที่เหลือในห้องให้อัปเดต Online List
        - ออกจาก Channel Group
        """
        # ลบผู้ใช้ออกจากรายชื่อออนไลน์และ Broadcast ให้ทุกคนทราบ
        if self.room_id in online_users_by_room and self.channel_name in online_users_by_room[self.room_id]:
            del online_users_by_room[self.room_id][self.channel_name]
            await self.broadcast_online_users()

        # ออกจาก Channel Group ของห้องแชท
        await self.channel_layer.group_discard(
            self.room_group_name,
            self.channel_name
        )

    # ====== การรับและส่งข้อมูล (Message Handling) ======

    async def receive(self, text_data):
        """
        เรียกเมื่อได้รับข้อมูลจาก WebSocket ฝั่ง Client
        - แปลง JSON ที่รับเข้ามา
        - บันทึกข้อความลงฐานข้อมูล
        - Broadcast ข้อความไปยังทุกคนในห้องผ่าน Channel Group
        รองรับ: ข้อความธรรมดา, Speech-to-Text flag, รูปภาพ, ไฟล์, พิกัด GPS
        """
        # แปลงข้อมูล JSON ที่รับเข้ามาจาก WebSocket
        data = json.loads(text_data)
        message_text = data.get('message', '').strip()
        # is_stt: True = ข้อความนี้มาจากระบบ Speech-to-Text
        is_stt = data.get('is_stt', False)

        # ข้อมูลเสริม: URL ของรูปภาพหรือไฟล์ที่อัปโหลดแล้ว (จาก upload_file view)
        image_url = data.get('image_url', None)
        file_url = data.get('file_url', None)
        # ข้อมูลพิกัด GPS จากปุ่ม Check-in
        latitude = data.get('latitude', None)
        longitude = data.get('longitude', None)
        location_name = data.get('location_name', '')

        # ประมวลผลเฉพาะเมื่อมีเนื้อหาที่ส่งได้ (ข้อความ, ไฟล์, หรือพิกัด)
        if message_text or image_url or file_url or (latitude and longitude):
            user = self.scope["user"]
            # บันทึกข้อความลง Database (ใช้ database_sync_to_async เพราะ ORM เป็น sync)
            await self.save_message(user, self.room_id, message_text, is_stt, latitude, longitude, location_name)

            # Broadcast ข้อความไปยังทุกคนใน Channel Group ของห้องนี้
            await self.channel_layer.group_send(
                self.room_group_name,
                {
                    'type': 'chat_message',   # ชี้ไปที่ method chat_message() ด้านล่าง
                    'message': message_text,
                    'username': user.username,
                    'user_id': user.id,
                    'is_stt': is_stt,
                    'image_url': image_url,
                    'file_url': file_url,
                    'latitude': latitude,
                    'longitude': longitude,
                    'location_name': location_name,
                    # แปลงเวลาเป็น Local Timezone ก่อนส่ง
                    'timestamp': timezone.localtime(timezone.now()).strftime('%H:%M')
                }
            )

    # ====== Channel Group Event Handlers ======

    async def chat_message(self, event):
        """
        Handler สำหรับ event ประเภท 'chat_message' ที่ได้รับจาก Channel Group
        ทำหน้าที่ส่งข้อมูลข้อความกลับไปยัง WebSocket ของ Client แต่ละราย
        เรียกโดยอัตโนมัติเมื่อมีการ group_send ด้วย type='chat_message'
        """
        # ส่งข้อมูลทั้งหมดกลับไปยัง WebSocket ของ Client ที่ subscribe อยู่
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

    # ====== ระบบแสดงผู้ใช้ออนไลน์ (Online Presence System) ======

    async def broadcast_online_users(self):
        """
        Broadcast รายชื่อผู้ใช้ที่ออนไลน์อยู่ในห้องนี้ไปยังทุกคน
        คัดกรองผู้ใช้ที่ซ้ำกันออกก่อน (กรณี 1 คนเปิดหลายแท็บ/หน้าจอ)
        """
        if self.room_id in online_users_by_room:
            # ใช้ user_id เป็น key เพื่อกรองคนซ้ำออก (deduplication)
            unique_users = {}
            for channel, user_info in online_users_by_room[self.room_id].items():
                unique_users[user_info['id']] = user_info
            online_list = list(unique_users.values())
        else:
            online_list = []

        # ส่ง event ไปยัง Channel Group เพื่อให้ทุกคนอัปเดต Online List
        await self.channel_layer.group_send(
            self.room_group_name,
            {
                'type': 'online_users_update',   # ชี้ไปที่ method online_users_update()
                'users': online_list
            }
        )

    async def online_users_update(self, event):
        """
        Handler สำหรับ event ประเภท 'online_users_update' จาก Channel Group
        ส่งรายชื่อผู้ใช้ออนไลน์ไปยัง WebSocket ของ Client เพื่ออัปเดต UI
        """
        await self.send(text_data=json.dumps({
            'type': 'online_users',   # ฝั่ง JS ใช้ type นี้แยกแยะจาก chat_message
            'users': event['users']
        }))

    # ====== ฟังก์ชันช่วยสำหรับฐานข้อมูล (Database Helper) ======

    @database_sync_to_async
    def save_message(self, user, room_id, content, is_stt, lat=None, lon=None, loc_name=''):
        """
        บันทึกข้อความลงฐานข้อมูลแบบ Synchronous
        ใช้ decorator @database_sync_to_async เพื่อให้เรียกจาก async context ได้
        โดยที่ Django ORM จะทำงานใน Thread Pool แยกต่างหาก ไม่บล็อก Event Loop
        """
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
