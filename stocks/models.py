# ====== models.py — ระบบวิเคราะห์หุ้น AI (stocks app) ======
# กำหนดโครงสร้างฐานข้อมูลทั้งหมดของแอป stocks
# ครอบคลุม Watchlist, AnalysisCache, Portfolio, MomentumCandidate, ScannableSymbol

from django.db import models
from django.contrib.auth import get_user_model

# ดึง User model ที่กำหนดไว้ใน settings (รองรับ Custom User)
User = get_user_model()

# ====== ประเภทสินทรัพย์ ======

class AssetCategory(models.TextChoices):
    """ประเภทของสินทรัพย์ที่ระบบรองรับ ใช้ใน Watchlist และ Portfolio"""
    STOCK = 'STOCK', 'Stock (หุ้น)'
    CRYPTO = 'CRYPTO', 'Cryptocurrency'
    COMMODITY = 'COMMODITY', 'Commodity (ทอง/น้ำมัน)'
    FOREX = 'FOREX', 'Forex'
# ====== Telegram Integration ======
class UserTelegramProfile(models.Model):
    """
    ผูกบัญชีผู้ใช้เว็บในระบบเข้ากับ Telegram Chat ID สำหรับรับแจ้งเตือน
    """
    user = models.OneToOneField(User, on_delete=models.CASCADE, related_name='telegram_profile')
    chat_id = models.CharField(max_length=50, unique=True, help_text="ได้จากการทักหาบอทแล้วดู ID")
    is_active = models.BooleanField(default=True, help_text="เปิด/ปิด การแจ้งเตือนเข้า Telegram")
    created_at = models.DateTimeField(auto_now_add=True)

    class Meta:
        verbose_name = "Telegram Profile"
        verbose_name_plural = "Telegram Profiles"

    def __str__(self):
        return f"Telegram: {self.user.username} ({self.chat_id})"


# ====== Watchlist — รายการหุ้นที่ผู้ใช้ต้องการติดตาม ======

class Watchlist(models.Model):
    """
    บันทึกรายการสินทรัพย์ที่ผู้ใช้แต่ละคนต้องการเฝ้าติดตาม
    แต่ละ user จะมี symbol เดียวกันได้เพียงครั้งเดียว (unique_together)
    """
    # ผู้ใช้เจ้าของรายการ (ลบ user แล้ว watchlist ที่เชื่อมจะถูกลบตามด้วย)
    user = models.ForeignKey(User, on_delete=models.CASCADE, null=True, blank=True)
    # สัญลักษณ์หุ้น เช่น AAPL, BTC-USD, PTT.BK, GC=F
    symbol = models.CharField(max_length=20, help_text="e.g. AAPL, BTC-USD, PTT.BK, GC=F")
    # ชื่อเต็มของสินทรัพย์ (ไม่บังคับ)
    name = models.CharField(max_length=100, blank=True)
    # ประเภทสินทรัพย์ (หุ้น, คริปโต, สินค้าโภคภัณฑ์, Forex)
    category = models.CharField(max_length=20, choices=AssetCategory.choices, default=AssetCategory.STOCK)
    # สถานะการใช้งาน (สามารถปิดการใช้งานได้โดยไม่ต้องลบ)
    is_active = models.BooleanField(default=True)
    # วันที่เพิ่มเข้า watchlist
    created_at = models.DateTimeField(auto_now_add=True)

    class Meta:
        verbose_name = "Watchlist"
        verbose_name_plural = "Watchlists"
        ordering = ['symbol']
        # ผู้ใช้แต่ละคนมี symbol เดียวกันได้เพียงครั้งเดียว
        unique_together = ('user', 'symbol')

    def __str__(self):
        return f"{self.symbol} - {self.name or 'N/A'}"

# ====== AnalysisCache — แคชผลวิเคราะห์ AI เพื่อไม่ต้องเรียก API ซ้ำ ======

