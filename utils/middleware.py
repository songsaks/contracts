from django.shortcuts import redirect
from django.contrib import messages


# URL prefix → ชื่อ field ใน UserProfile
_APP_ACCESS_MAP = {
    '/contracts/': 'access_rentals',
    '/repairs/':   'access_repairs',
    '/pos/':       'access_pos',
    '/pms/':       'access_pms',
    '/payroll/':   'access_payroll',
    '/stocks/':    'access_stocks',
    '/chat/':      'access_chat',
    # ใช้ prefix เฉพาะส่วน management — ไม่รวม /accounts/login/, /accounts/logout/
    '/accounts/users/': 'access_accounts',
    '/accounts/roles/': 'access_accounts',
}

# ชื่อแสดงผลสำหรับแต่ละ app
_APP_NAMES = {
    'access_rentals':  'ระบบสัญญาเช่า',
    'access_repairs':  'ระบบซ่อมบำรุง',
    'access_pos':      'ระบบขายสินค้า (POS)',
    'access_pms':      'ระบบจัดการโครงการ (PMS)',
    'access_payroll':  'ระบบเงินเดือน',
    'access_stocks':   'ระบบวิเคราะห์หุ้น AI',
    'access_chat':     'ศูนย์แชทกลาง',
    'access_accounts': 'ระบบจัดการพนักงาน',
}


class AppPermissionMiddleware:
    """
    ตรวจสิทธิ์การเข้าถึงแต่ละ app โดยตรงจาก UserProfile.access_* flag
    - superuser / is_staff → ผ่านทั้งหมด (admin/manager เข้าได้ทุก app)
    - user อื่น → ต้องมี access_<app>=True ใน profile
    """

    def __init__(self, get_response):
        self.get_response = get_response

    def __call__(self, request):
        user = request.user

        # anonymous, superuser, staff → ไม่ต้องตรวจ
        if not user.is_authenticated or user.is_superuser or user.is_staff:
            return self.get_response(request)

        path = request.path

        for prefix, access_field in _APP_ACCESS_MAP.items():
            if path.startswith(prefix):
                try:
                    has_access = getattr(user.profile, access_field, False)
                except Exception:
                    has_access = False

                if not has_access:
                    app_name = _APP_NAMES.get(access_field, access_field)
                    messages.warning(
                        request,
                        f"คุณไม่มีสิทธิ์เข้าใช้งาน{app_name} "
                        f"กรุณาติดต่อผู้ดูแลระบบเพื่อขอสิทธิ์"
                    )
                    return redirect('/')
                break  # พบ prefix แล้ว หยุดวน

        return self.get_response(request)
