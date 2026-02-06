from django.shortcuts import render, get_object_or_404, redirect
from django.contrib import messages
from django.contrib.auth.decorators import login_required
from django.utils import timezone
from django.db.models import Sum, Count, Q
from decimal import Decimal
from .models import Project, ProductItem, Customer, Supplier, ProjectOwner, CustomerRequirement
from .forms import ProjectForm, ProductItemForm, CustomerForm, SupplierForm, ProjectOwnerForm, CustomerRequirementForm, SalesServiceJobForm
from repairs.models import RepairItem

@login_required
def dispatch(request):
    return render(request, 'pms/dispatch.html')

@login_required
def service_create(request):
    if request.method == 'POST':
        form = SalesServiceJobForm(request.POST, job_type=Project.JobType.SERVICE)
        if form.is_valid():
            project = form.save(commit=False)
            project.job_type = Project.JobType.SERVICE
            project.save()
            messages.success(request, 'สร้างงานบริการขายสำเร็จ')
            return redirect('pms:project_detail', pk=project.pk)
    else:
        form = SalesServiceJobForm(initial={'status': Project.Status.SOURCING}, job_type=Project.JobType.SERVICE)
    return render(request, 'pms/service_form.html', {'form': form, 'title': 'สร้างงานบริการขายใหม่', 'theme_color': 'success'})

@login_required
def repair_create(request):
    if request.method == 'POST':
        form = SalesServiceJobForm(request.POST, job_type=Project.JobType.REPAIR)
        if form.is_valid():
            project = form.save(commit=False)
            project.job_type = Project.JobType.REPAIR
            project.save()
            messages.success(request, 'สร้างใบแจ้งซ่อมสำเร็จ')
            return redirect('pms:project_detail', pk=project.pk)
    else:
        form = SalesServiceJobForm(initial={'status': Project.Status.SOURCING, 'name': 'แจ้งซ่อม - '}, job_type=Project.JobType.REPAIR)
    return render(request, 'pms/service_form.html', {'form': form, 'title': 'สร้างใบแจ้งซ่อม (On-site Repair)', 'theme_color': 'warning'})

# ... queue_management ...

# ... project_list ...

# ... project_detail ...

# ... project_create ...

@login_required
def project_update(request, pk):
    project = get_object_or_404(Project, pk=pk)
    
    # Determine Form Class, Title, and Theme based on Job Type
    theme_color = 'primary'
    form_kwargs = {'instance': project}

    if project.job_type == Project.JobType.SERVICE:
        FormClass = SalesServiceJobForm
        template = 'pms/service_form.html'
        title = 'แก้ไขงานขาย'
        theme_color = 'success'
        form_kwargs['job_type'] = Project.JobType.SERVICE
    elif project.job_type == Project.JobType.REPAIR:
        FormClass = SalesServiceJobForm
        template = 'pms/service_form.html'
        title = 'แก้ไขงานซ่อม'
        theme_color = 'warning'
        form_kwargs['job_type'] = Project.JobType.REPAIR
    else:
        FormClass = ProjectForm
        template = 'pms/project_form.html'
        title = 'แก้ไขโครงการ'

    if request.method == 'POST':
        form = FormClass(request.POST, **form_kwargs)
        if form.is_valid():
            form.save()
            messages.success(request, f'อัปเดต{title.replace("แก้ไข", "")}สำเร็จ')
            return redirect('pms:project_detail', pk=project.pk)
    else:
        form = FormClass(**form_kwargs)
        
    return render(request, template, {'form': form, 'title': title, 'theme_color': theme_color})

@login_required
def queue_management(request):
    # Sales/Project Queue: Projects in DELIVERY status
    delivery_queue = Project.objects.filter(
        status=Project.Status.DELIVERY, 
        job_type__in=[Project.JobType.PROJECT, Project.JobType.SERVICE]
    ).order_by('deadline', 'created_at')
    
    # Repair Queue: Repair Jobs (Onsite) that are active
    # Active statuses logic: Not Closed, Billing, Accepted, Cancelled
    # Or maybe user wants specific "Queue" like waiting for technician?
    # Let's show SOURCING (Diagnosing), ORDERING (Waiting Parts), DELIVERY (Fixing/Onsite)
    repair_queue = Project.objects.filter(
        job_type=Project.JobType.REPAIR,
        status__in=[
            Project.Status.SOURCING, 
            Project.Status.QUOTED, 
            Project.Status.ORDERING, 
            Project.Status.RECEIVED_QC,
            Project.Status.DELIVERY
        ]
    ).order_by('created_at')
    
    return render(request, 'pms/queue_dashboard.html', {
        'delivery_queue': delivery_queue,
        'repair_queue': repair_queue,
    })

