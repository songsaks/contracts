# ====== marketing/services/gemini_agent.py ======
# บริการ AI Growth Officer & Performance Marketing Agent ขับเคลื่อนด้วย Google Gemini API

import json
import os
import re
from decimal import Decimal
from django.conf import settings
from django.utils import timezone
import google.genai as genai
from google.genai import types

from marketing.models import (
    DailyMetric,
    MarketingCampaign,
    AdCreative,
    AIActionPlan,
    CreativeIdea,
    CompetitorIntel,
)


def get_gemini_client():
    """ดึง Gemini Client จากการตั้งค่า"""
    api_key = getattr(settings, 'GEMINI_API_KEY', os.environ.get('GEMINI_API_KEY'))
    if not api_key:
        return None
    return genai.Client(api_key=api_key)


def generate_daily_action_plan(target_date=None):
    """
    สร้างแผนงานปฏิบัติการประจำวัน (AI Action Plan)
    วิเคราะห์ผลตอบแทน (ROAS), วินิจฉัยจุดรั่วไหล, คัดเลือกแอดที่ควร Scale / Kill
    และสรุปเป็น Action Checklist 3-5 ข้อ
    """
    if not target_date:
        target_date = timezone.now().date()

    # ดึงสถิติของวันนั้น หรือสถิติล่าสุด
    metrics = DailyMetric.objects.filter(date=target_date)
    if not metrics.exists():
        # ถ้าวันนี้ยังไม่มีข้อมูล ให้ดึงข้อมูลล่าสุด 7 วันมาวิเคราะห์
        metrics = DailyMetric.objects.all().order_by('-date')[:20]

    total_spend = sum([m.ad_spend for m in metrics])
    total_revenue = sum([m.revenue for m in metrics])
    total_orders = sum([m.conversions for m in metrics])
    total_cogs = sum([m.cogs for m in metrics])
    total_fees = sum([m.other_fees for m in metrics])
    overall_roas = (total_revenue / total_spend) if total_spend > 0 else Decimal('0.00')
    net_profit = total_revenue - (total_spend + total_cogs + total_fees)

    # รวบรวมข้อมูลรายแคมเปญ/แอดเพื่อส่งให้ AI
    campaign_breakdown = []
    for m in metrics:
        c_name = m.campaign.name if m.campaign else "ไม่ระบุแคมเปญ"
        ad_name = m.creative.name if m.creative else "-"
        ad_status = m.creative.status if m.creative else "-"
        campaign_breakdown.append({
            "campaign": c_name,
            "creative": ad_name,
            "status": ad_status,
            "platform": m.get_platform_display(),
            "spend": float(m.ad_spend),
            "revenue": float(m.revenue),
            "roas": float(m.roas),
            "orders": m.conversions,
            "profit": float(m.net_profit),
        })

    client = get_gemini_client()

    prompt_data = {
        "date": str(target_date),
        "total_spend": float(total_spend),
        "total_revenue": float(total_revenue),
        "overall_roas": float(round(overall_roas, 2)),
        "net_profit": float(round(net_profit, 2)),
        "total_orders": total_orders,
        "items": campaign_breakdown,
    }

    system_instruction = (
        "คุณคือ 'Chief Growth Officer & Senior Performance Marketing AI' มืออาชีพ "
        "หน้าที่ของคุณคือวิเคราะห์ตัวเลขทางการตลาด (ค่าแอด, ยอดขาย, ROAS, กำไรสุทธิ) "
        "เพื่อออกคำสั่งและแผนปฏิบัติการประจำวัน (Daily Action Plan) ให้เจ้าของธุรกิจและทีมงานทำตามทันที "
        "เน้นการทำกำไรสูงสุด (Maximize Net Profit) และหยุดแอดที่ผลาญเงินโดยไม่ทำยอดขาย "
        "คุณต้องตอบกลับเป็นโครงสร้าง JSON ภาษาไทยเท่านั้น โดยมี Key ดังนี้:\n"
        "1. executive_summary: สรุปภาพรวมสั้นๆ 2-3 ประโยค ว่าสถานการณ์วันนี้เป็นอย่างไร\n"
        "2. status_level: 'healthy' (ถ้า ROAS >= 3.0 และกำไรดี), 'warning' (ถ้า ROAS 2.0-2.9), 'critical' (ถ้า ROAS < 2.0 หรือขาดทุน)\n"
        "3. scale_recommendations: รายการแอดหรือแคมเปญที่ควรเพิ่มงบ [{\"name\": \"...\", \"action\": \"เพิ่มงบ 15%\", \"reason\": \"...\"}]\n"
        "4. kill_recommendations: รายการแอดหรือแคมเปญที่ควรปิด [{\"name\": \"...\", \"action\": \"ปิดแอดทันที\", \"reason\": \"...\"}]\n"
        "5. creative_fatigue_alerts: แอดที่ผลเริ่มตก [{\"name\": \"...\", \"advice\": \"...\"}]\n"
        "6. action_items: Checklist งาน 3-5 ข้อเรียงตามลำดับความสำคัญ [{\"id\": 1, \"task\": \"...\", \"priority\": \"high|medium|low\", \"impact\": \"...\"}]"
    )

    result_json = None
    raw_response_text = ""

    if client:
        try:
            # ใช้โมเดล gemini-2.5-flash หรือ gemini-3-flash-preview
            response = client.models.generate_content(
                model='gemini-2.5-flash',
                contents=f"นี่คือข้อมูลการตลาดยอดขายของวันนี้:\n{json.dumps(prompt_data, ensure_ascii=False)}",
                config=types.GenerateContentConfig(
                    system_instruction=system_instruction,
                    response_mime_type="application/json",
                    temperature=0.3,
                )
            )
            raw_response_text = response.text
            result_json = json.loads(raw_response_text)
        except Exception as e:
            # Fallback หากเกิดปัญหากับเครือข่ายหรือโควตา
            raw_response_text = f"Gemini Error: {str(e)}"

    # หากไม่มี client หรือ parse ไม่ได้ ให้ใช้ Fallback Rule-Based Agent
    if not result_json:
        result_json = _generate_fallback_plan(prompt_data)

    # บันทึกลงตาราง AIActionPlan
    action_items_list = result_json.get('action_items', [])
    for idx, item in enumerate(action_items_list):
        if 'completed' not in item:
            item['completed'] = False
        if 'id' not in item:
            item['id'] = idx + 1

    action_plan = AIActionPlan.objects.create(
        date=target_date,
        title=f"AI Daily Action Plan — {target_date.strftime('%d/%m/%Y')}",
        status_level=result_json.get('status_level', 'healthy'),
        executive_summary=result_json.get('executive_summary', 'ภาพรวมผลประกอบการอยู่ในเกณฑ์ปกติ'),
        total_spend=total_spend,
        total_revenue=total_revenue,
        overall_roas=overall_roas,
        net_profit=net_profit,
        scale_recommendations=result_json.get('scale_recommendations', []),
        kill_recommendations=result_json.get('kill_recommendations', []),
        creative_fatigue_alerts=result_json.get('creative_fatigue_alerts', []),
        action_items=action_items_list,
        ai_model_name='Google Gemini 2.5 Flash' if client else 'Heuristic Fallback Engine',
        raw_ai_response=raw_response_text,
    )

    return action_plan


