# 👤 Accounts App — ระบบจัดการผู้ใช้และสิทธิ์การเข้าถึง (User & Role Management)

ระบบจัดการบัญชีผู้ใช้งาน โปรไฟล์พนักงาน ตำแหน่งงาน (Role) และควบคุมสิทธิ์การเข้าถึงโมดูลต่าง ๆ ในระดับ URL Prefix (URL Prefix: `/accounts/`)

---

## 🌟 ฟีเจอร์หลัก (Key Features)

1. **การจัดการตำแหน่งงานและบทบาท (Role Management)**:
   * รองรับการเพิ่ม แก้ไข ปรับแต่ง Role ได้ผ่านหน้า UI
   * ตัวอย่างบทบาท: Admin, Manager, Reception, Technician Lead, Technician, Sale, HR/Payroll
   * กำหนดสถานะพิเศษ เช่น `is_staff_role` (สิทธิ์ดูแลระบบ), `is_technician_role` (ตำแหน่งช่าง แสดงปุ่ม GPS), `can_view_all_reports` (ดูรายงานพนักงานทุกคนได้)
2. **ระบบสิทธิ์แบบแยกโมดูล (Granular Permission Controls)**:
   * โมเดล `UserProfile` กำหนดสิทธิ์รายแอปอย่างชัดเจน:
     * `access_rentals`: ระบบสัญญาเช่า (`/contracts/`)
     * `access_repairs`: ระบบงานซ่อม (`/repairs/`)
     * `access_pos`: ระบบขายหน้าร้าน (`/pos/`)
     * `access_pms`: ระบบบริหารโครงการ (`/pms/`)
     * `access_payroll`: ระบบเงินเดือน (`/payroll/`)
     * `access_stocks`: ระบบวิเคราะห์หุ้น AI (`/stocks/`)
     * `access_chat`: ระบบแชทกลาง (`/chat/`)
     * `access_ops`: ระบบแผนงานและการปฏิบัติการ (`/ops/`)
     * `access_board`: กระดานความรู้ (`/board/`)
     * `access_accounts`: จัดการพนักงานและสิทธิ์ (`/accounts/users/`, `/accounts/roles/`)
3. **การบังคับใช้สิทธิ์ (Middleware Enforcement)**:
   * ทำงานร่วมกับ `AppPermissionMiddleware` ในการตรวจสอบทุกคำขอ (Request) ทันที
   * หากผู้ใช้ไม่มีสิทธิ์ในโมดูลนั้น ระบบจะไม่อนุญาตให้เข้าถึงและแจ้งเตือนกลับ

---

## 🗄️ โครงสร้างโมเดลฐานข้อมูล (Models)

* **`Role`**: บทบาท/ตำแหน่งงาน, สิทธิ์พิเศษ และสี Badge
* **`UserProfile`**: ส่วนขยายของผู้ใช้ Django (`User`), กำหนดตำแหน่ง, สิทธิ์การเข้าถึงรายโมดูล, ข้อมูลติดต่อ และรูปประจำตัว

---

## 🔗 เส้นทาง URL หลัก (URL Endpoints)

* `/accounts/login/`: หน้าจอเข้าสู่ระบบ
* `/accounts/logout/`: ออกจากระบบ
* `/accounts/users/`: รายชื่อผู้ใช้งานและกำหนดสิทธิ์เข้าถึงรายบุคคล
* `/accounts/roles/`: จัดการบทบาทและตำแหน่งงาน
* `/accounts/profile/`: หน้าข้อมูลส่วนตัวของผู้ใช้
