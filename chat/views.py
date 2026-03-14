from django.shortcuts import render, get_object_or_404, redirect
from django.contrib.auth import get_user_model
from django.contrib.auth.decorators import login_required
from django.contrib import messages
from django.db.models import Q
from django.http import JsonResponse
from django.utils import timezone
from channels.layers import get_channel_layer
from asgiref.sync import async_to_sync
from .models import ChatRoom, ChatMessage

User = get_user_model()

# ====== Views หลักของระบบแชท (Chat Views) ======


@login_required
def chat_index(request):
    """
    หน้าแรกของระบบแชท: แสดงรายการห้องแชททั้งหมดที่ผู้ใช้มีสิทธิ์เข้าถึง
    - Superuser: เห็นทุกห้องที่ is_active=True
    - User ทั่วไป: เห็นเฉพาะห้องสาธารณะ หรือห้องส่วนตัวที่ตนเองได้รับอนุญาต
    - กรองเฉพาะห้องแชทกลาง (ไม่รวมห้องที่ผูกกับโครงการ PMS)
    """
    # ค้นหาห้องที่เป็น is_active และไม่ใช่ห้องโครงการ
    # และ (เป็นห้องสาธารณะ หรือ ผู้ใช้มีสิทธิ์เข้าถึงห้องส่วนตัว)
    if request.user.is_superuser:
        # Superuser เห็นทุกห้องที่เปิดใช้งาน
        rooms = ChatRoom.objects.filter(is_active=True, project__isnull=True).order_by('created_at')
    else:
        # ผู้ใช้ทั่วไป: ดึงเฉพาะห้องที่ตนเองมีสิทธิ์ (Q object ใช้ OR condition)
        rooms = ChatRoom.objects.filter(
            Q(is_private=False) | Q(allowed_users=request.user),
            is_active=True,
            project__isnull=True
        ).distinct().order_by('created_at')

    return render(request, 'chat/index.html', {
        'rooms': rooms
    })


@login_required
def chat_room(request, room_id):
    """
    หน้าห้องแชท: แสดงกล่องข้อความและโหลดประวัติข้อความย้อนหลัง
    ตรวจสอบสิทธิ์ก่อนอนุญาตให้เข้าห้องส่วนตัว
    """
    # ค้นหาห้องตามไอดี ถ้าไม่พบจะคืนค่า 404
    room = get_object_or_404(ChatRoom, pk=room_id)

    # ตรวจสอบสิทธิ์การเข้าถึงห้องส่วนตัว (Private Room Access Check)
    if room.is_private and not request.user.is_superuser:
        if not room.allowed_users.filter(id=request.user.id).exists():
            messages.error(request, f"คุณไม่มีสิทธิ์เข้าถึงห้องแชท '{room.name}' (Private Room)")
            return redirect('chat:index')

    # ดึงข้อความย้อนหลังล่าสุด 50 ข้อความ เรียงตามเวลาจากเก่าไปใหม่
    chat_messages = room.messages.all().order_by('timestamp')[:50]

    try:
        user_role = request.user.profile.role
    except Exception:
        user_role = ''
    is_technician = user_role in ('technician', 'technician_lead') or request.user.is_staff or request.user.is_superuser

    # รายชื่อสมาชิกทั้งหมดในห้อง:
    # ห้องส่วนตัว → ใช้ allowed_users + ตัวเอง
    # ห้องสาธารณะ → ผู้ใช้ทุกคนที่เคยส่งข้อความในห้องนี้
    if room.is_private:
        member_qs = User.objects.filter(
            Q(allowed_chat_rooms=room) | Q(id=request.user.id),
            is_active=True
        ).distinct()
    else:
        member_qs = User.objects.filter(
            chatmessage__room=room, is_active=True
        ).distinct()

    room_members = list(member_qs.values('id', 'username'))

    return render(request, 'chat/room.html', {
        'room': room,
        'chat_messages': chat_messages,
        'is_technician': is_technician,
        'room_members': room_members,
    })


# ====== View สำหรับห้องแชทโครงการ PMS ======

@login_required
def project_chat(request, project_id):
    """
    ทางลัดเพื่อเข้าห้องแชทที่ผูกกับโครงการ PMS
    ถ้าห้องแชทยังไม่มี จะสร้างใหม่อัตโนมัติ (get_or_create)
    แล้ว redirect ไปหน้าห้องแชทนั้นทันที
    """
    from pms.models import Project
    project = get_object_or_404(Project, pk=project_id)

    # ดึงหรือสร้างห้องแชทที่เชื่อมกับโครงการนี้
    room, created = ChatRoom.objects.get_or_create(
        project=project,
        defaults={
            'name': f"🚀 {project.name}",
            'description': f"ห้องแชทสื่อสารสำหรับโครงการ: {project.name}",
            'color_hex': '#06b6d4'
        }
    )
    return redirect('chat:room', room_id=room.id)


# ====== View สำหรับการอัปโหลดไฟล์ผ่าน AJAX ======

@login_required
def upload_file(request, room_id):
    """
    รับไฟล์อัปโหลดจาก User ผ่าน AJAX แล้วบันทึกลง Database
    จากนั้น Broadcast ข้อมูลเข้า Channel Layer เพื่อแจ้งทุกคนในห้องทันที
    รองรับทั้งไฟล์รูปภาพ (image/*) และไฟล์เอกสาร (PDF, Word ฯลฯ)
    """
    if request.method == 'POST' and request.FILES.get('file'):
        room = get_object_or_404(ChatRoom, pk=room_id)

        # ตรวจสอบสิทธิ์ห้องส่วนตัวก่อนอนุญาตให้อัปโหลด
        if room.is_private and not request.user.is_superuser:
            if not room.allowed_users.filter(id=request.user.id).exists():
                return JsonResponse({'error': 'Permission denied'}, status=403)

        uploaded_file = request.FILES['file']
        # ตรวจสอบประเภทไฟล์: รูปภาพหรือไฟล์เอกสาร
        is_image = uploaded_file.content_type.startswith('image/')

        # สร้าง ChatMessage record ก่อน (content ว่าง เพราะส่งเป็นไฟล์อย่างเดียว)
        message = ChatMessage.objects.create(
            room=room,
            user=request.user,
            content="",
        )

        # บันทึกไฟล์ลงฟิลด์ที่ถูกต้องตามประเภท
        if is_image:
            message.image = uploaded_file
        else:
            message.file = uploaded_file

        message.save()

        # ส่งข้อความไปเตือนผู้ใช้ทุกคนที่อยู่ในห้อง (Broadcast ผ่าน Channel Layer)
        # ใช้ async_to_sync เพราะ view นี้เป็น synchronous แต่ channel_layer เป็น async
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
