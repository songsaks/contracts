from django import forms
from .models import RepairJob, RepairItem, Customer, Device, Technician, DeviceType

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
            'brand': forms.TextInput(attrs={'class': 'w-full rounded-md border-gray-300 shadow-sm focus:border-blue-500 focus:ring-blue-500 px-3 py-2', 'placeholder': 'Brand'}),
            'model': forms.TextInput(attrs={'class': 'w-full rounded-md border-gray-300 shadow-sm focus:border-blue-500 focus:ring-blue-500 px-3 py-2', 'placeholder': 'Model'}),
            'serial_number': forms.TextInput(attrs={'class': 'w-full rounded-md border-gray-300 shadow-sm focus:border-blue-500 focus:ring-blue-500 px-3 py-2', 'placeholder': 'Serial Number'}),
            'device_type': forms.Select(attrs={'class': 'w-full rounded-md border-gray-300 shadow-sm focus:border-blue-500 focus:ring-blue-500 px-3 py-2'}),
        }

class RepairJobForm(forms.ModelForm):
    class Meta:
        model = RepairJob
        fields = ['fix_id']
        widgets = {
            'fix_id': forms.TextInput(attrs={'class': 'w-full rounded-md border-gray-300 shadow-sm focus:border-blue-500 focus:ring-blue-500 px-3 py-2', 'placeholder': 'Manual Fix ID (Optional)'}),
        }

class RepairItemForm(forms.ModelForm):
    class Meta:
        model = RepairItem
        fields = ['issue_description', 'technicians', 'status', 'price']
        widgets = {
            'issue_description': forms.Textarea(attrs={'rows': 2, 'class': 'w-full rounded-md border-gray-300 shadow-sm focus:border-blue-500 focus:ring-blue-500 px-3 py-2', 'placeholder': 'Describe the issue'}),
            'technicians': forms.SelectMultiple(attrs={'class': 'w-full rounded-md border-gray-300 shadow-sm focus:border-blue-500 focus:ring-blue-500 px-3 py-2'}),
            'status': forms.Select(attrs={'class': 'w-full rounded-md border-gray-300 shadow-sm focus:border-blue-500 focus:ring-blue-500 px-3 py-2'}),
            'price': forms.NumberInput(attrs={'class': 'w-full rounded-md border-gray-300 shadow-sm focus:border-blue-500 focus:ring-blue-500 px-3 py-2'}),
        }

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