class AnalysisCache(models.Model):
    """
    เก็บผลการวิเคราะห์ AI (Gemini) สำหรับแต่ละ symbol ต่อผู้ใช้
    บันทึกเป็น JSON หรือ Markdown เพื่อแสดงผลซ้ำโดยไม่เสีย API quota
    """
    # ผู้ใช้เจ้าของผลวิเคราะห์
    user = models.ForeignKey(User, on_delete=models.CASCADE, null=True, blank=True)
    # สัญลักษณ์หุ้นที่วิเคราะห์
    symbol = models.CharField(max_length=20)
    # ข้อมูลผลวิเคราะห์ที่ได้รับจาก AI (รูปแบบ JSON หรือ Markdown)
    analysis_data = models.TextField(help_text="JSON or Markdown from AI")
    # เวลาที่อัปเดตล่าสุด (auto_now ทำให้อัปเดตทุกครั้งที่บันทึก)
    last_updated = models.DateTimeField(auto_now=True)

    class Meta:
        # เรียงจากผลวิเคราะห์ล่าสุดก่อน
        ordering = ['-last_updated']

    def __str__(self):
        return f"Analysis: {self.symbol} at {self.last_updated}"

# ====== Portfolio — พอร์ตการลงทุนของผู้ใช้ ======

class Portfolio(models.Model):
    """
    บันทึกรายการสินทรัพย์ที่ผู้ใช้ถือครองอยู่จริง
    ใช้คำนวณ P/L, Market Value, Trailing Stop และ DCA
    """
    # ผู้ใช้เจ้าของพอร์ต
    user = models.ForeignKey(User, on_delete=models.CASCADE, null=True, blank=True)
    # สัญลักษณ์หุ้น เช่น PTT.BK, AAPL
    symbol = models.CharField(max_length=20)
    # ชื่อสินทรัพย์ (ไม่บังคับ)
    name = models.CharField(max_length=100, blank=True)
    # จำนวนหน่วยที่ถือครอง (รองรับทศนิยม สำหรับ Crypto)
    quantity = models.DecimalField(max_digits=12, decimal_places=4, default=0)
    # ราคาทุนเฉลี่ย (Average Cost Basis)
    entry_price = models.DecimalField(max_digits=12, decimal_places=4, default=0)
    # ประเภทสินทรัพย์
    category = models.CharField(max_length=20, choices=AssetCategory.choices, default=AssetCategory.STOCK)
    # วันที่เพิ่มเข้าพอร์ต
    added_at = models.DateTimeField(auto_now_add=True)
    # ราคาสูงสุดนับจากเข้าซื้อ (ใช้คำนวณ Trailing Stop)
    highest_price = models.DecimalField(max_digits=12, decimal_places=4, default=0, blank=True)
    # ATR ล่าสุด ณ วันที่ scan (อัปเดตทุกครั้งที่ portfolio_scan)
    atr = models.FloatField(default=0.0, blank=True)
    # ATR multiplier สำหรับ trailing stop (default 2.5x ATR)
    trail_multiplier = models.FloatField(default=2.5, blank=True)

    class Meta:
        verbose_name = "Portfolio"
        verbose_name_plural = "Portfolios"
        ordering = ['symbol']
        # ผู้ใช้แต่ละคนมี symbol เดียวกันได้เพียงครั้งเดียวในพอร์ต
        unique_together = ('user', 'symbol')

    def __str__(self):
        return f"Port: {self.symbol} ({self.quantity})"

# ====== MomentumCandidate — ผลลัพธ์การสแกนหาหุ้น Momentum ======

