# คู่มือ Ichimoku Cloud Filter — Precision Momentum Scanner

> เวอร์ชัน: v8 | อัปเดต: เมษายน 2026  
> ไฟล์ที่เกี่ยวข้อง: `stocks/models.py`, `stocks/views.py`, `stocks/templates/stocks/precision_scan.html`

---

## 1. Ichimoku Cloud คืออะไร?

**Ichimoku Kinko Hyo** (一目均衡表) แปลว่า "มองเห็นสมดุลในพริบตาเดียว" — เป็นระบบ Technical Analysis ของญี่ปุ่นที่รวม **Trend / Momentum / Support/Resistance / และ Time** ไว้ในกราฟเดียว

ไม่เหมือน Indicator ทั่วไปที่ดูแค่ราคาหรือ Volume — Ichimoku มี **5 เส้นพร้อมกัน** และสร้าง "เมฆ" (Kumo) ที่เป็นทั้ง Support และ Resistance

---

## 2. องค์ประกอบหลัก 5 ส่วน

### 2.1 Tenkan-sen (เส้นแดง — Conversion Line)
```
Tenkan = (Highest High 9 periods + Lowest Low 9 periods) / 2
```
- **ความหมาย:** Momentum ระยะสั้น (9 วัน) — เหมือน EMA9 แต่ใช้ Midpoint ไม่ใช่ Mean
- **สัญญาณ:** เส้นชี้ขึ้น = Momentum บวก / เส้นชี้ลง = Momentum ลบ
- **เปรียบเหมือน:** EMA9 ในระบบ Minervini — วัดแรงซื้อระยะสั้น

### 2.2 Kijun-sen (เส้นน้ำเงิน — Base Line)
```
Kijun = (Highest High 26 periods + Lowest Low 26 periods) / 2
```
- **ความหมาย:** Trend ระยะกลาง (26 วัน ≈ 1 เดือนการซื้อขาย)
- **สัญญาณ:** ราคาอยู่เหนือ Kijun = Bullish / ใต้ Kijun = Bearish
- **เปรียบเหมือน:** SMA50 ที่ใช้เป็น Dynamic Support

### 2.3 Senkou Span A (ขอบบนของ Kumo — Leading Span A)
```
Span A = (Tenkan + Kijun) / 2  →  Plot ล่วงหน้า 26 แท่ง
```
- **ความหมาย:** คาดการณ์แนว Support/Resistance อนาคต 26 วัน
- **วิธีอ่าน:** Plot ล่วงหน้าทำให้เห็น "Kumo อนาคต" ว่าหนาหรือบาง

### 2.4 Senkou Span B (ขอบล่างของ Kumo — Leading Span B)
```
Span B = (Highest High 52 periods + Lowest Low 52 periods) / 2  →  Plot ล่วงหน้า 26 แท่ง
```
- **ความหมาย:** Support/Resistance ระยะยาว (52 วัน ≈ 2 เดือนครึ่ง)
- **วิธีอ่าน:** Span B เปลี่ยนช้า — แสดงแนว Support แข็งแกร่งของตลาด

### 2.5 Chikou Span (เส้นเขียว — Lagging Span)
```
Chikou = ราคาปัจจุบัน (Close)  →  Plot ย้อนหลัง 26 แท่ง
```
- **ความหมาย:** เปรียบราคาวันนี้กับราคา 26 วันก่อน
- **สัญญาณ:** Chikou อยู่เหนือราคา 26 วันก่อน = ไม่มีแนวต้านจากอดีต = Bullish

---

## 3. Kumo (เมฆ) คืออะไร?

**Kumo** = พื้นที่ระหว่าง Span A และ Span B

| สี Kumo | ความหมาย |
|---------|-----------|
| **เขียว** (Span A > Span B) | Kumo Bullish — Trend ขาขึ้น |
| **แดง** (Span B > Span A) | Kumo Bearish — Trend ขาลง |
| **หนา** | แนว Support/Resistance แข็งแกร่ง — ยากจะทะลุ |
| **บาง** | แนว Support/Resistance อ่อน — ทะลุง่าย |

