from django.shortcuts import render, get_object_or_404, redirect
from django.contrib.auth.decorators import login_required
from django.contrib import messages
from django.db.models import Q
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
    messages_query = room.messages.all().order_by('timestamp')[:50]
    
    return render(request, 'chat/room.html', {
        'room': room,
        'messages': messages_query
    })

# หน้าแชทเฉพาะโครงการ (PMS Project Chat)
@login_required
def project_chat(request, project_id):
    from pms.models import Project
    project = get_object_or_404(Project, pk=project_id)
    
    # ค้นหาว่ามีห้องแชทของโครงการนี้อยู่แล้วหรือยัง ถ้ายังให้สร้างใหม่
    # โดยจะลิงก์ชื่อห้องตามชื่อโครงการ
    room, created = ChatRoom.objects.get_or_create(
        project=project,
        defaults={
            'name': f"🚀 {project.name}",
            'description': f"ห้องแชทสื่อสารสำหรับโครงการ: {project.name}",
            'color_hex': '#06b6d4' # สี Cyan สำหรับ PMS
        }
    )
    
    # ส่งต่อไปยังหน้าห้องแชทปกติ
    return redirect('chat:room', room_id=room.id)
