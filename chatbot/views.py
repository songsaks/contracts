import json
from django.http import JsonResponse
from django.views.decorators.csrf import csrf_exempt
from django.views.decorators.http import require_POST
from django.contrib.auth.decorators import login_required
from .services.gemini import gemini_chat_sync

@csrf_exempt
@require_POST
def chatbot_message(request):
    """
    Endpoint for Chatbot integration
    POST payload: {"text": "คำถามของผู้ใช้"}
    """
    try:
        data = json.loads(request.body.decode("utf-8"))
        user_text = data.get("text", "").strip()
        if not user_text:
            return JsonResponse({"reply": "กรุณาใส่ข้อความ"}, status=400)
        
        # In a real environment, we'd use request.user
        # For now, if logged in, pass user object
        user = request.user if request.user.is_authenticated else None
        
        answer = gemini_chat_sync(user_text=user_text, user=user)
        return JsonResponse({"reply": answer})
        
    except Exception as e:
        return JsonResponse({"error": str(e)}, status=500)
