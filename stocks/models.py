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
    FUND = 'FUND', 'Mutual Fund (กองทุน)'
    CASH = 'CASH', 'Cash (เงินสด)'

class MarketType(models.TextChoices):
    """ตลาด/ประเภทสินทรัพย์ที่ชัดเจน — ใช้แยก หุ้นไทย / หุ้น US / Crypto"""
    SET = 'SET', 'หุ้นไทย (SET)'
    US = 'US', 'หุ้น US'
    CRYPTO = 'CRYPTO', 'Cryptocurrency'
    FUND = 'FUND', 'กองทุน (Fund)'
    CASH = 'CASH', 'เงินสด (Cash)'
    OTHER = 'OTHER', 'อื่นๆ'
# ====== Telegram Integration ======
class StrategyPattern(models.TextChoices):
    """กลยุทธ์การเทรดที่ใช้เลือกใน Watchlist และ Portfolio"""
    PRECISION = 'PRECISION', 'Precision (Demand Zone)'
    TURTLE_S1 = 'TURTLE_S1', 'Turtle S1 (Breakout 20D / Exit 10D Low)'
    TURTLE_S2 = 'TURTLE_S2', 'Turtle S2 (Breakout 55D / Exit 20D Low)'
    SEPA = 'SEPA', 'SEPA (Minervini)'
    CUP_HANDLE = 'CUP_HANDLE', 'Cup & Handle'
    OTHER = 'OTHER', 'อื่นๆ'

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
    # จำนวนหน่วยที่ถือครอง (รองรับทศนิยม สำหรับ Crypto เช่น 0.0000001 BTC)
    quantity = models.DecimalField(max_digits=15, decimal_places=7, default=0)
    # ราคาทุนเฉลี่ย (Average Cost Basis)
    entry_price = models.DecimalField(max_digits=15, decimal_places=7, default=0)
    # ประเภทสินทรัพย์
    category = models.CharField(max_length=20, choices=AssetCategory.choices, default=AssetCategory.STOCK)
    # กลยุทธ์การเข้าซื้อ
    strategy = models.CharField(max_length=50, blank=True, null=True, help_text="e.g. Turtle S1, SEPA, Cup&Handle")
    # ตลาด: SET=หุ้นไทย, US=หุ้นอเมริกา, CRYPTO=คริปโต, OTHER=อื่นๆ
    market = models.CharField(max_length=10, choices=MarketType.choices, default=MarketType.SET)
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

    # ====== US-specific / extended fields ======
    # ตลาด: 'SET' (ไทย) หรือ 'US' (Nasdaq/S&P500)
    market = models.CharField(max_length=10, default='SET', db_index=True)
    # Relative Strength Rating เทียบ Nasdaq/S&P 500 (0-99)
    rs_rating = models.IntegerField(default=0)
    # Stage 2 Weinstein (Price > SMA150 rising)
    stage2 = models.BooleanField(default=False)
    # MACD Bullish Crossover ใน 3 วันล่าสุด
    macd_crossover = models.BooleanField(default=False)
    # Bollinger Band Squeeze (volatility contraction)
    bb_squeeze = models.BooleanField(default=False)
    # Return เทียบ Benchmark 1 เดือน (vs SPY หรือ SET Index)
    rel_1m = models.FloatField(default=0.0)
    # Return เทียบ Benchmark 3 เดือน
    rel_3m = models.FloatField(default=0.0)
    # RVOL เป็น Bullish direction (แท่งขึ้น + volume สูง)
    rvol_bullish = models.BooleanField(default=False)

    class Meta:
        ordering = ['-technical_score']
        unique_together = ('user', 'symbol', 'market')

    def __str__(self):
        return f"{self.symbol} [{self.market}] - Score: {self.technical_score}"

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
    market = models.CharField(max_length=10, default='SET')  # 'SET' or 'US'

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

    # ====== John Ehlers Indicators (v12) ======
    ehlers_supersmoother = models.FloatField(null=True, blank=True)
    ehlers_laguerre_rsi  = models.FloatField(null=True, blank=True)
    ehlers_fisher        = models.FloatField(null=True, blank=True)
    ehlers_fisher_trigger= models.FloatField(null=True, blank=True)
    ehlers_itl_daily     = models.FloatField(null=True, blank=True)
    ehlers_itl_weekly    = models.FloatField(null=True, blank=True)
    ehlers_itl_bullish   = models.BooleanField(default=False)

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

    # ====== Explosive Launcher (v10) ======
    launcher_score      = models.IntegerField(default=0)          # คะแนนความอั้น (0-100)
    turtle_dist_pct     = models.FloatField(default=99.0)         # % ระยะห่างจากจุดเบรค Turtle (DC20)
    is_explosive        = models.BooleanField(default=False)      # เป็นหุ้นที่พร้อมระเบิดหรือไม่ (score > 70)
    tightness_idx       = models.FloatField(default=99.0)         # ดัชนีความบีบตัวของราคา (ต่ำยิ่งดี)

    class Meta:
        ordering = ['-scan_run', '-technical_score']

    def __str__(self):
        return f"{self.symbol} - Score: {self.technical_score} (run: {self.scan_run})"

    @property
    def ehlers_pattern_data(self):
        from .utils import classify_ehlers_pattern
        return classify_ehlers_pattern(
            self.ehlers_laguerre_rsi,
            self.ehlers_fisher,
            self.ehlers_fisher_trigger,
            self.price,
            self.ehlers_supersmoother
        )

    @property
    def is_short_term(self):
        return (
            self.launcher_score >= 70 or
            self.is_volume_surge or
            self.pocket_pivot or
            self.macd_crossover
        )

    @property
    def is_medium_term(self):
        return (
            self.is_canslim or
            self.vcp_setup or
            self.is_52w_breakout
        )

    @property
    def is_long_term(self):
        return (
            self.stage2 and
            self.ema20_aligned and
            self.ehlers_itl_bullish
        )

    @property
    def is_canslim(self):
        # CAN SLIM Core Criteria:
        # C: Current Earnings (EPS/Rev growth >= 20%)
        # L: Leader (Relative Strength rating >= 80)
        # I: Institutional support (CMF >= 0.1 or Pocket Pivot)
        # M: Market direction (Stage 2 Uptrend)
        return (
            self.stage2 and 
            self.rs_rating >= 80 and 
            (self.eps_growth >= 20.0 or self.rev_growth >= 20.0) and 
            ((self.cmf is not None and self.cmf >= 0.1) or self.pocket_pivot)
        )

    @property
    def canslim_reasons(self):
        reasons = []
        # C - Current Earnings
        if self.eps_growth >= 20.0 or self.rev_growth >= 20.0:
            reasons.append(f"C: ผ่าน (EPS {self.eps_growth:+.1f}%, Rev {self.rev_growth:+.1f}%)")
        else:
            reasons.append(f"C: ไม่ผ่าน (EPS {self.eps_growth:+.1f}%, Rev {self.rev_growth:+.1f}%)")
            
        # N - New price high
        if self.is_52w_breakout:
            reasons.append("N: ผ่าน (เบรคไฮ 52w)")
        elif self.zone_proximity <= 10.0:
            reasons.append(f"N: ผ่าน (ใกล้จุดซื้อ ห่าง {self.zone_proximity:.1f}%)")
        else:
            reasons.append("N: ยังไม่เบรคไฮ")
            
        # S - Supply & Demand (Volume)
        if self.is_volume_surge:
            reasons.append(f"S: ผ่าน (วอลุ่มพุ่ง {self.volume_surge:.1f}x)")
        else:
            reasons.append(f"S: วอลุ่มปกติ ({self.volume_surge:.1f}x)")
            
        # L - Leader
        if self.rs_rating >= 80:
            reasons.append(f"L: ผ่าน (หุ้นผู้นำ RS {self.rs_rating})")
        else:
            reasons.append(f"L: ไม่ผ่าน (หุ้นล้าหลัง RS {self.rs_rating})")
            
        # I - Institutional support
        if self.cmf is not None and self.cmf >= 0.1:
            reasons.append(f"I: ผ่าน (รายใหญ่ช้อน CMF {self.cmf:.2f})")
        elif self.pocket_pivot:
            reasons.append("I: ผ่าน (เกิด Pocket Pivot)")
        else:
            reasons.append("I: ไม่มีสะสมเด่น")
            
        # M - Market Direction
        if self.stage2:
            reasons.append("M: ผ่าน (ขาขึ้น Stage 2)")
        else:
            reasons.append("M: ไม่ผ่าน (ไม่ใช่ Stage 2)")
            
        return " | ".join(reasons)




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
    strategy        = models.CharField(max_length=50, choices=StrategyPattern.choices, default=StrategyPattern.PRECISION)
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
    # มูลค่าบริษัท (Market Cap) สำหรับจัดลำดับความสำคัญ
    market_cap = models.FloatField(default=0.0, help_text="Market capitalization in THB for SET, USD for US")
    # สถานะการใช้งาน (False = ไม่ถูกนำไปสแกน)
    is_active = models.BooleanField(default=True)
    # เวลาที่อัปเดตล่าสุด
    last_updated = models.DateTimeField(auto_now=True)
    last_cap_update = models.DateTimeField(null=True, blank=True)

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
    # ตลาดของหุ้นที่ขาย — ใช้คำนวณ USD→THB ได้ถูกต้องโดยไม่ต้องเดาจาก symbol
    market = models.CharField(max_length=10, choices=MarketType.choices, default=MarketType.SET)
    
    # ====== Localization & Tithe fields (v2) ======
    settlement_rate = models.DecimalField(max_digits=12, decimal_places=4, default=1.0, help_text="อัตราแลกเปลี่ยน ณ ตอนขาย (e.g. USDTHB)")
    profit_loss_thb = models.DecimalField(max_digits=14, decimal_places=2, default=0, help_text="กำไร/ขาดทุนในหน่วยบาท (คำนวณ ณ วันขาย)")
    sell_revenue_thb = models.DecimalField(max_digits=14, decimal_places=2, default=0, help_text="รายได้รวมในหน่วยบาท")

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
    # ── Market ────────────────────────────────────────────────────
    market          = models.CharField(max_length=10, default='SET')  # 'SET' | 'US'
    breakout_vol_ok = models.BooleanField(default=False)  # Volume ≥1.5x avg on breakout bar

    class Meta:
        ordering = ['-scan_run', '-confidence_score']
        indexes  = [models.Index(fields=['user', 'scan_run', 'market'])]
        verbose_name = 'Cup & Handle Candidate'

    def __str__(self):
        return f"{self.symbol} [{self.stage}] score={self.confidence_score}"


