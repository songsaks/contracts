from django import forms
from decimal import Decimal
from .models import (
    Project, ProductItem, Customer, Supplier, ProjectOwner,
    CustomerRequirement, SLAPlan, JobStatus, JobStatusAssignment, Skill
)

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

    # ตรวจสอบความซ้ำซ้อนของชื่อลูกค้าทั้งในระบบ PMS และระบบ Repairs
    def clean_name(self):
        name = self.cleaned_data.get('name')
        if not name:
            return name

        # 1. ตรวจสอบในระบบ PMS
        pms_exists = Customer.objects.filter(name__iexact=name)
        if self.instance.pk:
            pms_exists = pms_exists.exclude(pk=self.instance.pk)
        
        if pms_exists.exists():
            raise forms.ValidationError(f"⚠️ มีลูกค้าชื่อ '{name}' อยู่แล้วในระบบ PMS กรุณาตรวจสอบ")

        # 2. ตรวจสอบในระบบแจ้งซ่อม (Repairs)
        from repairs.models import Customer as RepairCustomer
        repair_exists = RepairCustomer.objects.filter(name__iexact=name).exists()
        if repair_exists:
            raise forms.ValidationError(f"⚠️ มีลูกค้าชื่อ '{name}' อยู่ในระบบแจ้งซ่อม (Repairs) แล้ว กรุณาใช้ชื่อที่ต่างกันหรือตรวจสอบข้อมูล")

        return name

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
        fields = ['name', 'customer', 'owner', 'status', 'start_date', 'deadline', 'description', 'remarks']
        widgets = {
            'name': forms.TextInput(attrs={'class': 'form-control'}),
            'customer': forms.Select(attrs={'class': 'form-select'}),
            'owner': forms.Select(attrs={'class': 'form-select'}),
            'status': forms.Select(attrs={'class': 'form-select no-tom-select'}),
            'start_date': forms.DateInput(attrs={'class': 'form-control', 'type': 'date'}),
            'deadline': forms.DateInput(attrs={'class': 'form-control', 'type': 'date'}),
            'description': forms.Textarea(attrs={'class': 'form-control', 'rows': 3}),
            'remarks': forms.Textarea(attrs={'class': 'form-control', 'rows': 2, 'placeholder': 'หมายเหตุภายใน...'}),
        }

    # กำหนดตัวเลือกสถานะงานแบบ Dynamic ตามประเภทงาน 'PROJECT'
    def __init__(self, *args, **kwargs):
        super(ProjectForm, self).__init__(*args, **kwargs)
        from .models import JobStatus
        choices = JobStatus.get_choices(Project.JobType.PROJECT)
        if choices:
            self.fields['status'].choices = choices
        else:
            # ค่าเริ่มต้นกรณีไม่มีข้อมูลในฐานข้อมูล
            self.fields['status'].choices = [
                (Project.Status.DRAFT, 'รวบรวม'),
                (Project.Status.SOURCING, 'จัดหา'),
                (Project.Status.QUOTED, 'เสนอราคา'),
                (Project.Status.CONTRACTED, 'ทำสัญญา'),
                (Project.Status.ORDERING, 'สั่งซื้อ'),
                (Project.Status.RECEIVED_QC, 'รับของ/QC'),
                (Project.Status.INSTALLATION, 'ติดตั้ง'),
                (Project.Status.ACCEPTED, 'ตรวจรับ'),
                (Project.Status.BILLING, 'วางบิล'),
                (Project.Status.WAITING_FOR_SALE_KEY, 'รอคีย์ขาย'),
                (Project.Status.CLOSED, 'ปิดจบ'),
                (Project.Status.CANCELLED, 'ยกเลิก'),
            ]

        # หากสร้างใหม่ (ไม่มี pk) ให้ปิดการแก้ไขสถานะ (ใช้ค่าเริ่มต้นตามที่ view กำหนด)
        if not self.instance.pk:
            self.fields['status'].disabled = True

