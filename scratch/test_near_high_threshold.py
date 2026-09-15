"""ตรวจว่าเกณฑ์ "ใกล้ High 52 สัปดาห์" ตรงกับ Minervini Trend Template และตรงกันทุกจุด

ไม่ต้องใช้ฐานข้อมูล — อ่านซอร์สด้วย AST แล้วเทียบกับ check_trend_template ซึ่งเป็น
ตัวนิยาม Trend Template ของระบบ
รันจาก repo root: python3 scratch/test_near_high_threshold.py
"""
import ast
import re
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
SCANNERS = (ROOT / 'stocks/views/scanners.py').read_text()
UTILS = (ROOT / 'stocks/utils.py').read_text()

fails = []

# 1. ค่าคงที่ต้องเป็น 0.75 ตามข้อที่ 7 ของ Trend Template (ภายใน 25% ของ High 52 สัปดาห์)
const = re.search(r'^MINERVINI_NEAR_HIGH_RATIO\s*=\s*([0-9.]+)', SCANNERS, re.M)
ok = bool(const) and float(const.group(1)) == 0.75
print(f'1) MINERVINI_NEAR_HIGH_RATIO = {const.group(1) if const else "ไม่พบ"} (ต้อง 0.75):', ok)
fails.append(ok)

# 2. ประตูกรองต้องอ้างค่าคงที่เสมอ — ตัวเลขดิบที่ยังเหลือได้มีแค่ชั้นให้คะแนน
#    ของ us_momentum_scanner (0.90 / 0.80) ซึ่งเป็นการไล่ระดับคะแนน ไม่ใช่ตัวคัดออก
#    ถ้ามีตัวเลขอื่นโผล่มา แปลว่ามีคนพิมพ์เกณฑ์ใหม่ทับแทนที่จะใช้ค่าคงที่
SCORE_TIERS = {'0.90', '0.80'}
code_only = '\n'.join(l.split('#')[0] for l in SCANNERS.splitlines())
raw = set(re.findall(r'year_high\s*\*\s*([0-9]*\.[0-9]+)', code_only))
extra = raw - SCORE_TIERS
print(f'2) ไม่มีเกณฑ์ตัวเลขดิบนอกจากชั้นคะแนน:', not extra, f'(พบเพิ่ม: {sorted(extra) or "ไม่มี"})')
fails.append(not extra)

uses = len(re.findall(r'year_high\s*\*\s*MINERVINI_NEAR_HIGH_RATIO', SCANNERS))
print(f'3) จุดที่ใช้ค่าคงที่: {uses} จุด (ต้อง 3):', uses == 3)
fails.append(uses == 3)

# 4. ต้องตรงกับ check_trend_template ซึ่งเป็นตัวนิยาม Trend Template ของระบบเอง
tt = re.search(r"'price_within_25pct_of_high':\s*price\s*>=\s*year_high\s*\*\s*([0-9.]+)", UTILS)
same = bool(tt) and bool(const) and float(tt.group(1)) == float(const.group(1))
print(f'4) ตรงกับ check_trend_template ({tt.group(1) if tt else "?"}):', same)
fails.append(same)

# 5. ซอร์สยัง parse ได้ (กัน typo จากการแก้ด้วยสคริปต์)
try:
    ast.parse(SCANNERS); parsed = True
except SyntaxError as e:
    parsed = False; print('   SyntaxError:', e)
print('5) scanners.py parse ผ่าน:', parsed)
fails.append(parsed)

print('\nสรุป:', 'ผ่านหมด' if all(fails) else 'มีข้อที่ไม่ผ่าน')
raise SystemExit(0 if all(fails) else 1)
