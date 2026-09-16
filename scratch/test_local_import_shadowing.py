"""จับ UnboundLocalError จาก import ที่ซ่อนอยู่กลางฟังก์ชัน

อาการจริงที่เจอบนเครื่องจริง (ทุกไม้ในพอร์ตขึ้นราคา 0 หมด):

    UnboundLocalError: cannot access local variable 'timezone'
    where it is not associated with a value
      File "stocks/views/portfolio.py", line 389, in portfolio_list
        item.stop_updated_at = timezone.now()

กลไก: `from django.utils import timezone` ถูกเขียนไว้กลางฟังก์ชัน portfolio_list
(บรรทัด 741) Python มองทั้งฟังก์ชันตอน compile แล้วตัดสินว่า `timezone` เป็น
"ตัวแปรโลคอล" ของฟังก์ชันนี้ ตั้งแต่บรรทัดแรก โค้ดที่ใช้ชื่อนี้ก่อนถึงบรรทัด 741
จึงไม่ได้ไปหยิบตัวจาก django แต่ไปอ่านตัวแปรโลคอลที่ยังไม่มีค่า → ระเบิดทุกครั้ง

น่ากลัวตรงที่ portfolio_list จับ exception รายไม้แล้วใส่แถวสถานะ error แทน
หน้าเว็บจึงขึ้น 200 ปกติ ไม่มี error ให้เห็น มีแค่ราคาเป็น 0 ทั้งตาราง

เทสต์นี้กวาดทั้ง stocks/ ด้วย AST โดยนับเฉพาะ scope ของฟังก์ชันนั้นจริงๆ
(ไม่ลงไปในฟังก์ชันซ้อน / lambda / comprehension ซึ่งมี scope ของตัวเอง)

รันจาก repo root: python3 scratch/test_local_import_shadowing.py
"""
import ast
import unittest
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]

NESTED = (ast.FunctionDef, ast.AsyncFunctionDef, ast.Lambda, ast.ClassDef,
          ast.ListComp, ast.SetComp, ast.DictComp, ast.GeneratorExp)

# จุดที่มีอยู่ก่อนแล้ว ไม่ได้เกิดจากงานรอบนี้ — ยังไม่แก้เพราะอยู่นอกขอบเขต
# แต่ล็อกรายการไว้เพื่อไม่ให้มีเพิ่ม (ดูหมายเหตุใน test_no_new_shadowing)
KNOWN = {
    ('stocks/alert_engine.py', 'evaluate_user_alerts', '_compute_signals'),
    ('stocks/alert_engine.py', 'evaluate_user_alerts', '_cea'),
    ('stocks/trading_bridge.py', 'sync_trade_status', '_Dec'),
    ('stocks/utils.py', 'find_supply_demand_zones', 'ta'),
    ('stocks/views/ai_analysis.py', '_run', '_c2'),
    ('stocks/views/core.py', 'dashboard', 'yf'),
    ('stocks/views/core.py', 'analyze', 'json'),
    ('stocks/views/core.py', 'analyze', 'timezone'),
    ('stocks/views/scanners.py', 'mean_reversion_scanner', '_MRC'),
    ('stocks/views/scanners.py', 'momentum_scanner', '_tm'),
    ('stocks/views/scanners.py', 'precision_momentum_scanner', '_t'),
    ('stocks/views/scanners.py', 'multi_factor_scanner', 'cache'),
    ('stocks/views/scanners.py', 'us_multi_factor_scanner', 'cache'),
    ('stocks/views/scanners.py', 'us_precision_scanner', '_t'),
    ('stocks/views/scanners.py', 'cup_handle_scanner', 'get_top_ranked_symbols'),
    ('stocks/views/scanners.py', '_run_precision_bg', 'logging'),
    ('stocks/views/scanners.py', '_run_momentum_bg', 'logging'),
    ('stocks/views/scanners.py', '_process_precision_scan', 'logging'),
}


def _own_scope(fn):
    """ทุกโหนดที่อยู่ใน scope ของ fn เอง — ไม่ข้ามเข้าไปใน scope ซ้อน"""
    stack = list(fn.body)
    while stack:
        node = stack.pop()
        yield node
        if isinstance(node, NESTED):
            continue
        stack.extend(ast.iter_child_nodes(node))


def shadowing_in(path):
    """คืน (ชื่อฟังก์ชัน, ชื่อตัวแปร, บรรทัดที่ใช้, บรรทัดที่ import)"""
    tree = ast.parse(path.read_text(encoding='utf-8'))
    out = []
    for fn in ast.walk(tree):
        if not isinstance(fn, (ast.FunctionDef, ast.AsyncFunctionDef)):
            continue
        imports = {}
        for node in _own_scope(fn):
            if isinstance(node, (ast.Import, ast.ImportFrom)):
                for alias in node.names:
                    key = (alias.asname or alias.name).split('.')[0]
                    imports.setdefault(key, node.lineno)
        if not imports:
            continue
        for node in _own_scope(fn):
            if isinstance(node, ast.Name) and isinstance(node.ctx, ast.Load):
                line = imports.get(node.id)
                if line is not None and node.lineno < line:
                    out.append((fn.name, node.id, node.lineno, line))
    return out


