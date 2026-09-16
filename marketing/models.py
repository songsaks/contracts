# ====== marketing/models.py ======
# กำหนดโครงสร้างฐานข้อมูลสำหรับระบบ AI Marketing & Growth OS
# รองรับการติดตามแคมเปญ, ครีเอทีฟ, ตัวเลขสถิติรายวัน (ROAS), แผนปฏิบัติการ AI, และการส่องคู่แข่ง

from decimal import Decimal
from django.db import models
from django.utils import timezone


# ====== 1. Marketing Campaign (แคมเปญโฆษณา) ======
class MarketingCampaign(models.Model):
    PLATFORM_CHOICES = (
        ('meta', 'Meta (Facebook / Instagram)'),
        ('tiktok', 'TikTok Ads'),
        ('google', 'Google Ads / YouTube'),
        ('line', 'LINE Ads'),
        ('shopee', 'Shopee Ads'),
        ('lazada', 'Lazada Ads'),
        ('other', 'ช่องทางอื่น ๆ'),
    )

    OBJECTIVE_CHOICES = (
        ('conversions', 'ยอดขาย / ปิดการขาย (Conversions)'),
        ('messages', 'ทักแชท / ข้อความ (Messages)'),
        ('leads', 'กรอกฟอร์ม / ผู้สนใจ (Leads)'),
        ('traffic', 'เข้าชมเว็บไซต์ (Traffic)'),
        ('brand', 'การรับรู้แบรนด์ (Brand Awareness)'),
    )

    STATUS_CHOICES = (
        ('active', 'กำลังเปิดใช้งาน (Active)'),
        ('paused', 'หยุดชั่วคราว (Paused)'),
        ('ended', 'สิ้นสุดแล้ว (Ended)'),
    )

    name = models.CharField(max_length=200, verbose_name="ชื่อแคมเปญ")
    platform = models.CharField(max_length=20, choices=PLATFORM_CHOICES, default='meta', verbose_name="แพลตฟอร์ม")
    objective = models.CharField(max_length=30, choices=OBJECTIVE_CHOICES, default='conversions', verbose_name="วัตถุประสงค์")
    status = models.CharField(max_length=20, choices=STATUS_CHOICES, default='active', verbose_name="สถานะ")
    
    daily_budget = models.DecimalField(max_digits=12, decimal_places=2, default=Decimal('0.00'), verbose_name="งบประมาณรายวัน (บาท)")
    target_roas = models.DecimalField(max_digits=5, decimal_places=2, default=Decimal('3.00'), verbose_name="เป้าหมาย ROAS (เท่า)")
    
    target_audience = models.TextField(blank=True, verbose_name="กลุ่มเป้าหมาย (Audience)")
    product_focus = models.CharField(max_length=200, blank=True, verbose_name="สินค้าหลักในแคมเปญ")
    notes = models.TextField(blank=True, verbose_name="บันทึกเพิ่มเติม")

    created_at = models.DateTimeField(auto_now_add=True, verbose_name="วันที่สร้าง")
    updated_at = models.DateTimeField(auto_now=True, verbose_name="อัปเดตล่าสุด")

    class Meta:
        ordering = ['-updated_at']
        verbose_name = "แคมเปญโฆษณา"
        verbose_name_plural = "แคมเปญโฆษณา"

    def __str__(self):
        return f"[{self.get_platform_display()}] {self.name}"

    def get_platform_badge(self):
        badges = {
            'meta': 'bg-blue-500/10 text-blue-500 border-blue-500/20',
            'tiktok': 'bg-pink-500/10 text-pink-500 border-pink-500/20',
            'google': 'bg-emerald-500/10 text-emerald-500 border-emerald-500/20',
            'line': 'bg-green-500/10 text-green-500 border-green-500/20',
            'shopee': 'bg-orange-500/10 text-orange-500 border-orange-500/20',
            'lazada': 'bg-indigo-500/10 text-indigo-500 border-indigo-500/20',
        }
        return badges.get(self.platform, 'bg-slate-500/10 text-slate-500 border-slate-500/20')