# ====== USSepaCandidate — ผลลัพธ์ US SEPA Scanner (แยกต่างหากจาก PrecisionScanCandidate) ======

class USSepaCandidate(models.Model):
    """
    เก็บผลการสแกน US SEPA (Minervini Stage 2 + VCP + RS) สำหรับหุ้น US
    แยกต่างหากจาก PrecisionScanCandidate อย่างสมบูรณ์
    """
    user        = models.ForeignKey(User, on_delete=models.CASCADE, null=True, blank=True)
    scan_run    = models.DateTimeField(db_index=True)
    symbol      = models.CharField(max_length=20)
    name        = models.CharField(max_length=100, blank=True, default='')
    sector      = models.CharField(max_length=100, default='Unknown')
    price       = models.FloatField(default=0.0)

    # ── SEPA Stage 2 ────────────────────────────────────────────
    stage2      = models.BooleanField(default=False)    # price > SMA150 AND SMA150 rising

    # ── Relative Strength ───────────────────────────────────────
    rs_rating   = models.IntegerField(default=0)        # 0-99 percentile vs universe

    # ── VCP (Volatility Contraction Pattern) ────────────────────
    vcp_setup        = models.BooleanField(default=False)
    vcp_contractions = models.IntegerField(default=0)
    vcp_tightness    = models.FloatField(default=0.0)   # depth of last contraction (%)
    vcp_vdu          = models.BooleanField(default=False)

    # ── Institutional Signals ───────────────────────────────────
    pocket_pivot  = models.BooleanField(default=False)
    vdu_near_zone = models.BooleanField(default=False)

    # ── Technicals ──────────────────────────────────────────────
    adx   = models.FloatField(default=0.0)
    rsi   = models.FloatField(default=0.0)
    rvol  = models.FloatField(default=1.0)

    # ── Price levels ────────────────────────────────────────────
    year_high      = models.FloatField(default=0.0)
    upside_to_high = models.FloatField(default=0.0)     # (year_high - price) / price * 100

    # ── Minervini Earnings Criteria (v2) ────────────────────────
    eps_growth     = models.FloatField(default=0.0)    # EPS Quarterly Growth YoY (%)
    rev_growth     = models.FloatField(default=0.0)    # Revenue Growth YoY (%)
    roe            = models.FloatField(default=0.0)    # Return on Equity (%)
    eps_accel      = models.BooleanField(default=False) # EPS Acceleration: Q ล่าสุด > Q ก่อน
    earnings_pass  = models.BooleanField(default=False) # ผ่านเกณฑ์ Minervini Earnings (EPS≥25 OR Rev≥25)

    class Meta:
        ordering = ['-scan_run', '-rs_rating']
        indexes  = [models.Index(fields=['user', 'scan_run'])]
        verbose_name = 'US SEPA Candidate'

    def __str__(self):
        return f"{self.symbol} RS={self.rs_rating} VCP={self.vcp_setup}"


