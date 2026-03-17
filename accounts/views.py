# ====== accounts/views.py ======
# Views สำหรับระบบจัดการพนักงาน (User Management)
# ครอบคลุม: แสดงรายชื่อ, สร้าง, แก้ไข, เปิด/ปิดใช้งาน และนำเข้าด้วย Excel

from django.shortcuts import render, redirect, get_object_or_404
from django.contrib.auth.decorators import login_required, user_passes_test
from django.contrib.auth.models import User
from django.contrib import messages
from .models import UserProfile, Role
from .forms import UserCreateForm, UserUpdateForm
from django.db.models import Q
import json


def _role_map_json():
    """คืน JSON string ของ {code: {is_staff, can_view_all, is_tech}} สำหรับ JS"""
    data = {
        r.code: {
            'is_staff': r.is_staff_role,
            'view_all': r.can_view_all_reports,
            'is_tech':  r.is_technician_role,
            'name':     r.name,
        }
        for r in Role.objects.all()
    }
    return json.dumps(data)


# ====== ฟังก์ชันตรวจสิทธิ์ (Permission Check) ======
# User Management — เฉพาะ Superuser เท่านั้น
def is_admin_or_manager(user):
    return user.is_authenticated and user.is_superuser


# ====== View: user_list — แสดงรายชื่อพนักงานทั้งหมด ======
@login_required
@user_passes_test(is_admin_or_manager, login_url='/')
def user_list(request):
    # รับค่าจาก Query String สำหรับค้นหาและกรองข้อมูล
    search_query = request.GET.get('search', '')
    role_filter = request.GET.get('role', '')
    status_filter = request.GET.get('status', 'active')

    users = User.objects.all().order_by('first_name', 'username')

    # ซ่อน Superuser จากหน้านี้เพื่อความปลอดภัยและแยกส่วนการบริหาร
    users = users.exclude(is_superuser=True)

    # กรองตามคำค้นหา: ชื่อจริง นามสกุล หรือ username
    if search_query:
        users = users.filter(
            Q(first_name__icontains=search_query) |
            Q(last_name__icontains=search_query) |
            Q(username__icontains=search_query)
        )

    # กรองตาม Role ของพนักงาน
    if role_filter:
        users = users.filter(profile__role=role_filter)

    # กรองตามสถานะบัญชี (Active / Inactive / ทั้งหมด)
    if status_filter == 'active':
        users = users.filter(is_active=True)
    elif status_filter == 'inactive':
        users = users.filter(is_active=False)

    context = {
        'users': users.select_related('profile'),
        'search_query': search_query,
        'role_filter': role_filter,
        'status_filter': status_filter,
        'roles': Role.objects.order_by('order', 'name').values_list('code', 'name'),
        'role_map_json': _role_map_json(),
    }
    return render(request, 'accounts/user_list.html', context)


# ====== View: user_create — สร้างพนักงานใหม่ ======
@login_required
@user_passes_test(is_admin_or_manager, login_url='/')
def user_create(request):
    if request.method == 'POST':
        form = UserCreateForm(request.POST)
        if form.is_valid():
            new_user = form.save()
            messages.success(request, f"เพิ่มพนักงาน {new_user.first_name} เรียบร้อยแล้ว (รหัสผ่านเริ่มต้น: 12345678)")
            return redirect('accounts:user_list')
        else:
            messages.error(request, "ข้อมูลไม่ถูกต้อง โปรดตรวจสอบฟอร์มข้อมูลอีกครั้ง")
    else:
        # แสดงฟอร์มเปล่าสำหรับสร้างพนักงานใหม่
        form = UserCreateForm()

    return render(request, 'accounts/user_form.html', {
        'form': form, 'title': 'เพิ่มพนักงานใหม่',
        'role_map_json': _role_map_json(),
    })