# ====== 2. Ad Creative (ชิ้นงานโฆษณา/คลิป/รูปภาพ) ======
class AdCreative(models.Model):
    FORMAT_CHOICES = (
        ('video', 'วิดีโอสั้น / Reels / TikTok (Video)'),
        ('image', 'รูปภาพเดี่ยว (Single Image)'),
        ('carousel', 'ภาพชุด / แคตตาล็อก (Carousel)'),
        ('story', 'สตอรี่แนวตั้ง (Story)'),
    )

    STATUS_CHOICES = (
        ('winner', '🚀 ตัวทำเงิน (Winner - Scale Up)'),
        ('testing', '⚡ กำลังทดสอบ (Testing)'),
        ('fatigued', '⚠️ แอดเริ่มล้า (Fatigued - Need Refresh)'),
        ('killed', '🛑 ปิดใช้งาน (Killed - Underperformed)'),
    )

    campaign = models.ForeignKey(MarketingCampaign, on_delete=models.CASCADE, related_name='creatives', verbose_name="แคมเปญ")
    name = models.CharField(max_length=200, verbose_name="ชื่อชิ้นงานโฆษณา (Ad Name)")
    format = models.CharField(max_length=20, choices=FORMAT_CHOICES, default='video', verbose_name="รูปแบบชิ้นงาน")
    
    hook_text = models.TextField(blank=True, verbose_name="Hook 3 วินาทีแรก / พาดหัว", help_text="ประโยคเปิดคลิปหรือคำพาดหัวบนรูปภาพ")
    angle = models.CharField(max_length=150, blank=True, verbose_name="มุมการขาย (Angle)", help_text="เช่น ปัญหาผิว, เทียบกับคู่แข่ง, โปรโมชั่น")
    
    status = models.CharField(max_length=20, choices=STATUS_CHOICES, default='testing', verbose_name="สถานะประสิทธิภาพ")
    media_url = models.CharField(max_length=500, blank=True, verbose_name="ลิงก์ไฟล์ชิ้นงาน / รหัส Ads")
    notes = models.TextField(blank=True, verbose_name="บันทึกข้อสังเกต")

    created_at = models.DateTimeField(auto_now_add=True, verbose_name="วันที่เพิ่ม")

    class Meta:
        ordering = ['status', '-created_at']
        verbose_name = "ชิ้นงานโฆษณา (Creative)"
        verbose_name_plural = "ชิ้นงานโฆษณา (Creatives)"

    def __str__(self):
        return f"{self.name} ({self.get_status_display()})"

    def get_status_badge(self):
        badges = {
            'winner': 'bg-emerald-500/15 text-emerald-600 dark:text-emerald-400 border-emerald-500/30',
            'testing': 'bg-amber-500/15 text-amber-600 dark:text-amber-400 border-amber-500/30',
            'fatigued': 'bg-purple-500/15 text-purple-600 dark:text-purple-400 border-purple-500/30',
            'killed': 'bg-rose-500/15 text-rose-600 dark:text-rose-400 border-rose-500/30',
        }
        return badges.get(self.status, 'bg-slate-500/15 text-slate-600 border-slate-500/30')


