from decimal import Decimal
from datetime import timedelta
from django.core.management.base import BaseCommand
from django.utils import timezone
from marketing.models import (
    MarketingCampaign,
    AdCreative,
    DailyMetric,
    AIActionPlan,
    CreativeIdea,
    CompetitorIntel,
)


class Command(BaseCommand):
    help = 'Seed realistic online marketing data for AI Marketing OS demonstration'

    def handle(self, *args, **options):
        self.stdout.write("Seeding Marketing OS data...")

        # 1. Campaigns
        c1, _ = MarketingCampaign.objects.get_or_create(
            name="เซรั่มลดริ้วรอย Retinol 9Com (TikTok Ads)",
            defaults={
                'platform': 'tiktok',
                'objective': 'conversions',
                'daily_budget': Decimal('2500.00'),
                'target_roas': Decimal('3.50'),
                'product_focus': 'เซรั่ม Retinol Age-Defying 9Com',
                'target_audience': 'ผู้หญิง 25-45 ปี สนใจสกินแคร์ ชะลอวัย ริ้วรอย',
                'status': 'active',
            }
        )

        c2, _ = MarketingCampaign.objects.get_or_create(
            name="กล้องวงจรปิด Wi-Fi ไร้สาย Set 4 ตัว (Meta Ads)",
            defaults={
                'platform': 'meta',
                'objective': 'conversions',
                'daily_budget': Decimal('3000.00'),
                'target_roas': Decimal('4.00'),
                'product_focus': 'ชุดกล้องวงจรปิด 9Com Security Guard',
                'target_audience': 'เจ้าของบ้าน, ผู้ประกอบการร้านค้า, วัย 30-55 ปี',
                'status': 'active',
            }
        )

        c3, _ = MarketingCampaign.objects.get_or_create(
            name="บริการงานซ่อม & อัปเกรดคอมพิวเตอร์ด่วน (Google Search)",
            defaults={
                'platform': 'google',
                'objective': 'leads',
                'daily_budget': Decimal('1200.00'),
                'target_roas': Decimal('3.00'),
                'product_focus': 'บริการซ่อมคอมพิวเตอร์และโน้ตบุ๊ก 9Com Repair',
                'target_audience': 'ผู้ค้นหาคีย์เวิร์ด: ซ่อมคอมด่วน, ร้านซ่อมใกล้ฉัน',
                'status': 'active',
            }
        )

        # 2. Creatives
        cr1, _ = AdCreative.objects.get_or_create(
            campaign=c1,
            name="VDO-01 รีวิวหน้าสดตื่นนอน 7 วัน",
            defaults={
                'format': 'video',
                'hook_text': 'หยุดทาครีมตัวเดิมถ้าตื่นมาแล้วหน้ายังโทรมแบบนี้!',
                'angle': 'ปัญหาหน้าโทรมจากนอนดึก',
                'status': 'winner',
            }
        )

        cr2, _ = AdCreative.objects.get_or_create(
            campaign=c1,
            name="VDO-02 เทียบครีมเคาน์เตอร์แบรนด์",
            defaults={
                'format': 'video',
                'hook_text': 'จ่ายหลักพันทำไม ถ้าส่วนผสมเดียวกันเป๊ะราคาแค่ 490?',
                'angle': 'เทียบความคุ้มค่ากับแบรนด์แพง',
                'status': 'testing',
            }
        )

        cr3, _ = AdCreative.objects.get_or_create(
            campaign=c1,
            name="VDO-03 สัมภาษณ์เภสัชกรผิวหนัง",
            defaults={
                'format': 'video',
                'hook_text': 'ทำไมคนอายุเกิน 30 ต้องเริ่มใช้ Retinol ตั้งแต่วันนี้',
                'angle': 'ความเชี่ยวชาญทางการแพทย์',
                'status': 'fatigued',
            }
        )

        cr4, _ = AdCreative.objects.get_or_create(
            campaign=c2,
            name="VDO-CCTV-01 โจรปีนบ้านจับภาพได้ชัด",
            defaults={
                'format': 'video',
                'hook_text': 'ติดกล้องไว้เถอะครับ ก่อนจะเสียดายแบบบ้านหลังนี้!',
                'angle': 'สร้างความตระหนักเรื่องความปลอดภัย',
                'status': 'winner',
            }
        )

        cr5, _ = AdCreative.objects.get_or_create(
            campaign=c2,
            name="IMG-CCTV-02 ภาพโปรโมชั่นแถมเมมโมรี่การ์ด",
            defaults={
                'format': 'image',
                'hook_text': 'โปรด่วน 3 วันสุดท้าย เซตกล้อง 4 ตัว แถมฟรี SD Card 64GB',
                'angle': 'โปรโมชั่นลดแลกแจกแถม',
                'status': 'killed',
            }
        )

        # 3. Daily Metrics (ย้อนหลัง 14 วัน)
        today = timezone.now().date()
        for i in range(14, -1, -1):
            d = today - timedelta(days=i)
            
            # TikTok Metric
            DailyMetric.objects.get_or_create(
                date=d,
                campaign=c1,
                creative=cr1,
                platform='tiktok',
                defaults={
                    'ad_spend': Decimal('2200.00') + Decimal(str(i * 45)),
                    'revenue': Decimal('9800.00') + Decimal(str(i * 180)),
                    'conversions': 18 + (i % 5),
                    'cogs': Decimal('2800.00'),
                    'other_fees': Decimal('650.00'),
                    'clicks': 420 + (i * 12),
                    'impressions': 18500 + (i * 500),
                    'notes': 'TikTok Conversion Ads ตัวทำเงินหลัก',
                }
            )

            # Meta Metric
            DailyMetric.objects.get_or_create(
                date=d,
                campaign=c2,
                creative=cr4,
                platform='meta',
                defaults={
                    'ad_spend': Decimal('2800.00') + Decimal(str(i * 30)),
                    'revenue': Decimal('13500.00') + Decimal(str(i * 220)),
                    'conversions': 12 + (i % 4),
                    'cogs': Decimal('4900.00'),
                    'other_fees': Decimal('900.00'),
                    'clicks': 350 + (i * 10),
                    'impressions': 14200 + (i * 400),
                    'notes': 'Meta Ads กล้องวงจรปิด',
                }
            )

            # Google Metric
            DailyMetric.objects.get_or_create(
                date=d,
                campaign=c3,
                platform='google',
                defaults={
                    'ad_spend': Decimal('1100.00'),
                    'revenue': Decimal('3900.00') + Decimal(str(i * 60)),
                    'conversions': 5 + (i % 3),
                    'cogs': Decimal('850.00'),
                    'other_fees': Decimal('200.00'),
                    'clicks': 110,
                    'impressions': 2800,
                    'notes': 'Google Search งานซ่อม',
                }
            )

        # 4. Initial AI Action Plan
        if not AIActionPlan.objects.exists():
            AIActionPlan.objects.create(
                date=today,
                title=f"AI Daily Action Plan — {today.strftime('%d/%m/%Y')}",
                status_level='healthy',
                executive_summary=(
                    "ภาพรวมผลประกอบการวันนี้แข็งแกร่งมาก! ยอดขายรวมทำได้ตามเป้าหมาย โดยมี ROAS เฉลี่ยสูงถึง 4.52x "
                    "แคมเปญ TikTok เซรั่ม Retinol และ Meta กล้องวงจรปิดยังคงเป็น Winner สร้างกำไรสุทธิหลักอย่างสม่ำเสมอ "
                    "อย่างไรก็ตาม ชิ้นงาน VDO-03 สัมภาษณ์เภสัชกร เริ่มมีอัตราความถี่สูงขึ้นและ CTR ตกลง ควรเตรียมผลัดเปลี่ยน Creative ชุดใหม่"
                ),
                total_spend=Decimal('6100.00'),
                total_revenue=Decimal('27200.00'),
                overall_roas=Decimal('4.46'),
                net_profit=Decimal('10900.00'),
                scale_recommendations=[
                    {
                        "name": "เซรั่ม Retinol (VDO-01 หน้าสด 7 วัน)",
                        "action": "สเกลงบประมาณเพิ่ม 20% (จาก 2,200 เป็น 2,640 บาท)",
                        "reason": "ROAS แตะ 4.8x อย่างต่อเนื่อง และ Margin เกิน 45%"
                    },
                    {
                        "name": "ชุดกล้องวงจรปิด (VDO-CCTV-01)",
                        "action": "ขยายกลุ่มเป้าหมายไปยังจังหวัดหัวเมืองหลักภาคอีสาน",
                        "reason": "Conversion Rate เสถียร CPA เพียง 233 บาทต่อเซต"
                    }
                ],
                kill_recommendations=[
                    {
                        "name": "IMG-CCTV-02 ภาพโปรโมชั่นแถมเมมโมรี่การ์ด",
                        "action": "กดปิดแอดทันที (Kill)",
                        "reason": "ROAS ต่ำกว่า 1.4x ค่าคลิกแพงขึ้น 3 เท่าตัวเมื่อเทียบกับวิดีโอ"
                    }
                ],
                creative_fatigue_alerts=[
                    {
                        "name": "VDO-03 สัมภาษณ์เภสัชกร",
                        "advice": "ความถี่ขึ้นเป็น 3.1 ครั้งต่อคนแล้ว CTR ลดลง 40% แนะนำให้อัดคลิป Hook สไตล์ใหม่มาเสริม"
                    }
                ],
                action_items=[
                    {"id": 1, "task": "ปรับเพิ่มงบประมาณ 20% บนแคมเปญ TikTok VDO-01 ก่อนเวลา 11:30 น.", "priority": "high", "completed": False, "impact": "ขยายกำไรสุทธิ +15-20%"},
                    {"id": 2, "task": "ตรวจสอบว่าแอด IMG-CCTV-02 ถูกปิดเรียบร้อย เพื่อหยุดการเสียค่าแอดเปล่า", "priority": "high", "completed": False, "impact": "ประหยัดงบรั่วไหล 500 บ./วัน"},
                    {"id": 3, "task": "สั่งทีมตัดต่อเตรียม 3 Hooks ใหม่ตามไอเดียใน Creative Lab", "priority": "medium", "completed": False, "impact": "แก้ปัญหาแอดล้าในอีก 7 วันข้างหน้า"},
                    {"id": 4, "task": "เปิดโปรโมชั่น Bundle แพ็กคู่สำหรับกล้องวงจรปิด รับมือคู่แข่งเจ้า A", "priority": "medium", "completed": False, "impact": "เพิ่ม Average Order Value"},
                ],
                ai_model_name='Google Gemini 2.5 Flash',
            )

        # 5. Creative Ideas
        if not CreativeIdea.objects.exists():
            CreativeIdea.objects.create(
                product_name="เซรั่ม Retinol 9Com",
                target_persona="วัยทำงาน 30+ นอนดึก ผิวหน้ามีริ้วรอย",
                angle_theme="ปัญหาหน้าโทรมจากการนอนดึก",
                format="tiktok_reels",
                hook_options=[
                    "หยุดทาครีมตัวเดิมถ้าตื่นมาแล้วหน้ายังโทรมแบบนี้!",
                    "ใครที่นอนดึกตื่นเช้าแล้วหน้าแห้งเป็นขุย ฟังคลิปนี้ด่วน",
                    "3 ความลับของเซรั่ม Retinol ที่เคาน์เตอร์แบรนด์ไม่อยากให้คุณรู้",
                    "เทียบหน้า 7 วันก่อนใช้กับหลังใช้ ชัดเจนขนาดนี้!",
                    "ถ้าไม่อยากโดนทักว่าอายุเกินจริง ลองใช้วิธีนี้ก่อนนอน",
                ],
                script_outline=(
                    "[0-3s Hook]: หยุดทาครีมตัวเดิมถ้าตื่นมาแล้วหน้ายังโทรมแบบนี้!\n"
                    "[3-15s Problem]: เคยมั้ย? ทาครีมกระปุกละหลายพัน แต่ตื่นเช้ามาหน้ายังหมอง รูขุมขนกว้าง ริ้วรอยยังชัด\n"
                    "[15-30s Solution]: นั่นเพราะผิวขาด Retinol บริสุทธิ์! เซรั่มตัวนี้คิดค้นมาเพื่อคนนอนดึกโดยเฉพาะ ซึมไว ไม่เหนอะหนะ\n"
                    "[30-45s Proof]: ทดสอบกับผู้ใช้จริงกว่า 500 คน ผิวกระชับขึ้น รูขุมขนดูเล็กลงใน 7 คืนแรก\n"
                    "[45-60s CTA]: พิเศษสำหรับคนดูคลิปนี้ ซื้อ 1 ขวด แถมฟรีมาร์กหน้าทองคำ กดสั่งที่ตะกร้าซ้ายล่างได้เลยครับ!"
                ),
                caption_copy=(
                    "🔥 ส่องเคล็ดลับกู้หน้าโทรมใน 7 วันสำหรับคนนอนดึก!\n\n"
                    "ตื่นมาหน้าเด้งฉ่ำ ไม่ต้องพึ่งฟิลเตอร์ ด้วยเซรั่ม Retinol 9Com\n"
                    "✅ ลดเลือนริ้วรอย\n"
                    "✅ รูขุมขนกระชับ\n"
                    "✅ อ่อนโยน ผิวแพ้ง่ายใช้ได้\n\n"
                    "👇 จิ้มตะกร้าหรือพิมพ์ 'สนใจ' เพื่อรับส่วนลดพิเศษ 40% วันนี้!\n"
                    "#Retinol #สกินแคร์กู้หน้าโทรม #ของดีบอกต่อ #9Com"
                )
            )

        # 6. Competitor Intel
        if not CompetitorIntel.objects.exists():
            CompetitorIntel.objects.create(
                brand_name="แบรนด์ความงามคู่แข่ง X",
                platform="Facebook & TikTok Ads",
                pricing_promotion="1 แถม 1 ราคา 390 บาท ส่งฟรีปลายทาง",
                hook_observed="ใช้ Micro-Influencer จำนวนมากรีวิวคลิปแกะกล่องและทาโชว์หน้ากล้อง เคลมว่าสิวหายใน 3 วัน",
                ai_counter_strategy=(
                    "1. ชูจุดเด่นด้านความปลอดภัยและผลวิจัย: เนื่องจากคู่แข่งเคลมสั้นเกินจริง (3 วัน) เราควรวางโพสต์แบบให้ความรู้ทางการแพทย์ เพื่อสร้างความน่าเชื่อถือที่ยาวนานกว่า\n"
                    "2. แก้เกมด้านราคา: อย่าลงไปสู้สงครามตัดราคา 1 แถม 1 แต่ให้ทำชุดของแถมพรีเมียม (เช่น เครื่องนวดหน้ากัวซา) เพื่อเพิ่มมูลค่า perceived value\n"
                    "3. ยิง Retargeting: ดึงลูกค้าที่เคยซื้อของคู่แข่งแล้วเกิดอาการระคายเคือง มาใช้สูตรอ่อนโยนของเรา"
                )
            )

        self.stdout.write(self.style.SUCCESS("Successfully seeded Marketing OS demo data!"))
