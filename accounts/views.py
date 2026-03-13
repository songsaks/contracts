# ====== accounts/views.py ======
# Views สำหรับระบบจัดการพนักงาน (User Management)
# ครอบคลุม: แสดงรายชื่อ, สร้าง, แก้ไข, เปิด/ปิดใช้งาน และนำเข้าด้วย Excel

from django.shortcuts import render, redirect, get_object_or_404
from django.contrib.auth.decorators import login_required, user_passes_test
from django.contrib.auth.models import User
from django.contrib import messages
from .models import UserProfile
from .forms import UserCreateForm, UserUpdateForm
from django.db.models import Q


# ====== ฟังก์ชันตรวจสิทธิ์ (Permission Check) ======
# ตรวจว่าผู้ใช้มีสิทธิ์เข้าหน้า User Management หรือไม่
def is_admin_or_manager(user):
    if not user.is_authenticated:
        return False
    if user.is_superuser:
        return True
    try:
        # สิทธิ์เข้าถึงหน้าจัดการพนักงาน: ต้องเป็น Superuser หรือมีติ๊กถูก access_accounts ใน Profile
        return user.profile.access_accounts
    except Exception:
        return False


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

    from .models import ROLE_CHOICES

    context = {
        'users': users,
        'search_query': search_query,
        'role_filter': role_filter,
        'status_filter': status_filter,
        'roles': ROLE_CHOICES,
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

    return render(request, 'accounts/user_form.html', {'form': form, 'title': 'เพิ่มพนักงานใหม่'})


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

    return render(request, 'accounts/user_form.html', {'form': form, 'title': f'แก้ไขข้อมูลพนักงาน: {target_user.get_full_name() or target_user.username}'})


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
