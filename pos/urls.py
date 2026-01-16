from django.urls import path
from . import views

app_name = 'pos'

urlpatterns = [
    # Main Page
    path('', views.pos_view, name='index'),
    
    # API endpoints
    path('api/products/', views.api_product_list, name='api_product_list'),
    path('api/products/create/', views.api_product_create, name='api_product_create'),
    path('api/products/<int:pk>/update/', views.api_product_update, name='api_product_update'),
    path('api/order/process/', views.api_process_order, name='api_process_order'),
]