class MomentumCandidate(models.Model):
    """
    เก็บผลลัพธ์ที่ได้จากการสแกนหุ้นด้วยเกณฑ์ Momentum/Trend Template
    (สไตล์ Mark Minervini) รวมถึงข้อมูล Supply & Demand Zone
    ข้อมูลนี้จะถูกลบและสร้างใหม่ทุกครั้งที่มีการสแกน
    """
    # ผู้ใช้ที่ทำการสแกน (แยกผลลัพธ์ตาม user)
    user = models.ForeignKey(User, on_delete=models.CASCADE, null=True, blank=True)
    # สัญลักษณ์หุ้น (ไม่มี .BK)
    symbol = models.CharField(max_length=20)
    # สัญลักษณ์ที่ใช้ query Yahoo Finance (มี .BK ต่อท้าย)
    symbol_bk = models.CharField(max_length=30, blank=True)
    # กลุ่มอุตสาหกรรม เช่น Financial, Technology, Energy
    sector = models.CharField(max_length=100, default="Unknown")
    # ราคาปัจจุบัน ณ ขณะสแกน
    price = models.FloatField(default=0.0)
    # RSI 14 วัน (Relative Strength Index)
    rsi = models.FloatField(default=0.0)
    # ADX 14 วัน (Average Directional Index — วัดความแรงของเทรนด์)
    adx = models.FloatField(default=0.0)
    # MFI 14 วัน (Money Flow Index — วัดแรงซื้อ/ขาย)
    mfi = models.FloatField(default=0.0)
    # Relative Volume (ปริมาณซื้อขายปัจจุบันเทียบค่าเฉลี่ย 20 วัน)
    rvol = models.FloatField(default=1.0)
    # การเติบโตของกำไรต่อหุ้น (EPS Quarterly Growth %)
    eps_growth = models.FloatField(default=0.0)
    # การเติบโตของรายได้ (Revenue Growth %)
    rev_growth = models.FloatField(default=0.0)
    # คะแนนรวมทางเทคนิค (0-100) ใช้จัดอันดับหุ้น
    technical_score = models.IntegerField(default=0)

    # ====== Supply & Demand / Entry Strategy fields ======
    # กลยุทธ์การเข้าซื้อที่ระบบแนะนำ เช่น "Sniper (DZ)"
    entry_strategy = models.CharField(max_length=100, blank=True, verbose_name="กลยุทธ์การเข้าซื้อ")
    # ขอบบนของโซนเข้าซื้อ (Demand Zone — จุดที่รายใหญ่มักเข้าซื้อสะสม)
    demand_zone_start = models.FloatField(null=True, blank=True, verbose_name="โซนเข้าซื้อ (บน)")
    # ขอบล่างของโซนเข้าซื้อ (ราคาที่ต่ำที่สุดที่ยังถือว่าอยู่ในโซน)
    demand_zone_end = models.FloatField(null=True, blank=True, verbose_name="โซนเข้าซื้อ (ล่าง)")
    # จุดตัดขาดทุน (Stop Loss) อยู่ใต้ขอบล่างของโซนเล็กน้อย
    stop_loss = models.FloatField(null=True, blank=True, verbose_name="จุดตัดขาดทุน")
    # อัตราส่วนกำไร/ความเสี่ยง (Risk-Reward Ratio) ยิ่งสูงยิ่งดี
    risk_reward_ratio = models.FloatField(null=True, blank=True, verbose_name="RR Ratio")
    # ขอบล่างของโซนขาย (Supply Zone — เป้าหมายกำไร)
    supply_zone_start = models.FloatField(null=True, blank=True, verbose_name="โซนขาย (ล่าง)")
    # ขอบบนของโซนขาย (buffer เพื่อการแสดงผล)
    supply_zone_end = models.FloatField(null=True, blank=True, verbose_name="โซนขาย (บน)")

    # ราคาสูงสุดใน 52 สัปดาห์ (1 ปี)
    year_high = models.FloatField(default=0.0)
    # ระยะห่างจากราคาปัจจุบันไปยัง 52-Week High (%)
    upside_to_high = models.FloatField(default=0.0)
    # ระยะห่างจากราคาปัจจุบันไปยัง Demand Zone Start (%)
    # ค่า 999 = ยังไม่มีโซนหรือไม่สามารถคำนวณได้
    zone_proximity = models.FloatField(default=999.0, help_text="Percentage distance to Demand Zone Start")
    # เวลาที่สแกนล่าสุด (auto_now อัปเดตทุกครั้งที่บันทึก)
    scanned_at = models.DateTimeField(auto_now=True)

    class Meta:
        ordering = ['-technical_score']
        unique_together = ('user', 'symbol')

    def __str__(self):
        return f"{self.symbol} - Score: {self.technical_score}"