**กฎทอง:** ราคาอยู่เหนือ Kumo เขียว = Bullish ที่สุด

---

## 4. Ichimoku Fields ใน Precision Scanner

ระบบคำนวณ 4 เงื่อนไขและเก็บใน `PrecisionScanCandidate`:

---

### 4.1 `ichimoku_above_kumo` — ราคาอยู่เหนือ Kumo

```python
ichimoku_above_kumo = current_price > max(SpanA[-1], SpanB[-1]) > 0
```

**อธิบาย:**
- ตรวจว่าราคาปัจจุบัน **สูงกว่า Kumo ทั้งหมด** (เหนือทั้ง Span A และ Span B)
- เป็นเงื่อนไขพื้นฐานที่สำคัญที่สุด — หุ้นที่อยู่ใต้ Kumo ถือว่าอยู่ในเขต Bearish
- ถ้าราคาอยู่ **ใน** Kumo = Neutral / กำลังต้านกัน = ไม่นับ

**ทำไมสำคัญ:**
> Kumo คือ "เขตที่ไม่มีคนซื้อมือแรก" — หุ้นที่ทะลุเหนือ Kumo แสดงว่าชนะ Supply ทั้งหมดในช่วง 26-52 วันที่ผ่านมา ตรงกับหลัก Minervini ที่ต้องการราคาเหนือ All Moving Averages

**ตัวอย่าง:** หุ้น WHA ราคา 84.22 > SpanA 4.26 และ SpanB 4.08 → `True`

---

### 4.2 `ichimoku_tk_cross` — TK Cross Bullish ใน 5 แท่งล่าสุด

```python
for i in range(-5, 0):
    if tenkan[i-1] <= kijun[i-1] and tenkan[i] > kijun[i]:
        ichimoku_tk_cross = True
        break
```

**อธิบาย:**
- ตรวจว่า **Tenkan-sen ตัด Kijun-sen ขึ้น** ภายใน 5 วันทำการล่าสุด
- TK Cross = สัญญาณ Momentum เปลี่ยนจาก Neutral → Bullish
- ดูเฉพาะ Cross ขึ้น (Tenkan ผ่าน Kijun จากล่างขึ้นบน)

**ทำไมสำคัญ:**
> TK Cross เหนือ Kumo = สัญญาณซื้อที่แข็งแกร่งที่สุดใน Ichimoku เทียบได้กับ MACD Crossover แต่ใช้ Midpoint แทน EMA จึงสะอาดกว่าในหุ้นที่มี Spike

**จุดควรระวัง:** TK Cross ใต้ Kumo = สัญญาณอ่อน (อย่าเพิ่งเข้า)

---

### 4.3 `ichimoku_kumo_green` — Kumo อนาคตเป็นสีเขียว

```python
ichimoku_kumo_green = SpanA[-1] > SpanB[-1] and SpanA[-1] > 0
```

**อธิบาย:**
- เนื่องจาก SpanA และ SpanB ถูก **Plot ล่วงหน้า 26 แท่ง** — ค่า `[-1]` จึงหมายถึง Kumo ณ ปัจจุบัน (ซึ่งถูก Calculate จาก 26 วันก่อน และแสดงวันนี้)
- `SpanA > SpanB` = Kumo เขียว = เมฆขาขึ้น

**ทำไมสำคัญ:**
> Kumo เขียวแสดงว่า Sentiment ในช่วง 26 วันที่ผ่านมาเป็นบวก และตลาดมีแนว Support ขาขึ้นรองรับ — หุ้นที่อยู่เหนือ Kumo แดงอาจ Bounce แต่ยังเสี่ยง

**Bonus:** Kumo ที่เพิ่งเปลี่ยนจากแดงเป็นเขียว (Kumo Twist) = สัญญาณ Trend Reversal ที่ดีมาก

