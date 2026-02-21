from django import forms
from decimal import Decimal
from .models import Project, ProductItem, Customer, Supplier, ProjectOwner, CustomerRequirement, SLAPlan

class CustomerForm(forms.ModelForm):
    class Meta:
        model = Customer
        fields = [
            'name', 'phone', 'email', 'address', 'sla_plan',
            'tax_id', 'branch', 'segment', 'industry', 'source',
            'line_id', 'facebook', 'map_url', 'notes'
        ]
        widgets = {
            'name': forms.TextInput(attrs={'class': 'form-control', 'placeholder': 'ชื่อบริษัท/องค์กร หรือ ชื่อลูกค้า'}),
            'phone': forms.TextInput(attrs={'class': 'form-control', 'placeholder': '081-xxx-xxxx'}),
            'email': forms.EmailInput(attrs={'class': 'form-control', 'placeholder': 'example@mail.com'}),
            'address': forms.Textarea(attrs={'class': 'form-control', 'rows': 2}),
            'sla_plan': forms.Select(attrs={'class': 'form-select'}),
            'tax_id': forms.TextInput(attrs={'class': 'form-control', 'placeholder': 'เลข 13 หลัก'}),
            'branch': forms.TextInput(attrs={'class': 'form-control', 'placeholder': 'เช่น สำนักงานใหญ่'}),
            'segment': forms.Select(attrs={'class': 'form-select'}),
            'industry': forms.TextInput(attrs={'class': 'form-control', 'placeholder': 'เช่น การเกษตร, ไอที'}),
            'source': forms.TextInput(attrs={'class': 'form-control', 'placeholder': 'เช่น แนะนำต่อ, Google'}),
            'line_id': forms.TextInput(attrs={'class': 'form-control'}),
            'facebook': forms.TextInput(attrs={'class': 'form-control'}),
            'map_url': forms.URLInput(attrs={'class': 'form-control', 'placeholder': 'https://goo.gl/maps/...'}),
            'notes': forms.Textarea(attrs={'class': 'form-control', 'rows': 2}),
        }
        labels = {
            'name': 'ชื่อลูกค้า/องค์กร',
            'sla_plan': 'ระดับการให้บริการ (SLA)',
            'phone': 'เบอร์โทรศัพท์',
            'email': 'อีเมล',
            'address': 'ที่อยู่',
        }

class SLAPlanForm(forms.ModelForm):
    class Meta:
        model = SLAPlan
        fields = ['name', 'response_time_hours', 'resolution_time_hours', 'is_active', 'description']
        widgets = {
            'name': forms.TextInput(attrs={'class': 'form-control', 'placeholder': 'เช่น Gold, Silver, Bronze'}),
            'response_time_hours': forms.NumberInput(attrs={'class': 'form-control', 'min': 1}),
            'resolution_time_hours': forms.NumberInput(attrs={'class': 'form-control', 'min': 1}),
            'is_active': forms.CheckboxInput(attrs={'class': 'form-check-input'}),
            'description': forms.Textarea(attrs={'class': 'form-control', 'rows': 3}),
        }

class SupplierForm(forms.ModelForm):
    class Meta:
        model = Supplier
        fields = ['name', 'contact_name', 'phone', 'email', 'address']
        widgets = {
            'name': forms.TextInput(attrs={'class': 'form-control'}),
            'contact_name': forms.TextInput(attrs={'class': 'form-control'}),
            'phone': forms.TextInput(attrs={'class': 'form-control'}),
            'email': forms.EmailInput(attrs={'class': 'form-control'}),
            'address': forms.Textarea(attrs={'class': 'form-control', 'rows': 3}),
        }
        labels = {
            'name': 'ชื่อร้าน/บริษัท',
            'contact_name': 'ชื่อผู้ติดต่อ',
            'phone': 'เบอร์โทรศัพท์',
            'email': 'อีเมล',
            'address': 'ที่อยู่',
        }

class ProjectOwnerForm(forms.ModelForm):
    class Meta:
        model = ProjectOwner
        fields = ['name', 'position', 'email', 'phone']
        widgets = {
            'name': forms.TextInput(attrs={'class': 'form-control'}),
            'position': forms.TextInput(attrs={'class': 'form-control'}),
            'email': forms.EmailInput(attrs={'class': 'form-control'}),
            'phone': forms.TextInput(attrs={'class': 'form-control'}),
        }

class ProjectForm(forms.ModelForm):
    project_value = forms.DecimalField(
        max_digits=12, decimal_places=2, required=False,
        label='มูลค่าโครงการ (บาท)',
        widget=forms.NumberInput(attrs={'class': 'form-control', 'placeholder': '0.00', 'step': '0.01'}),
    )

    class Meta:
        model = Project
        fields = ['name', 'customer', 'owner', 'status', 'start_date', 'deadline', 'description']
        widgets = {
            'name': forms.TextInput(attrs={'class': 'form-control'}),
            'customer': forms.Select(attrs={'class': 'form-select'}),
            'owner': forms.Select(attrs={'class': 'form-select'}),
            'status': forms.Select(attrs={'class': 'form-select'}),
            'start_date': forms.DateInput(attrs={'class': 'form-control', 'type': 'date'}),
            'deadline': forms.DateInput(attrs={'class': 'form-control', 'type': 'date'}),
            'description': forms.Textarea(attrs={'class': 'form-control', 'rows': 3}),
        }

    def __init__(self, *args, **kwargs):
        super(ProjectForm, self).__init__(*args, **kwargs)
        # Exclude CANCELLED from choices
        choices = [c for c in Project.Status.choices if c[0] != Project.Status.CANCELLED]
        self.fields['status'].choices = choices