class MorningBriefing(models.Model):
    """
    รายงานสรุปประจำวัน — ภาพรวมเศรษฐกิจ + แผนซื้อ/ขายหุ้น
    สร้างโดย AI จากข้อมูล Portfolio, Momentum, Precision, SEPA, Cup&Handle
    """
    user        = models.ForeignKey(User, on_delete=models.CASCADE)
    created_at  = models.DateTimeField(auto_now_add=True, db_index=True)
    report_md   = models.TextField(help_text='Markdown report from Gemini AI')
    # ข้อมูล snapshot ที่ใช้สร้างรายงาน
    portfolio_count     = models.IntegerField(default=0)
    momentum_set_count  = models.IntegerField(default=0)
    momentum_us_count   = models.IntegerField(default=0)
    precision_count     = models.IntegerField(default=0)
    sepa_count          = models.IntegerField(default=0)
    cup_handle_count    = models.IntegerField(default=0)

    class Meta:
        ordering = ['-created_at']
        verbose_name = 'Morning Briefing'

    def __str__(self):
        return f"Briefing {self.created_at.strftime('%Y-%m-%d %H:%M')} — {self.user.username}"


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

# ====== TurtleScanCandidate — ผลลัพธ์ Turtle Trader Scanner ======

class TurtleScanCandidate(models.Model):
    """
    เก็บผลลัพธ์การสแกนระบบ Turtle Trading
    System 1: Breakout 20-day high (Exit: 10-day low)
    System 2: Breakout 55-day high (Exit: 20-day low)
    """
    user = models.ForeignKey(User, on_delete=models.CASCADE, null=True, blank=True)
    scan_run = models.DateTimeField(db_index=True)
    symbol = models.CharField(max_length=20)
    market = models.CharField(max_length=10, default='SET', db_index=True)
    price = models.FloatField(default=0.0)
    
    # -- 20-day high breakout (System 1) --
    sys1_breakout = models.BooleanField(default=False)
    high_20d = models.FloatField(default=0.0)
    low_10d = models.FloatField(default=0.0) # Exit for System 1
    
    # -- 55-day high breakout (System 2) --
    sys2_breakout = models.BooleanField(default=False)
    high_55d = models.FloatField(default=0.0)
    low_20d = models.FloatField(default=0.0) # Exit for System 2
    
    avg_vol_20d = models.FloatField(default=0.0)
    atr_20d = models.FloatField(default=0.0)

    # -- Quality Metrics (v2 Upgrade) --
    technical_score = models.IntegerField(null=True, blank=True, help_text="คะแนนจาก Precision Scan")
    rs_rating       = models.IntegerField(null=True, blank=True, help_text="Relative Strength Rating")
    stage2          = models.BooleanField(default=False, help_text="True if Price > SMA150 and SMA150 rising")
    adx             = models.FloatField(null=True, blank=True, help_text="Average Directional Index")
    is_elite        = models.BooleanField(default=False, help_text="ผ่านเกณฑ์คุณภาพระดับสูงครบทุกข้อ")

    # Extended: 5-day window + near break
    sys1_days_ago = models.IntegerField(null=True, blank=True)   # 0=today, 1-4=within 5 days
    sys2_days_ago = models.IntegerField(null=True, blank=True)
    sys1_near     = models.BooleanField(default=False)            # within 3% of 20-day high
    sys2_near     = models.BooleanField(default=False)            # within 3% of 55-day high
    pct_to_20d    = models.FloatField(null=True, blank=True)      # % to 20-day high (negative = above)
    pct_to_55d    = models.FloatField(null=True, blank=True)

    class Meta:
        ordering = ['-scan_run', 'symbol']
        verbose_name = 'Turtle Scan Candidate'

    def __str__(self):
        return f"{self.symbol} - S1:{self.sys1_breakout} S2:{self.sys2_breakout} (run: {self.scan_run})"


