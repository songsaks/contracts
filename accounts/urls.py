from django.urls import path
from . import views

app_name = 'accounts'

urlpatterns = [
    path('users/', views.user_list, name='user_list'),
    path('users/add/', views.user_create, name='user_create'),
    path('users/import/', views.user_import_excel, name='user_import_excel'),
    path('users/<int:user_id>/edit/', views.user_update, name='user_update'),
    path('users/<int:user_id>/toggle-status/', views.user_toggle_status, name='user_toggle_status'),
]
