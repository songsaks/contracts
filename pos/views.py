from django.shortcuts import render, get_object_or_404
from django.http import JsonResponse
from django.views.decorators.http import require_POST
from django.db import transaction
from django.views.decorators.csrf import ensure_csrf_cookie
import json
from .models import Product, Order, OrderItem, Category
from .forms import ProductForm

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
    }
    return render(request, 'pos/index.html', context)

# --- API Endpoints for SPA ---

def api_product_list(request):
    """JSON API to get info for all products (refreshing data)"""
    products = Product.objects.filter(is_active=True).values(
        'id', 'name', 'price', 'stock', 'code', 'category_id', 'image'
    )
    return JsonResponse({'status': 'success', 'products': list(products)})

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

@require_POST
def api_process_order(request):
    """JSON API to process the checkout"""
    try:
        data = json.loads(request.body)
        items = data.get('items', [])
        payment_method = data.get('payment_method', 'CASH')
        
        if not items:
            return JsonResponse({'status': 'error', 'message': 'No items in order'}, status=400)

        with transaction.atomic():
            order = Order.objects.create(
                payment_method=payment_method,
                status='COMPLETED'
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
            
            order.total_amount = total
            order.save()
            
        return JsonResponse({
            'status': 'success', 
            'order_id': order.id, 
            'total': float(total)
        })
    except Exception as e:
        return JsonResponse({'status': 'error', 'message': str(e)}, status=400)
