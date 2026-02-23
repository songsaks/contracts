from django.urls import path
from . import views

app_name = 'stocks'

urlpatterns = [
    path('', views.dashboard, name='dashboard'),
    path('analyze/<str:symbol>/', views.analyze, name='analyze'),
    path('watchlist/add/', views.add_to_watchlist, name='add_to_watchlist'),
    path('watchlist/<int:pk>/delete/', views.delete_from_watchlist, name='delete_from_watchlist'),
    path('portfolio/', views.portfolio_list, name='portfolio_list'),
    path('portfolio/add/', views.add_to_portfolio, name='add_to_portfolio'),
    path('portfolio/<int:pk>/delete/', views.delete_from_portfolio, name='delete_from_portfolio'),
    path('recommendations/', views.recommendations, name='recommendations'),
    path('macro/', views.macro_economy, name='macro'),
]
