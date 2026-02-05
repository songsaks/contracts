from django.shortcuts import render, get_object_or_404, redirect
from django.contrib import messages
from django.contrib.auth.decorators import login_required
from django.utils import timezone
from django.db.models import Sum, Count, Q
from decimal import Decimal
from .models import Project, ProductItem, Customer, Supplier, ProjectOwner
from .forms import ProjectForm, ProductItemForm, CustomerForm, SupplierForm, ProjectOwnerForm

@login_required
def project_list(request):
    projects = Project.objects.all().order_by('-created_at')

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

    context = {
        'projects': projects,
        'status_choices': Project.Status.choices,
        'project_owners': ProjectOwner.objects.all(),
    }
    return render(request, 'pms/project_list.html', context)

@login_required
def project_detail(request, pk):
    project = get_object_or_404(Project, pk=pk)
    
    # Workflow steps (excluding CANCELLED for the happy path visualization)
    workflow_steps = [
        Project.Status.DRAFT,
        Project.Status.SOURCING,
        Project.Status.SUPPLIER_CHECK,
        Project.Status.QUOTED,
        Project.Status.CONTRACTED,
        Project.Status.ORDERING,
        Project.Status.RECEIVED_QC,
        Project.Status.DELIVERY,
        Project.Status.ACCEPTED,
        Project.Status.BILLING,
        Project.Status.CLOSED,
    ]

    context = {
        'project': project,
        'items': project.items.all(),
        'workflow_steps': workflow_steps,
        # total_value property is on the model
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
    if request.method == 'POST':
        form = ProjectForm(request.POST, instance=project)
        if form.is_valid():
            form.save()
            messages.success(request, 'อัปเดตโครงการสำเร็จ')
            return redirect('pms:project_detail', pk=project.pk)
    else:
        form = ProjectForm(instance=project)
    return render(request, 'pms/project_form.html', {'form': form, 'title': 'แก้ไขโครงการ'})

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
