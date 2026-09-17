# 📈 Stocks App — ระบบวิเคราะห์และสแกนหุ้นด้วย AI (Stock Market AI Platform)

ระบบวิเคราะห์ สแกนหุ้น และจำลองการเทรดอัตโนมัติ รองรับทั้งตลาดหุ้นไทย (SET) และตลาดหุ้นสหรัฐฯ (US - NYSE/Nasdaq) ขับเคลื่อนด้วยทฤษฎีเทรดระดับสากลและ Google Gemini AI

---

## 🌟 ฟีเจอร์หลัก (Key Features)

1. **Precision Momentum Scanner (`/stocks/momentum/precision/`)**:
   * สแกนคัดกรองหุ้นคุณภาพสูงด้วย Minervini Trend Template (8 ข้อ), Stage 2 (Weinstein), Pocket Pivot (Morales & Kacher), Wyckoff Spring/Upthrust, Volume Dry-Up (VDU), และ Volatility Contraction Pattern (VCP)
   * คำนวณ Relative Strength (RS Rating 0–99), Markov Market Regime (Bull/Bear/Choppy), และ Win Probability
   * ประเมิน Supply & Demand Zones, ATR Stop Loss, และ Risk/Reward Ratio
2. **ระบบสแกนรูปแบบราคาอื่น ๆ**:
   * **Minervini SEPA Scanner**: คัดหุ้นตามหลัก Specific Entry Point Analysis
   * **Cup with Handle Scanner**: ตรวจจับรูปแบบกราฟถ้วยหูพร้อมแนวเบรกเอาต์
   * **Turtle Breakout Scanner**: ระบบทะลุแนว 20 วัน / 50 วันตามกลยุทธ์เต่าในตำนาน
   * **Turnaround & Mean Reversion**: สแกนหุ้นกลับตัวจากแนวรับลึก
3. **Automated Trading Bots & Backtesting**:
   * บอทเทรดจำลองตามสัญญาณ (EMA, RSI/MACD, SEPA, Precision Bot)
   * คำนวณผลตอบแทน Drawdown และ Win Rate
4. **พอร์ตการลงทุนและรายการติดตาม (Portfolio & Watchlist)**:
   * ติดตามสถานะหุ้นในพอร์ตแบบเรียลไทม์
   * คำนวณ Trailing Stop อัตโนมัติ, แจ้งเตือนซื้อเพิ่ม (Pyramid Alert) และปล่อยกำไรวิ่ง (Let Profit Run)
5. **AI Plan & Insights (Gemini AI)**:
   * ส่งออกข้อมูลวิเคราะห์ทางเทคนิคในรูปแบบ JSON ให้ Gemini AI วิเคราะห์แผนการเทรดเชิงลึก

---

## 🗄️ โครงสร้างโมเดลฐานข้อมูล (Models)

* `PrecisionScanCandidate`: ผลลัพธ์การสแกนรอบต่าง ๆ ของ Precision Scanner (เก็บประวัติ 3 วันล่าสุด)
* `MomentumCandidate`: ผลการสแกน Momentum ทั่วไป
* `SEPACandidate` / `USSepaCandidate`: ผลสแกนตามกลยุทธ์ SEPA ของ Mark Minervini
* `CupHandleCandidate` / `TurtleScanCandidate`: ผลสแกนตามแพทเทิร์นเฉพาะ
* `Portfolio`: พอร์ตจำลองการถือครองหุ้น คำนวณจุด TP, SL, Trailing Stop และผลกำไรขาดทุน
* `TradingBot` / `BotExecutionLog`: การตั้งค่าและการบันทึกประวัติการส่งคำสั่งของบอทเทรด
* `ScanWatchlistItem`: รายการหุ้นที่ผู้ใช้บันทึกไว้ใน Watchlist

---

## 🔗 เส้นทาง URL หลัก (URL Endpoints)

* `/stocks/`: แดชบอร์ดภาพรวมระบบหุ้นและดัชนีตลาด
* `/stocks/momentum/precision/`: หน้าจอหลัก Precision Momentum Scanner (หุ้นไทย)
* `/stocks/momentum/precision/us/`: Precision Scanner สำหรับตลาดสหรัฐฯ
* `/stocks/momentum/precision/ai/`: API ขอคำแนะนำแผนเทรดจาก Google Gemini
* `/stocks/portfolio/`: หน้าจัดการพอร์ตการลงทุนและบันทึกการซื้อขาย
* `/stocks/watchlist/`: หน้าติดตามหุ้นที่บันทึกไว้
* `/stocks/bots/`: แดชบอร์ดจัดการและเปิดใช้งาน Trading Bots