class MeanReversionCandidate(models.Model):
    """ผลลัพธ์การสแกน Mean Reversion — Oversold/Overbought ใน Range-Bound Market (ADX < 25)"""
    DIRECTION_CHOICES = [('oversold', 'Oversold'), ('overbought', 'Overbought')]

    user       = models.ForeignKey(User, on_delete=models.CASCADE, null=True, blank=True)
    scan_run   = models.DateTimeField(db_index=True)
    symbol     = models.CharField(max_length=20)
    name       = models.CharField(max_length=100, blank=True, default='')
    market     = models.CharField(max_length=10, default='SET', db_index=True)

    price      = models.FloatField(default=0.0)
    direction  = models.CharField(max_length=10, choices=DIRECTION_CHOICES, default='oversold')

    rsi        = models.FloatField(default=50.0)
    adx        = models.FloatField(default=0.0)
    avg_vol_20d = models.FloatField(default=0.0)
    rvol       = models.FloatField(default=1.0)

    pattern    = models.CharField(max_length=30, blank=True, default='')

    support_level      = models.FloatField(null=True, blank=True)
    resistance_level   = models.FloatField(null=True, blank=True)
    mean_target        = models.FloatField(null=True, blank=True)   # SMA20

    dist_to_support_pct    = models.FloatField(default=0.0)
    dist_to_resistance_pct = models.FloatField(default=0.0)
    upside_pct             = models.FloatField(default=0.0)         # % to mean_target

    r_score    = models.IntegerField(default=0)   # Reversion Score 0-100
    rs_rating  = models.IntegerField(default=0)

    class Meta:
        ordering = ['-scan_run', '-r_score']
        verbose_name = 'Mean Reversion Candidate'

    def __str__(self):
        return f"{self.symbol} [{self.direction}] r={self.r_score} (run: {self.scan_run})"


