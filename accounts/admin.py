from django.contrib import admin
from django.contrib.auth.admin import UserAdmin as BaseUserAdmin
from django.contrib.auth import get_user_model
from .models import UserProfile, Role

User = get_user_model()


# ─── Inline: แสดง UserProfile ซ้อนในหน้า User ───────────────────
class UserProfileInline(admin.StackedInline):
    model = UserProfile
    can_delete = False
    verbose_name = "โปรไฟล์ / สิทธิ์การเข้าถึง"
    verbose_name_plural = "โปรไฟล์ / สิทธิ์การเข้าถึง"
    fields = (
        'role',
        'phone_number',
        'avatar',
        ('access_repairs', 'access_chat'),
        ('access_pms', 'access_rentals'),
        ('access_pos', 'access_payroll'),
        ('access_stocks', 'access_accounts'),
    )


# ─── ขยาย UserAdmin เดิมให้รวม Inline ─────────────────────────
class UserAdmin(BaseUserAdmin):
    inlines = (UserProfileInline,)
    list_display = ('username', 'first_name', 'last_name', 'get_role', 'is_staff', 'is_active', 'email')
    list_filter  = ('is_staff', 'is_superuser', 'is_active', 'profile__role')
    list_display_links = ('username', 'first_name', 'last_name')

    def get_role(self, obj):
        try:
            return obj.profile.get_role_display()
        except UserProfile.DoesNotExist:
            return '-'
    get_role.short_description = 'ตำแหน่ง'
    get_role.admin_order_field = 'profile__role'


# ─── Standalone: จัดการ UserProfile โดยตรง ──────────────────────
@admin.register(UserProfile)
class UserProfileAdmin(admin.ModelAdmin):
    list_display  = ('user', 'role', 'phone_number',
                     'access_pms', 'access_repairs', 'access_chat',
                     'access_rentals', 'access_payroll', 'access_accounts')
    list_filter   = ('role', 'access_pms', 'access_repairs', 'access_chat',
                     'access_rentals', 'access_payroll')
    search_fields = ('user__username', 'user__first_name', 'user__last_name', 'user__email')
    list_editable = ('role',
                     'access_pms', 'access_repairs', 'access_chat',
                     'access_rentals', 'access_payroll', 'access_accounts')
    ordering      = ('user__username',)
    fieldsets = (
        ('ผู้ใช้', {
            'fields': ('user', 'role', 'phone_number', 'avatar'),
        }),
        ('สิทธิ์การเข้าถึงระบบ', {
            'fields': (
                ('access_repairs', 'access_chat'),
                ('access_pms', 'access_rentals'),
                ('access_pos', 'access_payroll'),
                ('access_stocks', 'access_accounts'),
            ),
        }),
    )


# ─── Role: จัดการตำแหน่ง/บทบาท ──────────────────────────────────
@admin.register(Role)
class RoleAdmin(admin.ModelAdmin):
    list_display  = ('name', 'code', 'is_staff_role', 'is_technician_role', 'order', 'badge_color')
    list_editable = ('is_staff_role', 'is_technician_role', 'order')
    search_fields = ('name', 'code')
    ordering      = ('order', 'name')


# ─── Unregister User เดิม แล้ว Register ใหม่พร้อม Inline ────────
admin.site.unregister(User)
admin.site.register(User, UserAdmin)
