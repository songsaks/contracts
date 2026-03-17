# ====== accounts/forms.py ======
# Forms สำหรับสร้างและแก้ไขข้อมูลพนักงาน
# แยกเป็น 2 Form: UserCreateForm (สร้างใหม่) และ UserUpdateForm (แก้ไข)

from django import forms
from django.contrib.auth.models import User
from .models import UserProfile, ROLE_CHOICES, get_role_choices
from chat.models import ChatRoom


# ====== Form: UserCreateForm — ฟอร์มสร้างพนักงานใหม่ ======
class UserCreateForm(forms.ModelForm):
    """
    ฟอร์มสำหรับเพิ่มพนักงานใหม่เข้าระบบ
    รวม Field ของ User และ UserProfile ไว้ในฟอร์มเดียว
    """
    # ====== ข้อมูลส่วนตัว ======
    first_name = forms.CharField(label="ชื่อจริง", max_length=150, required=True)
    last_name = forms.CharField(label="นามสกุล", max_length=150, required=True)
    email = forms.EmailField(label="อีเมล", required=False)
    # ตำแหน่งงาน โหลดจาก Role model ใน DB
    role = forms.ChoiceField(label="ตำแหน่ง/บทบาท", choices=ROLE_CHOICES, required=True)

    def __init__(self, *args, **kwargs):
        super().__init__(*args, **kwargs)
        self.fields['role'].choices = get_role_choices()
    phone_number = forms.CharField(label="เบอร์โทรศัพท์", max_length=20, required=False)
    # รหัสผ่านใช้ PasswordInput เพื่อซ่อนตัวอักษรขณะพิมพ์
    password = forms.CharField(label="รหัสผ่านเข้าสู่ระบบ", widget=forms.PasswordInput, required=True, help_text="ตั้งรหัสผ่านให้พนักงาน (อย่างน้อย 6 ตัวอักษร)")

    # ====== สิทธิ์การเข้าถึงระบบย่อย (Permissions) ======
    # BooleanField แต่ละตัวควบคุมว่าพนักงานจะมีสิทธิ์เข้าระบบนั้น ๆ หรือไม่
    access_rentals = forms.BooleanField(label="เข้าใช้ระบบสัญญาเช่า", required=False)
    access_repairs = forms.BooleanField(label="เข้าใช้ระบบซ่อมบำรุง", required=False, initial=True)
    access_pos = forms.BooleanField(label="เข้าใช้ระบบขายสินค้า (POS)", required=False)
    access_pms = forms.BooleanField(label="เข้าใช้ระบบจัดการโครงการ (PMS)", required=False)
    access_chat = forms.BooleanField(label="เข้าใช้ศูนย์แชทกลาง", required=False, initial=True)
    access_payroll = forms.BooleanField(label="เข้าใช้ระบบเงินเดือน", required=False)
    access_stocks = forms.BooleanField(label="เข้าใช้ระบบวิเคราะห์หุ้น AI", required=False)
    access_accounts = forms.BooleanField(label="เข้าใช้ระบบจัดการพนักงาน (User Management)", required=False)

    # ====== สิทธิ์เข้าห้องแชทส่วนตัว ======
    chat_rooms = forms.ModelMultipleChoiceField(
        queryset=ChatRoom.objects.filter(is_active=True, is_private=True),
        widget=forms.CheckboxSelectMultiple,
        required=False,
        label="อนุญาตให้เข้าห้องแชท (Private Rooms)"
    )

    class Meta:
        model = User
        # Field ที่มาจาก Django User Model โดยตรง
        fields = ['username', 'first_name', 'last_name', 'email']
        labels = {
            'username': 'ชื่อผู้ใช้ (Username)',
        }
        help_texts = {
            'username': 'ใช้สำหรับล็อกอินเข้าระบบ (ภาษาอังกฤษหรือตัวเลข)',
        }

    def save(self, commit=True):
        """
        Override save() เพื่อบันทึกทั้ง User และ UserProfile พร้อมกัน
        รวมถึงตั้งรหัสผ่านด้วย set_password() เพื่อให้ Django hash รหัสผ่านอย่างปลอดภัย
        """
        user = super().save(commit=False)
        # ใช้ set_password แทนการกำหนด user.password ตรง ๆ เพื่อให้รหัสผ่านถูก hash
        user.set_password(self.cleaned_data['password'])
        if commit:
            user.save()
            # สร้าง UserProfile ที่ผูกกับ User นี้ (get_or_create เพื่อกันซ้ำ)
            profile, created = UserProfile.objects.get_or_create(user=user)
            profile.role = self.cleaned_data['role']
            profile.phone_number = self.cleaned_data['phone_number']

            # บันทึกสิทธิ์การเข้าระบบย่อยแต่ละตัว
            profile.access_rentals = self.cleaned_data.get('access_rentals', False)
            profile.access_repairs = self.cleaned_data.get('access_repairs', False)
            profile.access_pos = self.cleaned_data.get('access_pos', False)
            profile.access_pms = self.cleaned_data.get('access_pms', False)
            profile.access_chat = self.cleaned_data.get('access_chat', False)
            profile.access_payroll = self.cleaned_data.get('access_payroll', False)
            profile.access_stocks = self.cleaned_data.get('access_stocks', False)
            profile.access_accounts = self.cleaned_data.get('access_accounts', False)
            profile.save()

            # บันทึกห้องแชทที่ได้รับอนุญาต
            if 'chat_rooms' in self.cleaned_data:
                selected_rooms = self.cleaned_data['chat_rooms']
                for room in selected_rooms:
                    room.allowed_users.add(user)
        return user