# ====== MultiFactorCandidate — ผลลัพธ์ Multi-Factor Scoring ======

class MultiFactorCandidate(models.Model):
    """
    เก็บผลการสแกนหุ้นด้วย Multi-Factor Super Score
    ประกอบด้วย 4 ปัจจัย: Momentum, Volume/Flow, Sentiment, Fundamental
    """
    user = models.ForeignKey(User, on_delete=models.CASCADE, null=True, blank=True)
    symbol = models.CharField(max_length=20)
    sector = models.CharField(max_length=100, default="Unknown")
    price = models.FloatField(default=0.0)

    # ====== Factor Scores ======
    momentum_score = models.IntegerField(default=0)   # max 40
    volume_score = models.IntegerField(default=0)     # max 30
    sentiment_score = models.IntegerField(default=0)  # max 20 (filled by AI)
    fundamental_score = models.IntegerField(default=0)  # max 10
    super_score = models.IntegerField(default=0)      # sum of all (max 100)

    # ====== Indicators ======
    rsi = models.FloatField(default=0.0)
    adx = models.FloatField(default=0.0)
    mfi = models.FloatField(default=0.0)
    rvol = models.FloatField(default=1.0)
    eps_growth = models.FloatField(default=0.0)
    rev_growth = models.FloatField(default=0.0)

    # ====== Sentiment (AI) ======
    sentiment_label = models.CharField(max_length=20, blank=True)   # บวก/กลาง/ลบ
    sentiment_reason = models.TextField(blank=True)

    # ====== EMA ======
    above_ema200 = models.BooleanField(default=False)
    above_ema50 = models.BooleanField(default=False)

    scanned_at = models.DateTimeField(auto_now=True)

    class Meta:
        ordering = ['-super_score']

    def __str__(self):
        return f"{self.symbol} - SuperScore: {self.super_score}"


# ====== PrecisionScanCandidate — ผลลัพธ์ Precision Momentum Scanner ======

