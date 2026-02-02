from django import forms
from .models import RepairJob, RepairItem, Customer, Device, Technician, DeviceType, Brand

class CustomerForm(forms.ModelForm):
    class Meta:
        model = Customer
        fields = ['name', 'contact_number', 'address']
        widgets = {
            'name': forms.TextInput(attrs={'class': 'w-full rounded-md border-gray-300 shadow-sm focus:border-blue-500 focus:ring-blue-500 px-3 py-2'}),
            'contact_number': forms.TextInput(attrs={'class': 'w-full rounded-md border-gray-300 shadow-sm focus:border-blue-500 focus:ring-blue-500 px-3 py-2'}),
            'address': forms.Textarea(attrs={'rows': 3, 'class': 'w-full rounded-md border-gray-300 shadow-sm focus:border-blue-500 focus:ring-blue-500 px-3 py-2'}),
        }

class DeviceForm(forms.ModelForm):
    class Meta:
        model = Device
        fields = ['brand', 'model', 'serial_number', 'device_type']
        widgets = {
            'brand': forms.Select(attrs={'class': 'w-full rounded-md border-gray-300 shadow-sm focus:border-blue-500 focus:ring-blue-500 px-3 py-2'}),
            'model': forms.TextInput(attrs={'class': 'w-full rounded-md border-gray-300 shadow-sm focus:border-blue-500 focus:ring-blue-500 px-3 py-2', 'placeholder': 'Model'}),
            'serial_number': forms.TextInput(attrs={'class': 'w-full rounded-md border-gray-300 shadow-sm focus:border-blue-500 focus:ring-blue-500 px-3 py-2', 'placeholder': 'Serial Number'}),
            'device_type': forms.Select(attrs={'class': 'w-full rounded-md border-gray-300 shadow-sm focus:border-blue-500 focus:ring-blue-500 px-3 py-2'}),
        }

class RepairJobForm(forms.ModelForm):
    class Meta:
        model = RepairJob
        fields = ['fix_id', 'created_at']
        widgets = {
            'fix_id': forms.TextInput(attrs={'class': 'w-full rounded-md border-gray-300 shadow-sm focus:border-blue-500 focus:ring-blue-500 px-3 py-2', 'placeholder': 'Manual Fix ID (Optional)'}),
            'created_at': forms.DateTimeInput(attrs={'type': 'datetime-local', 'class': 'w-full rounded-md border-gray-300 shadow-sm focus:border-blue-500 focus:ring-blue-500 px-3 py-2'}),
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
            'issue_description': forms.Textarea(attrs={'rows': 2, 'class': 'w-full rounded-md border-gray-300 shadow-sm focus:border-blue-500 focus:ring-blue-500 px-3 py-2', 'placeholder': 'ระบุอาการเสีย'}),
            'accessories': forms.TextInput(attrs={'class': 'w-full rounded-md border-gray-300 shadow-sm focus:border-blue-500 focus:ring-blue-500 px-3 py-2', 'placeholder': 'เช่น สายชาร์จ, กระเป๋า, เมาส์'}),
            'technicians': forms.SelectMultiple(attrs={'class': 'w-full rounded-md border-gray-300 shadow-sm focus:border-blue-500 focus:ring-blue-500 px-3 py-2'}),
            'status': forms.Select(attrs={'class': 'w-full rounded-md border-gray-300 shadow-sm focus:border-blue-500 focus:ring-blue-500 px-3 py-2'}),
            'status_note': forms.TextInput(attrs={'class': 'w-full rounded-md border-gray-300 shadow-sm focus:border-blue-500 focus:ring-blue-500 px-3 py-2', 'placeholder': 'บันทึกสถานะเพิ่มเติม (เช่น รออะไหล่)'}),
            'price': forms.NumberInput(attrs={'class': 'w-full rounded-md border-gray-300 shadow-sm focus:border-blue-500 focus:ring-blue-500 px-3 py-2'}),
        }
    
    def __init__(self, *args, **kwargs):
        super().__init__(*args, **kwargs)
        self.fields['technicians'].required = False

class TechnicianForm(forms.ModelForm):
    class Meta:
        model = Technician
        fields = ['name', 'expertise']
        widgets = {
            'name': forms.TextInput(attrs={'class': 'w-full rounded-md border-gray-300 shadow-sm focus:border-blue-500 focus:ring-blue-500 px-3 py-2'}),
            'expertise': forms.TextInput(attrs={'class': 'w-full rounded-md border-gray-300 shadow-sm focus:border-blue-500 focus:ring-blue-500 px-3 py-2'}),
        }

class DeviceTypeForm(forms.ModelForm):
    class Meta:
        model = DeviceType
        fields = ['name', 'description']
        widgets = {
            'name': forms.TextInput(attrs={'class': 'w-full rounded-md border-gray-300 shadow-sm focus:border-blue-500 focus:ring-blue-500 px-3 py-2'}),
            'description': forms.Textarea(attrs={'rows': 2, 'class': 'w-full rounded-md border-gray-300 shadow-sm focus:border-blue-500 focus:ring-blue-500 px-3 py-2'}),
        }

class BrandForm(forms.ModelForm):
    class Meta:
        model = Brand
        fields = ['name']
        widgets = {
            'name': forms.TextInput(attrs={'class': 'w-full rounded-md border-gray-300 shadow-sm focus:border-blue-500 focus:ring-blue-500 px-3 py-2'}),
        }

