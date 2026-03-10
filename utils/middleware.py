from django.shortcuts import redirect
from django.contrib import messages

class AppPermissionMiddleware:
    """
    Middleware to restrict access to entire apps based on user permissions.
    If a user doesn't have any permission in an app, they are redirected to the landing page.
    """
    def __init__(self, get_response):
        self.get_response = get_response

    def __call__(self, request):
        # Exclude anonymous users, superusers, and staff (optionally)
        if not request.user.is_authenticated or request.user.is_superuser:
            return self.get_response(request)

        path = request.path
        
        # Mapping of URL prefixes to Django app labels
        # Note: rentals app is served under /contracts/
        app_mapping = {
            '/contracts/': 'rentals',
            '/repairs/': 'repairs',
            '/pos/': 'pos',
            '/pms/': 'pms',
            '/payroll/': 'payroll',
            '/stocks/': 'stocks',
            '/chatbot/': 'chatbot',
        }

        # Check if current path belongs to a restricted app
        for prefix, app_label in app_mapping.items():
            if path.startswith(prefix):
                # has_module_perms returns True if the user has ANY permission in the given app
                if not request.user.has_module_perms(app_label):
                    # For Stock AI, it's a special case also checking is_staff
                    if app_label == 'stocks' and not request.user.is_staff:
                        messages.warning(request, "ระบบวิเคราะห์หุ้น AI จำกัดสิทธิ์เฉพาะผู้ดูเละระบบ (Staff) เท่านั้น")
                    else:
                        messages.warning(request, f"คุณไม่มีสิทธิ์เข้าใช้งานระบบกลุ่ม {app_label.upper()} กรุณาติดต่อผู้ดูแลระบบเพื่อขอสิทธิ์")
                    
                    return redirect('/') # Redirect to landing page
        
        return self.get_response(request)