@login_required
def project_list(request):
    projects = Project.objects.all().order_by('-created_at')

    # Filter
    status_filter = request.GET.get('status')
    if status_filter:
        projects = projects.filter(status=status_filter)
    
    job_type_filter = request.GET.get('job_type')
    if job_type_filter:
        projects = projects.filter(job_type=job_type_filter)
        
    owner_filter = request.GET.get('owner')
    if owner_filter:
        projects = projects.filter(owner_id=owner_filter)

    date_from = request.GET.get('date_from')
    date_to = request.GET.get('date_to')
    if date_from and date_to:
        projects = projects.filter(created_at__date__range=[date_from, date_to])

    context = {
        'projects': projects,
        'status_choices': Project.Status.choices,
        'project_owners': ProjectOwner.objects.all(),
    }
    return render(request, 'pms/project_list.html', context)

@login_required
def project_detail(request, pk):
    project = get_object_or_404(Project, pk=pk)
    
    # Theme Color
    theme_color = 'primary'
    if project.job_type == Project.JobType.SERVICE:
        theme_color = 'success'
    elif project.job_type == Project.JobType.REPAIR:
        theme_color = 'warning'

    # Workflow steps based on job type
    raw_steps = []
    
    if project.job_type == Project.JobType.SERVICE:
        # Sales Service Workflow (Simplified)
        raw_steps = [
            (Project.Status.SOURCING, 'จัดหา'),
            (Project.Status.QUOTED, 'เสนอราคา'),
            (Project.Status.ORDERING, 'สั่งซื้อ'),
            (Project.Status.RECEIVED_QC, 'รับของ/QC'),
            (Project.Status.DELIVERY, 'ส่งมอบ'),
            (Project.Status.ACCEPTED, 'ตรวจรับ'),
            (Project.Status.CLOSED, 'ปิดจบ'),
        ]
    elif project.job_type == Project.JobType.REPAIR:
        # Repair Workflow (Custom Labels from User Request)
        raw_steps = [
            (Project.Status.SOURCING, 'รับแจ้งซ่อม'),
            (Project.Status.ORDERING, 'จัดคิวซ่อม'),
            (Project.Status.DELIVERY, 'ซ่อม'),
            (Project.Status.ACCEPTED, 'รอ'),
            (Project.Status.CLOSED, 'ปิดงานซ่อม'),
        ]
    else:
        # Full Project Workflow (Default Labels)
        raw_steps = [
            (Project.Status.DRAFT, 'รวบรวม'),
            (Project.Status.SOURCING, 'จัดหา'),
            (Project.Status.SUPPLIER_CHECK, 'เช็คราคา'),
            (Project.Status.QUOTED, 'เสนอราคา'),
            (Project.Status.CONTRACTED, 'ทำสัญญา'),
            (Project.Status.ORDERING, 'สั่งซื้อ'),
            (Project.Status.RECEIVED_QC, 'รับของ/QC'),
            (Project.Status.DELIVERY, 'ส่งมอบ'),
            (Project.Status.ACCEPTED, 'ตรวจรับ'),
            (Project.Status.BILLING, 'วางบิล'),
            (Project.Status.CLOSED, 'ปิดจบ'),
        ]

    # Wrapper class to make template logic work: {% if step == project.status %} and {{ step.label }}
    class StepWrapper:
        def __init__(self, value, label):
            self.value = value
            self.label = label
        def __eq__(self, other):
            return str(self.value) == str(other)
        def __str__(self):
            return str(self.value)

    workflow_steps = [StepWrapper(val, lbl) for val, lbl in raw_steps]

    # Get current status label
    current_status_label = project.get_status_display()
    for step in workflow_steps:
        if step == project.status:
            current_status_label = step.label
            break

    context = {
        'project': project,
        'items': project.items.all(),
        'workflow_steps': workflow_steps,
        'theme_color': theme_color,
        'current_status_label': current_status_label,
    }
    return render(request, 'pms/project_detail.html', context)

