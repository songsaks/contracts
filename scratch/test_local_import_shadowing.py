"""จับ UnboundLocalError จาก import ที่ซ่อนอยู่กลางฟังก์ชัน

อาการจริงที่เจอบนเครื่องจริง (ทุกไม้ในพอร์ตขึ้นราคา 0 หมด):

    UnboundLocalError: cannot access local variable 'timezone'
    where it is not associated with a value
      File "stocks/views/portfolio.py", line 389, in portfolio_list
        item.stop_updated_at = timezone.now()

กลไก: `from django.utils import timezone` ถูกเขียนไว้กลางฟังก์ชัน portfolio_list
Python มองทั้งฟังก์ชันตอน compile แล้วตัดสินว่า `timezone` เป็นตัวแปรโลคอลของ
ฟังก์ชันนี้ตั้งแต่บรรทัดแรก โค้ดที่ใช้ชื่อนี้ก่อนถึงบรรทัด import จึงไม่ได้ไปหยิบตัว
จาก django แต่ไปอ่านตัวแปรโลคอลที่ยังไม่มีค่า

น่ากลัวตรงที่ portfolio_list จับ exception รายไม้แล้วใส่แถวสถานะ error แทน
หน้าเว็บจึงขึ้น 200 ปกติ ไม่มี error ให้เห็น มีแค่ราคาเป็น 0 ทั้งตาราง

เครื่องมือกวาดในไฟล์นี้ต้องดู "การผูกค่าทุกแบบ" ไม่ใช่แค่ import:
  - ถ้ามีการกำหนดค่าให้ชื่อนั้นก่อนอยู่แล้ว (เช่น `_t = threading.Thread(...)`)
    การอ่านก็ไม่พัง แม้จะมี `import ... as _t` อยู่ทีหลัง — นั่นคือชื่อชนกันเฉยๆ
  - ถ้ามี import ชื่อเดียวกันหลายจุด ตัวที่ผูกค่าคือตัวที่ *บรรทัดน้อยที่สุด*
ทั้งสองข้อนี้เคยทำให้รุ่นแรกของเครื่องมือฟ้องผิด 15 จาก 18 จุด

รันจาก repo root: python3 scratch/test_local_import_shadowing.py
"""
import ast
import unittest
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]

NESTED = (ast.FunctionDef, ast.AsyncFunctionDef, ast.Lambda, ast.ClassDef,
          ast.ListComp, ast.SetComp, ast.DictComp, ast.GeneratorExp)


def _own_scope(fn):
    """ทุกโหนดที่อยู่ใน scope ของ fn เอง — ไม่ข้ามเข้าไปใน scope ซ้อน"""
    stack = list(fn.body)
    while stack:
        node = stack.pop()
        yield node
        if isinstance(node, NESTED):
            continue
        stack.extend(ast.iter_child_nodes(node))


def shadowing_in_function(fn):
    """คืน (ชื่อ, บรรทัดที่อ่าน, บรรทัด import) เฉพาะเคสที่ import เป็นตัวผูกค่าตัวแรก"""
    bind, import_lines = {}, {}

    def note(name, lineno, is_import=False):
        if name not in bind or lineno < bind[name]:
            bind[name] = lineno
        if is_import and (name not in import_lines or lineno < import_lines[name]):
            import_lines[name] = lineno

    args = fn.args
    for a in list(args.args) + list(args.kwonlyargs) + list(args.posonlyargs):
        note(a.arg, fn.lineno)
    for a in (args.vararg, args.kwarg):
        if a:
            note(a.arg, fn.lineno)

    reads = []
    for node in _own_scope(fn):
        if isinstance(node, (ast.Import, ast.ImportFrom)):
            for alias in node.names:
                note((alias.asname or alias.name).split('.')[0], node.lineno, is_import=True)
        elif isinstance(node, ast.Name):
            if isinstance(node.ctx, ast.Store):
                note(node.id, node.lineno)
            elif isinstance(node.ctx, ast.Load):
                reads.append((node.id, node.lineno))
        elif isinstance(node, (ast.FunctionDef, ast.AsyncFunctionDef, ast.ClassDef)):
            note(node.name, node.lineno)
        elif isinstance(node, ast.ExceptHandler) and node.name:
            note(node.name, node.lineno)
        elif isinstance(node, (ast.Global, ast.Nonlocal)):
            for n in node.names:
                bind[n] = -1          # ประกาศ global/nonlocal = ไม่ใช่ตัวแปรโลคอล

    out = []
    for name, line in reads:
        first = bind.get(name)
        if first is None or first < 0 or line >= first:
            continue
        if import_lines.get(name) == first:
            out.append((name, line, first))
    return out