def _generate_fallback_plan(data):
    """ฟังก์ชันสำรองแบบ Rule-Based เผื่อกรณีออฟไลน์"""
    roas = data.get('overall_roas', 0)
    profit = data.get('net_profit', 0)
    
    status = 'healthy' if roas >= 3.0 else ('warning' if roas >= 2.0 else 'critical')
    summary = f"ยอดขายรวม ฿{data.get('total_revenue', 0):,.2f} จากค่าแอด ฿{data.get('total_spend', 0):,.2f} ทำ ROAS รวมได้ {roas:.2f}x กำไรสุทธิ ฿{profit:,.2f}"

    scale_list = []
    kill_list = []
    for item in data.get('items', []):
        if item.get('roas', 0) >= 3.5:
            scale_list.append({
                'name': f"{item.get('campaign')} ({item.get('creative')})",
                'action': 'สเกลเพิ่มงบประมาณ 20%',
                'reason': f"ROAS สูงถึง {item.get('roas'):.2f}x และกำไรสุทธิเป็นบวกต่อเนื่อง"
            })
        elif item.get('roas', 0) < 1.5 and item.get('spend', 0) > 300:
            kill_list.append({
                'name': f"{item.get('campaign')} ({item.get('creative')})",
                'action': 'ปิดแอดทันที (Kill)',
                'reason': f"ROAS ต่ำเพียง {item.get('roas'):.2f}x ใช้เงินไปแล้วแต่ยอดขายไม่เข้าเกณฑ์"
            })

    return {
        'executive_summary': summary,
        'status_level': status,
        'scale_recommendations': scale_list,
        'kill_recommendations': kill_list,
        'creative_fatigue_alerts': [{'name': 'แคมเปญทั่วไป', 'advice': 'ตรวจสอบความถี่ (Frequency) อย่าให้เกิน 2.5 ครั้งต่อคน'}],
        'action_items': [
            {'id': 1, 'task': 'เพิ่มงบประมาณแคมเปญตัวทำเงิน 20% ในช่วงเวลา 11:00 น.', 'priority': 'high', 'impact': 'ขยายยอดขายเพิ่ม 15-25%'},
            {'id': 2, 'task': 'กดปิดชิ้นงานที่ ROAS ต่ำกว่า 1.5x ทันทีเพื่อรักษา Margin', 'priority': 'high', 'impact': 'ประหยัดค่าแอดที่ไม่ก่อให้เกิดผลลัพธ์'},
            {'id': 3, 'task': 'เตรียมอัดคลิปวิดีโอ 3 Hooks ใหม่สำหรับทดสอบสัปดาห์หน้า', 'priority': 'medium', 'impact': 'ป้องกันปัญหาแอดล้า (Creative Fatigue)'},
        ]
    }