@login_required
def project_create(request):
    if request.method == 'POST':
        form = ProjectForm(request.POST)
        if form.is_valid():
            project = form.save()
            messages.success(request, 'สร้างโครงการสำเร็จ')
            return redirect('pms:project_detail', pk=project.pk)
    else:
        form = ProjectForm()
    return render(request, 'pms/project_form.html', {'form': form, 'title': 'สร้างโครงการใหม่'})

@login_required
def project_update(request, pk):
    project = get_object_or_404(Project, pk=pk)
    
    # Determine Form Class, Title, and Theme based on Job Type
    theme_color = 'primary'
    form_kwargs = {'instance': project}

    if project.job_type == Project.JobType.SERVICE:
        FormClass = SalesServiceJobForm
        template = 'pms/service_form.html'
        title = 'แก้ไขงานขาย'
        theme_color = 'success'
        form_kwargs['job_type'] = Project.JobType.SERVICE
    elif project.job_type == Project.JobType.REPAIR:
        FormClass = SalesServiceJobForm
        template = 'pms/service_form.html'
        title = 'แก้ไขงานซ่อม'
        theme_color = 'warning'
        form_kwargs['job_type'] = Project.JobType.REPAIR
    else:
        FormClass = ProjectForm
        template = 'pms/project_form.html'
        title = 'แก้ไขโครงการ'

    if request.method == 'POST':
        form = FormClass(request.POST, **form_kwargs)
        if form.is_valid():
            form.save()
            messages.success(request, f'อัปเดต{title.replace("แก้ไข", "")}สำเร็จ')
            return redirect('pms:project_detail', pk=project.pk)
    else:
        form = FormClass(**form_kwargs)
        
    return render(request, template, {'form': form, 'title': title, 'theme_color': theme_color})

@login_required
def item_add(request, project_id):
    project = get_object_or_404(Project, pk=project_id)
    if request.method == 'POST':
        form = ProductItemForm(request.POST)
        if form.is_valid():
            item = form.save(commit=False)
            item.project = project
            item.save()
            messages.success(request, 'เพิ่มรายการสำเร็จ')
            return redirect('pms:project_detail', pk=project.pk)
    else:
        form = ProductItemForm()
    return render(request, 'pms/item_form.html', {'form': form, 'project': project, 'title': f'เพิ่มรายการใน {project.name}'})

@login_required
def item_update(request, item_id):
    item = get_object_or_404(ProductItem, pk=item_id)
    project = item.project
    if request.method == 'POST':
        form = ProductItemForm(request.POST, instance=item)
        if form.is_valid():
            form.save()
            messages.success(request, 'แก้ไขรายการสำเร็จ')
            return redirect('pms:project_detail', pk=project.pk)
    else:
        form = ProductItemForm(instance=item)
    return render(request, 'pms/item_form.html', {'form': form, 'project': project, 'title': f'แก้ไขรายการ {item.name}'})

@login_required
def item_delete(request, item_id):
    item = get_object_or_404(ProductItem, pk=item_id)
    project_pk = item.project.pk
    item.delete()
    messages.success(request, 'ลบรายการสำเร็จ')
    return redirect('pms:project_detail', pk=project_pk)

# Customer Views
@login_required
def customer_list(request):
    customers = Customer.objects.all().order_by('-created_at')
    return render(request, 'pms/customer_list.html', {'customers': customers})

@login_required
def customer_create(request):
    if request.method == 'POST':
        # Reuse ProjectForm style but for Customer?
        # We need a CustomerForm. Let's create one inline in forms.py later or just use modelform_factory if lazy, 
        # but user likely wants a proper form. I'll need to define it in forms.py.
        # Check forms.py first. It does not have CustomerForm.
        # I will assume I will add CustomerForm in step 2.

        form = CustomerForm(request.POST)
        if form.is_valid():
            form.save()
            messages.success(request, 'เพิ่มลูกค้าสำเร็จ')
            return redirect('pms:customer_list')
    else:

        form = CustomerForm()
    return render(request, 'pms/customer_form.html', {'form': form, 'title': 'เพิ่มลูกค้าใหม่'})

@login_required
def customer_update(request, pk):
    customer = get_object_or_404(Customer, pk=pk)

    if request.method == 'POST':
        form = CustomerForm(request.POST, instance=customer)
        if form.is_valid():
            form.save()
            messages.success(request, 'อัปเดตข้อมูลลูกค้าสำเร็จ')
            return redirect('pms:customer_list')
    else:
        form = CustomerForm(instance=customer)

    return render(request, 'pms/customer_form.html', {'form': form, 'title': 'แก้ไขข้อมูลลูกค้า'})

