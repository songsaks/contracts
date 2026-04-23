from django.urls import path
from . import views

app_name = 'board'

urlpatterns = [
    path('', views.board_list, name='list'),
    path('post/new/', views.board_create_post, name='create_post'),
    path('post/<int:pk>/', views.board_post_detail, name='post_detail'),
    path('post/<int:pk>/delete/', views.board_delete_post, name='delete_post'),
    path('post/<int:post_pk>/comment/', views.board_add_comment, name='add_comment'),
    path('comment/<int:pk>/delete/', views.board_delete_comment, name='delete_comment'),
    path('attachment/<int:pk>/delete/', views.delete_attachment, name='delete_attachment'),
    path('access/', views.board_manage_access, name='manage_access'),
    path('tags/', views.tag_manage, name='tag_manage'),
    path('categories/', views.category_list, name='category_list'),
    path('categories/create/', views.category_create, name='category_create'),
    path('categories/<int:pk>/edit/', views.category_edit, name='category_edit'),
    path('categories/<int:pk>/delete/', views.category_delete, name='category_delete'),
    path('upload-image/', views.upload_image, name='upload_image'),
    path('like/<int:pk>/', views.toggle_like, name='toggle_like'),
    path('dashboard/', views.board_dashboard, name='dashboard'),
]
