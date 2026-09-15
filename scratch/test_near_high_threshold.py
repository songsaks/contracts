"""ตรวจว่าเกณฑ์ "ใกล้ High 52 สัปดาห์" มีนิยามเดียวและถูกใช้ทุกที่จริง

เดิมค่านี้ถูกพิมพ์กระจาย 4 ที่แล้วเพี้ยนกันเป็น 0.60 / 0.65 / 0.75 ทั้งที่ทุกที่
เขียนกำกับว่าเป็น Minervini Trend Template เหมือนกัน เทสต์นี้กันไม่ให้เกิดซ้ำ
ใช้ ast อ่านโครงสร้างจริง ไม่ใช่ตัด string ที่ '#' (ซึ่งพลาดถ้ามี # อยู่ในสตริง)

ไม่ต้องใช้ฐานข้อมูลและไม่ต้อง import Django
รันจาก repo root: python3 scratch/test_near_high_threshold.py
"""
import ast
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]

# ไฟล์ที่มีตัวคัดกรองซึ่งเทียบราคากับ High 52 สัปดาห์
GATE_FILES = ['stocks/views/scanners.py', 'stocks/views/portfolio.py']
# ตัวนิยาม Trend Template ของระบบ — ค่าคงที่ต้องอยู่ที่นี่
HOME = 'stocks/utils.py'
# ตัวเลขดิบที่ยังเหลือได้: ชั้นไล่คะแนนของ us_momentum_scanner (ไม่ใช่ประตูกรอง)
SCORE_TIERS = {0.90, 0.80}
CONST = 'MINERVINI_NEAR_HIGH_RATIO'

fails = []


def check(label, ok, detail=''):
    print(f'{label}: {ok}' + (f'  {detail}' if detail else ''))
    fails.append(ok)


def _mults(path):
    """คูณที่ year_high เป็นตัวตั้งโดยตรง — ไม่นับ (price/year_high*100) ซึ่งเป็นคณิตเปอร์เซ็นต์
    ต้องเช็ค operand ตรงๆ ไม่ใช่ walk ทั้งต้นไม้ ไม่งั้นจะไปเจอ 100 ในนิพจน์ซ้อน"""
    tree = ast.parse((ROOT / path).read_text())
    for n in ast.walk(tree):
        if not (isinstance(n, ast.BinOp) and isinstance(n.op, ast.Mult)):
            continue
        sides = (n.left, n.right)
        if not any(isinstance(x, ast.Name) and x.id == 'year_high' for x in sides):
            continue
        yield [x for x in sides if not (isinstance(x, ast.Name) and x.id == 'year_high')]


def raw_multipliers(path):
    """ตัวเลขดิบที่ถูกคูณกับ year_high ตรงๆ"""
    return [float(o.value) for others in _mults(path) for o in others
            if isinstance(o, ast.Constant) and isinstance(o.value, (int, float))]


def const_uses(path):
    """จำนวนจุดที่คูณ year_high กับค่าคงที่"""
    return sum(1 for others in _mults(path) for o in others
               if isinstance(o, ast.Name) and o.id == CONST)


# 1. ค่าคงที่ต้องอยู่ที่ utils.py และเป็น 0.75 (ภายใน 25% ของ High 52 สัปดาห์)
home_tree = ast.parse((ROOT / HOME).read_text())
val = None
for node in home_tree.body:
    if isinstance(node, ast.Assign) and any(
            isinstance(t, ast.Name) and t.id == CONST for t in node.targets):
        val = node.value.value
check(f'1) {CONST} อยู่ที่ {HOME} และเป็น 0.75', val == 0.75, f'(ได้ {val})')

# 2. check_trend_template ต้องใช้ค่าคงที่ ไม่ใช่เลขดิบ
check('2) check_trend_template ใช้ค่าคงที่', const_uses(HOME) >= 1,
      f'({const_uses(HOME)} จุด)')

# 3. ทุกไฟล์ที่มีประตูกรองต้องใช้ค่าคงที่ และไม่มีเลขดิบนอกจากชั้นคะแนน
total = 0
for f in GATE_FILES:
    raws = [r for r in raw_multipliers(f) if r not in SCORE_TIERS]
    uses = const_uses(f)
    total += uses
    check(f'3) {f.split("/")[-1]}: ใช้ค่าคงที่ {uses} จุด, ไม่มีเลขดิบ',
          uses >= 1 and not raws, f'(เลขดิบที่พบ: {raws or "ไม่มี"})')

# 4. รวมทุกไฟล์ต้องมีอย่างน้อย 4 จุด (scanners 3 + portfolio 1)
#    ใช้ >= ไม่ใช่ == เพราะการเพิ่มสแกนเนอร์ใหม่ที่ใช้ค่าคงที่ถูกต้อง ไม่ควรทำให้เทสต์แดง
check('4) จุดที่ใช้ค่าคงที่รวมทุกไฟล์ ≥ 4', total >= 4, f'(ได้ {total})')

# 5. ข้อความบนหน้าเว็บต้องไม่โฆษณาเกณฑ์เก่า
stale = []
for html in (ROOT / 'stocks/templates/stocks').glob('*.html'):
    txt = html.read_text()
    for bad in ('65% of 52W High', '65% ของ High 52'):
        if bad in txt:
            stale.append(f'{html.name}: {bad}')
check('5) ไม่มีหน้าเว็บโฆษณา 65% ค้างอยู่', not stale, f'({stale or "ไม่มี"})')

print('\nสรุป:', 'ผ่านหมด' if all(fails) else 'มีข้อที่ไม่ผ่าน')
raise SystemExit(0 if all(fails) else 1)