class PrecisionScanCandidate(models.Model):
    """
    เก็บผลการสแกนหุ้นด้วย Precision Momentum Scanner (เวอร์ชันปรับปรุง)
    ปรับปรุงจาก MomentumCandidate:
    - ERC ต้องการ Volume ยืนยัน (body AND volume > 1.5x avg)
    - ADX filter >= 20 (กรองเฉพาะหุ้นที่มี trend แข็งแกร่ง)
    - Liquidity filter: avg 20d volume >= 500,000
    - Supply target = 52-week high เสมอ
    - ATR-based stop loss
    - Direction-aware RVOL scoring
    - เก็บประวัติ scan (3 runs ล่าสุด) + is_new_entry flag
    """
    user = models.ForeignKey(User, on_delete=models.CASCADE, null=True, blank=True)
    # ตลาด: 'SET' = ตลาดหุ้นไทย, 'US' = NYSE/Nasdaq
    market = models.CharField(max_length=10, default='SET', db_index=True)
    # เวลาที่รัน scan (ใช้ group scan runs ร่วมกัน)
    scan_run = models.DateTimeField(db_index=True)
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

    # ====== Precision-specific fields ======
    # ปริมาณซื้อขายเฉลี่ย 20 วัน (สำหรับแสดงผล Liquidity)
    avg_volume_20d = models.FloatField(default=0.0)
    # RVOL เกิดในวันขาขึ้น (True) หรือขาลง (False)
    rvol_bullish = models.BooleanField(default=True)
    # ERC มี Volume ยืนยันหรือไม่ (body + volume > 1.5x)
    erc_volume_confirmed = models.BooleanField(default=False)
    # แหล่งที่มาของ supply zone target ('52w' หรือ '120d')
    zone_target_source = models.CharField(max_length=10, default='52w')
    # หุ้นใหม่ในรอบสแกนนี้ (ไม่มีในรอบก่อน)
    is_new_entry = models.BooleanField(default=True)

    # ====== Supply & Demand Zone fields ======
    entry_strategy = models.CharField(max_length=100, blank=True)
    demand_zone_start = models.FloatField(null=True, blank=True)
    demand_zone_end = models.FloatField(null=True, blank=True)
    stop_loss = models.FloatField(null=True, blank=True)
    risk_reward_ratio = models.FloatField(null=True, blank=True)
    supply_zone_start = models.FloatField(null=True, blank=True)
    supply_zone_end = models.FloatField(null=True, blank=True)
    year_high = models.FloatField(default=0.0)
    upside_to_high = models.FloatField(default=0.0)
    zone_proximity = models.FloatField(default=999.0)

    # ====== Price Pattern fields ======
    price_pattern = models.CharField(max_length=30, blank=True, default='')
    price_pattern_score = models.IntegerField(default=0)  # positive=bullish, negative=bearish

    # ====== Relative Momentum vs SET Index ======
    rel_momentum_1m = models.FloatField(default=0.0)   # stock 1m return − SET 1m return (%)
    rel_momentum_3m = models.FloatField(default=0.0)   # stock 3m return − SET 3m return (%)

    # ====== New v3 indicators ======
    macd_histogram   = models.FloatField(null=True, blank=True)   # MACD histogram value (positive = bullish pressure)
    macd_crossover   = models.BooleanField(default=False)         # bullish MACD crossover in last 3 bars
    bb_squeeze       = models.BooleanField(default=False)         # Bollinger Band width in bottom 20th pct (pending breakout)
    ema20_aligned    = models.BooleanField(default=False)         # EMA20 > EMA50 > EMA200 full 3-layer alignment
    rs_rating        = models.IntegerField(default=0)             # Relative Strength Rating (0-99 percentile)

    # ====== Trend Following indicators (v4) ======
    ema20_slope      = models.FloatField(default=0.0)             # EMA20 slope % (5-day change) — >0.1% = rising
    ema20_rising     = models.BooleanField(default=False)         # EMA20 กำลังชี้ขึ้น (slope > 0.1%)
    hh_hl_structure  = models.BooleanField(default=False)         # Higher High + Higher Low ใน 20 candles ล่าสุด

    # ====== Stage Analysis & Risk (v5) ======
    stage2           = models.BooleanField(default=False)         # Weinstein Stage 2: price > SMA150 AND SMA150 rising
    earnings_soon    = models.BooleanField(default=False)         # US only: earnings date within 14 days (caution)

    # ====== Institutional Footprint (v6) ======
    pocket_pivot     = models.BooleanField(default=False)         # Pocket Pivot: up-day vol > max down-day vol in prior 10 sessions
    vdu_near_zone    = models.BooleanField(default=False)         # Volume Dry-Up: volume declining 3d + below 70% avg (quiet accumulation)

    # ====== Money Flow & Breakout (v7) ======
    cmf              = models.FloatField(null=True, blank=True)   # Chaikin Money Flow 20d (>0.1=accumulation, <-0.1=distribution)
    is_52w_breakout  = models.BooleanField(default=False)         # ราคาทะลุหรืออยู่ภายใน 1% ของ 52-week high

    # ====== Volume Surge ======
    volume_surge     = models.FloatField(default=1.0)             # current vol / avg_vol_20d ratio
    is_volume_surge  = models.BooleanField(default=False)         # True if volume_surge >= 1.5x

    # ====== Ichimoku Cloud (v8) ======
    ichimoku_above_kumo = models.BooleanField(default=False)      # ราคาอยู่เหนือ Kumo (SpanA & SpanB)
    ichimoku_tk_cross   = models.BooleanField(default=False)      # Tenkan ตัด Kijun ขึ้น ใน 5 แท่งล่าสุด
    ichimoku_kumo_green = models.BooleanField(default=False)      # Kumo อนาคตเป็นสีเขียว (SpanA > SpanB)
    ichimoku_chikou_ok  = models.BooleanField(default=False)      # Chikou อยู่เหนือราคา 26 แท่งก่อน
    ichimoku_score      = models.IntegerField(default=0)          # คะแนนรวม Ichimoku (0-4)

    # ====== Volatility Contraction Pattern (VCP) (v9) ======
    vcp_setup           = models.BooleanField(default=False)      # เข้าข่าย VCP Pattern หรือไม่
    vcp_contractions    = models.IntegerField(default=0)          # จำนวนการบีบตัว (T) เช่น 2, 3, 4
    vcp_tightness       = models.FloatField(default=0.0)          # ความลึกของการบีบตัวล่าสุด (%)
    vcp_vdu             = models.BooleanField(default=False)      # Volume Dry-Up ยืนยันในลูกสุดท้ายหรือไม่

    class Meta:
        ordering = ['-scan_run', '-technical_score']

    def __str__(self):
        return f"{self.symbol} - Score: {self.technical_score} (run: {self.scan_run})"


