import requests
from django.conf import settings

def send_telegram_message(chat_id, message, parse_mode="HTML"):
    """
    ส่งข้อความแจ้งเตือนเข้า Telegram สู่ผู้ใช้ที่ระบุด้วย chat_id
    """
    token = getattr(settings, 'TELEGRAM_BOT_TOKEN', None)
    if not token:
        print("❌ Error: ไม่พบ TELEGRAM_BOT_TOKEN ใน settings")
        return False
        
    url = f"https://api.telegram.org/bot{token}/sendMessage"
    payload = {
        'chat_id': chat_id,
        'text': message,
        'parse_mode': parse_mode,
        'disable_web_page_preview': True
    }
    
    try:
        response = requests.post(url, json=payload, timeout=10)
        response.raise_for_status()
        return True
    except Exception as e:
        print(f"❌ Error sending Telegram to {chat_id}: {e}")
        return False

def get_recent_chat_ids():
    """
    ดึงข้อความล่าสุดที่คนทักหา Bot เผื่อใช้หา Chat ID อัตโนมัติเวลาตั้งค่า
    """
    token = getattr(settings, 'TELEGRAM_BOT_TOKEN', None)
    if not token:
        return []
        
    url = f"https://api.telegram.org/bot{token}/getUpdates"
    try:
        response = requests.get(url, timeout=10)
        data = response.json()
        if data.get('ok'):
            users = {}
            for update in data.get('result', []):
                if 'message' in update:
                    chat = update['message']['chat']
                    users[chat['id']] = chat.get('first_name', 'Unknown')
            return users
    except Exception as e:
        print(f"Error fetching updates: {e}")
    return {}