# ====== Form: UserUpdateForm — ฟอร์มแก้ไขข้อมูลพนักงาน ======
class UserUpdateForm(forms.ModelForm):
    """
    ฟอร์มสำหรับแก้ไขข้อมูลพนักงานที่มีอยู่แล้ว
    รองรับการเปลี่ยนรหัสผ่าน, อัปโหลดรูปโปรไฟล์ และจัดการสิทธิ์
    """
    # ====== ข้อมูลโปรไฟล์เพิ่มเติม ======
    role = forms.ChoiceField(label="ตำแหน่ง/บทบาท", choices=ROLE_CHOICES, required=True)
    phone_number = forms.CharField(label="เบอร์โทรศัพท์", max_length=20, required=False)
    avatar = forms.ImageField(label="รูปโปรไฟล์", required=False)
    # (choices will be overridden in __init__ below)
    # new_password เป็น optional — ถ้าเว้นว่างไว้จะไม่เปลี่ยนรหัสผ่าน
    new_password = forms.CharField(label="ตั้งรหัสผ่านใหม่ (ทิ้งว่างไว้ถ้าไม่ต้องการเปลี่ยน)", widget=forms.PasswordInput, required=False, help_text="กรอกเพื่อล้างรหัสผ่านเดิมเป็นรหัสผ่านใหม่นี้")

    # ====== สิทธิ์การเข้าถึงระบบย่อย (Permissions) ======
    access_rentals = forms.BooleanField(label="เข้าใช้ระบบสัญญาเช่า", required=False)
    access_repairs = forms.BooleanField(label="เข้าใช้ระบบซ่อมบำรุง", required=False)
    access_pos = forms.BooleanField(label="เข้าใช้ระบบขายสินค้า (POS)", required=False)
    access_pms = forms.BooleanField(label="เข้าใช้ระบบจัดการโครงการ (PMS)", required=False)
    access_chat = forms.BooleanField(label="เข้าใช้ศูนย์แชทกลาง", required=False)
    access_payroll = forms.BooleanField(label="เข้าใช้ระบบเงินเดือน", required=False)
    access_stocks = forms.BooleanField(label="เข้าใช้ระบบวิเคราะห์หุ้น AI", required=False)
    access_accounts = forms.BooleanField(label="เข้าใช้ระบบจัดการพนักงาน (User Management)", required=False)

    # ====== สิทธิ์เข้าห้องแชทส่วนตัว ======
    chat_rooms = forms.ModelMultipleChoiceField(
        queryset=ChatRoom.objects.filter(is_active=True, is_private=True),
        widget=forms.CheckboxSelectMultiple,
        required=False,
        label="อนุญาตให้เข้าห้องแชท (Private Rooms)"
    )

    class Meta:
        model = User
        # Field ที่มาจาก Django User Model (ไม่รวม username เพราะไม่อนุญาตให้แก้ใน Update)
        fields = ['first_name', 'last_name', 'email', 'is_active']
        labels = {
            'first_name': 'ชื่อจริง',
            'last_name': 'นามสกุล',
            'email': 'อีเมล',
            'is_active': 'สถานะการทำงาน (Active)',
        }
        help_texts = {
            'is_active': 'นำเครื่องหมายถูกออก หากพนักงานลาออกหรือระงับการใช้งาน',
        }

    def __init__(self, *args, **kwargs):
        """
        โหลดค่าเริ่มต้นจาก UserProfile ของพนักงานที่ถูกแก้ไข
        เพื่อให้ฟอร์มแสดงข้อมูลปัจจุบันอยู่แล้วเมื่อเปิดหน้า Edit
        """
        super().__init__(*args, **kwargs)
        # โหลด role choices จาก DB
        self.fields['role'].choices = get_role_choices()
        if self.instance and hasattr(self.instance, 'profile'):
            self.fields['role'].initial = self.instance.profile.role
            self.fields['phone_number'].initial = self.instance.profile.phone_number
            self.fields['avatar'].initial = self.instance.profile.avatar

            # โหลดสิทธิ์ปัจจุบันของพนักงานเพื่อให้ Checkbox แสดงสถานะที่ถูกต้อง
            self.fields['access_rentals'].initial = self.instance.profile.access_rentals
            self.fields['access_repairs'].initial = self.instance.profile.access_repairs
            self.fields['access_pos'].initial = self.instance.profile.access_pos
            self.fields['access_pms'].initial = self.instance.profile.access_pms
            self.fields['access_chat'].initial = self.instance.profile.access_chat
            self.fields['access_payroll'].initial = self.instance.profile.access_payroll
            self.fields['access_stocks'].initial = self.instance.profile.access_stocks
            self.fields['access_accounts'].initial = self.instance.profile.access_accounts

            # โหลดห้องแชทที่ User นี้มีสิทธิ์เข้าถึงอยู่แล้ว
            if hasattr(self.instance, 'allowed_chat_rooms'):
                self.fields['chat_rooms'].initial = self.instance.allowed_chat_rooms.all()

    def save(self, commit=True):
        """
        Override save() เพื่ออัปเดตทั้ง User และ UserProfile
        เปลี่ยนรหัสผ่านเฉพาะเมื่อมีการกรอก new_password เข้ามาเท่านั้น
        """
        user = super().save(commit=False)
        # เปลี่ยนรหัสผ่านเฉพาะเมื่อผู้ดูแลระบบกรอก new_password มาด้วย
        if self.cleaned_data.get('new_password'):
            user.set_password(self.cleaned_data['new_password'])
        if commit:
            user.save()
            # อัปเดต UserProfile ที่ผูกกับ User นี้
            profile, created = UserProfile.objects.get_or_create(user=user)
            profile.role = self.cleaned_data['role']
            profile.phone_number = self.cleaned_data['phone_number']
            # อัปเดตรูปโปรไฟล์เฉพาะเมื่อมีการอัปโหลดไฟล์ใหม่
            if self.cleaned_data.get('avatar'):
                profile.avatar = self.cleaned_data['avatar']

            # บันทึกสิทธิ์การเข้าระบบย่อยแต่ละตัว
            profile.access_rentals = self.cleaned_data.get('access_rentals', False)
            profile.access_repairs = self.cleaned_data.get('access_repairs', False)
            profile.access_pos = self.cleaned_data.get('access_pos', False)
            profile.access_pms = self.cleaned_data.get('access_pms', False)
            profile.access_chat = self.cleaned_data.get('access_chat', False)
            profile.access_payroll = self.cleaned_data.get('access_payroll', False)
            profile.access_stocks = self.cleaned_data.get('access_stocks', False)
            profile.access_accounts = self.cleaned_data.get('access_accounts', False)
            profile.save()

            # อัปเดตห้องแชทที่ได้รับอนุญาต (Clear ของเดิมแล้วใส่ใหม่)
            if 'chat_rooms' in self.cleaned_data:
                # เข้าถึง M2M ผ่าน user (related_name='allowed_chat_rooms')
                user.allowed_chat_rooms.clear()
                selected_rooms = self.cleaned_data['chat_rooms']
                for room in selected_rooms:
                    room.allowed_users.add(user)
        return user