# ====== View: user_update — แก้ไขข้อมูลพนักงาน ======
@login_required
@user_passes_test(is_admin_or_manager, login_url='/')
def user_update(request, user_id):
    # ดึง User ที่ต้องการแก้ไข หากไม่พบจะ return 404
    target_user = get_object_or_404(User, id=user_id)
    if request.method == 'POST':
        # ส่ง instance=target_user เพื่อให้ฟอร์มอัปเดตแทนที่จะสร้างใหม่
        form = UserUpdateForm(request.POST, request.FILES, instance=target_user)
        if form.is_valid():
            form.save()
            messages.success(request, f"อัปเดตข้อมูลพนักงาน {target_user.username} สำเร็จแล้ว")
            return redirect('accounts:user_list')
        else:
            messages.error(request, "ข้อมูลไม่ถูกต้อง โปรดตรวจสอบฟอร์มข้อมูลอีกครั้ง")
    else:
        # โหลดฟอร์มพร้อมข้อมูลปัจจุบันของพนักงาน
        form = UserUpdateForm(instance=target_user)

    return render(request, 'accounts/user_form.html', {
        'form': form,
        'title': f'แก้ไขข้อมูลพนักงาน: {target_user.get_full_name() or target_user.username}',
        'role_map_json': _role_map_json(),
    })


# ====== View: user_toggle_status — เปิด/ปิดใช้งานบัญชีพนักงาน ======
@login_required
@user_passes_test(is_admin_or_manager, login_url='/')
def user_toggle_status(request, user_id):
    if request.method == 'POST':
        target_user = get_object_or_404(User, id=user_id)
        # ป้องกันการแก้ไขสถานะของบัญชี Superuser ผ่านหน้านี้
        if target_user.is_superuser:
            messages.error(request, "ไม่สามารถแก้ไขสถานะบัญชีระดับ Superuser ได้ที่หน้านี้")
            return redirect('accounts:user_list')

        # สลับสถานะ Active/Inactive
        target_user.is_active = not target_user.is_active
        target_user.save()
        status_word = "เปิดการใช้งาน" if target_user.is_active else "ระงับการใช้งาน"
        messages.success(request, f"{status_word} บัญชีของ {target_user.username} เรียบร้อยแล้ว")
    return redirect('accounts:user_list')


# ====== View: user_import_excel — นำเข้าพนักงานจากไฟล์ Excel ======
import pandas as pd
from django.http import HttpResponse

