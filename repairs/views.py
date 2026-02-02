from django.shortcuts import render, redirect, get_object_or_404
from django.http import JsonResponse
from django.urls import reverse
from django.db import transaction
from django.contrib.auth.decorators import login_required
from .models import RepairJob, RepairItem, Customer, Device, Technician, DeviceType, Brand
from .forms import CustomerForm, DeviceForm, RepairJobForm, RepairItemForm, TechnicianForm, DeviceTypeForm, BrandForm

from django.db.models import Q

@login_required
def repair_list(request):
    items = RepairItem.objects.select_related('job', 'device', 'job__customer').all()

    # Search
    q = request.GET.get('q')
    if q:
        items = items.filter(
            Q(job__job_code__icontains=q) |
            Q(job__customer__name__icontains=q) |
            Q(device__model__icontains=q) |
            Q(device__serial_number__icontains=q) |
            Q(issue_description__icontains=q) |
            Q(job__fix_id__icontains=q)
        ).distinct()

    # Filter by Status
    status = request.GET.get('status')
    if status:
        items = items.filter(status=status)

    # Sort
    sort = request.GET.get('sort', 'date_desc')
    if sort == 'date_desc':
        items = items.order_by('-created_at')
    elif sort == 'date_asc':
        items = items.order_by('created_at')
    elif sort == 'customer':
        items = items.order_by('job__customer__name')
    
    return render(request, 'repairs/repair_list.html', {'items': items, 'jobs': None}) # Pass items, clear jobs for safety check

@login_required
def repair_create(request):
    customer_id = request.GET.get('customer_id')
    prefilled_customer = None
    if customer_id:
        prefilled_customer = get_object_or_404(Customer, pk=customer_id)

    if request.method == 'POST':
        if prefilled_customer:
             # Skip customer form validation if existing customer
             customer_form = None
             customer = prefilled_customer
        else:
            customer_form = CustomerForm(request.POST, prefix='customer')

        job_form = RepairJobForm(request.POST, prefix='job')
        
        # Simple implementation: 1 device per job creation for now, to keep it simple initially
        # Enhancing to support at least one device in the main flow
        device_form = DeviceForm(request.POST, prefix='device')
        item_form = RepairItemForm(request.POST, prefix='item')

        if (prefilled_customer or customer_form.is_valid()) and job_form.is_valid() and device_form.is_valid() and item_form.is_valid():
            with transaction.atomic():
                # Save Customer if new
                if not prefilled_customer:
                    customer = customer_form.save()
                
                # Save Device linked to Customer
                device = device_form.save(commit=False)
                device.customer = customer
                device.save()
                
                # Save Job linked to Customer
                job = job_form.save(commit=False)
                job.customer = customer
                job.save()
                
                # Save Item linked to Job and Device
                item = item_form.save(commit=False)
                item.job = job
                item.device = device
                item.save()
                item_form.save_m2m() # Save technicians
                
                return redirect('repairs:repair_detail', pk=job.pk)
        else:
            print("DEBUG: Validation Failed")
            if not prefilled_customer and customer_form: print(f"Customer Errors: {customer_form.errors}")
            print(f"Job Errors: {job_form.errors}")
            print(f"Device Errors: {device_form.errors}")
            print(f"Item Errors: {item_form.errors}")
    else:
        if prefilled_customer:
            customer_form = None
        else:
            customer_form = CustomerForm(prefix='customer')
        job_form = RepairJobForm(prefix='job')
        device_form = DeviceForm(prefix='device')
        item_form = RepairItemForm(prefix='item')

    context = {
        'customer_form': customer_form,
        'prefilled_customer': prefilled_customer,
        'job_form': job_form,
        'device_form': device_form,
        'item_form': item_form,
    }
    return render(request, 'repairs/repair_form.html', context)

@login_required
def repair_detail(request, pk):
    job = get_object_or_404(RepairJob, pk=pk)
    return render(request, 'repairs/repair_detail.html', {'job': job})