# ====== Automated Trading Infrastructure (v2) ======

class BrokerType(models.TextChoices):
    """ประเภทของ Broker ที่ระบบรองรับสำหรับการเทรดจริง"""
    META_API = 'META_API', 'MetaApi (MT4/MT5 Cloud)'
    OANDA    = 'OANDA', 'OANDA (REST API)'
    IBKR     = 'IBKR', 'Interactive Brokers'
    TOP_TRADER = 'TOP_TRADER', 'Top-Trader (SET)'
    OTHER    = 'OTHER', 'อื่นๆ / Manual'

class TradingAccount(models.Model):
    """
    เก็บข้อมูลบัญชีเทรดจริงของผู้ใช้สำหรับเชื่อมต่อกับ API
    """
    user        = models.ForeignKey(User, on_delete=models.CASCADE, related_name='trading_accounts')
    broker      = models.CharField(max_length=20, choices=BrokerType.choices, default=BrokerType.META_API)
    account_id  = models.CharField(max_length=100, help_text="เลขพอร์ต หรือ Account ID")
    api_key     = models.TextField(blank=True, help_text="API Key / Token")
    api_secret  = models.TextField(blank=True, help_text="API Secret / Password")
    
    # สถานะพอร์ตเบื้องต้น (ดึงจาก API มาพักไว้)
    balance     = models.DecimalField(max_digits=14, decimal_places=2, default=0.0)
    equity      = models.DecimalField(max_digits=14, decimal_places=2, default=0.0)
    currency    = models.CharField(max_length=10, default='USD')
    
    is_active   = models.BooleanField(default=True, help_text="เปิด/ปิด การให้ Robot เข้าถึงพอร์ตนี้")
    created_at  = models.DateTimeField(auto_now_add=True)
    updated_at  = models.DateTimeField(auto_now=True)

    class Meta:
        verbose_name = "Trading Account"
        unique_together = ('user', 'account_id', 'broker')

    def __str__(self):
        return f"{self.broker} - {self.account_id} ({self.user.username})"

