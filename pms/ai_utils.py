import os
from google import genai
from django.conf import settings

# ฟังก์ชันส่งข้อมูลสรุปไปให้ Gemini AI เพื่อทำการวิเคราะห์เชิงกลยุทธ์และให้คำแนะนำทางธุรกิจ
def get_gemini_analysis(data_summary):
    api_key = getattr(settings, "GEMINI_API_KEY", None)
    if not api_key:
        return "ไม่พบคีย์ Gemini API ในระบบ (GEMINI_API_KEY is missing in settings)"

    client = genai.Client(api_key=api_key)
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
        response = client.models.generate_content(
            model='gemini-3-flash-preview',
            contents=prompt
        )
        if not response.text:
            return "AI ไม่ได้ตอบกลับข้อมูลใดๆ (Empty response from AI)"
        return response.text
    except Exception as e:
        error_msg = str(e)
        if "API_KEY_INVALID" in error_msg:
            return "คีย์ Gemini API ไม่ถูกต้อง กรุณาตรวจสอบในไฟล์ .env"
        return f"เกิดข้อผิดพลาดในการเชื่อมต่อกับ Gemini: {error_msg}"


# ฟังก์ชันวิเคราะห์ประสิทธิภาพการทำงานภาคสนามด้วย Gemini AI
def get_gemini_work_analysis(data_summary):
    api_key = getattr(settings, "GEMINI_API_KEY", None)
    if not api_key:
        return "ไม่พบคีย์ Gemini API ในระบบ (GEMINI_API_KEY is missing in settings)"

    client = genai.Client(api_key=api_key)
    prompt = f"""
    คุณคือผู้เชี่ยวชาญด้าน Field Service Management และการเพิ่มประสิทธิภาพการทำงานภาคสนาม
    นี่คือข้อมูลสรุปการทำงานของช่างภาคสนาม (Technician Work Summary) จากระบบ Check-in/Check-out:

    {data_summary}

    กรุณาวิเคราะห์และให้คำแนะนำในหัวข้อต่อไปนี้:

    ## 1. 📊 สรุปภาพรวมประสิทธิภาพ
    - ชั่วโมงทำงานรวม เทียบกับมาตรฐาน
    - จำนวนงานต่อวัน/ต่อช่าง
    - สัดส่วนประเภทงาน

    ## 2. ⚡ จุดแข็งของทีม
    - ใครทำงานได้ดี ทำไม
    - ประเภทงานที่ทำได้รวดเร็ว

    ## 3. ⚠️ จุดที่ควรปรับปรุง
    - ช่างหรืองานที่ใช้เวลานานเกินประมาณ
    - ปัญหาด้านการวางแผนเส้นทาง
    - งานที่ไม่สมดุล (คนหนึ่งทำมาก คนหนึ่งทำน้อย)

    ## 4. 🗺️ การวิเคราะห์สถานที่และเส้นทาง
    - สถานที่ที่ไปบ่อย
    - โอกาสจัดกลุ่มงานในพื้นที่เดียวกัน

    ## 5. 🎯 คำแนะนำเพื่อเพิ่มประสิทธิภาพ
    - การจัดตารางงานให้ดีขึ้น
    - การกระจายงานระหว่างทีม
    - ข้อเสนอแนะเชิงปฏิบัติ 3-5 ข้อ

    ตอบเป็นภาษาไทย ใช้ภาษากระชับ เป็นมืออาชีพ จัดรูปแบบด้วย Markdown (หัวข้อ รายการ ตัวหนา)
    เน้นคำแนะนำที่นำไปปฏิบัติได้จริง (Actionable Insights)
    """

    try:
        response = client.models.generate_content(
            model='gemini-3-flash-preview',
            contents=prompt
        )
        if not response.text:
            return "AI ไม่ได้ตอบกลับข้อมูลใดๆ (Empty response from AI)"
        return response.text
    except Exception as e:
        error_msg = str(e)
        if "API_KEY_INVALID" in error_msg:
            return "คีย์ Gemini API ไม่ถูกต้อง กรุณาตรวจสอบในไฟล์ .env"
        return f"เกิดข้อผิดพลาดในการเชื่อมต่อกับ Gemini: {error_msg}"
