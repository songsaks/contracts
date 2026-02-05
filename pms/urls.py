from django.urls import path
from . import views

app_name = 'pms'

urlpatterns = [
    path('', views.dashboard, name='dashboard'), # Changed index to dashboard
    path('projects/', views.project_list, name='project_list'),
    path('create/', views.project_create, name='project_create'),
    path('<int:pk>/', views.project_detail, name='project_detail'),
    path('<int:pk>/edit/', views.project_update, name='project_update'),
    path('<int:pk>/quotation/', views.project_quotation, name='project_quotation'),
    path('<int:project_id>/add-item/', views.item_add, name='item_add'),
    path('item/<int:item_id>/edit/', views.item_update, name='item_update'),
    path('item/<int:item_id>/delete/', views.item_delete, name='item_delete'),
    
    # Customer URLs
    path('customers/', views.customer_list, name='customer_list'),
    path('customers/create/', views.customer_create, name='customer_create'),
    path('customers/<int:pk>/edit/', views.customer_update, name='customer_update'),

    # Supplier URLs
    path('suppliers/', views.supplier_list, name='supplier_list'),
    path('suppliers/create/', views.supplier_create, name='supplier_create'),
    path('suppliers/<int:pk>/edit/', views.supplier_update, name='supplier_update'),
    # Manufacturer / Brand / Owner? -> Project Owner URLs
    path('owners/', views.project_owner_list, name='project_owner_list'),
    path('owners/create/', views.project_owner_create, name='project_owner_create'),
    path('owners/<int:pk>/edit/', views.project_owner_update, name='project_owner_update'),
]
