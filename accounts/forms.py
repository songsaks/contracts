from django import forms
from django.contrib.auth.models import User
from .models import UserProfile, ROLE_CHOICES

class UserCreateForm(forms.ModelForm):
    first_name = forms.CharField(label="ชื่อจริง", max_length=150, required=True)
    last_name = forms.CharField(label="นามสกุล", max_length=150, required=True)
    email = forms.EmailField(label="อีเมล", required=False)
    role = forms.ChoiceField(label="ตำแหน่ง/บทบาท", choices=ROLE_CHOICES, required=True)
    phone_number = forms.CharField(label="เบอร์โทรศัพท์", max_length=20, required=False)
    password = forms.CharField(label="รหัสผ่านเข้าสู่ระบบ", widget=forms.PasswordInput, required=True, help_text="ตั้งรหัสผ่านให้พนักงาน (อย่างน้อย 6 ตัวอักษร)")
    
    # Permissions
    access_rentals = forms.BooleanField(label="เข้าใช้ระบบสัญญาเช่า", required=False)
    access_repairs = forms.BooleanField(label="เข้าใช้ระบบซ่อมบำรุง", required=False, initial=True)
    access_pos = forms.BooleanField(label="เข้าใช้ระบบขายสินค้า (POS)", required=False)
    access_pms = forms.BooleanField(label="เข้าใช้ระบบจัดการโครงการ (PMS)", required=False)
    access_chat = forms.BooleanField(label="เข้าใช้ศูนย์แชทกลาง", required=False, initial=True)
    access_payroll = forms.BooleanField(label="เข้าใช้ระบบเงินเดือน", required=False)
    access_stocks = forms.BooleanField(label="เข้าใช้ระบบวิเคราะห์หุ้น AI", required=False)
    access_accounts = forms.BooleanField(label="เข้าใช้ระบบจัดการพนักงาน (User Management)", required=False)

    class Meta:
        model = User
        fields = ['username', 'first_name', 'last_name', 'email']
        labels = {
            'username': 'ชื่อผู้ใช้ (Username)',
        }
        help_texts = {
            'username': 'ใช้สำหรับล็อกอินเข้าระบบ (ภาษาอังกฤษหรือตัวเลข)',
        }

    def save(self, commit=True):
        user = super().save(commit=False)
        user.set_password(self.cleaned_data['password'])
        if commit:
            user.save()
            profile, created = UserProfile.objects.get_or_create(user=user)
            profile.role = self.cleaned_data['role']
            profile.phone_number = self.cleaned_data['phone_number']
            
            # Save permissions
            profile.access_rentals = self.cleaned_data.get('access_rentals', False)
            profile.access_repairs = self.cleaned_data.get('access_repairs', False)
            profile.access_pos = self.cleaned_data.get('access_pos', False)
            profile.access_pms = self.cleaned_data.get('access_pms', False)
            profile.access_chat = self.cleaned_data.get('access_chat', False)
            profile.access_payroll = self.cleaned_data.get('access_payroll', False)
            profile.access_stocks = self.cleaned_data.get('access_stocks', False)
            profile.access_accounts = self.cleaned_data.get('access_accounts', False)
            
            profile.save()
        return user


class UserUpdateForm(forms.ModelForm):
    role = forms.ChoiceField(label="ตำแหน่ง/บทบาท", choices=ROLE_CHOICES, required=True)
    phone_number = forms.CharField(label="เบอร์โทรศัพท์", max_length=20, required=False)
    avatar = forms.ImageField(label="รูปโปรไฟล์", required=False)
    new_password = forms.CharField(label="ตั้งรหัสผ่านใหม่ (ทิ้งว่างไว้ถ้าไม่ต้องการเปลี่ยน)", widget=forms.PasswordInput, required=False, help_text="กรอกเพื่อล้างรหัสผ่านเดิมเป็นรหัสผ่านใหม่นี้")

    # Permissions
    access_rentals = forms.BooleanField(label="เข้าใช้ระบบสัญญาเช่า", required=False)
    access_repairs = forms.BooleanField(label="เข้าใช้ระบบซ่อมบำรุง", required=False)
    access_pos = forms.BooleanField(label="เข้าใช้ระบบขายสินค้า (POS)", required=False)
    access_pms = forms.BooleanField(label="เข้าใช้ระบบจัดการโครงการ (PMS)", required=False)
    access_chat = forms.BooleanField(label="เข้าใช้ศูนย์แชทกลาง", required=False)
    access_payroll = forms.BooleanField(label="เข้าใช้ระบบเงินเดือน", required=False)
    access_stocks = forms.BooleanField(label="เข้าใช้ระบบวิเคราะห์หุ้น AI", required=False)
    access_accounts = forms.BooleanField(label="เข้าใช้ระบบจัดการพนักงาน (User Management)", required=False)

    class Meta:
        model = User
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
        super().__init__(*args, **kwargs)
        if self.instance and hasattr(self.instance, 'profile'):
            self.fields['role'].initial = self.instance.profile.role
            self.fields['phone_number'].initial = self.instance.profile.phone_number
            self.fields['avatar'].initial = self.instance.profile.avatar
            
            # Load permissions
            self.fields['access_rentals'].initial = self.instance.profile.access_rentals
            self.fields['access_repairs'].initial = self.instance.profile.access_repairs
            self.fields['access_pos'].initial = self.instance.profile.access_pos
            self.fields['access_pms'].initial = self.instance.profile.access_pms
            self.fields['access_chat'].initial = self.instance.profile.access_chat
            self.fields['access_payroll'].initial = self.instance.profile.access_payroll
            self.fields['access_stocks'].initial = self.instance.profile.access_stocks
            self.fields['access_accounts'].initial = self.instance.profile.access_accounts

    def save(self, commit=True):
        user = super().save(commit=False)
        if self.cleaned_data.get('new_password'):
            user.set_password(self.cleaned_data['new_password'])
        if commit:
            user.save()
            profile, created = UserProfile.objects.get_or_create(user=user)
            profile.role = self.cleaned_data['role']
            profile.phone_number = self.cleaned_data['phone_number']
            if self.cleaned_data.get('avatar'):
                profile.avatar = self.cleaned_data['avatar']
            
            # Save permissions
            profile.access_rentals = self.cleaned_data.get('access_rentals', False)
            profile.access_repairs = self.cleaned_data.get('access_repairs', False)
            profile.access_pos = self.cleaned_data.get('access_pos', False)
            profile.access_pms = self.cleaned_data.get('access_pms', False)
            profile.access_chat = self.cleaned_data.get('access_chat', False)
            profile.access_payroll = self.cleaned_data.get('access_payroll', False)
            profile.access_stocks = self.cleaned_data.get('access_stocks', False)
            profile.access_accounts = self.cleaned_data.get('access_accounts', False)
            
            profile.save()
        return user
