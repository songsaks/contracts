import os
import django

# ตั้งค่าสภาพแวดล้อมของ Django
os.environ.setdefault('DJANGO_SETTINGS_MODULE', 'config.settings')
django.setup()

from chat.models import ChatRoom

def create_default_rooms():
    # รายการห้องแชทตั้งต้น
    default_rooms = [
        {
            'name': 'ประกาศข่าวสาร 📢', 
            'description': 'ประกาศสำคัญสำหรับทุกคนในทีม 9Com',
            'color': '#3b82f6'
        },
        {
            'name': 'แชททั่วไป ☕', 
            'description': 'ห้องสำหรับพักผ่อนและพูดคุยเรื่องทั่วไป',
            'color': '#10b981'
        },
        {
            'name': 'ฝ่ายบริการลูกค้า 🛠️', 
            'description': 'เฉพาะห้องบริหารจัดการงานแก้ปัญหาลูกค้า (Support)',
            'color': '#f59e0b'
        },
        {
            'name': 'ฝ่ายขาย 📈', 
            'description': 'ห้องสำหรับจัดการเอกสารและลูกค้าสัมพันธ์',
            'color': '#ef4444'
        }
    ]

    for room_data in default_rooms:
        room, created = ChatRoom.objects.get_or_create(
            name=room_data['name'],
            defaults={
                'description': room_data['description'],
                'color_hex': room_data['color']
            }
        )
        if created:
            print(f"✅ สร้างห้องแชท: {room.name} สำเร็จ")
        else:
            print(f"ℹ️ ห้องแชท: {room.name} มีอยู่แล้ว")

if __name__ == "__main__":
    create_default_rooms()
