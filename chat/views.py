from django.shortcuts import render, get_object_or_404, redirect
from django.contrib.auth.decorators import login_required
from django.contrib import messages
from django.db.models import Q
from django.http import JsonResponse
from django.utils import timezone
from channels.layers import get_channel_layer
from asgiref.sync import async_to_sync
from .models import ChatRoom, ChatMessage

# เมื่อเข้าหน้าแชทหลัก: ดึงรายการห้องแชททั้งหมดที่เปิดใช้งาน
@login_required
def chat_index(request):
    # ค้นหาห้องที่เป็น is_active และไม่ใช่ห้องโครงการ
    # และ (เป็นห้องสาธารณะ หรือ ผู้ใช้มีสิทธิ์เข้าถึงห้องส่วนตัว)
    if request.user.is_superuser:
        rooms = ChatRoom.objects.filter(is_active=True, project__isnull=True).order_by('created_at')
    else:
        rooms = ChatRoom.objects.filter(
            Q(is_private=False) | Q(allowed_users=request.user),
            is_active=True, 
            project__isnull=True
        ).distinct().order_by('created_at')
    
    return render(request, 'chat/index.html', {
        'rooms': rooms
    })

# เมื่อเข้าแชทในแต่ละห้อง: ค้นหาข้อความเดิม (History) มาแสดงก่อน
@login_required
def chat_room(request, room_id):
    # ค้นหาห้องตามไอดี ถ้าไม่พบจะคืนค่า 404
    room = get_object_or_404(ChatRoom, pk=room_id)
    
    # ตรวจสอบสิทธิ์การเข้าถึงห้องส่วนตัว
    if room.is_private and not request.user.is_superuser:
        if not room.allowed_users.filter(id=request.user.id).exists():
            messages.error(request, f"คุณไม่มีสิทธิ์เข้าถึงห้องแชท '{room.name}' (Private Room)")
            return redirect('chat:index')
            
    # ดึงข้อความย้อนหลังล่าสุด 50 ข้อความ และเรียงตามเวลา
    chat_messages = room.messages.all().order_by('timestamp')[:50]
    
    return render(request, 'chat/room.html', {
        'room': room,
        'chat_messages': chat_messages
    })

# หน้าแชทเฉพาะโครงการ (PMS Project Chat)
@login_required
def project_chat(request, project_id):
    from pms.models import Project
    project = get_object_or_404(Project, pk=project_id)
    
    room, created = ChatRoom.objects.get_or_create(
        project=project,
        defaults={
            'name': f"🚀 {project.name}",
            'description': f"ห้องแชทสื่อสารสำหรับโครงการ: {project.name}",
            'color_hex': '#06b6d4'
        }
    )
    return redirect('chat:room', room_id=room.id)

@login_required
def upload_file(request, room_id):
    """ รับไฟล์อัปโหลดจาก User ผ่าน AJAX แล้วบันทึกลง Database + ส่งเข้า WebSocket ทันที """
    if request.method == 'POST' and request.FILES.get('file'):
        room = get_object_or_404(ChatRoom, pk=room_id)
        
        # ตรวจสอบสิทธิ์ห้องส่วนตัว
        if room.is_private and not request.user.is_superuser:
            if not room.allowed_users.filter(id=request.user.id).exists():
                return JsonResponse({'error': 'Permission denied'}, status=403)
                
        uploaded_file = request.FILES['file']
        is_image = uploaded_file.content_type.startswith('image/')
        
        message = ChatMessage.objects.create(
            room=room,
            user=request.user,
            content="",
        )
        
        if is_image:
            message.image = uploaded_file
        else:
            message.file = uploaded_file
            
        message.save()
        
        # ส่งข้อความไปเตือนผู้ใช้ทุกคนที่อยู่ในห้อง (Broadcast ผ่าน Channel Layer)
        channel_layer = get_channel_layer()
        async_to_sync(channel_layer.group_send)(
            f'chat_{room_id}',
            {
                'type': 'chat_message',
                'message': message.content,
                'username': request.user.username,
                'user_id': request.user.id,
                'is_stt': False,
                'image_url': message.image.url if message.image else None,
                'file_url': message.file.url if message.file else None,
                'latitude': None,
                'longitude': None,
                'location_name': '',
                'timestamp': timezone.localtime(message.timestamp).strftime('%H:%M')
            }
        )
        return JsonResponse({'status': 'ok'})
    return JsonResponse({'error': 'Invalid request'}, status=400)