def generate_creative_content(product_name, target_persona, angle_theme, format_type='tiktok_reels'):
    """
    สร้างไอเดียโฆษณา, Hook 3 วินาทีแรก, โครงสร้างสคริปต์วิดีโอ และแคปชั่นปิดการขาย
    """
    client = get_gemini_client()

    prompt = f"""
    สินค้า: {product_name}
    กลุ่มลูกค้าเป้าหมาย: {target_persona}
    มุมการขายหลัก (Angle): {angle_theme}
    รูปแบบ: {format_type}

    โปรดสร้างผลงานโฆษณาภาษาไทยที่ดึงดูดใจ และมีพลังในการปิดการขายสูง ตอบกลับเป็น JSON มีโครงสร้างดังนี้:
    {{
        "hook_options": [
            "Hook 1 (แนวสร้างความสงสัย/หยุดนิ้วโป้ง)",
            "Hook 2 (แนวแทงใจดำ/ปัญหาที่เจอ)",
            "Hook 3 (แนวความลับ/ข้อห้าม)",
            "Hook 4 (แนวผลลัพธ์ก่อน-หลัง)",
            "Hook 5 (แนวเปรียบเทียบกับทางเลือกเดิม)"
        ],
        "script_outline": "สคริปต์แบ่งฉากชัดเจน:\n[0-3s Hook] ...\n[3-15s Problem & Agitation] ...\n[15-30s Solution & Hero Product] ...\n[30-45s Social Proof/Review] ...\n[45-60s Offer & Call to Action] ...",
        "caption_copy": "ข้อความแคปชั่นโพสต์ มีพาดหัว บอดี้กระตุ้นการตัดสินใจ โปรโมชั่น และแฮชแท็กพร้อมอีโมจิสวยงาม"
    }}
    """

    hooks = [
        f"ใครที่มีปัญหา {angle_theme} ฟังคลิปนี้ด่วน ก่อนที่จะสายเกินไป!",
        f"หยุดทำแบบนี้ถ้าไม่อยากให้ {angle_theme} แย่ลงกว่าเดิม",
        f"ความลับของคนที่ใช้ {product_name} ทำไมถึงเห็นผลไวใน 7 วัน",
        f"เทียบกันชัดๆ ระหว่างวิธีเดิม กับการใช้ {product_name}",
        f"ถ้าคุณเป็น {target_persona} คุณต้องรู้สิ่งนี้!"
    ]
    script = (
        f"[0-3s Hook]: อย่าเพิ่งเลื่อนผ่านถ้าคุณเจอปัญหา {angle_theme} อยู่!\n"
        f"[3-15s Pain Point]: หลายคนเสียเงินไปหลักหมื่น แต่ก็ยังแก้ไม่ได้ เพราะแก้ไม่ตรงจุด\n"
        f"[15-35s Solution]: วันนี้ขอแนะนำ {product_name} ที่ถูกคิดค้นมาเพื่อ {target_persona} โดยเฉพาะ\n"
        f"[35-50s Proof]: ดูผลลัพธ์จากผู้ใช้จริงกว่า 1,000 คน ที่ได้ลองแล้วเปลี่ยนชีวิต\n"
        f"[50-60s CTA]: พิเศษวันนี้ มีโปรโมชั่นจำกัด 30 สิทธิ์แรก ทักแชทพิมพ์ 'สนใจ' รับราคาพิเศษทันที!"
    )
    caption = (
        f"🔥 เคล็ดลับแก้ {angle_theme} ที่ใครหลายคนยังไม่รู้!\n\n"
        f"สำหรับ {target_persona} ที่มองหาตัวช่วยจริงจัง วันนี้ {product_name} พร้อมให้คุณพิสูจน์แล้ว\n\n"
        f"✨ สิทธิพิเศษวันนี้:\n"
        f"✅ ลดทันที 30%\n"
        f"✅ ส่งฟรีปลายทาง\n"
        f"✅ รับประกันความพึงพอใจ\n\n"
        f"👇 สนใจทักข้อความหรือกดปุ่มด้านล่างได้เลยครับ!\n"
        f"#{product_name.replace(' ', '')} #การตลาดออนไลน์ #รีวิวของดี"
    )

    if client:
        try:
            response = client.models.generate_content(
                model='gemini-2.5-flash',
                contents=prompt,
                config=types.GenerateContentConfig(
                    response_mime_type="application/json",
                    temperature=0.7,
                )
            )
            data = json.loads(response.text)
            hooks = data.get('hook_options', hooks)
            script = data.get('script_outline', script)
            caption = data.get('caption_copy', caption)
        except Exception:
            pass

    idea = CreativeIdea.objects.create(
        product_name=product_name,
        target_persona=target_persona,
        angle_theme=angle_theme,
        hook_options=hooks,
        script_outline=script,
        caption_copy=caption,
        format=format_type,
    )
    return idea