@login_required
@user_passes_test(is_admin_or_manager, login_url='/')
def user_import_excel(request):
    # --- GET: ดาวน์โหลดไฟล์เทมเพลต Excel ---
    if request.method == 'GET' and request.GET.get('template'):
        # สร้าง DataFrame ว่างพร้อมหัวคอลัมน์มาตรฐาน
        df = pd.DataFrame(columns=[
            'username', 'password', 'first_name', 'last_name', 'email', 'role', 'phone_number'
        ])
        # ใส่ข้อมูลตัวอย่างหนึ่งแถวเพื่อให้ผู้ใช้เห็นรูปแบบที่ถูกต้อง
        df.loc[0] = ['somchai123', 'somchaipass123', 'Somchai', 'Jaidee', 'somchai@9com.cloud', 'technician', '0812345678']

        response = HttpResponse(content_type='application/vnd.openxmlformats-officedocument.spreadsheetml.sheet')
        response['Content-Disposition'] = 'attachment; filename="user_import_template.xlsx"'
        with pd.ExcelWriter(response, engine='openpyxl') as writer:
            df.to_excel(writer, index=False, sheet_name='Users')
        return response

    # --- POST: อ่านไฟล์ Excel และสร้าง/อัปเดตพนักงาน ---
    if request.method == 'POST':
        excel_file = request.FILES.get('excel_file')
        if not excel_file:
            messages.error(request, "กรุณาอัปโหลดไฟล์อิมพอร์ต (Excel)")
            return redirect('accounts:user_list')

        try:
            df = pd.read_excel(excel_file)
            imported_count = 0

            # ตรวจสอบว่ามีคอลัมน์ที่จำเป็นครบหรือไม่
            required_cols = ['username', 'password', 'first_name', 'last_name', 'role']
            missing_cols = [c for c in required_cols if c not in df.columns]
            if missing_cols:
                messages.error(request, f"ไฟล์ที่อัปโหลดขาดคอลัมน์ที่จำเป็น: {', '.join(missing_cols)}")
                return redirect('accounts:user_list')

            from django.db import transaction
            from .models import ROLE_CHOICES
            # รายชื่อ role ที่ระบบรองรับ สำหรับ validate ข้อมูลใน Excel
            valid_roles = [r[0] for r in ROLE_CHOICES]

            # ใช้ transaction.atomic() เพื่อให้การนำเข้าทั้งหมด rollback หากมีข้อผิดพลาด
            with transaction.atomic():
                for index, row in df.iterrows():
                    username = str(row['username']).strip()
                    first_name = str(row['first_name']).strip()
                    last_name = str(row['last_name']).strip()
                    password = str(row['password']).strip()
                    role = str(row['role']).strip()

                    # ข้ามแถวที่ไม่มี username
                    if pd.isna(row['username']) or not username:
                        continue

                    # หาก role ไม่ถูกต้อง ให้ใช้ค่า Default เป็น technician
                    if role not in valid_roles:
                        role = 'technician' # Default fallback

                    # สร้าง User ใหม่หรืออัปเดต User ที่มี username ซ้ำ
                    user, created = User.objects.get_or_create(username=username)
                    user.set_password(password)
                    user.first_name = first_name
                    user.last_name = last_name
                    if 'email' in df.columns and not pd.isna(row['email']):
                        user.email = str(row['email']).strip()
                    user.save()

                    # สร้างหรืออัปเดต UserProfile ที่ผูกกับ User นี้
                    profile, p_created = UserProfile.objects.get_or_create(user=user)
                    profile.role = role
                    if 'phone_number' in df.columns and not pd.isna(row['phone_number']):
                        profile.phone_number = str(row['phone_number']).strip()
                    profile.save()

                    imported_count += 1

            messages.success(request, f"นำเข้าพนักงานจาก Excel ได้สำเร็จ {imported_count} บัญชี")
        except Exception as e:
            messages.error(request, f"พบข้อผิดพลาดขณะอ่านข้อมูล: {str(e)}")

        return redirect('accounts:user_list')

    # --- GET ปกติ: แสดงหน้าอัปโหลด ---
    return render(request, 'accounts/user_import.html', {'title': 'อิมพอร์ตพนักงานด้วย Excel'})


# ──────────────────────────────────────────────────────────────────
# Role Management — จัดการตำแหน่ง/บทบาท (เพิ่ม ลบ แก้ไข)
# ──────────────────────────────────────────────────────────────────

def _sync_users_for_role(role):
    """Re-sync is_staff สำหรับ user ทุกคนที่ใช้ role นี้
       เรียกหลัง role.save() เพื่อให้สิทธิ์อัปเดตทันที"""
    for profile in UserProfile.objects.filter(role=role.code).select_related('user'):
        profile.sync_groups()

@login_required
@user_passes_test(is_admin_or_manager, login_url='/')
def role_list(request):
    roles = Role.objects.order_by('order', 'name')
    role_user_counts = {
        r.code: UserProfile.objects.filter(role=r.code).count()
        for r in roles
    }
    return render(request, 'accounts/role_list.html', {
        'roles': roles,
        'role_user_counts': role_user_counts,
    })