# ====== 3. Daily Performance Metric (สถิติการตลาดรายวัน) ======
class DailyMetric(models.Model):
    date = models.DateField(default=timezone.now, verbose_name="วันที่")
    campaign = models.ForeignKey(MarketingCampaign, on_delete=models.SET_NULL, null=True, blank=True, related_name='metrics', verbose_name="แคมเปญ")
    creative = models.ForeignKey(AdCreative, on_delete=models.SET_NULL, null=True, blank=True, related_name='metrics', verbose_name="ชิ้นงานโฆษณา")
    platform = models.CharField(max_length=20, choices=MarketingCampaign.PLATFORM_CHOICES, default='meta', verbose_name="ช่องทาง")

    ad_spend = models.DecimalField(max_digits=12, decimal_places=2, default=Decimal('0.00'), verbose_name="ค่าโฆษณา (บาท)")
    revenue = models.DecimalField(max_digits=12, decimal_places=2, default=Decimal('0.00'), verbose_name="ยอดขายที่ได้รับ (บาท)")
    conversions = models.PositiveIntegerField(default=0, verbose_name="จำนวนคำสั่งซื้อ / ลูกค้า (Orders)")
    
    impressions = models.PositiveIntegerField(default=0, verbose_name="จำนวนการมองเห็น (Impressions)")
    clicks = models.PositiveIntegerField(default=0, verbose_name="จำนวนคลิก (Clicks)")
    
    cogs = models.DecimalField(max_digits=12, decimal_places=2, default=Decimal('0.00'), verbose_name="ต้นทุนสินค้า (COGS)")
    other_fees = models.DecimalField(max_digits=12, decimal_places=2, default=Decimal('0.00'), verbose_name="ค่าส่ง/แพ็ก/ธรรมเนียม")

    notes = models.CharField(max_length=255, blank=True, verbose_name="บันทึกย่อ")
    created_at = models.DateTimeField(auto_now_add=True)

    class Meta:
        ordering = ['-date', '-ad_spend']
        verbose_name = "สถิติผลการตลาดรายวัน"
        verbose_name_plural = "สถิติผลการตลาดรายวัน"

    def __str__(self):
        return f"{self.date} | Spend: ฿{self.ad_spend:,.2f} | Rev: ฿{self.revenue:,.2f} (ROAS: {self.roas:.2f}x)"

    @property
    def roas(self):
        """คำนวณ Return on Ad Spend (ยอดขาย / ค่าแอด)"""
        if self.ad_spend and self.ad_spend > 0:
            return round(self.revenue / self.ad_spend, 2)
        return Decimal('0.00')

    @property
    def cpa(self):
        """คำนวณ Cost Per Acquisition / ต้นทุนต่อ 1 คำสั่งซื้อ"""
        if self.conversions and self.conversions > 0:
            return round(self.ad_spend / Decimal(str(self.conversions)), 2)
        return Decimal('0.00')

    @property
    def net_profit(self):
        """คำนวณกำไรสุทธิ = ยอดขาย - ค่าแอด - ต้นทุนสินค้า - ค่าใช้จ่ายอื่น"""
        return self.revenue - (self.ad_spend + self.cogs + self.other_fees)

    @property
    def profit_margin_pct(self):
        """อัตราส่วนกำไรสุทธิ (%)"""
        if self.revenue and self.revenue > 0:
            return round((self.net_profit / self.revenue) * Decimal('100.0'), 1)
        return Decimal('0.0')

    @property
    def ctr(self):
        """Click Through Rate (%)"""
        if self.impressions and self.impressions > 0:
            return round((Decimal(str(self.clicks)) / Decimal(str(self.impressions))) * Decimal('100.0'), 2)
        return Decimal('0.00')


# ====== 4. AI Action Plan (แผนงานปฏิบัติการวิเคราะห์โดย AI) ======
class AIActionPlan(models.Model):
    STATUS_CHOICES = (
        ('healthy', '🟢 สุขภาพพอร์ตดีเยี่ยม (Scaling Mode)'),
        ('warning', '🟡 ควรปรับปรุงเร่งด่วน (Adjustment Needed)'),
        ('critical', '🔴 ขาดทุน/ต้องหยุดเลือดไหล (Loss Prevention)'),
    )

    date = models.DateField(default=timezone.now, verbose_name="วันที่ประเมิน")
    title = models.CharField(max_length=200, default="AI Daily Action Plan", verbose_name="หัวข้อแผนงาน")
    status_level = models.CharField(max_length=20, choices=STATUS_CHOICES, default='healthy', verbose_name="ระดับสุขภาพแคมเปญ")
    
    executive_summary = models.TextField(verbose_name="บทสรุปสำหรับผู้บริหาร (Executive Summary)")
    
    total_spend = models.DecimalField(max_digits=12, decimal_places=2, default=Decimal('0.00'), verbose_name="ค่าแอดรวม")
    total_revenue = models.DecimalField(max_digits=12, decimal_places=2, default=Decimal('0.00'), verbose_name="ยอดขายรวม")
    overall_roas = models.DecimalField(max_digits=6, decimal_places=2, default=Decimal('0.00'), verbose_name="ROAS เฉลี่ย")
    net_profit = models.DecimalField(max_digits=12, decimal_places=2, default=Decimal('0.00'), verbose_name="กำไรสุทธิรวม")

    # เก็บผลลัพธ์การวินิจฉัยแบบ JSON
    scale_recommendations = models.JSONField(default=list, blank=True, verbose_name="แอดที่ควรสเกลเพิ่มงบ (Scale List)")
    kill_recommendations = models.JSONField(default=list, blank=True, verbose_name="แอดที่ควรปิดทันที (Kill List)")
    creative_fatigue_alerts = models.JSONField(default=list, blank=True, verbose_name="แอดที่เริ่มล้า (Fatigue Alerts)")
    
    # รายการงาน Checklist ให้ทำวันนี้
    # รูปแบบ: [{"id": 1, "task": "...", "priority": "high|medium|low", "completed": False, "impact": "..."}]
    action_items = models.JSONField(default=list, blank=True, verbose_name="Checklist งานที่ต้องทำวันนี้")
    
    ai_model_name = models.CharField(max_length=100, default="Google Gemini 2.5/3.0", verbose_name="โมเดลที่ใช้")
    raw_ai_response = models.TextField(blank=True, verbose_name="ข้อความดิบจาก AI")
    created_at = models.DateTimeField(auto_now_add=True, verbose_name="เวลาที่สร้าง")

    class Meta:
        ordering = ['-date', '-created_at']
        verbose_name = "แผนปฏิบัติการ AI (Action Plan)"
        verbose_name_plural = "แผนปฏิบัติการ AI (Action Plans)"

    def __str__(self):
        return f"Action Plan {self.date} - ROAS: {self.overall_roas}x"


