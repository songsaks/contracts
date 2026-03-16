import json
import re
import logging
from channels.generic.websocket import AsyncWebsocketConsumer

logger = logging.getLogger(__name__)
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

        # Heartbeat ping/pong — ตอบกลับทันทีเพื่อยืนยันว่า connection ยังมีชีวิตอยู่
        if data.get('type') == 'ping':
            await self.send(text_data=json.dumps({'type': 'pong'}))
            return

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
        gps_check_type = data.get('gps_check_type', None)
        gps_notes = data.get('gps_notes', '')

        # ประมวลผลเฉพาะเมื่อมีเนื้อหาที่ส่งได้ (ข้อความ, ไฟล์, หรือพิกัด)
        if message_text or image_url or file_url or (latitude and longitude):
            user = self.scope["user"]
            # บันทึกข้อความลง Database (ใช้ database_sync_to_async เพราะ ORM เป็น sync)
            await self.save_message(user, self.room_id, message_text, is_stt, latitude, longitude, location_name)
            # บันทึก GPS log สำหรับรายงานช่างภาคสนาม
            if latitude and longitude and gps_check_type:
                await self.save_gps_log(user, latitude, longitude, location_name, gps_check_type, gps_notes)

            # แยก @mention จากข้อความ (lowercase) เช่น ['all', 'somchai']
            raw_mentions = re.findall(r'@(\w+)', message_text, re.IGNORECASE)
            mentions = list({m.lower() for m in raw_mentions})

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
                    'mentions': mentions,
                    # แปลงเวลาเป็น Local Timezone ก่อนส่ง
                    'timestamp': timezone.localtime(timezone.now()).strftime('%H:%M')
                }
            )

            # ส่ง notification ไปยังผู้ใช้ที่ถูก @mention
            if mentions:
                room_name = await self.get_room_name(self.room_id)
                preview = (message_text[:70] + '…') if len(message_text) > 70 else message_text
                notif = {
                    'type': 'send_notification',
                    'room_id': self.room_id,
                    'room_name': room_name,
                    'sender': user.username,
                    'preview': preview,
                }
                if 'all' in mentions:
                    # Broadcast ไปทุกคนในห้องผ่าน room_notif group
                    await self.channel_layer.group_send(f'room_notif_{self.room_id}', notif)
                # ส่งตรงไปยัง user ที่ถูก mention เฉพาะ
                specific = [m for m in mentions if m != 'all']
                if specific:
                    uid_list = await self.get_user_ids_by_usernames(specific)
                    for uid in uid_list:
                        if uid != user.id:
                            await self.channel_layer.group_send(f'user_notif_{uid}', notif)

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
            'mentions': event.get('mentions', []),
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
        from decimal import Decimal, ROUND_HALF_UP
        room = ChatRoom.objects.get(id=room_id)
        def to_dec(v):
            if v is None: return None
            return Decimal(str(v)).quantize(Decimal('0.000000001'), rounding=ROUND_HALF_UP)
        ChatMessage.objects.create(
            room=room,
            user=user,
            content=content,
            is_speech_to_text=is_stt,
            latitude=to_dec(lat),
            longitude=to_dec(lon),
            location_name=loc_name
        )

    @database_sync_to_async
    def save_gps_log(self, user, lat, lon, loc_name, check_type, notes=''):
        """บันทึก GPS log สำหรับรายงานช่างภาคสนาม"""
        try:
            from pms.models import TechnicianGPSLog
            from decimal import Decimal, ROUND_HALF_UP

            # ตรวจสอบพิกัดอยู่ในประเทศไทย (bounding box กว้างๆ รวม EEZ)
            # ไทย: lat 5.5–20.5, lon 97.5–105.7
            lat_f = float(lat)
            lon_f = float(lon)
            if not (5.0 <= lat_f <= 21.0 and 97.0 <= lon_f <= 106.0):
                logger.warning(
                    "save_gps_log blocked: coords outside Thailand (%.6f, %.6f) user=%s",
                    lat_f, lon_f, user
                )
                return

            # Truncate to 9 decimal places to satisfy DecimalField(max_digits=12, decimal_places=9)
            lat_d = Decimal(str(lat)).quantize(Decimal('0.000000001'), rounding=ROUND_HALF_UP)
            lon_d = Decimal(str(lon)).quantize(Decimal('0.000000001'), rounding=ROUND_HALF_UP)
            TechnicianGPSLog.objects.create(
                user=user,
                latitude=lat_d,
                longitude=lon_d,
                location_name=loc_name or '',
                check_type=check_type,
                notes=notes or '',
            )
        except Exception as e:
            logger.error("save_gps_log failed for user %s: %s", user, e)

    @database_sync_to_async
    def get_room_name(self, room_id):
        return ChatRoom.objects.get(id=room_id).name

    @database_sync_to_async
    def get_user_ids_by_usernames(self, usernames):
        from django.contrib.auth import get_user_model
        User = get_user_model()
        return list(User.objects.filter(username__in=usernames, is_active=True).values_list('id', flat=True))


# ====== Notification Consumer — รับแจ้งเตือน @mention แบบ Real-time ======

class NotificationConsumer(AsyncWebsocketConsumer):
    """
    WebSocket Consumer สำหรับรับแจ้งเตือน @mention ของผู้ใช้แต่ละคน
    ใช้บนหน้า Chat Index เพื่อแสดงกระดิ่งแจ้งเตือนโดยไม่ต้องเปิดห้องแชท
    """

    async def connect(self):
        if self.scope["user"].is_anonymous:
            await self.close()
            return
        user = self.scope["user"]
        self.user_notif_group = f'user_notif_{user.id}'
        self.room_notif_groups = []

        # Subscribe ช่อง personal notification ของ user นี้
        await self.channel_layer.group_add(self.user_notif_group, self.channel_name)
        await self.accept()

        # Subscribe ช่อง @all ของทุกห้องที่ user มีสิทธิ์เข้าถึง
        room_ids = await self.get_accessible_room_ids(user)
        for room_id in room_ids:
            group = f'room_notif_{room_id}'
            await self.channel_layer.group_add(group, self.channel_name)
            self.room_notif_groups.append(group)

    async def disconnect(self, close_code):
        await self.channel_layer.group_discard(self.user_notif_group, self.channel_name)
        for group in self.room_notif_groups:
            await self.channel_layer.group_discard(group, self.channel_name)

    async def receive(self, text_data):
        pass  # Client ไม่ส่งข้อมูลมา

    async def send_notification(self, event):
        """ส่ง notification event ไปยัง WebSocket ของ Client"""
        await self.send(text_data=json.dumps({
            'type': 'notification',
            'room_id': event['room_id'],
            'room_name': event['room_name'],
            'sender': event['sender'],
            'preview': event['preview'],
        }))

    @database_sync_to_async
    def get_accessible_room_ids(self, user):
        from django.db.models import Q
        if user.is_superuser:
            return list(ChatRoom.objects.filter(is_active=True).values_list('id', flat=True))
        return list(ChatRoom.objects.filter(
            Q(is_private=False) | Q(allowed_users=user),
            is_active=True
        ).distinct().values_list('id', flat=True))
