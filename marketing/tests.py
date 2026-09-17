# ====== marketing/tests.py ======
from decimal import Decimal
from datetime import timedelta
from django.test import TestCase, Client
from django.urls import reverse
from django.contrib.auth.models import User
from django.utils import timezone

from marketing.models import (
    MarketingCampaign,
    AdCreative,
    DailyMetric,
    AIActionPlan,
    CreativeIdea,
    CompetitorIntel,
)
from marketing.services.metrics import get_marketing_summary
from marketing.services.gemini_agent import _generate_fallback_plan


class MarketingModelAndLogicTestCase(TestCase):
    def setUp(self):
        self.user = User.objects.create_user(username='testmarketer', password='password123')
        if hasattr(self.user, 'profile'):
            self.user.profile.access_marketing = True
            self.user.profile.save()

        self.campaign = MarketingCampaign.objects.create(
            name='Test TikTok Campaign',
            platform='tiktok',
            objective='conversions',
            daily_budget=Decimal('1000.00'),
            target_roas=Decimal('3.50'),
        )

        self.creative = AdCreative.objects.create(
            campaign=self.campaign,
            name='Test Video 01',
            format='video',
            hook_text='ทดสอบคำเปิดคลิป 3 วิแรก',
            status='winner',
        )

        self.metric = DailyMetric.objects.create(
            date=timezone.now().date(),
            campaign=self.campaign,
            creative=self.creative,
            platform='tiktok',
            ad_spend=Decimal('1000.00'),
            revenue=Decimal('4500.00'),
            conversions=10,
            cogs=Decimal('1200.00'),
            other_fees=Decimal('300.00'),
            clicks=150,
            impressions=5000,
        )

    def test_daily_metric_calculations(self):
        """ทดสอบสูตรคำนวณ ROAS, CPA, Net Profit และ Margin"""
        # ROAS = 4500 / 1000 = 4.50
        self.assertEqual(self.metric.roas, Decimal('4.50'))

        # CPA = 1000 / 10 = 100.00
        self.assertEqual(self.metric.cpa, Decimal('100.00'))

        # Net Profit = 4500 - (1000 + 1200 + 300) = 2000.00
        self.assertEqual(self.metric.net_profit, Decimal('2000.00'))

        # Profit Margin = (2000 / 4500) * 100 = 44.4%
        self.assertEqual(self.metric.profit_margin_pct, Decimal('44.4'))

        # CTR = (150 / 5000) * 100 = 3.00%
        self.assertEqual(self.metric.ctr, Decimal('3.00'))

    def test_marketing_summary_service(self):
        """ทดสอบการคำนวณและรวมยอดภาพรวม (get_marketing_summary)"""
        summary = get_marketing_summary(days=7)
        self.assertEqual(summary['total_spend'], Decimal('1000.00'))
        self.assertEqual(summary['total_revenue'], Decimal('4500.00'))
        self.assertEqual(summary['overall_roas'], Decimal('4.50'))
        self.assertEqual(summary['net_profit'], Decimal('2000.00'))
        self.assertEqual(summary['total_conversions'], 10)
        self.assertEqual(summary['active_campaigns_count'], 1)

    def test_ai_fallback_plan_generation(self):
        """ทดสอบฟังก์ชัน Heuristic AI Fallback Plan เมื่อออฟไลน์"""
        data = {
            'total_spend': 1000.0,
            'total_revenue': 4500.0,
            'overall_roas': 4.5,
            'net_profit': 2000.0,
            'items': [
                {'campaign': 'Test Camp', 'creative': 'Ad 1', 'spend': 1000, 'revenue': 4500, 'roas': 4.5}
            ]
        }
        plan = _generate_fallback_plan(data)
        self.assertEqual(plan['status_level'], 'healthy')
        self.assertTrue(len(plan['scale_recommendations']) > 0)
        self.assertTrue(len(plan['action_items']) >= 3)

    def test_views_access(self):
        """ทดสอบการเข้าถึงหน้าเว็บต่างๆ ของ marketing app"""
        client = Client()
        client.login(username='testmarketer', password='password123')

        # Dashboard
        response = client.get(reverse('marketing:dashboard'))
        self.assertEqual(response.status_code, 200)

        # Campaigns
        response = client.get(reverse('marketing:campaign_list'))
        self.assertEqual(response.status_code, 200)

        # Daily Metrics
        response = client.get(reverse('marketing:daily_metrics'))
        self.assertEqual(response.status_code, 200)

        # Action Plans
        response = client.get(reverse('marketing:action_plans'))
        self.assertEqual(response.status_code, 200)

        # Creative Lab
        response = client.get(reverse('marketing:creative_lab'))
        self.assertEqual(response.status_code, 200)

        # Competitor Radar
        response = client.get(reverse('marketing:competitor_radar'))
        self.assertEqual(response.status_code, 200)