# ====== 5. Creative & Script Lab (คลังไอเดียและสคริปต์โฆษณาที่ AI คิดให้) ======
class CreativeIdea(models.Model):
    FORMAT_CHOICES = (
        ('tiktok_reels', 'TikTok / Instagram Reels (9:16 แนวตั้ง)'),
        ('fb_video', 'Facebook Video Post (1:1 หรือ 4:5)'),
        ('carousel', 'Carousel Post สไลด์ภาพ'),
        ('direct_response', 'Direct-Response Long Copy (โพสต์ปิดการขาย)'),
    )

    product_name = models.CharField(max_length=200, verbose_name="สินค้า / บริการ")
    target_persona = models.CharField(max_length=200, verbose_name="กลุ่มลูกค้าเป้าหมาย")
    angle_theme = models.CharField(max_length=200, verbose_name="ธีม / มุมขายหลัก")
    
    hook_options = models.JSONField(default=list, blank=True, verbose_name="ตัวเลือก Hook 3 วินาทีแรก (5 แบบ)")
    script_outline = models.TextField(blank=True, verbose_name="โครงเรื่องสคริปต์วิดีโอ (Hook -> Pain -> Solution -> CTA)")
    caption_copy = models.TextField(blank=True, verbose_name="ข้อความแคปชั่นพร้อมโพสต์")
    
    format = models.CharField(max_length=30, choices=FORMAT_CHOICES, default='tiktok_reels', verbose_name="รูปแบบ")
    is_favorite = models.BooleanField(default=False, verbose_name="ชิ้นงานโปรด")
    
    created_at = models.DateTimeField(auto_now_add=True, verbose_name="วันที่คิดค้น")

    class Meta:
        ordering = ['-created_at']
        verbose_name = "ไอเดียและสคริปต์โฆษณา AI"
        verbose_name_plural = "ไอเดียและสคริปต์โฆษณา AI"

    def __str__(self):
        return f"{self.product_name} - {self.angle_theme}"


# ====== 6. Competitor Radar (สอดส่องคู่แข่งและการแก้เกม) ======
class CompetitorIntel(models.Model):
    brand_name = models.CharField(max_length=150, verbose_name="ชื่อแบรนด์คู่แข่ง")
    platform = models.CharField(max_length=50, default="Facebook / TikTok", verbose_name="ช่องทางที่พบ")
    ad_or_post_url = models.CharField(max_length=500, blank=True, verbose_name="ลิงก์โพสต์/แอดของคู่แข่ง")
    
    hook_observed = models.TextField(blank=True, verbose_name="Hook หรือจุดขายที่คู่แข่งใช้")
    pricing_promotion = models.CharField(max_length=255, blank=True, verbose_name="ราคา / โปรโมชั่นของเขา")
    
    ai_counter_strategy = models.TextField(blank=True, verbose_name="กลยุทธ์แก้เกมที่ AI แนะนำ")
    observed_date = models.DateField(default=timezone.now, verbose_name="วันที่ตรวจพบ")
    created_at = models.DateTimeField(auto_now_add=True)

    class Meta:
        ordering = ['-observed_date', '-created_at']
        verbose_name = "ข้อมูลคู่แข่ง (Competitor Intel)"
        verbose_name_plural = "ข้อมูลคู่แข่ง (Competitor Intel)"

    def __str__(self):
        return f"{self.brand_name} ({self.observed_date})"
