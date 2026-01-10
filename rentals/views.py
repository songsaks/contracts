from django.shortcuts import render, redirect, get_object_or_404
from django.db import transaction
from django.db.models import Sum, F
from django.contrib import messages
from django.contrib.auth.decorators import login_required
from .models import Asset, Contract, Tenant
from decimal import Decimal
from datetime import datetime

@login_required
def dashboard(request):
    active_contracts = Contract.objects.filter(status='ACTIVE')
    tenants = Tenant.objects.all()
    
    tenant_id = request.GET.get('tenant')
    if tenant_id:
        active_contracts = active_contracts.filter(tenant_id=tenant_id)
    
    # Financial Stats (should likely reflect filtered view or global? Usually dashboard stats are global, but context implies tailored view. I'll keep stats global for now unless requested, but filtering the list.)
    # Actually, usually if I filter the dashboard, I expect stats to update too.
    # Let's update stats to reflect the filtered contracts?
    # "Financial Stats"
    total_revenue = Contract.objects.aggregate(Sum('paid_amount'))['paid_amount__sum'] or 0
    # Total Receivable usually is for ALL active debt.
    # But if I filter by agency, maybe I want to see THEIR debt?
    # I will calculate stats based on the potentially filtered list for 'total_receivable' context but total_revenue might be historical.
    # To be safe and simple, I will keep stats Global for now as they are labelled "Total Revenue".
    # But wait, user might want to see specific agency debt.
    # Let's just filter the list first as requested.
    
    total_receivable = Contract.objects.filter(status='ACTIVE').aggregate(
        debt=Sum(F('total_amount') - F('paid_amount'))
    )['debt'] or 0

    return render(request, 'rentals/dashboard.html', {
        'contracts': active_contracts,
        'total_revenue': total_revenue,
        'total_receivable': total_receivable,
        'tenants': tenants,
        'selected_tenant': int(tenant_id) if tenant_id else None
    })

@login_required
def asset_list(request):
    assets = Asset.objects.all()
    return render(request, 'rentals/asset_list.html', {'assets': assets})

@login_required
def asset_create(request):
    if request.method == 'POST':
        name = request.POST.get('name')
        serial_number = request.POST.get('serial_number')
        description = request.POST.get('description')
        monthly_rate = request.POST.get('monthly_rate')
        Asset.objects.create(name=name, serial_number=serial_number, description=description, monthly_rate=monthly_rate)
        messages.success(request, 'Asset created successfully.')
        return redirect('rentals:asset_list')
    return render(request, 'rentals/asset_form.html')

@login_required
def asset_edit(request, pk):
    asset = get_object_or_404(Asset, pk=pk)
    if request.method == 'POST':
        asset.name = request.POST.get('name')
        asset.serial_number = request.POST.get('serial_number')
        asset.description = request.POST.get('description')
        asset.monthly_rate = request.POST.get('monthly_rate')
        
        # Only allow status change if not RENTED, or ensure we don't accidentally force it if hidden
        new_status = request.POST.get('status')
        if asset.status != 'RENTED' and new_status in ['AVAILABLE', 'MAINTENANCE']:
            asset.status = new_status
            
        asset.save()
        messages.success(request, 'Asset updated successfully.')
        return redirect('rentals:asset_list')
    return render(request, 'rentals/asset_edit.html', {'asset': asset})

@login_required
def asset_import(request):
    if request.method == 'POST' and request.FILES.get('excel_file'):
        import pandas as pd
        excel_file = request.FILES['excel_file']
        try:
            df = pd.read_excel(excel_file)
            count = 0
            for index, row in df.iterrows():
                # Basic validation
                name = row.get('Name')
                if not name or pd.isna(name):
                    continue

                serial = row.get('Serial Number')
                if pd.isna(serial):
                    serial = None
                
                monthly_rate = row.get('Monthly Rate', 0)
                if pd.isna(monthly_rate):
                    monthly_rate = 0
                
                description = row.get('Description', '')
                if pd.isna(description):
                    description = ''
                
                status = row.get('Status', 'AVAILABLE').upper()
                if status not in ['AVAILABLE', 'MAINTENANCE', 'RENTED']:
                    status = 'AVAILABLE'

                # Use update_or_create to avoid duplicates if serial is present
                if serial:
                    Asset.objects.update_or_create(
                        serial_number=serial,
                        defaults={
                            'name': name,
                            'monthly_rate': monthly_rate,
                            'description': description,
                            'status': status
                        }
                    )
                    count += 1
                else:
                    # If no serial, just create (allow duplicates? probably yes if no identifier)
                    Asset.objects.create(
                        name=name,
                        monthly_rate=monthly_rate,
                        description=description,
                        status=status,
                        serial_number=None
                    )
                    count += 1
            
            messages.success(request, f'Successfully imported {count} assets.')
            return redirect('rentals:asset_list')
        except Exception as e:
            messages.error(request, f'Error importing file: {e}')
            return redirect('rentals:asset_import')
            
    return render(request, 'rentals/asset_import.html')