# Supplier Views
@login_required
def supplier_list(request):
    suppliers = Supplier.objects.all().order_by('-created_at')
    return render(request, 'pms/supplier_list.html', {'suppliers': suppliers})

@login_required
def supplier_create(request):
    if request.method == 'POST':
        form = SupplierForm(request.POST)
        if form.is_valid():
            form.save()
            messages.success(request, 'เพิ่มซัพพลายเออร์สำเร็จ')
            return redirect('pms:supplier_list')
    else:
        form = SupplierForm()
    return render(request, 'pms/supplier_form.html', {'form': form, 'title': 'เพิ่มซัพพลายเออร์ใหม่'})

@login_required
def supplier_update(request, pk):
    supplier = get_object_or_404(Supplier, pk=pk)
    if request.method == 'POST':
        form = SupplierForm(request.POST, instance=supplier)
        if form.is_valid():
            form.save()
            messages.success(request, 'อัปเดตข้อมูลซัพพลายเออร์สำเร็จ')
            return redirect('pms:supplier_list')
    else:
        form = SupplierForm(instance=supplier)
    return render(request, 'pms/supplier_form.html', {'form': form, 'title': 'แก้ไขข้อมูลซัพพลายเออร์'})

# Project Owner Views
@login_required
def project_owner_list(request):
    owners = ProjectOwner.objects.all().order_by('name')
    return render(request, 'pms/project_owner_list.html', {'owners': owners})

@login_required
def project_owner_create(request):
    if request.method == 'POST':
        form = ProjectOwnerForm(request.POST)
        if form.is_valid():
            form.save()
            messages.success(request, 'เพิ่มเจ้าของโครงการสำเร็จ')
            return redirect('pms:project_owner_list')
    else:
        form = ProjectOwnerForm()
    return render(request, 'pms/project_owner_form.html', {'form': form, 'title': 'เพิ่มเจ้าของโครงการ'})

@login_required
def project_owner_update(request, pk):
    owner = get_object_or_404(ProjectOwner, pk=pk)
    if request.method == 'POST':
        form = ProjectOwnerForm(request.POST, instance=owner)
        if form.is_valid():
            form.save()
            messages.success(request, 'อัปเดตข้อมูลเจ้าของโครงการสำเร็จ')
            return redirect('pms:project_owner_list')
    else:
        form = ProjectOwnerForm(instance=owner)
    return render(request, 'pms/project_owner_form.html', {'form': form, 'title': 'แก้ไขข้อมูลเจ้าของโครงการ'})

# Report View
@login_required
def project_quotation(request, pk):
    project = get_object_or_404(Project, pk=pk)
    # Calculate totals
    subtotal = project.total_value
    # Assuming 7% VAT for now as common practice in Thailand, or just show total if no VAT logic yet
    # Since model doesn't have vat logic yet, we'll keep it simple or calculate on fly
    vat = subtotal * Decimal('0.07')
    grand_total = subtotal + vat
    
    context = {
        'project': project,
        'items': project.items.all(),
        'subtotal': subtotal,
        'vat': vat,
        'grand_total': grand_total,
        'today': timezone.now()
    }
    return render(request, 'pms/project_quotation.html', context)

# Dashboard
@login_required
def dashboard(request):
    projects = Project.objects.all()
    
    # Filter
    status_filter = request.GET.get('status')
    if status_filter:
        projects = projects.filter(status=status_filter)
        
    owner_filter = request.GET.get('owner')
    if owner_filter:
        projects = projects.filter(owner_id=owner_filter)

    date_from = request.GET.get('date_from')
    date_to = request.GET.get('date_to')
    if date_from and date_to:
        projects = projects.filter(created_at__date__range=[date_from, date_to])
        
    # Stats (calculate from FILTERED projects or ALL projects? Usually dashboard stats show global state unless filtered. 
    # But user said "dashboard... filter to display". I will calculate stats based on ALL projects for top cards, 
    # and show filtered table below. Or filter everything? Let's filter everything for powerful analysis.)
    
    # Actually, usually Top Cards are "All Time" or "Current State", and table is filtered.
    # Let's do: Top Cards = All Time (Active, Completed, Total Value). 
    # Table = Filterable.
    
    all_projects = Project.objects.all()
    total_projects = all_projects.count()
    active_projects = all_projects.exclude(status__in=[Project.Status.CLOSED, Project.Status.CANCELLED]).count()
    completed_projects = all_projects.filter(status=Project.Status.CLOSED).count()
    
    total_revenue = 0
    for p in all_projects:
        total_revenue += p.total_value

    context = {
        'projects': projects.order_by('-created_at'),
        'total_projects': total_projects,
        'active_projects': active_projects,
        'completed_projects': completed_projects,
        'total_revenue': total_revenue,
        'status_choices': Project.Status.choices,
        'project_owners': ProjectOwner.objects.all(),
    }
    return render(request, 'pms/dashboard.html', context)