# ====== ScanWatchlistItem — ติดตามหุ้นจาก Precision Scanner ======
class ScanWatchlistItem(models.Model):
    """
    บันทึกหุ้นที่ผู้ใช้ต้องการติดตามจาก Precision Scanner
    แจ้งเตือนเมื่อ technical_score เปลี่ยนแปลงเกิน threshold ระหว่าง scan
    """
    user            = models.ForeignKey(User, on_delete=models.CASCADE, related_name='scan_watchlist')
    symbol          = models.CharField(max_length=20)
    market          = models.CharField(max_length=10, default='SET', db_index=True)
    sector          = models.CharField(max_length=100, default='Unknown')
    added_date      = models.DateTimeField(auto_now_add=True)
    note            = models.TextField(blank=True)
    alert_threshold = models.IntegerField(default=10)   # แจ้งเตือนเมื่อ score เปลี่ยน >= นี้

    class Meta:
        verbose_name = "Scan Watchlist Item"
        verbose_name_plural = "Scan Watchlist Items"
        unique_together = ('user', 'symbol', 'market')
        ordering = ['-added_date']

    def __str__(self):
        return f"Watch: {self.symbol} ({self.user.username})"


# ====== ValueScanCandidate — US Value Stock Scanner ======

class ValueScanCandidate(models.Model):
    user        = models.ForeignKey(User, on_delete=models.CASCADE)
    scan_run    = models.DateTimeField(db_index=True)
    symbol      = models.CharField(max_length=20)
    name        = models.CharField(max_length=100, default='')
    sector      = models.CharField(max_length=100, default='Unknown')
    price       = models.FloatField(default=0)
    market_cap  = models.FloatField(default=0)          # USD billions

    # ── Valuation Metrics ────────────────────────────────
    pe_ratio       = models.FloatField(null=True, blank=True)   # trailing P/E
    forward_pe     = models.FloatField(null=True, blank=True)
    pb_ratio       = models.FloatField(null=True, blank=True)
    peg_ratio      = models.FloatField(null=True, blank=True)
    ps_ratio       = models.FloatField(null=True, blank=True)
    dividend_yield = models.FloatField(default=0)               # percent

    # ── Quality Metrics ──────────────────────────────────
    roe            = models.FloatField(null=True, blank=True)   # percent
    profit_margin  = models.FloatField(null=True, blank=True)   # percent
    debt_equity    = models.FloatField(null=True, blank=True)   # ratio
    current_ratio  = models.FloatField(null=True, blank=True)
    revenue_growth = models.FloatField(null=True, blank=True)   # % YoY
    fcf_yield      = models.FloatField(null=True, blank=True)   # FCF/MktCap %

    # ── Price Action ─────────────────────────────────────
    rsi            = models.FloatField(default=50)
    year_high      = models.FloatField(default=0)
    year_low       = models.FloatField(default=0)
    pct_from_high  = models.FloatField(default=0)               # % below 52w high (positive = cheaper)
    above_ema200   = models.BooleanField(default=False)

    # ── Scores ───────────────────────────────────────────
    valuation_score    = models.IntegerField(default=0)         # 0-40
    quality_score      = models.IntegerField(default=0)         # 0-35
    price_action_score = models.IntegerField(default=0)         # 0-25
    total_score        = models.IntegerField(default=0)         # 0-100

    # ── Meta ─────────────────────────────────────────────
    is_new_entry = models.BooleanField(default=False)

    class Meta:
        ordering = ['-scan_run', '-total_score']

    def __str__(self):
        return f"{self.symbol} - Value Score: {self.total_score} (run: {self.scan_run})"


