from django.urls import path
from . import views

app_name = 'stocks'

urlpatterns = [
    path('', views.dashboard, name='dashboard'),
    path('analyze/<str:symbol>/', views.analyze, name='analyze'),
    path('analyze/crew/<str:symbol>/', views.crew_analyze, name='crew_analyze'),
    path('watchlist/add/', views.add_to_watchlist, name='add_to_watchlist'),
    path('watchlist/<int:pk>/delete/', views.delete_from_watchlist, name='delete_from_watchlist'),
    path('portfolio/', views.portfolio_list, name='portfolio_list'),
    path('portfolio/scan/', views.portfolio_scan, name='portfolio_scan'),
    path('portfolio/add/', views.add_to_portfolio, name='add_to_portfolio'),
    path('portfolio/<int:pk>/delete/', views.delete_from_portfolio, name='delete_from_portfolio'),
    path('portfolio/<int:pk>/sell/', views.sell_stock, name='sell_stock'),
    path('portfolio/report/', views.realized_pl_report, name='realized_pl_report'),
    path('portfolio/tithe/', views.tithe_report, name='tithe_report'),
    path('portfolio/tithe/mark-paid/', views.tithe_mark_paid, name='tithe_mark_paid'),
    path('portfolio/exit-plan/', views.portfolio_exit_plan, name='portfolio_exit_plan'),
    path('recommendations/', views.recommendations, name='recommendations'),
    path('us-recommendations/', views.us_recommendations, name='us_recommendations'),
    path('macro/', views.macro_economy, name='macro'),
    path('momentum/', views.momentum_scanner, name='momentum_scanner'),
    path('momentum/precision/', views.precision_momentum_scanner, name='precision_momentum_scanner'),
    path('momentum/precision/ai/', views.precision_scan_ai_analysis, name='precision_scan_ai_analysis'),
    path('momentum/precision/watchlist/', views.scan_watchlist_view, name='scan_watchlist_view'),
    path('momentum/precision/watchlist/toggle/', views.watchlist_item_toggle, name='watchlist_item_toggle'),
    path('momentum/us-precision/', views.us_precision_scanner, name='us_precision_scanner'),
    path('momentum/us-precision/ai/', views.us_precision_scan_ai_analysis, name='us_precision_scan_ai_analysis'),
    path('multi-factor/', views.multi_factor_scanner, name='multi_factor_scanner'),
    path('value/us-value/', views.us_value_scanner, name='us_value_scanner'),
    path('entry-finder/<str:symbol>/', views.entry_finder, name='entry_finder'),
    path('signup/', views.signup, name='signup'),
]