---

### 4.4 `ichimoku_chikou_ok` — Chikou Span Clear

```python
ichimoku_chikou_ok = df['Close'].iloc[-1] > df['Close'].iloc[-27]
```

**อธิบาย:**
- ราคาปัจจุบัน (Close วันนี้) **สูงกว่าราคาเมื่อ 26 วันก่อน**
- Chikou Span ถูก Plot ย้อนหลัง 26 แท่ง → การดู Chikou ณ ปัจจุบันจึงเทียบกับราคา `[-27]`
- เงื่อนไขนี้ตรวจว่า Chikou "อยู่เหนือ Candle อดีต" = ไม่มีแนวต้านจากราคาในอดีต

**ทำไมสำคัญ:**
> Chikou เหนืออดีต = ไม่มีคนที่ซื้อ 26 วันก่อนขาดทุน = ไม่มีแรงขายจากคนที่รอตัดขาดทุน ตรงกับหลัก O'Neil ที่ต้องการหุ้นที่ไม่มี Overhead Supply

**จุดควรระวัง:** ถ้า Chikou ชนแนวต้าน (Kumo หรือราคาอดีต) ใน 26 วันหน้า = หุ้นอาจชะลอตัว

---

### 4.5 `ichimoku_score` — คะแนนรวม (0–4)

```python
ichimoku_score = sum([
    ichimoku_above_kumo,   # +1
    ichimoku_tk_cross,     # +1
    ichimoku_kumo_green,   # +1
    ichimoku_chikou_ok,    # +1
])
```

| Score | ความหมาย | สี |
|-------|----------|-----|
| **4/4** | Ichimoku Bullish สมบูรณ์แบบ — ทุกเงื่อนไขผ่าน | เขียวเข้ม |
| **3/4** | Bullish แข็งแกร่ง — ขาดเงื่อนไขเดียว | เขียว |
| **2/4** | Neutral-Bullish — ยังมีข้อกังวล | เหลือง |
| **1/4** | อ่อน — ผ่านเงื่อนไขเดียว | เทา |
| **0/4** | Bearish / ไม่ผ่านเลย | ไม่แสดง |

---

## 5. การใช้งานใน Precision Scanner

### 5.1 คอลัมน์ ICHI ในตาราง

คอลัมน์ ICHI แสดงผล 2 ชั้น:

```
☁ 4
▲K TK ☁G CH
```

**ชั้นบน — Score หลัก:**

