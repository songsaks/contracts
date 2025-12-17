from django.urls import path
from . import views

app_name = 'rentals'

urlpatterns = [
    path('', views.dashboard, name='dashboard'),
    path('assets/', views.asset_list, name='asset_list'),
    path('assets/new/', views.asset_create, name='asset_create'),
    path('assets/<int:pk>/edit/', views.asset_edit, name='asset_edit'),
    path('assets/import/', views.asset_import, name='asset_import'),
    path('tenants/new/', views.tenant_create, name='tenant_create'),
    path('contracts/new/', views.contract_create, name='contract_create'),
    path('contracts/<int:pk>/cancel/', views.contract_cancel, name='contract_cancel'),
    path('contracts/<int:pk>/complete/', views.contract_complete, name='contract_complete'),
    path('contracts/<int:pk>/payment/', views.contract_payment, name='contract_payment'),
    path('reports/', views.reports, name='reports'),
]
