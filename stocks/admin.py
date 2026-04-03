from django.contrib import admin
from .models import Watchlist, AnalysisCache, Portfolio, SoldStock

@admin.register(Watchlist)
class WatchlistAdmin(admin.ModelAdmin):
    list_display = ('symbol', 'name', 'category', 'user', 'is_active', 'created_at')
    list_filter = ('category', 'is_active')
    search_fields = ('symbol', 'name')

@admin.register(AnalysisCache)
class AnalysisCacheAdmin(admin.ModelAdmin):
    list_display = ('symbol', 'user', 'last_updated')
    search_fields = ('symbol',)

@admin.register(Portfolio)
class PortfolioAdmin(admin.ModelAdmin):
    list_display = ('symbol', 'user', 'quantity', 'entry_price', 'added_at')
    search_fields = ('symbol',)

@admin.register(SoldStock)
class SoldStockAdmin(admin.ModelAdmin):
    list_display = ('symbol', 'user', 'quantity', 'sell_price', 'profit_loss', 'sold_at')
    list_filter = ('symbol', 'sold_at')
    search_fields = ('symbol',)

from .models import UserTelegramProfile
@admin.register(UserTelegramProfile)
class UserTelegramProfileAdmin(admin.ModelAdmin):
    list_display = ('user', 'chat_id', 'is_active')
