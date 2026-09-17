# ====== marketing/admin.py ======
from django.contrib import admin
from .models import (
    MarketingCampaign,
    AdCreative,
    DailyMetric,
    AIActionPlan,
    CreativeIdea,
    CompetitorIntel,
)


@admin.register(MarketingCampaign)
class MarketingCampaignAdmin(admin.ModelAdmin):
    list_display = ('name', 'platform', 'objective', 'status', 'daily_budget', 'target_roas', 'updated_at')
    list_filter = ('platform', 'objective', 'status')
    search_fields = ('name', 'target_audience', 'product_focus')


@admin.register(AdCreative)
class AdCreativeAdmin(admin.ModelAdmin):
    list_display = ('name', 'campaign', 'format', 'status', 'angle', 'created_at')
    list_filter = ('status', 'format', 'campaign')
    search_fields = ('name', 'hook_text', 'angle')


@admin.register(DailyMetric)
class DailyMetricAdmin(admin.ModelAdmin):
    list_display = ('date', 'campaign', 'creative', 'platform', 'ad_spend', 'revenue', 'conversions')
    list_filter = ('date', 'platform', 'campaign')
    date_hierarchy = 'date'


@admin.register(AIActionPlan)
class AIActionPlanAdmin(admin.ModelAdmin):
    list_display = ('date', 'title', 'status_level', 'total_spend', 'total_revenue', 'overall_roas', 'net_profit', 'created_at')
    list_filter = ('status_level', 'date')
    date_hierarchy = 'date'


@admin.register(CreativeIdea)
class CreativeIdeaAdmin(admin.ModelAdmin):
    list_display = ('product_name', 'angle_theme', 'format', 'is_favorite', 'created_at')
    list_filter = ('format', 'is_favorite')
    search_fields = ('product_name', 'angle_theme', 'target_persona')


@admin.register(CompetitorIntel)
class CompetitorIntelAdmin(admin.ModelAdmin):
    list_display = ('brand_name', 'platform', 'pricing_promotion', 'observed_date')
    list_filter = ('platform', 'observed_date')
    search_fields = ('brand_name', 'hook_observed', 'ai_counter_strategy')