# Customer Requirement Views
@login_required
def requirement_list(request):
    requirements = CustomerRequirement.objects.all().order_by('-created_at')
    return render(request, 'pms/requirement_list.html', {'requirements': requirements})

@login_required
def requirement_create(request):
    if request.method == 'POST':
        form = CustomerRequirementForm(request.POST)
        if form.is_valid():
            form.save()
            messages.success(request, 'บันทึกความต้องการสำเร็จ')
            return redirect('pms:requirement_list')
    else:
        form = CustomerRequirementForm()
    return render(request, 'pms/requirement_form.html', {'form': form, 'title': 'บันทึกความต้องการเบื้องต้น'})

@login_required
def requirement_update(request, pk):
    requirement = get_object_or_404(CustomerRequirement, pk=pk)
    if request.method == 'POST':
        form = CustomerRequirementForm(request.POST, instance=requirement)
        if form.is_valid():
            form.save()
            messages.success(request, 'แก้ไขความต้องการสำเร็จ')
            return redirect('pms:requirement_list')
    else:
        form = CustomerRequirementForm(instance=requirement)
    return render(request, 'pms/requirement_form.html', {'form': form, 'title': 'แก้ไขความต้องการ'})

@login_required
def requirement_delete(request, pk):
    requirement = get_object_or_404(CustomerRequirement, pk=pk)
    requirement.delete()
    messages.success(request, 'ลบรายการความต้องการสำเร็จ')
    return redirect('pms:requirement_list')

@login_required
def create_project_from_requirement(request, pk):
    requirement = get_object_or_404(CustomerRequirement, pk=pk)
    
    # Check query param for job type
    job_type = request.GET.get('type', 'PROJECT') # Default to PROJECT if not specified
    
    if requirement.is_converted:
        messages.warning(request, 'รายการนี้ถูกสร้างเป็นงานแล้ว')
        if requirement.project:
            return redirect('pms:project_detail', pk=requirement.project.pk)
        return redirect('pms:requirement_list')

    if request.method == 'POST':
        if job_type in ['SERVICE', 'REPAIR']:
             form = SalesServiceJobForm(request.POST)
        else:
             form = ProjectForm(request.POST)

        if form.is_valid():
            project = form.save(commit=False)
            if job_type == 'SERVICE':
                project.job_type = Project.JobType.SERVICE
            elif job_type == 'REPAIR':
                project.job_type = Project.JobType.REPAIR
            else:
                project.job_type = Project.JobType.PROJECT
            
            project.save()
            
            # Link Requirement
            requirement.is_converted = True
            requirement.project = project
            requirement.save()
            
            job_label = 'โครงการ'
            if job_type == 'SERVICE': job_label = 'งานบริการขาย'
            elif job_type == 'REPAIR': job_label = 'ใบแจ้งซ่อม'

            messages.success(request, f"สร้าง{job_label}จากความต้องการสำเร็จ")
            return redirect('pms:project_detail', pk=project.pk)
    else:
        # Pre-fill description
        job_label = 'โครงการ'
        status = Project.Status.DRAFT
        
        if job_type == 'SERVICE': 
            job_label = 'งานขาย'
            status = Project.Status.SOURCING
        elif job_type == 'REPAIR':
            job_label = 'แจ้งซ่อม'
            status = Project.Status.SOURCING

        initial_data = {
            'description': requirement.content,
            'name': f"{job_label}ใหม่ ({requirement.created_at.strftime('%d/%m/%Y')})",
            'status': status,
        }
        
        if job_type in ['SERVICE', 'REPAIR']:
            form = SalesServiceJobForm(initial=initial_data)
            template = 'pms/service_form.html'
            title = f'สร้าง{job_label}จากความต้องการ'
        else:
            form = ProjectForm(initial=initial_data)
            template = 'pms/project_form.html'
            title = 'สร้างโครงการจากความต้องการ'

    return render(request, template, {
        'form': form, 
        'title': title,
    })
