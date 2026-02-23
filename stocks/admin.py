from django.contrib import admin
from .models import Watchlist, AnalysisCache

@admin.register(Watchlist)
class WatchlistAdmin(admin.ModelAdmin):
    list_display = ('symbol', 'name', 'category', 'is_active', 'created_at')
    list_filter = ('category', 'is_active')
    search_fields = ('symbol', 'name')

@admin.register(AnalysisCache)
class AnalysisCacheAdmin(admin.ModelAdmin):
    list_display = ('symbol', 'last_updated')
    search_fields = ('symbol',)
