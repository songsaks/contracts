from django.db import models
from django.contrib.auth import get_user_model

User = get_user_model()

class AssetCategory(models.TextChoices):
    STOCK = 'STOCK', 'Stock (หุ้น)'
    CRYPTO = 'CRYPTO', 'Cryptocurrency'
    COMMODITY = 'COMMODITY', 'Commodity (ทอง/น้ำมัน)'
    FOREX = 'FOREX', 'Forex'

class Watchlist(models.Model):
    symbol = models.CharField(max_length=20, unique=True, help_text="e.g. AAPL, BTC-USD, PTT.BK, GC=F")
    name = models.CharField(max_length=100, blank=True)
    category = models.CharField(max_length=20, choices=AssetCategory.choices, default=AssetCategory.STOCK)
    is_active = models.BooleanField(default=True)
    created_at = models.DateTimeField(auto_now_add=True)
    
    class Meta:
        verbose_name = "Watchlist"
        verbose_name_plural = "Watchlists"
        ordering = ['symbol']

    def __str__(self):
        return f"{self.symbol} - {self.name or 'N/A'}"

class AnalysisCache(models.Model):
    symbol = models.CharField(max_length=20)
    analysis_data = models.TextField(help_text="JSON or Markdown from AI")
    last_updated = models.DateTimeField(auto_now=True)
    
    class Meta:
        ordering = ['-last_updated']

    def __str__(self):
        return f"Analysis: {self.symbol} at {self.last_updated}"

class Portfolio(models.Model):
    symbol = models.CharField(max_length=20, unique=True)
    name = models.CharField(max_length=100, blank=True)
    quantity = models.DecimalField(max_digits=12, decimal_places=4, default=0)
    entry_price = models.DecimalField(max_digits=12, decimal_places=4, default=0)
    category = models.CharField(max_length=20, choices=AssetCategory.choices, default=AssetCategory.STOCK)
    added_at = models.DateTimeField(auto_now_add=True)

    class Meta:
        verbose_name = "Portfolio"
        verbose_name_plural = "Portfolios"
        ordering = ['symbol']

    def __str__(self):
        return f"Port: {self.symbol} ({self.quantity})"

class MomentumCandidate(models.Model):
    symbol = models.CharField(max_length=20)
    symbol_bk = models.CharField(max_length=30, blank=True)
    sector = models.CharField(max_length=100, default="Unknown")
    price = models.FloatField(default=0.0)
    rsi = models.FloatField(default=0.0)
    adx = models.FloatField(default=0.0)
    mfi = models.FloatField(default=0.0)
    rvol = models.FloatField(default=1.0)
    eps_growth = models.FloatField(default=0.0)
    rev_growth = models.FloatField(default=0.0)
    technical_score = models.IntegerField(default=0)
    year_high = models.FloatField(default=0.0)
    upside_to_high = models.FloatField(default=0.0)
    scanned_at = models.DateTimeField(auto_now=True)

    class Meta:
        ordering = ['-technical_score']

    def __str__(self):
        return f"{self.symbol} - Score: {self.technical_score}"

class ScannableSymbol(models.Model):
    symbol = models.CharField(max_length=20, unique=True)
    index_name = models.CharField(max_length=50, default="SET100")
    is_active = models.BooleanField(default=True)
    last_updated = models.DateTimeField(auto_now=True)

    class Meta:
        ordering = ['symbol']

    def __str__(self):
        return f"{self.symbol} ({self.index_name})"