@login_required
def repair_update_status(request, item_id):
    item = get_object_or_404(RepairItem, pk=item_id)
    if request.method == 'POST':
        new_status = request.POST.get('status')
        note = request.POST.get('status_note')
        if new_status:
            item.status = new_status
            if note is not None:
                item.status_note = note
            
            # Handle additional updates
            issue_desc = request.POST.get('issue_description')
            accessories = request.POST.get('accessories')
            
            if issue_desc:
                item.issue_description = issue_desc
            if accessories is not None: # Can be empty string
                item.accessories = accessories

            item.save()
    return redirect('repairs:repair_detail', pk=item.job.pk)

@login_required
def get_repair_item_note(request, item_id):
    item = get_object_or_404(RepairItem, pk=item_id)
    return JsonResponse({'note': item.status_note})

@login_required
def get_repair_job_notes(request, job_id):
    job = get_object_or_404(RepairJob, pk=job_id)
    items = job.items.all()
    data = []
    for item in items:
        data.append({
            'device': f"{item.device.brand} {item.device.model}",
            'status': item.get_status_display(),
            'note': item.status_note,
            'status_code': item.status 
        })
    return JsonResponse({'items': data})

# --- New Views ---

@login_required
def customer_list(request):
    customers = Customer.objects.all().order_by('-id')
    return render(request, 'repairs/customer_list.html', {'customers': customers})

@login_required
def customer_create(request):
    if request.method == 'POST':
        form = CustomerForm(request.POST)
        if form.is_valid():
            form.save()
            return redirect('repairs:customer_list')
    else:
        form = CustomerForm()
    return render(request, 'repairs/customer_form.html', {'form': form})

@login_required
def device_list(request):
    devices = Device.objects.all().order_by('-id')
    return render(request, 'repairs/device_list.html', {'devices': devices})



@login_required
def technician_list(request):
    techs = Technician.objects.all()
    return render(request, 'repairs/technician_list.html', {'techs': techs})

@login_required
def technician_create(request):
    if request.method == 'POST':
        form = TechnicianForm(request.POST)
        if form.is_valid():
            form.save()
            return redirect('repairs:technician_list')
    else:
        form = TechnicianForm()
    return render(request, 'repairs/technician_form.html', {'form': form})

@login_required
def device_type_list(request):
    device_types = DeviceType.objects.all()
    return render(request, 'repairs/device_type_list.html', {'device_types': device_types})

@login_required
def device_type_create(request):
    if request.method == 'POST':
        form = DeviceTypeForm(request.POST)
        if form.is_valid():
            form.save()
            return redirect('repairs:device_type_list')
    else:
        form = DeviceTypeForm()
    return render(request, 'repairs/device_type_form.html', {'form': form})
    
@login_required
def repair_print(request, pk):
    job = get_object_or_404(RepairJob, pk=pk)
    return render(request, 'repairs/repair_print.html', {'job': job})

# --- Brand Views ---

@login_required
def brand_list(request):
    brands = Brand.objects.all().order_by('name')
    return render(request, 'repairs/brand_list.html', {'brands': brands})

@login_required
def brand_create(request):
    if request.method == 'POST':
        form = BrandForm(request.POST)
        if form.is_valid():
            form.save()
            return redirect('repairs:brand_list')
    else:
        form = BrandForm()
    return render(request, 'repairs/brand_form.html', {'form': form, 'title': 'Create Brand'})

@login_required
def brand_update(request, pk):
    brand = get_object_or_404(Brand, pk=pk)
    if request.method == 'POST':
        form = BrandForm(request.POST, instance=brand)
        if form.is_valid():
            form.save()
            return redirect('repairs:brand_list')
    else:
        form = BrandForm(instance=brand)
    return render(request, 'repairs/brand_form.html', {'form': form, 'title': 'Edit Brand'})

@login_required
def brand_delete(request, pk):
    brand = get_object_or_404(Brand, pk=pk)
    if request.method == 'POST':
        try:
            brand.delete()
        except Exception:
            # Handle potential protection error if brands are used
            pass
        return redirect('repairs:brand_list')
    return render(request, 'repairs/brand_confirm_delete.html', {'brand': brand})