def scan_all():
    found = {}
    for path in sorted(ROOT.glob('stocks/**/*.py')):
        try:
            hits = shadowing_in(path)
        except SyntaxError:
            continue
        for fname, name, use_line, imp_line in hits:
            key = (str(path.relative_to(ROOT)), fname, name)
            found.setdefault(key, (use_line, imp_line))
    return found


class TheMechanismTests(unittest.TestCase):
    """ยืนยันว่า Python ทำแบบนี้จริง ไม่ใช่ทฤษฎี"""

    def test_a_late_import_makes_the_name_local_for_the_whole_function(self):
        ns = {}
        exec(
            'import math\n'
            'def f():\n'
            '    first = math.floor(1.5)\n'   # ใช้ก่อน
            '    import math\n'               # import ทีหลัง → math เป็นโลคอลทั้งฟังก์ชัน
            '    return first, math.floor(2.5)\n',
            ns,
        )
        with self.assertRaises(UnboundLocalError):
            ns['f']()

    def test_moving_the_import_out_fixes_it(self):
        ns = {}
        exec(
            'import math\n'
            'def f():\n'
            '    return math.floor(1.5), math.floor(2.5)\n',
            ns,
        )
        self.assertEqual(ns['f'](), (1, 2))

    def test_a_nested_function_has_its_own_scope(self):
        # เหตุผลที่เครื่องมือกวาดต้องไม่ลงไปใน scope ซ้อน ไม่งั้นจะฟ้องผิด
        ns = {}
        exec(
            'import math\n'
            'def outer():\n'
            '    def inner():\n'
            '        return math.floor(1.5)\n'
            '    import math\n'
            '    return inner()\n',
            ns,
        )
        self.assertEqual(ns['outer'](), 1)


class PortfolioIsCleanTests(unittest.TestCase):
    """ไฟล์ที่พังจริงต้องสะอาด ไม่ใช่แค่แก้บรรทัดเดียวที่เห็น"""

    PATH = ROOT / 'stocks' / 'views' / 'portfolio.py'

    def test_no_shadowing_left_in_portfolio_view(self):
        hits = shadowing_in(self.PATH)
        pretty = [f'{f}() ใช้ `{n}` ที่บรรทัด {u} แต่ import ที่ {i}'
                  for f, n, u, i in hits]
        self.assertEqual(pretty, [], 'ยังมี import ที่บังชื่อเหลืออยู่:\n  '
                                     + '\n  '.join(pretty))

    def test_timezone_is_imported_at_module_level(self):
        src = self.PATH.read_text(encoding='utf-8')
        head = src.split('def portfolio_list', 1)[0]
        self.assertIn('from django.utils import timezone', head,
                      'timezone ต้องถูก import ที่ระดับโมดูล')

    def test_the_line_that_crashed_still_uses_timezone(self):
        # กันการ "แก้" ด้วยการลบฟีเจอร์ทิ้ง — stop ที่ขยับขึ้นต้องยังบันทึกเวลาไว้
        src = self.PATH.read_text(encoding='utf-8')
        self.assertIn('item.stop_updated_at = timezone.now()', src)


class NoNewShadowingTests(unittest.TestCase):
    """ของเก่า 18 จุดยังไม่แก้ (อยู่นอกขอบเขตงานรอบนี้) แต่ห้ามมีเพิ่ม

    ทั้ง 18 จุดเป็น "ระเบิดเวลา" ไม่ใช่บั๊กที่แสดงอาการแน่นอน — มันพังก็ต่อเมื่อ
    บรรทัดที่ใช้ชื่อนั้นถูกรันจริงก่อนบรรทัด import ถ้าอยู่คนละสาขาเงื่อนไขก็รอดไป
    ของ portfolio_list พังทุกครั้งเพราะทั้งสองบรรทัดอยู่บนทางเดินหลัก
    """

    def test_no_new_shadowing(self):
        found = set(scan_all())
        new = found - KNOWN
        self.assertEqual(sorted(new), [],
                         'เพิ่มจุดใหม่ — ย้าย import ขึ้นไประดับโมดูล '
                         'หรือใช้ชื่อ alias ที่ไม่ชนกัน:\n  '
                         + '\n  '.join(map(str, sorted(new))))

    def test_the_known_list_does_not_go_stale(self):
        found = set(scan_all())
        fixed = KNOWN - found
        self.assertEqual(sorted(fixed), [],
                         'แก้ไปแล้วแต่ยังค้างใน KNOWN — ลบออกจากลิสต์ด้วย:\n  '
                         + '\n  '.join(map(str, sorted(fixed))))


if __name__ == '__main__':
    unittest.main(verbosity=2)
