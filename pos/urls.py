from django.urls import path
from . import views

app_name = 'pos'

urlpatterns = [
    # Main Page
    path('', views.pos_view, name='index'),
    
    # API endpoints
    path('api/products/', views.api_product_list, name='api_product_list'),
    
    # Category Management
    path('api/categories/create/', views.api_category_create, name='api_category_create'),
    path('api/categories/<int:pk>/update/', views.api_category_update, name='api_category_update'),
    path('api/categories/<int:pk>/delete/', views.api_category_delete, name='api_category_delete'),

    path('api/products/create/', views.api_product_create, name='api_product_create'),
    path('api/products/<int:pk>/update/', views.api_product_update, name='api_product_update'),
    path('api/order/process/', views.api_process_order, name='api_process_order'),
    path('api/report/', views.api_sales_report, name='api_sales_report'),
    path('api/report/export/', views.export_sales_csv, name='export_sales_csv'),
]
