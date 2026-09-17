# ====== marketing/urls.py ======
from django.urls import path
from . import views

app_name = 'marketing'

urlpatterns = [
    path('', views.dashboard, name='dashboard'),
    path('dashboard/', views.dashboard, name='dashboard_alt'),
    path('campaigns/', views.campaign_list, name='campaign_list'),
    path('campaigns/create/', views.campaign_create, name='campaign_create'),
    path('creatives/create/', views.creative_create, name='creative_create'),
    path('metrics/', views.daily_metrics, name='daily_metrics'),
    path('action-plans/', views.action_plans, name='action_plans'),
    path('creative-lab/', views.creative_lab, name='creative_lab'),
    path('competitor-radar/', views.competitor_radar, name='competitor_radar'),
    path('guide/', views.user_guide, name='user_guide'),
    path('campaigns/<int:pk>/delete/', views.campaign_delete, name='campaign_delete'),
    path('metrics/<int:pk>/delete/', views.metric_delete, name='metric_delete'),
    path('action-plans/<int:pk>/delete/', views.action_plan_delete, name='action_plan_delete'),
    path('competitor-radar/<int:pk>/delete/', views.competitor_delete, name='competitor_delete'),
    path('creative-lab/<int:pk>/delete/', views.creative_idea_delete, name='creative_idea_delete'),

    # ====== APIs ======
    path('api/generate-action-plan/', views.api_generate_action_plan, name='api_generate_action_plan'),
    path('api/toggle-action-item/', views.api_toggle_action_item, name='api_toggle_action_item'),
    path('api/generate-creative/', views.api_generate_creative, name='api_generate_creative'),
    path('api/analyze-competitor/', views.api_analyze_competitor, name='api_analyze_competitor'),
]