def analyze_competitor_intel(brand_name, platform, observed_angle, pricing_promotion, post_url=""):
    """
    วิเคราะห์การเคลื่อนไหวของคู่แข่ง และวางกลยุทธ์แก้เกม
    """
    client = get_gemini_client()
    counter_strategy = (
        f"1. ชิงจุดขายที่คู่แข่งยังขาด: คู่แข่งเน้นเล่นเรื่อง '{pricing_promotion}' แต่เราควรชูจุดเด่นด้านคุณภาพและการบริการที่เหนือกว่า\n"
        f"2. สวนแอดด้วย Hook เปรียบเทียบ: สร้างคลิปประเภท 'เทียบให้ดูชัดๆ' โดยไม่เอ่ยชื่อคู่แข่งตรงๆ\n"
        f"3. ทำ Bundle Offer: เสนอเซตแพ็กคู่ที่ความคุ้มค่าสูงกว่าราคาชิ้นเดี่ยวของคู่แข่ง"
    )

    if client:
        try:
            prompt = (
                f"วิเคราะห์คู่แข่งชื่อ: {brand_name}\n"
                f"ช่องทาง: {platform}\n"
                f"มุมการขายที่เขาใช้: {observed_angle}\n"
                f"ราคาและโปรโมชั่นของเขา: {pricing_promotion}\n\n"
                f"แนะนำกลยุทธ์แก้เกม (Counter Strategy) 3 ข้ออย่างเฉียบขาดในฐานะผู้เชี่ยวชาญการตลาด"
            )
            response = client.models.generate_content(
                model='gemini-2.5-flash',
                contents=prompt,
            )
            if response.text:
                counter_strategy = response.text.strip()
        except Exception:
            pass

    intel = CompetitorIntel.objects.create(
        brand_name=brand_name,
        platform=platform,
        ad_or_post_url=post_url,
        hook_observed=observed_angle,
        pricing_promotion=pricing_promotion,
        ai_counter_strategy=counter_strategy,
    )
    return intel