class SalesServiceJobForm(forms.ModelForm):
    project_value = forms.DecimalField(
        max_digits=12, decimal_places=2, required=False,
        label='มูลค่าโครงการ (บาท)',
        widget=forms.NumberInput(attrs={'class': 'form-control', 'placeholder': '0.00', 'step': '0.01'}),
    )

    class Meta:
        model = Project
        fields = ['name', 'customer', 'owner', 'status', 'start_date', 'deadline', 'description', 'remarks']
        widgets = {
            'name': forms.TextInput(attrs={'class': 'form-control', 'placeholder': 'ชื่องานขาย/บริการ'}),
            'customer': forms.Select(attrs={'class': 'form-select'}),
            'owner': forms.Select(attrs={'class': 'form-select'}),
            'status': forms.Select(attrs={'class': 'form-select no-tom-select'}),
            'start_date': forms.DateInput(attrs={'class': 'form-control', 'type': 'date'}),
            'deadline': forms.DateInput(attrs={'class': 'form-control', 'type': 'date'}),
            'description': forms.Textarea(attrs={'class': 'form-control', 'rows': 3}),
            'remarks': forms.Textarea(attrs={'class': 'form-control', 'rows': 2, 'placeholder': 'หมายเหตุภายใน...'}),
        }

    # กำหนดตัวเลือกสถานะงานแบบ Dynamic ตามประเภทงานที่ระบุ (Service, Repair, Rental)
    def __init__(self, *args, **kwargs):
        job_type = kwargs.pop('job_type', None)
        super(SalesServiceJobForm, self).__init__(*args, **kwargs)
        
        if not job_type and self.instance and self.instance.pk:
            job_type = self.instance.job_type

        from .models import JobStatus
        dynamic_choices = JobStatus.get_choices(job_type)
        if dynamic_choices:
            self.fields['status'].choices = dynamic_choices
        else:
            # ค่าเริ่มต้นแบบแยกประเภทงาน กรณีไม่มีข้อมูลในฐานข้อมูล
            if job_type == Project.JobType.REPAIR:
                self.fields['status'].choices = [
                    (Project.Status.SOURCING, 'รับแจ้งซ่อม'),
                    (Project.Status.SUPPLIER_CHECK, 'เช็คราคา'),
                    (Project.Status.ORDERING, 'จัดคิวซ่อม'),
                    (Project.Status.DELIVERY, 'ซ่อม'),
                    (Project.Status.WAITING_FOR_SALE_KEY, 'รอคีย์ขาย'),
                    (Project.Status.CLOSED, 'ปิดงานซ่อม'),
                    (Project.Status.CANCELLED, 'ยกเลิก'),
                ]
            elif job_type == Project.JobType.SERVICE:
                self.fields['status'].choices = [
                    (Project.Status.SOURCING, 'จัดหา'),
                    (Project.Status.QUOTED, 'เสนอราคา'),
                    (Project.Status.ORDERING, 'สั่งซื้อ'),
                    (Project.Status.RECEIVED_QC, 'รับของ/QC'),
                    (Project.Status.DELIVERY, 'ส่งมอบ'),
                    (Project.Status.ACCEPTED, 'ตรวจรับ'),
                    (Project.Status.WAITING_FOR_SALE_KEY, 'รอคีย์ขาย'),
                    (Project.Status.CLOSED, 'ปิดจบ'),
                    (Project.Status.CANCELLED, 'ยกเลิก'),
                ]
            elif job_type == Project.JobType.RENTAL:
                self.fields['status'].choices = [
                    (Project.Status.SOURCING, 'จัดหา'),
                    (Project.Status.CONTRACTED, 'ทำสัญญา'),
                    (Project.Status.RENTING, 'เช่า'),
                    (Project.Status.WAITING_FOR_SALE_KEY, 'รอคีย์ขาย'),
                    (Project.Status.CLOSED, 'ปิดจบ'),
                    (Project.Status.CANCELLED, 'ยกเลิก'),
                ]
            elif job_type == Project.JobType.SURVEY:
                self.fields['status'].choices = [
                    ('QUEUE_SURVEY', 'จัดคิวดูหน้างาน'),
                    ('SURVEYING', 'กำลังดูหน้างาน'),
                    (Project.Status.QUOTED, 'เสนอราคา'),
                    (Project.Status.CLOSED, 'ปิดจบ'),
                    (Project.Status.CANCELLED, 'ยกเลิก'),
                ]
            else:
                self.fields['status'].choices = [(c[0], c[1]) for c in Project.Status.choices]

        # หากสร้างใหม่ (ไม่มี pk) ให้ลบ status ออกจาก form validation ทั้งหมด
        # view จะ set project.status = SOURCING (หรือ first status) ก่อน save() เอง
        if not self.instance.pk:
            self.fields.pop('status', None)

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
        fields = ['owner', 'customer', 'title', 'description', 'status', 'remarks']
        widgets = {
            'owner': forms.Select(attrs={'class': 'form-select'}),
            'customer': forms.Select(attrs={'class': 'form-select'}),
            'title': forms.TextInput(attrs={'class': 'form-control', 'placeholder': 'เรื่อง...'}),
            'description': forms.Textarea(attrs={'class': 'form-control', 'rows': 4, 'placeholder': 'รายละเอียดคำขอ...'}),
            'remarks': forms.Textarea(attrs={'class': 'form-control', 'rows': 2, 'placeholder': 'หมายเหตุภายใน...'}),
            'status': forms.Select(attrs={'class': 'form-select'}),
        }
