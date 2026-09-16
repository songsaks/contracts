# 📜 Rentals App — ระบบบริหารจัดการสัญญาเช่า (Rental Contracts System)

ระบบจัดการทรัพย์สินและสัญญาเช่าสำหรับธุรกิจให้เช่าอุปกรณ์ เครื่องจักร อาคารสถานที่ หรือยานพาหนะ (URL Prefix: `/contracts/`)

---

## 🌟 ฟีเจอร์หลัก (Key Features)

1. **การจัดการทรัพย์สิน (Asset Management)**:
   * บันทึกรายการทรัพย์สิน/เครื่องจักร พร้อมหมายเลขซีเรียล (Serial Number) ที่ไม่ซ้ำกัน
   * กำหนดอัตราค่าเช่ารายเดือน (Monthly Rate)
   * ควบคุมสถานะความพร้อมใช้งาน: `AVAILABLE` (พร้อมเช่า), `MAINTENANCE` (ซ่อมบำรุง), `RENTED` (กำลังเช่า)
2. **การจัดการข้อมูลผู้เช่า (Tenant Management)**:
   * รองรับทั้งบุคคลธรรมดาและนิติบุคคล (หน่วยงาน/บริษัท)
   * บันทึกเลขประจำตัวประชาชน/พาสปอร์ต, อีเมล, เบอร์โทรศัพท์ และที่อยู่
3. **การทำสัญญาเช่า (Contract Management)**:
   * ผูกผู้เช่า (Tenant) เข้ากับทรัพย์สิน (Asset) รายการเดียวหรือหลายรายการ
   * กำหนดวันที่เริ่มต้น วันสิ้นสุดสัญญา และวงเงินมัดจำ
   * คำนวณยอดเงินรวมและสถานะสัญญา (Active, Expired, Terminated)

---

## 🗄️ โครงสร้างโมเดลฐานข้อมูล (Models)

* **`Asset`**: ทรัพย์สินหรือเครื่องจักรให้เช่า
  * `name`, `serial_number`, `description`, `status`, `monthly_rate`
* **`Tenant`**: ผู้เช่า (บุคคลหรือนิติบุคคล)
  * `agency_name`, `contact_person`, `document_id`, `email`, `phone`, `address`
* **`Contract`**: สัญญาเช่า
  * `contract_number`, `tenant`, `assets` (ManyToMany), `start_date`, `end_date`, `deposit_amount`, `status`

---

## 🔗 เส้นทาง URL หลัก (URL Endpoints)

* `/contracts/`: รายการสัญญาเช่าทั้งหมดและแดชบอร์ด
* `/contracts/create/`: สร้างสัญญาเช่าฉบับใหม่
* `/contracts/<id>/`: ดูรายละเอียดสัญญาเช่าและพิมพ์เอกสาร
* `/contracts/assets/`: จัดการรายการทรัพย์สินและเครื่องจักร
* `/contracts/tenants/`: จัดการรายชื่อผู้เช่า