@login_required
@user_passes_test(is_admin_or_manager, login_url='/')
def role_create(request):
    if request.method == 'POST':
        code             = request.POST.get('code', '').strip().lower().replace(' ', '_')
        name             = request.POST.get('name', '').strip()
        is_staff         = request.POST.get('is_staff_role') == 'on'
        is_tech          = request.POST.get('is_technician_role') == 'on'
        can_view_all     = request.POST.get('can_view_all_reports') == 'on'
        badge_color      = request.POST.get('badge_color', 'bg-slate-100 text-slate-800 border-slate-200').strip()
        order            = int(request.POST.get('order', 0) or 0)

        if not code or not name:
            messages.error(request, "กรุณากรอกรหัสตำแหน่งและชื่อตำแหน่ง")
        elif Role.objects.filter(code=code).exists():
            messages.error(request, f"รหัสตำแหน่ง '{code}' มีอยู่แล้ว")
        else:
            Role.objects.create(
                code=code, name=name,
                is_staff_role=is_staff, is_technician_role=is_tech,
                can_view_all_reports=can_view_all,
                badge_color=badge_color, order=order,
            )
            messages.success(request, f"เพิ่มตำแหน่ง '{name}' เรียบร้อยแล้ว")
            return redirect('accounts:role_list')

    return render(request, 'accounts/role_form.html', {
        'title': 'เพิ่มตำแหน่งใหม่',
        'role': None,
        'badge_presets': _badge_presets(),
    })


@login_required
@user_passes_test(is_admin_or_manager, login_url='/')
def role_update(request, role_id):
    role = get_object_or_404(Role, id=role_id)
    if request.method == 'POST':
        name             = request.POST.get('name', '').strip()
        is_staff         = request.POST.get('is_staff_role') == 'on'
        is_tech          = request.POST.get('is_technician_role') == 'on'
        can_view_all     = request.POST.get('can_view_all_reports') == 'on'
        badge_color      = request.POST.get('badge_color', role.badge_color).strip()
        order            = int(request.POST.get('order', role.order) or 0)

        if not name:
            messages.error(request, "กรุณากรอกชื่อตำแหน่ง")
        else:
            role.name                 = name
            role.is_staff_role        = is_staff
            role.is_technician_role   = is_tech
            role.can_view_all_reports = can_view_all
            role.badge_color          = badge_color
            role.order                = order
            role.save()
            # sync users ที่ใช้ role นี้ (เผื่อ can_view_all เปลี่ยน)
            _sync_users_for_role(role)
            messages.success(request, f"แก้ไขตำแหน่ง '{name}' เรียบร้อยแล้ว")
            return redirect('accounts:role_list')

    return render(request, 'accounts/role_form.html', {
        'title': f'แก้ไขตำแหน่ง — {role.name}',
        'role': role,
        'badge_presets': _badge_presets(),
    })


@login_required
@user_passes_test(is_admin_or_manager, login_url='/')
def role_delete(request, role_id):
    role = get_object_or_404(Role, id=role_id)
    user_count = UserProfile.objects.filter(role=role.code).count()
    if request.method == 'POST':
        if user_count > 0:
            messages.error(request, f"ไม่สามารถลบได้ — มีพนักงาน {user_count} คนใช้ตำแหน่งนี้อยู่")
        else:
            role.delete()
            messages.success(request, f"ลบตำแหน่ง '{role.name}' เรียบร้อยแล้ว")
            return redirect('accounts:role_list')
    return render(request, 'accounts/role_confirm_delete.html', {
        'role': role,
        'user_count': user_count,
    })


def _badge_presets():
    return [
        ('bg-red-100 text-red-800 border-red-200',       'แดง'),
        ('bg-orange-100 text-orange-800 border-orange-200', 'ส้ม'),
        ('bg-yellow-100 text-yellow-800 border-yellow-200', 'เหลือง'),
        ('bg-green-100 text-green-800 border-green-200', 'เขียว'),
        ('bg-cyan-100 text-cyan-800 border-cyan-200',    'ฟ้าอ่อน'),
        ('bg-blue-100 text-blue-800 border-blue-200',    'น้ำเงิน'),
        ('bg-indigo-100 text-indigo-800 border-indigo-200', 'คราม'),
        ('bg-purple-100 text-purple-800 border-purple-200', 'ม่วง'),
        ('bg-pink-100 text-pink-800 border-pink-200',    'ชมพู'),
        ('bg-slate-100 text-slate-800 border-slate-200', 'เทา'),
    ]