@login_required
def tenant_create(request):
    if request.method == 'POST':
        Tenant.objects.create(
            agency_name=request.POST.get('agency_name'),
            contact_person=request.POST.get('contact_person'),
            email=request.POST.get('email'),
            phone=request.POST.get('phone'),
            document_id=request.POST.get('document_id'),
            address=request.POST.get('address')
        )
        messages.success(request, 'Tenant registered successfully.')
        return redirect('rentals:contract_create')
    return render(request, 'rentals/tenant_form.html')

@login_required
def contract_create(request):
    if request.method == 'POST':
        tenant_id = request.POST.get('tenant')
        asset_ids = request.POST.getlist('assets')
        start_date_str = request.POST.get('start_date')
        end_date_str = request.POST.get('end_date')
        payment_frequency = request.POST.get('payment_frequency')
        
        if not asset_ids:
            messages.error(request, 'Please select at least one asset.')
            return redirect('rentals:contract_create')

        try:
            with transaction.atomic():
                start_date = datetime.strptime(start_date_str, '%Y-%m-%d').date()
                end_date = datetime.strptime(end_date_str, '%Y-%m-%d').date()
                days = (end_date - start_date).days
                
                if days <= 0:
                    raise ValueError("End date must be after start date.")

                assets_to_rent = Asset.objects.filter(id__in=asset_ids)
                
                # Check availability
                for asset in assets_to_rent:
                    if asset.status != 'AVAILABLE':
                        raise ValueError(f"Asset {asset.name} is no longer available.")
                
                # Calculate Total Amount
                monthly_total = sum(a.monthly_rate for a in assets_to_rent)
                
                # Calculate duration in months (rounding up to nearest month)
                import math
                num_months = math.ceil(days / 30)
                if num_months < 1:
                    num_months = 1
                
                total_amount = monthly_total * Decimal(num_months)
                total_amount = round(total_amount, 2)

                tenant = Tenant.objects.get(id=tenant_id)
                contract = Contract.objects.create(
                    tenant=tenant,
                    start_date=start_date,
                    end_date=end_date,
                    payment_frequency=payment_frequency,
                    total_amount=total_amount,
                    status='ACTIVE'
                )
                contract.assets.set(assets_to_rent)
                
                assets_to_rent.update(status='RENTED')
                
                messages.success(request, f'Contract created. Total: \u0e3f{total_amount}')
                return redirect('rentals:dashboard')
        except ValueError as e:
            messages.error(request, str(e))
        except Exception as e:
            messages.error(request, f"An error occurred: {str(e)}")
            
    # GET context
    tenants = Tenant.objects.all()
    available_assets = Asset.objects.filter(status='AVAILABLE')
    return render(request, 'rentals/contract_form.html', {
        'tenants': tenants,
        'assets': available_assets
    })

@login_required
def contract_cancel(request, pk):
    contract = get_object_or_404(Contract, pk=pk)
    if contract.status == 'ACTIVE':
        with transaction.atomic():
            contract.status = 'CANCELLED'
            contract.save()
            contract.assets.update(status='AVAILABLE')
            messages.success(request, 'Contract cancelled.')
    return redirect('rentals:dashboard')

@login_required
def contract_complete(request, pk):
    contract = get_object_or_404(Contract, pk=pk)
    if contract.status == 'ACTIVE':
        with transaction.atomic():
            contract.status = 'COMPLETED'
            contract.save()
            contract.assets.update(status='AVAILABLE')
            messages.success(request, 'Contract completed.')
    return redirect('rentals:dashboard')

@login_required
def contract_payment(request, pk):
    contract = get_object_or_404(Contract, pk=pk)
    if request.method == 'POST':
        amount = Decimal(request.POST.get('payment_amount', '0'))
        if amount > 0:
            with transaction.atomic():
                contract.paid_amount += amount
                contract.save()
                messages.success(request, f'Payment of \u0e3f{amount} recorded.')
        return redirect('rentals:dashboard')
    return render(request, 'rentals/contract_payment.html', {'contract': contract})

@login_required
def reports(request):
    # Base query for both
    base_query = Contract.objects.all().order_by('-created_at')
    
    # Filtered rentals for screen view
    rentals = base_query
    
    tenants = Tenant.objects.all()
    
    tenant_id = request.GET.get('tenant')
    if tenant_id:
        rentals = rentals.filter(tenant_id=tenant_id)

    status = request.GET.get('status')
    if status:
        rentals = rentals.filter(status=status)
        
    return render(request, 'rentals/reports.html', {
        'rentals': rentals,       # Filtered
        'all_rentals': base_query, # Unfiltered for print
        'tenants': tenants,
        'selected_tenant': int(tenant_id) if tenant_id else None,
        'status_choices': Contract.STATUS_CHOICES,
        'selected_status': status,
    })