| แสดงผล | ความหมาย | สี |
|--------|----------|-----|
| `☁ 4` | ผ่านครบ 4/4 — Bullish สมบูรณ์แบบ | เขียวเข้ม (#15803d) |
| `☁ 3` | ผ่าน 3/4 — Bullish แข็งแกร่ง | เขียว (#16a34a) |
| `☁ 2` | ผ่าน 2/4 — Neutral มีข้อกังวล | เหลือง (#ca8a04) |
| `☁ 1` | ผ่าน 1/4 — อ่อน | เทา |
| `-`   | ผ่าน 0/4 — Bearish | ไม่แสดง Score |

**ชั้นล่าง — รายละเอียด 4 เงื่อนไข:**

```
▲K  TK  ☁G  CH
```

| ตัวย่อ | ชื่อเต็ม | ผ่านเมื่อ | สีเขียว = |
|--------|---------|----------|-----------|
| **▲K** | Above Kumo | ราคา > max(SpanA, SpanB) | ราคาพ้นเมฆแล้ว |
| **TK** | TK Cross | Tenkan ตัด Kijun ขึ้น ใน 5 วัน | Momentum เปิดใหม่ |
| **☁G** | Kumo Green | SpanA > SpanB | เมฆอนาคตขาขึ้น |
| **CH** | Chikou OK | Close > Close[-27] | ไม่มีแนวต้านจากอดีต |

**ตัวอย่างการอ่าน:**

```
☁ 4          → Score 4/4 เต็ม
▲K TK ☁G CH  → ทุกตัวสีเขียว = ผ่านหมด = Bullish สมบูรณ์แบบ
```

```
☁ 3          → Score 3/4
▲K TK ☁G CH  → TK สีเทา = ยังไม่มี TK Cross ใน 5 วันล่าสุด
               รอ TK Cross เพื่อยืนยัน Momentum ก่อนเข้า
```

```
☁ 2          → Score 2/4 — ระวัง
▲K TK ☁G CH  → เฉพาะ ▲K และ ☁G ผ่าน = ราคาอยู่เหนือ Kumo เขียว
               แต่ไม่มี TK Cross และ Chikou ยังไม่ Clear
```

### 5.2 Badge ☁3 / ☁4 ที่ Symbol

หุ้นที่ได้ **Score ≥ 3** จะแสดง Badge สีเขียว `☁3` หรือ `☁4` ที่ชื่อหุ้น — ช่วยให้เห็นภาพรวมได้เร็ว

---

## 6. กลยุทธ์การใช้ Ichimoku ร่วมกับ Precision Scanner

### กลยุทธ์ที่ 1: Ichimoku Confirmation (แนะนำ)
> ใช้ Ichimoku เป็น **ตัวกรองยืนยัน** หลังจาก Precision Scanner คัดหุ้นมาแล้ว

**เงื่อนไขที่ดีที่สุด:**
- RS Rating ≥ 70 (จาก Precision Scanner)
- ADX ≥ 20 (Trend แข็งแกร่ง)
- Ichimoku Score **≥ 3** (ผ่านอย่างน้อย 3 ใน 4)
- `ichimoku_above_kumo = True` (บังคับ — ราคาต้องอยู่เหนือ Kumo)

### กลยุทธ์ที่ 2: TK Cross Entry Timing
> รอ **TK Cross** ขณะที่ราคาอยู่เหนือ Kumo เพื่อหา Entry ที่แม่นยำ

**เงื่อนไข:**
- `ichimoku_above_kumo = True`
- `ichimoku_tk_cross = True` (เพิ่งเกิด Cross ใน 5 วัน)
- `ichimoku_kumo_green = True`

### กลยุทธ์ที่ 3: Avoid Bearish Kumo
> **หลีกเลี่ยง** หุ้นที่มี Ichimoku Score 0–1 แม้ว่า RS Rating จะสูง

ตัวอย่าง: RS 85 แต่ราคาอยู่ใต้ Kumo แดง → รอให้ราคาทะลุเหนือ Kumo ก่อน

---

## 7. ข้อจำกัดของ Ichimoku

| ข้อจำกัด | วิธีรับมือ |
|---------|-----------|
| ช้ากว่าตลาด (Lagging) เพราะใช้ period 9/26/52 | ใช้คู่กับ MACD หรือ RSI สำหรับ Timing |
| ทำงานได้ดีในตลาด Trending ไม่ดีใน Sideways | ตรวจ ADX ≥ 20 ก่อน |
| ต้องการข้อมูลอย่างน้อย 52 แท่ง | หุ้น IPO ใหม่อาจไม่มีข้อมูลพอ |
| TK Cross เกิดบ่อยใน Sideways Market | บังคับให้ `ichimoku_above_kumo = True` ก่อนนับ TK Cross |

---

## 8. ตัวอย่างการอ่านหุ้น

### ตัวอย่าง: WHA (Score 3/4)
```
ichimoku_above_kumo = True   ✓ ราคา 84.22 เหนือ Kumo
ichimoku_tk_cross   = False  ✗ ยังไม่มี TK Cross ใน 5 วัน
ichimoku_kumo_green = True   ✓ Kumo อนาคตเขียว
ichimoku_chikou_ok  = True   ✓ Chikou อยู่เหนืออดีต 26 วัน
ichimoku_score      = 3
```

**สรุป WHA:** Bullish แข็งแกร่ง ขาดแค่ TK Cross — รอสัญญาณ TK Cross เพื่อยืนยัน Momentum ก่อนเข้า

---

## 9. Formula อ้างอิง

```python
# Tenkan-sen (9-period)
high9  = df['High'].rolling(9).max()
low9   = df['Low'].rolling(9).min()
tenkan = (high9 + low9) / 2

# Kijun-sen (26-period)
high26 = df['High'].rolling(26).max()
low26  = df['Low'].rolling(26).min()
kijun  = (high26 + low26) / 2

# Senkou Span A — shifted forward 26 bars
span_a = ((tenkan + kijun) / 2).shift(26)

# Senkou Span B — shifted forward 26 bars
high52 = df['High'].rolling(52).max()
low52  = df['Low'].rolling(52).min()
span_b = ((high52 + low52) / 2).shift(26)

# Chikou Span — current close shifted back 26 bars (implicit)
# ตรวจสอบโดยเปรียบ Close[-1] กับ Close[-27]
```

---

---

# คู่มือ Price Pattern — Precision Scanner

> ไฟล์คำนวณ: `stocks/utils.py` → `detect_price_pattern(df)`  
> ใช้ข้อมูล **3 แท่งเทียนล่าสุด** (OHLC) เพื่อตรวจจับ Pattern

---

## Pattern คืออะไร?

Price Pattern คือ **รูปแบบแท่งเทียน** ที่บ่งบอกว่า Momentum กำลังเปลี่ยนทิศทาง — ระบบตรวจ 7 Pattern แบ่งเป็น Bullish และ Bearish

---

## ผลต่อคะแนน BUY Score

| ประเภท | Score | ผลต่อ BUY Score |
|--------|-------|----------------|
| Bullish Pattern | +6 ถึง +10 | บวกเพิ่ม |
| Bearish Pattern | -5 ถึง -10 | หักออก |
| ไม่มี Pattern | 0 | ไม่มีผล |

---

## 🔴 Bearish Patterns (สัญญาณเตือน)

### Bearish Engulf (Score: -10)
```
แท่ง 2: ▲ Bullish (ปิดสูงกว่าเปิด)
แท่ง 1: ▼ Bearish ใหญ่ ครอบแท่ง 2 ทั้งหมด
```
- **ความหมาย:** แรงขายกลืนกิน Demand ทั้งหมดในแท่งก่อน — สัญญาณ Reversal แข็งแกร่งที่สุด
- **เงื่อนไข:** เปิดสูงกว่า Close แท่งก่อน, ปิดต่ำกว่า Open แท่งก่อน
- **ควรทำ:** หลีกเลี่ยง หรือรอยืนยันว่าราคาไม่ลงต่อ

---

### Shooting Star (Score: -8)
```
      |   ← ไส้เทียนบนยาว (≥ 2× ตัว Body)
     [ ]  ← Body เล็ก อยู่ล่าง
     (ไม่มีไส้ล่าง หรือสั้นมาก)
```
- **ความหมาย:** ราคาพุ่งขึ้นสูงระหว่างวันแต่ถูก **แรงขายดึงกลับ** ก่อนปิด — สัญญาณแรงซื้อหมดแรง
- **เงื่อนไข:** ไส้บน ≥ 2× ตัว Body, ปิดในครึ่งล่างของ Range
- **มักพบเมื่อ:** ราคาวิ่งขึ้นมาไกลแล้ว (NEAR TP) — สัญญาณระวังระยะสั้น
- **ควรทำ:** ถ้าถือหุ้นอยู่ให้ระวัง / ถ้าจะเข้าให้รอวันถัดไปก่อน

---

### Doji (Score: -5)
```
      |
      +   ← ไม่มี Body (เปิด ≈ ปิด)
      |
```
- **ความหมาย:** แรงซื้อและแรงขายเท่ากัน — ตลาด **ลังเล** ยังไม่มีทิศทาง
- **เงื่อนไข:** Body ≤ 10% ของ Range ทั้งแท่ง
- **ควรทำ:** รอดูแท่งถัดไปก่อนตัดสินใจ

---

## 🟢 Bullish Patterns (สัญญาณบวก)

### Bullish Engulf (Score: +10)
```
แท่ง 2: ▼ Bearish (ปิดต่ำกว่าเปิด)
แท่ง 1: ▲ Bullish ใหญ่ ครอบแท่ง 2 ทั้งหมด
```
- **ความหมาย:** แรงซื้อกลืนกิน Supply ทั้งหมดในแท่งก่อน — สัญญาณ Reversal ขาขึ้นแข็งแกร่ง
- **ควรทำ:** สัญญาณเข้าที่ดี โดยเฉพาะเมื่ออยู่ใน Demand Zone

---

### Hammer / Pin Bar (Score: +10)
```
     [ ]  ← Body เล็ก อยู่บน
      |   ← ไส้เทียนล่างยาว (≥ 2× ตัว Body)
```
- **ความหมาย:** ราคาร่วงลงระหว่างวันแต่ถูก **แรงซื้อดันกลับขึ้น** ก่อนปิด — Rejection ที่ Support
- **เงื่อนไข:** ไส้ล่าง ≥ 2× ตัว Body, ปิดในครึ่งบนของ Range
- **มักพบเมื่อ:** ราคาแตะ Demand Zone แล้วเด้งกลับ
- **ควรทำ:** สัญญาณ Entry ที่ดีมาก

---

### Morning Star (Score: +8)
```
แท่ง 3: ▼ Bearish ใหญ่
แท่ง 2: ⬜ Body เล็กมาก (Doji-like) — ลังเล
แท่ง 1: ▲ Bullish ปิดสูงกว่ากึ่งกลางแท่ง 3
```
- **ความหมาย:** 3 แท่งกลับตัวจาก Bearish → Bullish — แรงขายหมดแรง แรงซื้อเริ่มเข้า
- **ควรทำ:** สัญญาณ Reversal ที่น่าเชื่อถือสูง

---

### Inside Bar Breakout ↑ (Score: +6)
```
แท่ง 3: แท่งใหญ่ (High และ Low กว้าง)
แท่ง 2: แท่งเล็กอยู่ "ใน" แท่ง 3 (Inside Bar — Consolidation)
แท่ง 1: ปิดสูงกว่า High ของแท่ง 2 (Breakout!)
```
- **ความหมาย:** หลังจาก Consolidate แล้วราคา Break ขึ้น = แรงซื้อสะสมพร้อมวิ่ง
- **ควรทำ:** สัญญาณ Momentum Breakout ระยะสั้น

---

## วิธีอ่านในตาราง Scanner

| แสดงผล | ความหมาย | สี |
|--------|----------|-----|
| `▼ Shooting Star` | Bearish -8 pts | แดง |
| `▼ Bearish Engulf` | Bearish -10 pts | แดง |
| `▼ Doji` | ลังเล -5 pts | แดง |
| `▲ Morning Star` | Bullish +8 pts | เขียว |
| `▲ Bullish Engulf` | Bullish +10 pts | เขียว |
| `▲ Hammer` | Bullish +10 pts | เขียว |
| `▲ Inside Bar↑` | Bullish +6 pts | เขียว |
| `-` | ไม่มี Pattern ชัดเจน | เทา |

---

## ข้อสำคัญ

> Pattern คำนวณจาก **แท่งล่าสุดเท่านั้น** — เป็น Snapshot ณ เวลาที่สแกน ไม่ใช่ Realtime  
> ใช้ Pattern เป็น **ตัวยืนยันเพิ่มเติม** เท่านั้น ไม่ควรใช้เป็นสัญญาณเข้าหรือออกเพียงอย่างเดียว

---

*คู่มือนี้เป็นส่วนหนึ่งของ Stocks Analysis System — Contracts Project*