class TradeOrder(models.Model):
    """
    บันทึกรายการคำสั่งซื้อขายจริงที่ส่งไปยัง Broker
    ใช้ติดตามสถานะตั้งแต่เริ่มเปิด จนถึงปิดออเดอร์ พร้อมรายละเอียดครบถ้วน
    """
    class OrderStatus(models.TextChoices):
        PENDING   = 'PENDING',   'รอเข้าซื้อ (Pending)'
        OPEN      = 'OPEN',      'เปิดสถานะแล้ว (Live)'
        CLOSED    = 'CLOSED',    'ปิดสถานะแล้ว (Closed)'
        CANCELLED = 'CANCELLED', 'ยกเลิก (Cancelled)'

    user    = models.ForeignKey(User, on_delete=models.CASCADE)
    account = models.ForeignKey(TradingAccount, on_delete=models.CASCADE, related_name='orders')

    symbol   = models.CharField(max_length=20,  help_text="e.g. XAUUSD, GC=F")
    order_id = models.CharField(max_length=100, blank=True, help_text="Ticket ID จาก Broker")

    # ── รายละเอียดการเทรด ──────────────────────────────────────────
    order_type  = models.CharField(max_length=10, choices=[('BUY','Buy'),('SELL','Sell')])
    volume      = models.DecimalField(max_digits=12, decimal_places=4, help_text="Lots")
    entry_price = models.DecimalField(max_digits=12, decimal_places=4, null=True, blank=True)
    stop_loss   = models.DecimalField(max_digits=12, decimal_places=4, null=True, blank=True)
    take_profit = models.DecimalField(max_digits=12, decimal_places=4, null=True, blank=True)

    # ── สถานะและเวลา ───────────────────────────────────────────────
    status    = models.CharField(max_length=20, choices=OrderStatus.choices, default=OrderStatus.PENDING)
    opened_at = models.DateTimeField(null=True, blank=True)
    closed_at = models.DateTimeField(null=True, blank=True)

    # ── ผลลัพธ์ทางการเงิน ──────────────────────────────────────────
    exit_price    = models.DecimalField(max_digits=12, decimal_places=4, null=True, blank=True)
    pips          = models.DecimalField(max_digits=10, decimal_places=2, default=0)
    profit_loss   = models.DecimalField(max_digits=14, decimal_places=2, default=0, help_text="Net P/L หลังหักค่าธรรมเนียม")
    gross_pl      = models.DecimalField(max_digits=14, decimal_places=2, default=0, help_text="Gross P/L ก่อนหักค่าธรรมเนียม")
    commission    = models.DecimalField(max_digits=10, decimal_places=4, default=0, help_text="ค่านายหน้า Broker")
    swap          = models.DecimalField(max_digits=10, decimal_places=4, default=0, help_text="ค่า Swap / ดอกเบี้ยค้างคืน")
    actual_rr     = models.DecimalField(max_digits=8,  decimal_places=3, default=0, help_text="R:R จริงที่ได้รับ")

    # ── สถิติการเทรด ────────────────────────────────────────────────
    risk_usd      = models.DecimalField(max_digits=12, decimal_places=2, default=0, help_text="ความเสี่ยงเป็น USD ($)")
    risk_pct      = models.DecimalField(max_digits=6,  decimal_places=3, default=0, help_text="ความเสี่ยงเป็น % ของบัญชี")
    duration_sec  = models.IntegerField(default=0, help_text="ระยะเวลา Hold (วินาที)")

    # ── กลยุทธ์และบันทึก ────────────────────────────────────────────
    strategy      = models.CharField(max_length=50,  blank=True, help_text="e.g. SNIPER, TURTLE")
    signal_source = models.CharField(max_length=100, blank=True, help_text="สัญญาณที่ trigger: DC10, DC20, DC55, Manual")
    exit_reason   = models.CharField(max_length=100, blank=True, null=True, help_text="TP / SL / Manual / Panic")
    comment       = models.TextField(blank=True, help_text="บันทึกเพิ่มเติมจาก Robot หรือ AI")

    created_at = models.DateTimeField(auto_now_add=True)

    class Meta:
        ordering = ['-opened_at', '-created_at']
        verbose_name = "Trade Order"
        indexes = [
            models.Index(fields=['user', 'symbol', 'status']),
            models.Index(fields=['user', 'opened_at']),
        ]

    @property
    def duration_display(self):
        """แปลง duration_sec เป็นข้อความที่อ่านง่าย"""
        s = int(self.duration_sec or 0)
        if s < 60:    return f"{s}s"
        if s < 3600:  return f"{s//60}m {s%60}s"
        if s < 86400: return f"{s//3600}h {(s%3600)//60}m"
        return f"{s//86400}d {(s%86400)//3600}h"

    def calculate_and_save_pl(self, exit_p, commission=0, swap=0):
        """
        คำนวณ P/L ครบถ้วนและบันทึกลง DB
        XAUUSD: 1 Lot = 100 oz, pip value ≈ $1/pip
        Spot Crypto / Forex: 1 Lot = 1 unit, multiplier = 1
        """
        from decimal import Decimal
        ep = Decimal(str(entry_p := float(self.entry_price or 0)))
        xp = Decimal(str(float(exit_p)))
        vol = Decimal(str(float(self.volume)))

        symbol_upper = str(self.symbol or "").upper()
        is_gold = any(x in symbol_upper for x in ['XAU', 'GC=F', 'GOLD'])
        multiplier = Decimal('100') if is_gold else Decimal('1')

        # Price diff * multiplier * lots
        price_diff = (xp - ep) if self.order_type == 'BUY' else (ep - xp)
        gross = price_diff * vol * multiplier
        net   = gross - Decimal(str(commission)) - Decimal(str(swap))

        self.exit_price   = xp
        self.gross_pl     = round(gross, 2)
        self.commission   = round(Decimal(str(commission)), 4)
        self.swap         = round(Decimal(str(swap)), 4)
        self.profit_loss  = round(net, 2)
        self.pips         = round(price_diff, 2)

        if self.stop_loss and self.entry_price:
            risk_pts = abs(float(self.entry_price) - float(self.stop_loss))
            risk_mult = 100 if is_gold else 1
            self.risk_usd = round(float(risk_pts) * float(self.volume) * risk_mult, 2)

        if self.risk_usd and float(self.risk_usd) != 0:
            self.actual_rr = round(float(self.gross_pl) / float(self.risk_usd), 3)

        if self.opened_at and self.closed_at:
            self.duration_sec = int((self.closed_at - self.opened_at).total_seconds())

        self.status    = TradeOrder.OrderStatus.CLOSED
        self.save()
        return self

