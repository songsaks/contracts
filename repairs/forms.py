from django import forms
from .models import RepairJob, RepairItem, Customer, Device, Technician, DeviceType, Brand

class CustomerForm(forms.ModelForm):
    class Meta:
        model = Customer
        fields = ['name', 'contact_number', 'address']
        widgets = {
            'name': forms.TextInput(attrs={'class': 'form-control', 'placeholder': 'ชื่อ-นามสกุล หรือ บริษัท'}),
            'contact_number': forms.TextInput(attrs={'class': 'form-control', 'placeholder': 'เบอร์โทรศัพท์'}),
            'address': forms.Textarea(attrs={'rows': 3, 'class': 'form-control', 'placeholder': 'ที่อยู่ (ถ้ามี)'}),
        }

class DeviceForm(forms.ModelForm):
    class Meta:
        model = Device
        fields = ['brand', 'model', 'serial_number', 'device_type']
        widgets = {
            'brand': forms.Select(attrs={'class': 'form-select'}),
            'model': forms.TextInput(attrs={'class': 'form-control', 'placeholder': 'รุ่น (Model)'}),
            'serial_number': forms.TextInput(attrs={'class': 'form-control', 'placeholder': 'Serial Number'}),
            'device_type': forms.Select(attrs={'class': 'form-select'}),
        }
    
    def __init__(self, *args, **kwargs):
        super().__init__(*args, **kwargs)
        self.fields['device_type'].required = False
        self.fields['brand'].required = False
        self.fields['model'].required = False
        self.fields['serial_number'].required = False

class RepairJobForm(forms.ModelForm):
    class Meta:
        model = RepairJob
        fields = ['fix_id', 'created_at']
        widgets = {
            'fix_id': forms.TextInput(attrs={'class': 'form-control', 'placeholder': 'J...'}),
            'created_at': forms.DateTimeInput(attrs={'type': 'datetime-local', 'class': 'form-control'}),
        }
    
    def __init__(self, *args, **kwargs):
        super().__init__(*args, **kwargs)
        self.fields['created_at'].required = False
        self.fields['created_at'].input_formats = ['%Y-%m-%dT%H:%M']

class RepairItemForm(forms.ModelForm):
    class Meta:
        model = RepairItem
        fields = ['issue_description', 'accessories', 'technicians', 'status', 'status_note', 'price']
        widgets = {
            'issue_description': forms.Textarea(attrs={'rows': 2, 'class': 'form-control', 'placeholder': 'ระบุอาการเสียที่ลูกค้าแจ้ง'}),
            'accessories': forms.TextInput(attrs={'class': 'form-control', 'placeholder': 'เช่น สายชาร์จ, กระเป๋า'}),
            'technicians': forms.SelectMultiple(attrs={'class': 'form-select', 'size': '3'}),
            'status': forms.Select(attrs={'class': 'form-select'}),
            'status_note': forms.TextInput(attrs={'class': 'form-control', 'placeholder': 'หมายเหตุสถานะ'}),
            'price': forms.NumberInput(attrs={'class': 'form-control', 'placeholder': '0.00'}),
        }
    
    def __init__(self, *args, **kwargs):
        super().__init__(*args, **kwargs)
        self.fields['technicians'].required = False
        
        # If creating new repair job, restrict status to 'RECEIVED' only
        if not self.instance.pk:
            self.fields['status'].choices = [('RECEIVED', 'รับแจ้ง')]
            self.fields['status'].initial = 'RECEIVED'

class TechnicianForm(forms.ModelForm):
    class Meta:
        model = Technician
        fields = ['name', 'expertise']
        widgets = {
            'name': forms.TextInput(attrs={'class': 'form-control'}),
            'expertise': forms.TextInput(attrs={'class': 'form-control'}),
        }

class DeviceTypeForm(forms.ModelForm):
    class Meta:
        model = DeviceType
        fields = ['name', 'description']
        widgets = {
            'name': forms.TextInput(attrs={'class': 'form-control'}),
            'description': forms.Textarea(attrs={'rows': 2, 'class': 'form-control'}),
        }

class BrandForm(forms.ModelForm):
    class Meta:
        model = Brand
        fields = ['name']
        widgets = {
            'name': forms.TextInput(attrs={'class': 'form-control'}),
        }

