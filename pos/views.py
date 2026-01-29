from django.shortcuts import render, get_object_or_404
from django.http import JsonResponse
from django.views.decorators.http import require_POST
from django.db import transaction
from django.db.models import Sum, F
from django.utils import timezone
from django.views.decorators.csrf import ensure_csrf_cookie
import json
from django.contrib.auth.decorators import login_required
from .models import Product, Order, OrderItem, Category
from .forms import ProductForm, CategoryForm

@login_required
@ensure_csrf_cookie
def pos_view(request):
    """
    Main Single Page Application view.
    Loads initial data and renders the SPA template.
    """
    products = Product.objects.filter(is_active=True).select_related('category').order_by('category__name', 'name')
    categories = Category.objects.all()
    context = {
        'products': products,
        'categories': categories,
        'user': request.user,
    }
    return render(request, 'pos/index.html', context)

# --- API Endpoints for SPA ---

@login_required
def api_product_list(request):
    """JSON API to get info for all products (refreshing data)"""
    products = Product.objects.filter(is_active=True).values(
        'id', 'name', 'price', 'stock', 'code', 'category_id', 'image'
    )
    return JsonResponse({'status': 'success', 'products': list(products)})

@login_required
@require_POST
def api_product_create(request):
    """JSON API to create a new product"""
    form = ProductForm(request.POST, request.FILES)
    if form.is_valid():
        product = form.save()
        return JsonResponse({
            'status': 'success',
            'product': {
                'id': product.id,
                'name': product.name,
                'price': float(product.price),
                'stock': product.stock,
                'category_id': product.category.id if product.category else None,
                'image_url': product.image.url if product.image else None
            }
        })
    return JsonResponse({'status': 'error', 'errors': form.errors}, status=400)

@login_required
@require_POST
def api_product_update(request, pk):
    """JSON API to update a product"""
    product = get_object_or_404(Product, pk=pk)
    form = ProductForm(request.POST, request.FILES, instance=product)
    if form.is_valid():
        product = form.save()
        return JsonResponse({
            'status': 'success',
             'product': {
                'id': product.id,
                'name': product.name,
                'price': float(product.price),
                'stock': product.stock,
                'category_id': product.category.id if product.category else None,
                'image_url': product.image.url if product.image else None
            }
        })
    return JsonResponse({'status': 'error', 'errors': form.errors}, status=400)

@login_required
@require_POST
def api_process_order(request):
    """JSON API to process the checkout"""
    try:
        data = json.loads(request.body)
        items = data.get('items', [])
        payment_method = data.get('payment_method', 'CASH')
        discount = float(data.get('discount', 0))
        
        if not items:
            return JsonResponse({'status': 'error', 'message': 'No items in order'}, status=400)

        with transaction.atomic():
            order = Order.objects.create(
                payment_method=payment_method,
                status='COMPLETED',
                discount_amount=discount
            )
            
            total = 0
            for item in items:
                try:
                    product = Product.objects.get(id=item['id'])
                except Product.DoesNotExist:
                    continue
                
                quantity = int(item['quantity'])
                if quantity <= 0: continue
                    
                price = product.price 
                subtotal = price * quantity
                
                OrderItem.objects.create(
                    order=order,
                    product=product,
                    quantity=quantity,
                    price=price,
                    subtotal=subtotal
                )
                
                # Simple stock management
                product.stock -= quantity
                product.save()
                
                total += subtotal
            
            # Apply Discount to Total
            final_total = max(0, float(total) - discount)
            order.total_amount = final_total
            order.save()
            
        return JsonResponse({
            'status': 'success', 
            'order_id': order.id, 
            'total': float(total)
        })
    except Exception as e:
        return JsonResponse({'status': 'error', 'message': str(e)}, status=400)

# --- Category Management ---

@login_required
@require_POST
def api_category_create(request):
    """JSON API to create a new category"""
    name = request.POST.get('name')
    if name:
        category = Category.objects.create(name=name)
        return JsonResponse({
            'status': 'success',
            'category': {'id': category.id, 'name': category.name}
        })
    return JsonResponse({'status': 'error', 'message': 'Name is required'}, status=400)

@login_required
@require_POST
def api_category_update(request, pk):
    """JSON API to update a category"""
    category = get_object_or_404(Category, pk=pk)
    name = request.POST.get('name')
    if name:
        category.name = name
        category.save()
        return JsonResponse({
            'status': 'success',
            'category': {'id': category.id, 'name': category.name}
        })
    return JsonResponse({'status': 'error', 'message': 'Name is required'}, status=400)

@login_required
@require_POST
def api_category_delete(request, pk):
    """JSON API to delete a category"""
    category = get_object_or_404(Category, pk=pk)
    category.delete()
    return JsonResponse({'status': 'success'})

