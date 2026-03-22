from django.urls import path
from . import views

app_name = 'stocks'

urlpatterns = [
    path('', views.dashboard, name='dashboard'),
    path('analyze/<str:symbol>/', views.analyze, name='analyze'),
    path('watchlist/add/', views.add_to_watchlist, name='add_to_watchlist'),
    path('watchlist/<int:pk>/delete/', views.delete_from_watchlist, name='delete_from_watchlist'),
    path('portfolio/', views.portfolio_list, name='portfolio_list'),
    path('portfolio/scan/', views.portfolio_scan, name='portfolio_scan'),
    path('portfolio/add/', views.add_to_portfolio, name='add_to_portfolio'),
    path('portfolio/<int:pk>/delete/', views.delete_from_portfolio, name='delete_from_portfolio'),
    path('portfolio/<int:pk>/sell/', views.sell_stock, name='sell_stock'),
    path('portfolio/report/', views.realized_pl_report, name='realized_pl_report'),
    path('portfolio/exit-plan/', views.portfolio_exit_plan, name='portfolio_exit_plan'),
    path('recommendations/', views.recommendations, name='recommendations'),
    path('us-recommendations/', views.us_recommendations, name='us_recommendations'),
    path('macro/', views.macro_economy, name='macro'),
    path('momentum/', views.momentum_scanner, name='momentum_scanner'),
    path('momentum/precision/', views.precision_momentum_scanner, name='precision_momentum_scanner'),
    path('multi-factor/', views.multi_factor_scanner, name='multi_factor_scanner'),
    path('entry-finder/<str:symbol>/', views.entry_finder, name='entry_finder'),
    path('signup/', views.signup, name='signup'),
]