class BotActivity(models.Model):
    """
    บันทึกสถานะการทำงาน (Heartbeat) และกิจกรรมของบอทที่รันบน Server
    ช่วยให้หน้าจอ UI แสดงผลได้ว่าบอททำงานอยู่จริงหรือไม่
    """
    bot_name = models.CharField(max_length=100, default="Gold Robot")
    status = models.CharField(max_length=50, default="ACTIVE") # ACTIVE, STOPPED, ERROR
    last_heartbeat = models.DateTimeField(auto_now=True)
    message = models.TextField(blank=True, help_text="บันทึกกิจกรรมล่าสุดของบอท")

    class Meta:
        verbose_name = "Bot Activity"
        verbose_name_plural = "Bot Activities"

    def __str__(self):
        return f"{self.bot_name} - {self.status} ({self.last_heartbeat})"

class InvestmentDashboardInsight(models.Model):
    """
    ข้อมูลสำหรับหน้า Investment Dashboard แยกตามผู้ใช้
    เก็บ Top 5 หุ้นแนะนำ (SET/US) พร้อมบทวิเคราะห์ AI แบบถาวร
    """
    user = models.ForeignKey(User, on_delete=models.CASCADE, related_name='investment_insights')
    created_at = models.DateTimeField(auto_now_add=True, db_index=True)
    
    # ข้อมูลหุ้น Top 5 (เก็บเป็น List of Dicts)
    set_top_stocks = models.JSONField(default=list, help_text="Top 5 SET stocks metadata")
    us_top_stocks = models.JSONField(default=list, help_text="Top 5 US stocks metadata")
    
    # บทวิเคราะห์และกลยุทธ์จาก AI
    ai_strategy = models.TextField(help_text="AI Analysis and Strategy Summary")
    
    # สรุปภาพรวมตลาด (Market Sentiment)
    market_outlook = models.CharField(max_length=100, blank=True, help_text="e.g. Bullish, Sideways, Caution")
    
    is_active = models.BooleanField(default=True)

    class Meta:
        ordering = ['-created_at']
        verbose_name = 'Investment Dashboard Insight'
        verbose_name_plural = 'Investment Dashboard Insights'

    def __str__(self):
        return f"Insight {self.created_at.strftime('%Y-%m-%d')} for {self.user.username}"

class UserTradingConfig(models.Model):
    """
    เก็บการตั้งค่า UI และการเทรดส่วนตัวของผู้ใช้ (Persistent UI State)
    เพื่อให้การตั้งค่าไม่หายไปเมื่อ Refresh หน้าจอ หรือสลับเครื่อง (Sync across devices)
    """
    user = models.OneToOneField(User, on_delete=models.CASCADE, related_name='trading_config')
    
    # --- Smart Alerts Config ---
    alert_enabled = models.BooleanField(default=False)
    alert_high_target = models.FloatField(null=True, blank=True)
    alert_low_target = models.FloatField(null=True, blank=True)
    
    # --- Risk Management Config ---
    default_capital = models.FloatField(default=1000.0)
    default_risk_pct = models.FloatField(default=1.0)
    
    updated_at = models.DateTimeField(auto_now=True)

    def __str__(self):
        return f"Config: {self.user.username}"

# ====== Portfolio Cash — จัดการเงินสดและกระแสเงินเข้า/ออก ======

class PortfolioCash(models.Model):
    """
    เก็บยอดเงินสดคงเหลือแยกตามสกุลเงิน (THB, USD)
    """
    user = models.ForeignKey(User, on_delete=models.CASCADE, related_name='portfolio_cash')
    currency = models.CharField(max_length=10, default='THB', help_text="e.g. THB, USD")
    balance = models.DecimalField(max_digits=16, decimal_places=2, default=0)
    updated_at = models.DateTimeField(auto_now=True)

    class Meta:
        verbose_name = "Portfolio Cash"
        verbose_name_plural = "Portfolio Cash"
        unique_together = ('user', 'currency')

    def __str__(self):
        return f"{self.user.username} - {self.balance} {self.currency}"

