import os
import google.generativeai as genai
from django.conf import settings

def get_gemini_analysis(data_summary):
    api_key = getattr(settings, "GEMINI_API_KEY", None)
    if not api_key:
        return "ไม่พบคีย์ Gemini API ในระบบ (GEMINI_API_KEY is missing in settings)"

    genai.configure(api_key=api_key, transport='rest')
    # Use 'gemini-2.0-flash' which is verified to work in this environment
    model = genai.GenerativeModel('gemini-2.0-flash')
    
    prompt = f"""
    คุณคือผู้เชี่ยวชาญด้านการวิเคราะห์ข้อมูลธุรกิจ (Business Analyst) 
    นี่คือข้อมูลสรุปจากระบบบริหารโครงการ (Project Management System) ประจำเดือน/ปีที่เลือก:
    
    {data_summary}
    
    กรุณาวิเคราะห์ข้อมูลนี้และให้คำแนะนำในหัวข้อดังนี้:
    1. สรุปภาพรวมผลการดำเนินงาน (Executive Summary)
    2. จุดเด่นและโอกาส (Strengths & Opportunities)
    3. ข้อควรระวังหรือจุดที่ควรปรับปรุง (Areas for Improvement)
    4. คำแนะนำเชิงกลยุทธ์สำหรับเดือนถัดไป (Strategic Recommendations)
    
    ตอบเป็นภาษาไทย โดยใช้ภาษาที่เป็นมืออาชีพ แต่เข้าใจง่าย และจัดรูปแบบด้วย Markdown ที่สวยงาม (เช่น ใช้หัวข้อ รายการสัญลักษณ์ หรือตัวหนา)
    """
    
    try:
        response = model.generate_content(prompt)
        if not response.text:
            return "AI ไม่ได้ตอบกลับข้อมูลใดๆ (Empty response from AI)"
        return response.text
    except Exception as e:
        error_msg = str(e)
        if "API_KEY_INVALID" in error_msg:
            return "คีย์ Gemini API ไม่ถูกต้อง กรุณาตรวจสอบในไฟล์ .env"
        return f"เกิดข้อผิดพลาดในการเชื่อมต่อกับ Gemini: {error_msg}"