# ====== ScannableSymbol — รายชื่อหุ้นที่ระบบสแกนได้ ======

class ScannableSymbol(models.Model):
    """
    รายชื่อหุ้นที่ระบบจะสแกนเมื่อผู้ใช้กดปุ่ม Scan
    ข้อมูลถูก seed ครั้งแรกโดย refresh_set100_symbols()
    และถูกอัปเดตอัตโนมัติเมื่อมีการ login (ผ่าน signals.py)
    """
    # สัญลักษณ์หุ้น (ไม่มี .BK — จะถูกเติมอัตโนมัติตอนสแกน)
    symbol = models.CharField(max_length=20)
    # ชื่อดัชนีที่หุ้นนี้อยู่ เช่น "SET100", "SET100+MAI"
    index_name = models.CharField(max_length=50, default="SET100")
    # ตลาด: 'SET' = ตลาดหุ้นไทย, 'US' = NYSE/Nasdaq
    market = models.CharField(max_length=10, default='SET', db_index=True)
    # กลุ่มอุตสาหกรรม (cache จาก yfinance.info — ดึงครั้งเดียว)
    sector = models.CharField(max_length=100, default='Unknown', blank=True)
    # สถานะการใช้งาน (False = ไม่ถูกนำไปสแกน)
    is_active = models.BooleanField(default=True)
    # เวลาที่อัปเดตล่าสุด
    last_updated = models.DateTimeField(auto_now=True)

    class Meta:
        ordering = ['symbol']
        unique_together = ('symbol', 'market')

    def __str__(self):
        return f"{self.symbol} ({self.index_name}) [{self.market}]"


# ====== SoldStock — บันทึกประวัติการขายหุ้นและผลกำไรขาดทุน ======

class SoldStock(models.Model):
    """
    บันทึกรายการหุ้นที่ขายไปแล้ว เพื่อเก็บประวัติและคำนวณกำไร/ขาดทุน
    ใช้สำหรับแสดงกราฟ Performance ประวัติการเทรด
    """
    user = models.ForeignKey(User, on_delete=models.CASCADE)
    symbol = models.CharField(max_length=20)
    quantity = models.DecimalField(max_digits=12, decimal_places=4)
    buy_price = models.DecimalField(max_digits=12, decimal_places=4, help_text="ราคาทุนเฉลี่ยขณะที่ซื้อ")
    bought_at = models.DateTimeField(null=True, blank=True, help_text="วันที่เข้าซื้อครั้งแรก")
    sell_price = models.DecimalField(max_digits=12, decimal_places=4, help_text="ราคาที่ขายออกไป")
    profit_loss = models.DecimalField(max_digits=12, decimal_places=4, help_text="กำไร/ขาดทุนสุทธิ (เป็นจำนวนเงิน)")
    profit_loss_pct = models.DecimalField(max_digits=8, decimal_places=2, help_text="กำไร/ขาดทุน (%)")
    sold_at = models.DateTimeField(auto_now_add=True)

    class Meta:
        verbose_name = "Sold Stock"
        verbose_name_plural = "Sold Stocks"
        ordering = ['-sold_at']

    def __str__(self):
        return f"Sold: {self.symbol} (P/L: {self.profit_loss})"


# ====== TitheRecord — บันทึกการถวายทศางค์จากกำไรหุ้น ======

# ====== CupHandleCandidate — ผลลัพธ์ Cup & Handle Scanner ======

