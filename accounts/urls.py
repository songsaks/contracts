from django.urls import path
from . import views

app_name = 'accounts'

urlpatterns = [
    path('users/', views.user_list, name='user_list'),
    path('users/add/', views.user_create, name='user_create'),
    path('users/import/', views.user_import_excel, name='user_import_excel'),
    path('users/<int:user_id>/edit/', views.user_update, name='user_update'),
    path('users/<int:user_id>/toggle-status/', views.user_toggle_status, name='user_toggle_status'),
    # Role management
    path('roles/', views.role_list, name='role_list'),
    path('roles/add/', views.role_create, name='role_create'),
    path('roles/<int:role_id>/edit/', views.role_update, name='role_update'),
    path('roles/<int:role_id>/delete/', views.role_delete, name='role_delete'),
]