def shadowing_in(path):
    tree = ast.parse(path.read_text(encoding='utf-8'))
    out = []
    for fn in ast.walk(tree):
        if isinstance(fn, (ast.FunctionDef, ast.AsyncFunctionDef)):
            for name, use, imp in shadowing_in_function(fn):
                out.append((fn.name, name, use, imp))
    return out


def scan_all():
    found = {}
    for path in sorted(ROOT.glob('stocks/**/*.py')):
        try:
            hits = shadowing_in(path)
        except SyntaxError:
            continue
        for fname, name, use, imp in hits:
            found.setdefault((str(path.relative_to(ROOT)), fname, name), (use, imp))
    return found


class TheMechanismTests(unittest.TestCase):
    """ยืนยันว่า Python ทำแบบนี้จริง ไม่ใช่ทฤษฎี"""

    def test_a_late_import_makes_the_name_local_for_the_whole_function(self):
        ns = {}
        exec('import math\n'
             'def f():\n'
             '    first = math.floor(1.5)\n'     # ใช้ก่อน
             '    import math\n'                 # import ทีหลัง → math เป็นโลคอลทั้งฟังก์ชัน
             '    return first, math.floor(2.5)\n', ns)
        with self.assertRaises(UnboundLocalError):
            ns['f']()

    def test_moving_the_import_out_fixes_it(self):
        ns = {}
        exec('import math\n'
             'def f():\n'
             '    return math.floor(1.5), math.floor(2.5)\n', ns)
        self.assertEqual(ns['f'](), (1, 2))

    def test_a_nested_function_has_its_own_scope(self):
        ns = {}
        exec('import math\n'
             'def outer():\n'
             '    def inner():\n'
             '        return math.floor(1.5)\n'
             '    import math\n'
             '    return inner()\n', ns)
        self.assertEqual(ns['outer'](), 1)

    def test_an_earlier_assignment_makes_the_read_safe(self):
        """เคสที่เครื่องมือรุ่นแรกฟ้องผิด — ชื่อถูกกำหนดค่าไปแล้วก่อนถึง import"""
        ns = {}
        exec('import math\n'
             'def f():\n'
             '    math = 7\n'                    # ผูกค่าด้วยการกำหนดค่า ไม่ใช่ import
             '    got = math + 1\n'              # อ่านได้ ไม่พัง
             '    import math\n'                 # แค่ผูกค่าใหม่ทับ ไม่ใช่บั๊ก
             '    return got, math.floor(2.5)\n', ns)
        self.assertEqual(ns['f'](), (8, 2))


