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
        # เรียงตาม technical_score จากมากไปน้อย (หุ้นดีสุดขึ้นก่อน)
        ordering = ['-technical_score']

    def __str__(self):
        return f"{self.symbol} - Score: {self.technical_score}"

# ====== ScannableSymbol — รายชื่อหุ้นที่ระบบสแกนได้ ======

class ScannableSymbol(models.Model):
    """
    รายชื่อหุ้นที่ระบบจะสแกนเมื่อผู้ใช้กดปุ่ม Scan
    ข้อมูลถูก seed ครั้งแรกโดย refresh_set100_symbols()
    และถูกอัปเดตอัตโนมัติเมื่อมีการ login (ผ่าน signals.py)
    """
    # สัญลักษณ์หุ้น (ไม่มี .BK — จะถูกเติมอัตโนมัติตอนสแกน)
    symbol = models.CharField(max_length=20, unique=True)
    # ชื่อดัชนีที่หุ้นนี้อยู่ เช่น "SET100", "SET100+MAI"
    index_name = models.CharField(max_length=50, default="SET100")
    # สถานะการใช้งาน (False = ไม่ถูกนำไปสแกน)
    is_active = models.BooleanField(default=True)
    # เวลาที่อัปเดตล่าสุด
    last_updated = models.DateTimeField(auto_now=True)

    class Meta:
        ordering = ['symbol']

    def __str__(self):
        return f"{self.symbol} ({self.index_name})"