class JobStatusForm(forms.ModelForm):
    class Meta:
        model = JobStatus
        fields = ['job_type', 'status_key', 'label', 'sort_order', 'is_active']
        widgets = {
            'job_type': forms.Select(attrs={'class': 'form-select'}),
            'status_key': forms.TextInput(attrs={'class': 'form-control', 'placeholder': 'เช่น SOURCING, CLOSED'}),
            'label': forms.TextInput(attrs={'class': 'form-control', 'placeholder': 'ชื่อที่แสดงในงาน'}),
            'sort_order': forms.NumberInput(attrs={'class': 'form-control'}),
            'is_active': forms.CheckboxInput(attrs={'class': 'form-check-input'}),
        }
    
    # เปลี่ยนตัวพิมพ์เล็กให้เป็นตัวพิมพ์ใหญ่สำหรับ Status Key (เช่น sourcing -> SOURCING)
    def clean_status_key(self):
        return self.cleaned_data.get('status_key').upper()

class SkillForm(forms.ModelForm):
    class Meta:
        model = Skill
        fields = ['name', 'skill_type', 'description', 'is_active']
        widgets = {
            'name':        forms.TextInput(attrs={'class': 'form-control', 'placeholder': 'เช่น ติดตั้งระบบเครือข่าย, ซ่อมเครื่องใช้ไฟฟ้า'}),
            'skill_type':  forms.Select(attrs={'class': 'form-select'}),
            'description': forms.Textarea(attrs={'class': 'form-control', 'rows': 3, 'placeholder': 'คำอธิบายทักษะ (ไม่บังคับ)'}),
            'is_active':   forms.CheckboxInput(attrs={'class': 'form-check-input'}),
        }
        labels = {
            'name':       'ชื่อทักษะ',
            'skill_type': 'ประเภทงาน',
            'description':'คำอธิบาย',
            'is_active':  'เปิดใช้งาน',
        }


class JobStatusAssignmentForm(forms.ModelForm):
    class Meta:
        model = JobStatusAssignment
        fields = ['responsible_users']
        widgets = {
            'responsible_users': forms.SelectMultiple(attrs={'class': 'form-select', 'size': '5'}),
        }