class CupHandleCandidate(models.Model):
    """
    เก็บผลการสแกนหุ้นที่กำลัง form Cup & Handle Pattern
    (William O'Neil — CAN SLIM methodology)
    """
    user     = models.ForeignKey(User, on_delete=models.CASCADE, null=True, blank=True)
    scan_run = models.DateTimeField(db_index=True)
    symbol   = models.CharField(max_length=20, db_index=True)
    sector   = models.CharField(max_length=100, default='Unknown')
    price    = models.FloatField(default=0.0)

    # ── Cup geometry ──────────────────────────────────────────────
    cup_high        = models.FloatField(default=0.0)   # ขอบซ้าย/ขวาของ Cup (pivot high)
    cup_low         = models.FloatField(default=0.0)   # ก้น Cup
    cup_depth_pct   = models.FloatField(default=0.0)   # ความลึก Cup เป็น % (15-35% = ideal)
    cup_length_days = models.IntegerField(default=0)   # ความยาว Cup เป็นวัน (≥35 วัน = ideal)
    cup_start_date  = models.DateField(null=True, blank=True)
    cup_end_date    = models.DateField(null=True, blank=True)

    # ── Handle geometry ───────────────────────────────────────────
    handle_high       = models.FloatField(default=0.0)  # ขอบบนของ Handle
    handle_low        = models.FloatField(default=0.0)  # ขอบล่างของ Handle
    handle_depth_pct  = models.FloatField(default=0.0)  # ความลึก Handle (≤15% = ideal)
    handle_length_days= models.IntegerField(default=0)
    handle_start_date = models.DateField(null=True, blank=True)

    # ── Breakout & Target ─────────────────────────────────────────
    breakout_price  = models.FloatField(default=0.0)   # ราคา breakout = cup_high
    target_price    = models.FloatField(default=0.0)   # target = cup_high + cup_depth
    stop_loss       = models.FloatField(default=0.0)   # SL = ใต้ handle_low
    risk_reward     = models.FloatField(default=0.0)

    # ── Volume ───────────────────────────────────────────────────
    avg_vol_20d         = models.FloatField(default=0.0)
    cup_vol_confirmed   = models.BooleanField(default=False)  # Volume ลดลงใน Cup (ideal)
    handle_vol_dry      = models.BooleanField(default=False)  # Volume แห้งใน Handle (ideal)

    # ── Pattern Stage ─────────────────────────────────────────────
    # 'forming'  = กำลัง form Cup ยังไม่ครบ
    # 'handle'   = Cup ครบแล้ว กำลัง form Handle
    # 'ready'    = Handle ครบ รอ Breakout
    # 'breakout' = Breakout แล้ว (Volume confirm)
    stage           = models.CharField(max_length=20, default='forming')
    confidence_score= models.IntegerField(default=0)   # 0-100
    rs_rating       = models.IntegerField(default=0)
    adx             = models.FloatField(default=0.0)
    rsi             = models.FloatField(default=0.0)

    class Meta:
        ordering = ['-scan_run', '-confidence_score']
        indexes  = [models.Index(fields=['user', 'scan_run'])]
        verbose_name = 'Cup & Handle Candidate'

    def __str__(self):
        return f"{self.symbol} [{self.stage}] score={self.confidence_score}"


class TitheRecord(models.Model):
    """
    ติดตามการถวายทศางค์ 10% จากกำไรหุ้นรายเดือน
    คำนวณจาก SoldStock.profit_loss ที่เป็นบวกในแต่ละเดือน
    """
    user = models.ForeignKey(User, on_delete=models.CASCADE)
    year = models.IntegerField()
    month = models.IntegerField()   # 1–12
    is_paid = models.BooleanField(default=False)
    paid_at = models.DateTimeField(null=True, blank=True)
    note = models.TextField(blank=True)

    class Meta:
        verbose_name = "Tithe Record"
        verbose_name_plural = "Tithe Records"
        unique_together = ('user', 'year', 'month')
        ordering = ['-year', '-month']

    def __str__(self):
        return f"Tithe {self.year}/{self.month:02d} — {'paid' if self.is_paid else 'unpaid'}"
