# ====== Chatbot Views ======
# ไฟล์นี้จัดการ API endpoint สำหรับรับข้อความจากผู้ใช้
# และส่งต่อไปยัง Gemini AI Service เพื่อประมวลผลคำตอบ

import json
from django.http import JsonResponse
from django.views.decorators.csrf import csrf_exempt
from django.views.decorators.http import require_POST
from django.contrib.auth.decorators import login_required
from .services.gemini import gemini_chat_sync  # นำเข้า service ที่ติดต่อกับ Gemini AI

# @csrf_exempt: ปิดการตรวจสอบ CSRF token เนื่องจากเป็น API endpoint ที่รับ request จาก JavaScript
# @require_POST: อนุญาตเฉพาะ HTTP POST method เท่านั้น
@csrf_exempt
@require_POST
def chatbot_message(request):
    """
    Endpoint สำหรับรับข้อความจากผู้ใช้และส่งคืนคำตอบจาก Gemini AI

    Endpoint for Chatbot integration
    POST payload: {"text": "คำถามของผู้ใช้"}

    Returns:
        JsonResponse: {"reply": "คำตอบจาก AI"} หรือ {"error": "ข้อความ error"}
    """
    try:
        # แปลง request body จาก bytes เป็น JSON object
        data = json.loads(request.body.decode("utf-8"))

        # ดึงข้อความที่ผู้ใช้ส่งมา และตัดช่องว่างหัวท้ายออก
        user_text = data.get("text", "").strip()

        # ตรวจสอบว่าผู้ใช้ส่งข้อความมาหรือไม่
        if not user_text:
            return JsonResponse({"reply": "กรุณาใส่ข้อความ"}, status=400)

        # In a real environment, we'd use request.user
        # For now, if logged in, pass user object
        # ตรวจสอบว่าผู้ใช้ login อยู่หรือไม่ เพื่อส่ง context ผู้ใช้ให้ AI
        user = request.user if request.user.is_authenticated else None

        # เรียก Gemini AI service เพื่อประมวลผลคำถามและรับคำตอบกลับมา
        answer = gemini_chat_sync(user_text=user_text, user=user)

        # ส่งคำตอบกลับไปยัง client ในรูปแบบ JSON
        return JsonResponse({"reply": answer})

    except Exception as e:
        # หากเกิดข้อผิดพลาดใดๆ ให้ส่ง error message กลับพร้อม HTTP status 500
        return JsonResponse({"error": str(e)}, status=500)