@login_required
def api_sales_report(request):
    """JSON API to get sales report data"""
    today = timezone.now().date()
    
    # Get date range from request (default to today)
    start_date = request.GET.get('start_date')
    end_date = request.GET.get('end_date')
    
    try:
        if start_date:
            start_date = timezone.datetime.strptime(start_date, '%Y-%m-%d').date()
        else:
            start_date = today
            
        if end_date:
            end_date = timezone.datetime.strptime(end_date, '%Y-%m-%d').date()
        else:
            end_date = start_date
    except ValueError:
        # Fallback to today if parsing fails
        start_date = today
        end_date = today

    # Filter completed orders within range
    # created_at is DateTime, so we filter by date range
    orders_qs = Order.objects.filter(
        status='COMPLETED', 
        created_at__date__gte=start_date,
        created_at__date__lte=end_date
    )
    
    total_sales = orders_qs.aggregate(sum=Sum('total_amount'))['sum'] or 0
    
    # Payment method breakdown
    cash_sales = orders_qs.filter(payment_method='CASH').aggregate(sum=Sum('total_amount'))['sum'] or 0
    qr_sales = orders_qs.filter(payment_method='QR').aggregate(sum=Sum('total_amount'))['sum'] or 0
    
    # Stock info (Always current)
    stock_value = Product.objects.filter(is_active=True).aggregate(
        val=Sum(F('price') * F('stock'))
    )['val'] or 0
    
    # Low stock items (< 10)
    low_stock_qs = Product.objects.filter(is_active=True, stock__lt=10)
    low_stock = []
    for p in low_stock_qs:
        low_stock.append({
            'name': p.name,
            'stock': p.stock,
            'image': p.image.url if p.image else None,
            'price': float(p.price)
        })
    
    # Recent orders (last 5 within filter)
    recent_orders_qs = orders_qs.order_by('-created_at')[:20] # Show more orders if filtering
    recent_orders = []
    for o in recent_orders_qs:
        recent_orders.append({
            'id': o.id,
            'total_amount': float(o.total_amount),
            'payment_method': o.payment_method,
            'created_at': o.created_at
        })
    
    # Product Performance (Detailed)
    # 1. Get all active products
    all_products = Product.objects.filter(is_active=True).select_related('category')
    
    # 2. Aggregate sales for the period
    sales_stats = OrderItem.objects.filter(
        order__status='COMPLETED',
        order__created_at__date__gte=start_date,
        order__created_at__date__lte=end_date
    ).values('product').annotate(
        total_qty=Sum('quantity'),
        total_revenue=Sum('subtotal')
    )
    
    # 3. Map sales data
    sales_map = {stat['product']: stat for stat in sales_stats}
    
    product_performance = []
    for p in all_products:
        stat = sales_map.get(p.id, {'total_qty': 0, 'total_revenue': 0})
        product_performance.append({
            'name': p.name,
            'code': p.code or '-',
            'category': p.category.name if p.category else 'Uncategorized',
            'price': float(p.price),
            'stock': p.stock,
            'sold_qty': stat['total_qty'] or 0,
            'revenue': float(stat['total_revenue'] or 0)
        })
        
    # Discount
    total_discount = orders_qs.aggregate(sum=Sum('discount_amount'))['sum'] or 0

    return JsonResponse({
        'status': 'success',
        'data': {
            'sales_amount': float(total_sales),
            'cash_sales': float(cash_sales),
            'qr_sales': float(qr_sales),
            'total_discount': float(total_discount),
            'stock_value': float(stock_value),
            'low_stock': low_stock,
            'recent_orders': recent_orders,
            'product_performance': product_performance,
            'period': {
                'start': start_date,
                'end': end_date
            }
        }
    })

@login_required
def export_sales_csv(request):
    """Export sales report to CSV"""
    import csv
    from django.http import HttpResponse

    today = timezone.now().date()
    start_date = request.GET.get('start_date')
    end_date = request.GET.get('end_date')
    
    try:
        if start_date:
            start_date = timezone.datetime.strptime(start_date, '%Y-%m-%d').date()
        else:
            start_date = today
        if end_date:
            end_date = timezone.datetime.strptime(end_date, '%Y-%m-%d').date()
        else:
            end_date = start_date
    except ValueError:
        start_date = today
        end_date = today

    response = HttpResponse(content_type='text/csv')
    response['Content-Disposition'] = f'attachment; filename="sales_report_{start_date}_{end_date}.csv"'
    
    # BOM for Excel to open UTF-8 correctly
    response.write(u'\ufeff'.encode('utf8'))
    
    writer = csv.writer(response)
    writer.writerow(['Period', f'{start_date} to {end_date}'])
    writer.writerow([])
    
    # Summary
    orders_qs = Order.objects.filter(
        status='COMPLETED', 
        created_at__date__gte=start_date,
        created_at__date__lte=end_date
    )
    total_sales = orders_qs.aggregate(sum=Sum('total_amount'))['sum'] or 0
    total_discount = orders_qs.aggregate(sum=Sum('discount_amount'))['sum'] or 0
    cash_sales = orders_qs.filter(payment_method='CASH').aggregate(sum=Sum('total_amount'))['sum'] or 0
    qr_sales = orders_qs.filter(payment_method='QR').aggregate(sum=Sum('total_amount'))['sum'] or 0

    writer.writerow(['Total Sales', total_sales])
    writer.writerow(['Total Discount', total_discount])
    writer.writerow(['Total Cash Get', cash_sales])
    writer.writerow(['QR Sales', qr_sales])
    writer.writerow([])

    # Product Details
    writer.writerow(['Product Name', 'Code', 'Category', 'Current Price', 'Current Stock', 'Sold Qty', 'Revenue'])
    
    sales_stats = OrderItem.objects.filter(
        order__status='COMPLETED',
        order__created_at__date__gte=start_date,
        order__created_at__date__lte=end_date
    ).values('product').annotate(
        total_qty=Sum('quantity'),
        total_revenue=Sum('subtotal')
    )
    sales_map = {stat['product']: stat for stat in sales_stats}
    
    products = Product.objects.filter(is_active=True).select_related('category').order_by('name')
    
    for p in products:
        stat = sales_map.get(p.id, {'total_qty': 0, 'total_revenue': 0})
        writer.writerow([
            p.name,
            p.code or '-',
            p.category.name if p.category else 'Uncategorized',
            p.price,
            p.stock,
            stat['total_qty'] or 0,
            stat['total_revenue'] or 0
        ])
        
    return response