class TheSweepDoesNotCryWolfTests(unittest.TestCase):
    """เครื่องมือกวาดต้องไม่ฟ้องเคสที่ไม่พังจริง ไม่งั้นจะไปแก้ของที่ไม่เสีย"""

    def _hits(self, src):
        fn = ast.parse(src).body[0]
        return shadowing_in_function(fn)

    def test_flags_a_real_read_before_import(self):
        hits = self._hits('def f():\n'
                          '    x = timezone.now()\n'
                          '    from django.utils import timezone\n'
                          '    return x, timezone\n')
        self.assertEqual([h[0] for h in hits], ['timezone'])

    def test_ignores_a_name_assigned_before_the_import(self):
        # ตรงกับของจริงใน scanners.py: `_t = threading.Thread(...)` แล้วมี
        # `from datetime import time as _t` อยู่ทีหลังคนละสาขา
        hits = self._hits('def f():\n'
                          '    _t = threading.Thread()\n'
                          '    _t.start()\n'
                          '    from datetime import time as _t\n'
                          '    return _t\n')
        self.assertEqual(hits, [])

    def test_uses_the_earliest_import_when_there_are_several(self):
        # import ซ้ำสองจุด ตัวที่ผูกค่าคือตัวแรก การอ่านหลังจากนั้นจึงปลอดภัย
        hits = self._hits('def f():\n'
                          '    from django.core.cache import cache as c\n'
                          '    c.set("k", 1)\n'
                          '    from django.core.cache import cache as c\n'
                          '    return c\n')
        self.assertEqual(hits, [])

    def test_ignores_a_function_parameter(self):
        hits = self._hits('def f(json):\n'
                          '    x = json\n'
                          '    import json\n'
                          '    return x\n')
        self.assertEqual(hits, [])

    def test_ignores_a_name_declared_global(self):
        hits = self._hits('def f():\n'
                          '    global logging\n'
                          '    logging.info("x")\n'
                          '    import logging\n')
        self.assertEqual(hits, [])


class EveryFileIsCleanTests(unittest.TestCase):
    def test_nothing_in_stocks_reads_a_name_before_its_local_import(self):
        found = scan_all()
        pretty = [f'{p}:{u} {fn}() ใช้ `{n}` ก่อน import ที่บรรทัด {i}'
                  for (p, fn, n), (u, i) in sorted(found.items())]
        self.assertEqual(pretty, [], 'ย้าย import ขึ้นไประดับโมดูล '
                                     'หรือใช้ชื่อ alias ที่ไม่ชนกัน:\n  '
                                     + '\n  '.join(pretty))


class TheThreeRealOnesStayFixedTests(unittest.TestCase):
    """สามจุดที่แก้ไปจริง — ล็อกไว้ทีละไฟล์ เผื่อมีคนเผลอใส่กลับ"""

    def test_portfolio_imports_timezone_at_module_level(self):
        path = ROOT / 'stocks' / 'views' / 'portfolio.py'
        head = path.read_text(encoding='utf-8').split('def portfolio_list', 1)[0]
        self.assertIn('from django.utils import timezone', head)

    def test_portfolio_still_stamps_the_stop(self):
        # กันการ "แก้" ด้วยการลบฟีเจอร์ทิ้ง
        src = (ROOT / 'stocks' / 'views' / 'portfolio.py').read_text(encoding='utf-8')
        self.assertIn('item.stop_updated_at = timezone.now()', src)

    def test_utils_imports_ta_once_at_module_level(self):
        src = (ROOT / 'stocks' / 'utils.py').read_text(encoding='utf-8')
        self.assertEqual(src.count('from stocks.pandas_ta_compat import ta'), 1,
                         'ควรมีที่ระดับโมดูลที่เดียว ตัวที่ซ้ำในฟังก์ชันไม่มีประโยชน์'
                         ' และเสี่ยงบังชื่อ')
        head = src.split('\ndef ', 1)[0]
        self.assertIn('from stocks.pandas_ta_compat import ta', head)

    def test_core_imports_json_and_yfinance_at_module_level(self):
        src = (ROOT / 'stocks' / 'views' / 'core.py').read_text(encoding='utf-8')
        head = src.split('\ndef ', 1)[0]
        self.assertIn('import json', head)
        self.assertIn('import yfinance as yf', head)
        for dead in ('                import yfinance as yf', '        import json'):
            self.assertNotIn(dead + '\n', src, 'ยังมี import ซ่อนอยู่ในฟังก์ชัน')


if __name__ == '__main__':
    unittest.main(verbosity=2)
