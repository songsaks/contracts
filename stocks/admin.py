from django.contrib import admin
from .models import (
    Watchlist, AnalysisCache, Portfolio, SoldStock, UserTelegramProfile,
    MomentumCandidate, MultiFactorCandidate, PrecisionScanCandidate,
    ValueScanCandidate, CupHandleCandidate, USSepaCandidate,
)


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


@admin.register(UserTelegramProfile)
class UserTelegramProfileAdmin(admin.ModelAdmin):
    list_display = ('user', 'chat_id', 'is_active')


# ─────────────────────────────────────────────────────────────────
# Scan Result Models
# ─────────────────────────────────────────────────────────────────

@admin.register(MomentumCandidate)
class MomentumCandidateAdmin(admin.ModelAdmin):
    list_display = ('symbol', 'market', 'user', 'price', 'technical_score', 'rsi', 'adx', 'scanned_at')
    list_filter = ('market', 'user')
    search_fields = ('symbol',)
    ordering = ('-scanned_at',)
    actions = ['delete_selected']

    def get_queryset(self, request):
        return super().get_queryset(request).select_related('user')


@admin.register(MultiFactorCandidate)
class MultiFactorCandidateAdmin(admin.ModelAdmin):
    list_display = ('symbol', 'user', 'price', 'super_score', 'momentum_score', 'volume_score', 'scanned_at')
    list_filter = ('user',)
    search_fields = ('symbol',)
    ordering = ('-scanned_at',)
    actions = ['delete_selected']

    def get_queryset(self, request):
        return super().get_queryset(request).select_related('user')


@admin.register(PrecisionScanCandidate)
class PrecisionScanCandidateAdmin(admin.ModelAdmin):
    list_display = ('symbol', 'market', 'user', 'scan_run', 'price', 'technical_score', 'rs_rating', 'stage2')
    list_filter = ('market', 'user', 'stage2', 'scan_run')
    search_fields = ('symbol',)
    ordering = ('-scan_run', '-technical_score')
    date_hierarchy = 'scan_run'
    actions = ['delete_selected']

    def get_queryset(self, request):
        return super().get_queryset(request).select_related('user')


@admin.register(ValueScanCandidate)
class ValueScanCandidateAdmin(admin.ModelAdmin):
    list_display = ('symbol', 'user', 'scan_run', 'price', 'total_score', 'pe_ratio', 'roe', 'sector')
    list_filter = ('user', 'sector')
    search_fields = ('symbol', 'name')
    ordering = ('-scan_run', '-total_score')
    date_hierarchy = 'scan_run'
    actions = ['delete_selected']

    def get_queryset(self, request):
        return super().get_queryset(request).select_related('user')


@admin.register(CupHandleCandidate)
class CupHandleCandidateAdmin(admin.ModelAdmin):
    list_display = ('symbol', 'user', 'scan_run', 'price', 'rs_rating', 'cup_depth_pct', 'breakout_price')
    list_filter = ('user',)
    search_fields = ('symbol',)
    ordering = ('-scan_run',)
    date_hierarchy = 'scan_run'
    actions = ['delete_selected']

    def get_queryset(self, request):
        return super().get_queryset(request).select_related('user')


@admin.register(USSepaCandidate)
class USSepaScandidateAdmin(admin.ModelAdmin):
    list_display = ('symbol', 'user', 'scan_run', 'price', 'rs_rating', 'stage2', 'vcp_setup', 'adx')
    list_filter = ('user', 'stage2', 'vcp_setup')
    search_fields = ('symbol', 'name')
    ordering = ('-scan_run', '-rs_rating')
    date_hierarchy = 'scan_run'
    actions = ['delete_selected']

    def get_queryset(self, request):
        return super().get_queryset(request).select_related('user')