class CashTransaction(models.Model):
    """
    บันทึกรายการเงินเข้า/ออก (Deposit, Withdrawal, Dividend, Fee)
    ช่วยให้ผู้ใช้ monitor กระแสเงินสดในพอร์ตได้
    """
    class TransactionType(models.TextChoices):
        DEPOSIT = 'DEPOSIT', 'เงินเข้า (Deposit)'
        WITHDRAWAL = 'WITHDRAWAL', 'เงินออก (Withdrawal)'
        DIVIDEND = 'DIVIDEND', 'ปันผล (Dividend)'
        FEE = 'FEE', 'ค่าธรรมเนียม/อื่นๆ (Fee)'
        BUY = 'BUY', 'ซื้อหุ้น (Buy)'
        SELL = 'SELL', 'ขายหุ้น (Sell)'
        ADJUSTMENT = 'ADJUSTMENT', 'ปรับปรุงยอด (Adjustment)'

    user = models.ForeignKey(User, on_delete=models.CASCADE, related_name='cash_transactions')
    amount = models.DecimalField(max_digits=16, decimal_places=2, help_text="ยอดเงิน (บวก=เข้า, ลบ=ออก)")
    currency = models.CharField(max_length=10, default='THB')
    transaction_type = models.CharField(max_length=20, choices=TransactionType.choices, default=TransactionType.DEPOSIT)
    note = models.CharField(max_length=255, blank=True)
    created_at = models.DateTimeField(auto_now_add=True)

    class Meta:
        verbose_name = "Cash Transaction"
        verbose_name_plural = "Cash Transactions"
        ordering = ['-created_at']

    def __str__(self):
        return f"{self.transaction_type} {self.amount} {self.currency} ({self.user.username})"

class PortfolioFund(models.Model):
    """
    บันทึกเงินลงทุนในกองทุนรวม (Manual Entry)
    """
    user = models.ForeignKey(User, on_delete=models.CASCADE, related_name='portfolio_funds')
    name = models.CharField(max_length=100, verbose_name="ชื่อกองทุน")
    cost = models.DecimalField(max_digits=16, decimal_places=2, default=0, verbose_name="ต้นทุน (Cost)")
    market_value = models.DecimalField(max_digits=16, decimal_places=2, default=0, verbose_name="มูลค่าตลาด (Market Value)")
    currency = models.CharField(max_length=10, default='THB')
    updated_at = models.DateTimeField(auto_now=True)

    class Meta:
        verbose_name = "Portfolio Fund"
        verbose_name_plural = "Portfolio Funds"

    def __str__(self):
        return f"{self.name} ({self.user.username})"

class AIManualScanResult(models.Model):
    """
    เก็บผลลัพธ์การสแกนด้วย AI Manual Scanner
    """
    user = models.ForeignKey(User, on_delete=models.CASCADE)
    market = models.CharField(max_length=10)
    symbol = models.CharField(max_length=20)
    grade = models.CharField(max_length=5)
    reasoning = models.TextField()
    rank = models.IntegerField(default=0)
    created_at = models.DateTimeField(auto_now_add=True)
    scan_run = models.DateTimeField(db_index=True, null=True, blank=True)

    class Meta:
        ordering = ['rank', 'grade', 'symbol']
        verbose_name = "AI Manual Scan Result"
        verbose_name_plural = "AI Manual Scan Results"

    def __str__(self):
        return f"AI Rank {self.rank}: {self.symbol} (Grade {self.grade})"


class DailyAgentReport(models.Model):
    """
    รายงานวิเคราะห์เทคนิคคอลสแกนเนอร์และเปรียบเทียบพอร์ตของบอทรายวัน (รอบเช้า 10:00 / บ่าย 13:00)
    """
    user = models.ForeignKey(User, on_delete=models.CASCADE, related_name='daily_agent_reports')
    created_at = models.DateTimeField(auto_now_add=True, db_index=True)
    report_date = models.DateField(db_index=True)
    time_slot = models.CharField(max_length=10)  # '10:00' หรือ '13:00'
    report_md = models.TextField()
    is_read = models.BooleanField(default=False)

    class Meta:
        ordering = ['-report_date', '-time_slot']
        unique_together = ('user', 'report_date', 'time_slot')
        verbose_name = "Daily Agent Report"
        verbose_name_plural = "Daily Agent Reports"

    def __str__(self):
        return f"Report {self.report_date} {self.time_slot} — {self.user.username}"

