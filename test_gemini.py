import os
import django
import sys
import json

# Setup Django
os.environ.setdefault('DJANGO_SETTINGS_MODULE', 'config.settings')
django.setup()

from django.conf import settings
from google import genai
from stocks.models import PrecisionScanCandidate

def run():
    candidates = PrecisionScanCandidate.objects.filter(
        market='SET',
        rs_rating__gte=60,
        stage2=True
    ).order_by('-technical_score')[:60]

    stocks_data = []
    for c in candidates:
        stocks_data.append({
            'symbol': c.symbol,
            'price': float(c.price) if c.price else 0,
            'rs_rating': float(c.rs_rating) if c.rs_rating else 0,
            'rsi': float(c.rsi) if c.rsi else 50.0,
            'vcp_setup': c.vcp_setup,
            'adx': float(c.adx) if c.adx else 0,
            'stage2': c.stage2,
            'technical_score': float(c.technical_score) if c.technical_score else 0,
            'cmf': float(c.cmf) if c.cmf else 0.0,
            'volume_surge': float(c.volume_surge) if c.volume_surge else 0.0,
            'pocket_pivot': c.pocket_pivot,
            'vdu': c.vdu_near_zone,
        })

    print(f"Total stocks: {len(stocks_data)}")
    
    client = genai.Client(api_key=settings.GEMINI_API_KEY)
    
    prompt = f"""คุณคือ AI Analyst ระดับโลก ที่เชี่ยวชาญระบบ SEPA ของ Mark Minervini และ Ehlers Engineering
อ้างอิงจากคู่มือของระบบ:
1. SEPA System: คัดเลือกหุ้นที่มี Stage 2 (Uptrend), RS Rating > 60, มีรูปแบบ VCP (Volatility Contraction Pattern), และ Fundamental แข็งแกร่ง
2. 3-Step Formula: หาหุ้นที่มีการพักตัวสร้างฐาน (VCP/Cup & Handle) -> มีพลัง (Momentum/RS สูง) -> คุณภาพเกรดสถาบัน (SEPA)

**เงื่อนไขพิเศษจากผู้ใช้งาน**: 
1. **Early Stage Momentum**: ผู้ใช้ต้องการ "หุ้นเริ่มต้นวิ่ง" ที่เพิ่งเริ่มเบรค หรือกำลังฟอร์มตัวสวยๆ โดยที่ **ค่า RSI ยังไม่สูงจนเกินไป** (หลีกเลี่ยงหุ้น RSI สูงกว่า 70-75 หรือ Overbought ไปไกล) เน้น RSI ระดับ 50-65
2. **Trade with Market Maker (Smart Money Footprints)**: เราต้องการเทรดอยู่ฝั่งเดียวกับรายใหญ่ (MM) ให้วิเคราะห์ร่องรอยการสะสมของสถาบัน (Accumulation) จากข้อมูลต่อไปนี้:
   - มีการบีบตัว (vcp_setup) และวอลุ่มแห้ง (vdu) ก่อนจะลากขึ้น
   - มีค่า CMF เป็นบวก (cmf > 0) แปลว่ามีเม็ดเงินสถาบันไหลเข้าสุทธิ
   - มีวอลุ่มซื้อพุ่งผิดปกติ (volume_surge > 1.2)
   - มีสัญญาณ Pocket Pivot (pocket_pivot) วันที่แรงซื้อชนะแรงขาย 10 วันย้อนหลัง
ให้พิจารณาค่าเหล่านี้ประกอบเพื่อคัดเลือก "หุ้นที่รายใหญ่กำลังแอบเก็บสะสม" ก่อนที่รายย่อย (Retail) จะรู้ตัว!

วิเคราะห์ข้อมูลหุ้น SET จำนวน {len(stocks_data)} ตัวด้านล่างนี้ และคัดเลือกหุ้น "ที่ดีที่สุด" ตามหลักการในคู่มือ และเงื่อนไขพิเศษด้านบน (เลือกมา 5-10 ตัวที่สวยที่สุด)
สำค้ญมาก: โปรดจัดอันดับ (rank) จากหุ้นที่สวยที่สุดอันดับ 1 ไล่ลงไปเรื่อยๆ (โดยตัวที่สวยที่สุดต้องได้ Grade A)

ข้อมูลหุ้น (JSON):
{json.dumps(stocks_data)}

รูปแบบที่ต้องตอบกลับ (JSON เท่านั้น ห้ามมีข้อความอื่น):
{{
    "status": "success",
    "market": "SET",
    "selected_stocks": [
        {{
            "rank": 1,
            "symbol": "ชื่อหุ้น",
            "reasoning": "คำอธิบายโดยละเอียดว่าทำไมถึงเลือกหุ้นตัวนี้ (เช่น RSI อยู่ในโซนเริ่มต้นวิ่ง, VCP, Stage 2 ฯลฯ)",
            "grade": "A, B, หรือ C"
        }}
    ]
}}
"""
    try:
        response = client.models.generate_content(
            model='gemini-2.5-flash',
            contents=prompt,
            config={'response_mime_type': 'application/json'}
        )
        print(response.text)
    except Exception as e:
        print(f"ERROR: {str(e)}")

if __name__ == '__main__':
    run()
