"""ตรวจว่าเกณฑ์ "ใกล้ High 52 สัปดาห์" ของ Minervini Trend Template มีนิยามเดียว

เดิมค่านี้ถูกพิมพ์กระจายหลายที่แล้วเพี้ยนกันเป็น 0.60 / 0.65 / 0.75 ทั้งที่ทุกที่
เขียนกำกับว่าเป็นเกณฑ์เดียวกัน เทสต์นี้กันไม่ให้เกิดซ้ำ

วิธีตรวจ: ใช้ ast หา "การคูณตัวแปร High 52 สัปดาห์ด้วยค่าคงตัว" ทุกจุดในไฟล์ที่
เกี่ยวข้อง แล้วบังคับว่าต้องอ้าง MINERVINI_NEAR_HIGH_RATIO เว้นแต่จะอยู่ใน
ALLOWED ซึ่งเป็นรายการ "ตัวเลขที่เป็นคนละเกณฑ์จริงๆ" พร้อมเหตุผลกำกับทีละตัว
ใครเพิ่มเลขดิบใหม่จะถูกจับทันที ต้องเลือกว่าจะใช้ค่าคงที่หรือมาขึ้นทะเบียนที่นี่

ไม่ต้องใช้ฐานข้อมูลและไม่ต้อง import Django
รันจาก repo root: python3 scratch/test_near_high_threshold.py
"""
import ast
import re
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
CONST = 'MINERVINI_NEAR_HIGH_RATIO'
HOME = 'stocks/utils.py'          # ที่อยู่ของค่าคงที่ (ข้าง check_trend_template)
FILES = [HOME, 'stocks/views/scanners.py', 'stocks/views/portfolio.py']

# ตัวเลขดิบที่ "ไม่ใช่" เกณฑ์ Trend Template — ขึ้นทะเบียนไว้พร้อมเหตุผล
# key = (ไฟล์, ค่า) เพื่อไม่ให้ค่าที่อนุญาตในไฟล์หนึ่งไปเปิดช่องให้อีกไฟล์
ALLOWED = {
    ('stocks/utils.py', 0.99): 'เบรก/แตะ 52W High (±1%) — คนละเกณฑ์กับ Trend Template',
    ('stocks/utils.py', 0.90): 'ชั้นไล่คะแนนความใกล้ยอด',
    ('stocks/utils.py', 0.85): 'ชั้นไล่คะแนนความใกล้ยอด',
    ('stocks/views/scanners.py', 0.90): 'ชั้นไล่คะแนนของ us_momentum_scanner',
    ('stocks/views/scanners.py', 0.80): 'ชั้นไล่คะแนนของ us_momentum_scanner',
    ('stocks/views/scanners.py', 0.88): 'VDU near high — เกณฑ์วอลุ่มแห้ง ไม่ใช่ประตู Trend Template',
}

fails = []


def check(label, ok, detail=''):
    print(f'{label}: {ok}' + (f'  {detail}' if detail else ''))
    fails.append(ok)


def near_high_mults(path):
    """คืน [(บรรทัด, ตัวคูณอีกฝั่ง)] ของทุกจุดที่คูณตัวแปร High 52 สัปดาห์โดยตรง

    จับทุกชื่อที่ขึ้นต้นด้วย year_h (scanners.py ใช้ทั้ง year_high และ year_h)
    เทียบเฉพาะ operand ตรงๆ ไม่ walk ทั้งต้นไม้ ไม่งั้นจะไปเจอ 100 ใน
    (price / year_high * 100) ซึ่งเป็นคณิตเปอร์เซ็นต์ ไม่ใช่เกณฑ์
    """
    tree = ast.parse((ROOT / path).read_text())
    for n in ast.walk(tree):
        if not (isinstance(n, ast.BinOp) and isinstance(n.op, ast.Mult)):
            continue
        sides = [n.left, n.right]
        hi = [x for x in sides if isinstance(x, ast.Name) and x.id.startswith('year_h')]
        if not hi:
            continue
        for other in (x for x in sides if x not in hi):
            yield n.lineno, other


# 1. ค่าคงที่ต้องอยู่ที่ utils.py และเป็น 0.75 (ภายใน 25% ของ High 52 สัปดาห์)
val, err = None, ''
for node in ast.parse((ROOT / HOME).read_text()).body:
    if isinstance(node, ast.Assign) and any(
            isinstance(t, ast.Name) and t.id == CONST for t in node.targets):
        if isinstance(node.value, ast.Constant):
            val = node.value.value
        else:
            err = ' (ไม่ใช่ค่าคงตัว — เทสต์อ่านไม่ได้)'   # กันพังถ้ามีคนเขียนเป็นนิพจน์
check(f'1) {CONST} อยู่ที่ {HOME} และเป็น 0.75', val == 0.75, f'(ได้ {val}{err})')

# 2. ทุกไฟล์: จุดที่คูณ High 52 สัปดาห์ ต้องใช้ค่าคงที่ หรืออยู่ในทะเบียน ALLOWED
total_const = 0
for f in FILES:
    bad, uses = [], 0
    for lineno, other in near_high_mults(f):
        if isinstance(other, ast.Name) and other.id == CONST:
            uses += 1
        elif isinstance(other, ast.Constant) and isinstance(other.value, (int, float)):
            if (f, float(other.value)) not in ALLOWED:
                bad.append(f'บรรทัด {lineno} → *{other.value}')
    total_const += uses
    check(f'2) {f.split("/")[-1]}: ใช้ค่าคงที่ {uses} จุด, ไม่มีเลขดิบนอกทะเบียน',
          not bad, f'({bad or "ไม่มี"})')

# 3. ต้องมีอย่างน้อย 5 จุด (utils 2: check_trend_template + tt_price_score,
#    scanners 3, portfolio 1 = 6) — ใช้ >= เพื่อไม่ให้แดงเมื่อมีคนเพิ่มจุดที่ถูกต้อง
check('3) จุดที่ใช้ค่าคงที่รวมทุกไฟล์ ≥ 5', total_const >= 5, f'(ได้ {total_const})')

# 4. ข้อความบนหน้าเว็บต้องตรงกับค่าคงที่ — คิดเปอร์เซ็นต์จากค่าจริง ไม่พิมพ์ตายตัว
want = f'{(val or 0) * 100:.0f}'
pat = re.compile(r'(\d{2})%\s*(?:of\s*52W\s*High|ของ\s*High\s*52)', re.I)
stale = []
for html in (ROOT / 'stocks/templates').rglob('*.html'):
    for m in pat.finditer(html.read_text()):
        if m.group(1) != want:
            stale.append(f'{html.name}:{m.group(0)}')
check(f'4) หน้าเว็บระบุ {want}% ตรงกับค่าคงที่', not stale, f'({stale or "ไม่มี"})')

print('\nสรุป:', 'ผ่านหมด' if all(fails) else 'มีข้อที่ไม่ผ่าน')
raise SystemExit(0 if all(fails) else 1)