class SalesServiceJobForm(forms.ModelForm):
    project_value = forms.DecimalField(
        max_digits=12, decimal_places=2, required=False,
        label='มูลค่าโครงการ (บาท)',
        widget=forms.NumberInput(attrs={'class': 'form-control', 'placeholder': '0.00', 'step': '0.01'}),
    )

    class Meta:
        model = Project
        fields = ['name', 'customer', 'owner', 'status', 'start_date', 'deadline', 'description']
        widgets = {
            'name': forms.TextInput(attrs={'class': 'form-control', 'placeholder': 'ชื่องานขาย/บริการ'}),
            'customer': forms.Select(attrs={'class': 'form-select'}),
            'owner': forms.Select(attrs={'class': 'form-select'}),
            'status': forms.Select(attrs={'class': 'form-select'}),
            'start_date': forms.DateInput(attrs={'class': 'form-control', 'type': 'date'}),
            'deadline': forms.DateInput(attrs={'class': 'form-control', 'type': 'date'}),
            'description': forms.Textarea(attrs={'class': 'form-control', 'rows': 3}),
        }

    def __init__(self, *args, **kwargs):
        job_type = kwargs.pop('job_type', None)
        super(SalesServiceJobForm, self).__init__(*args, **kwargs)
        
        # If job_type not passed, try to get from instance
        if not job_type and self.instance and self.instance.pk:
            job_type = self.instance.job_type

        if job_type == Project.JobType.REPAIR:
            REPAIR_CHOICES = [
                (Project.Status.SOURCING, 'รับแจ้งซ่อม'),
                (Project.Status.ORDERING, 'จัดคิวซ่อม'),
                (Project.Status.DELIVERY, 'ซ่อม'),
                (Project.Status.ACCEPTED, 'รอ'),
                (Project.Status.CLOSED, 'ปิดงานซ่อม'),
            ]
            self.fields['status'].choices = REPAIR_CHOICES
        elif job_type == Project.JobType.SERVICE:
             SERVICE_CHOICES = [
                (Project.Status.SOURCING, 'จัดหา'),
                (Project.Status.QUOTED, 'เสนอราคา'),
                (Project.Status.ORDERING, 'สั่งซื้อ'),
                (Project.Status.RECEIVED_QC, 'รับของ/QC'),
                (Project.Status.DELIVERY, 'ส่งมอบ'),
                (Project.Status.ACCEPTED, 'ตรวจรับ'),
                (Project.Status.CLOSED, 'ปิดจบ'),
            ]
             self.fields['status'].choices = SERVICE_CHOICES

class ProductItemForm(forms.ModelForm):
    class Meta:
        model = ProductItem
        fields = ['item_type', 'name', 'description', 'supplier', 'quantity', 'unit_cost', 'unit_price']
        widgets = {
            'item_type': forms.Select(attrs={'class': 'form-select'}),
            'name': forms.TextInput(attrs={'class': 'form-control'}),
            'description': forms.Textarea(attrs={'class': 'form-control', 'rows': 2}),
            'supplier': forms.Select(attrs={'class': 'form-select'}),
            'quantity': forms.NumberInput(attrs={'class': 'form-control'}),
            'unit_cost': forms.NumberInput(attrs={'class': 'form-control'}),
            'unit_price': forms.NumberInput(attrs={'class': 'form-control'}),
        }

class CustomerRequirementForm(forms.ModelForm):
    class Meta:
        model = CustomerRequirement
        fields = ['content']
        widgets = {
            'content': forms.Textarea(attrs={'class': 'form-control', 'rows': 3, 'placeholder': 'พูดหรือพิมพ์รายละเอียดความต้องการ...', 'id': 'requirement-content'}),
        }


from .models import CustomerRequest

class CustomerRequestForm(forms.ModelForm):
    class Meta:
        model = CustomerRequest
        fields = ['owner', 'customer', 'title', 'description', 'status']
        widgets = {
            'owner': forms.Select(attrs={'class': 'form-select'}),
            'customer': forms.Select(attrs={'class': 'form-select'}),
            'title': forms.TextInput(attrs={'class': 'form-control', 'placeholder': 'เรื่อง...'}),
            'description': forms.Textarea(attrs={'class': 'form-control', 'rows': 4, 'placeholder': 'รายละเอียดคำขอ...'}),
            'status': forms.Select(attrs={'class': 'form-select'}),
        }
