# 🤖 Chatbot App — ผู้ช่วย AI อัจฉริยะ (9Com Intelligence Assistant)

ระบบแชทบอทตอบคำถามและให้คำปรึกษาผ่านการเชื่อมต่อกับ **Google Gemini AI** (URL Prefix: `/chatbot/`)

---

## 🌟 ฟีเจอร์หลัก (Key Features)

1. **ผู้ช่วยถาม-ตอบอัจฉริยะ (AI Assistant)**:
   * รองรับการสนทนาภาษาไทยและภาษาอังกฤษอย่างเป็นธรรมชาติ
   * ให้คำแนะนำเกี่ยวกับการใช้งานฟังก์ชันต่าง ๆ ภายในระบบ
2. **Context-Aware Assistance**:
   * นำข้อมูลบริบทของผู้ใช้งานที่เข้าสู่ระบบ (เช่น ชื่อ แผนก สิทธิ์) มาช่วยให้คำตอบที่ตรงกับตัวตนของผู้ใช้มากยิ่งขึ้น
3. **API Integration แบบรวดเร็ว**:
   * REST API Endpoint (`/chatbot/message/`) สำหรับรับส่งข้อมูล JSON กับ Frontend วิดเจ็ตแชทบอท
   * มีกลไก Handle Error และ Fallback เพื่อความเสถียรในการใช้งาน

---

## 🛠️ โครงสร้างและการทำงาน (Architecture)

* **`views.py`**:
  * `chatbot_message`: รับข้อความแบบ POST JSON payload `{"text": "คำถาม"}` และส่งคำตอบกลับ `{"reply": "คำตอบจาก AI"}`
* **`services/gemini.py`**:
  * `gemini_chat_sync`: ฟังก์ชันเชื่อมต่อ Google Gemini SDK โดยใช้ API Key จาก `settings.GEMINI_API_KEY`

---

## 🔗 เส้นทาง URL หลัก (URL Endpoints)

* `/chatbot/message/`: API Endpoint สำหรับรับข้อความและส่งคำตอบของ AI
