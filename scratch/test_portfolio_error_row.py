"""กันหน้าพอร์ตล้มทั้งหน้า เพราะหุ้นตัวเดียวคำนวณไม่ผ่าน

ที่มาของบั๊กจริง (VariableDoesNotExist ที่ /stocks/portfolio/):

  {{ item.effective_stop|default:item.trailing_stop_data.trailing_stop }}

Django จับ VariableDoesNotExist ให้เฉพาะ "ตัวแปรหลัก" ของ {{ }} เท่านั้น
แต่ **อาร์กิวเมนต์ของ filter ไม่ถูกจับ** — FilterExpression.resolve() เรียก
arg.resolve(context) ตรงๆ ไม่มี try/except ล้อม

พอ portfolio_list เจอ exception กับหุ้นตัวใดตัวหนึ่ง มันจะใส่แถวสถานะ error
ที่มี trailing_stop_data = None การไปหยิบ .trailing_stop ต่อจาก None จึงระเบิด
และพาทั้งหน้าเป็น 500 ทั้งที่ตั้งใจให้เสียแค่แถวเดียว

ทางแก้: คิดตัวเลขให้จบในวิว (display_stop) แล้วเทมเพลตหยิบค่าชั้นเดียว

รันจาก repo root: python3 scratch/test_portfolio_error_row.py
"""
import ast
import re
import sys
import unittest
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT))

import django
from django.conf import settings

if not settings.configured:
    settings.configure(
        DEBUG=False,
        SECRET_KEY='x',
        INSTALLED_APPS=['django.contrib.contenttypes', 'django.contrib.auth'],
        TEMPLATES=[{
            'BACKEND': 'django.template.backends.django.DjangoTemplates',
            'DIRS': [], 'APP_DIRS': False, 'OPTIONS': {},
        }],
        USE_TZ=True,
    )
    django.setup()

from django.template import Context, Template, VariableDoesNotExist  # noqa: E402

TEMPLATE = ROOT / 'stocks' / 'templates' / 'stocks' / 'portfolio.html'
VIEW = ROOT / 'stocks' / 'views' / 'portfolio.py'

# คีย์ที่วิวตั้งเป็น None ได้จริง — ห้ามมีตัวไหนถูกใช้เป็นอาร์กิวเมนต์ของ filter
NULLABLE_KEYS = ('trailing_stop_data', 'mom_data', 'stop_breach', 'rr_now')

# แถวสถานะ error ที่วิวสร้างตอนหุ้นตัวนั้นคำนวณไม่ผ่าน
ERROR_ROW = {
    'obj': None, 'current_price': 0, 'day_change': 0, 'market_value': 0,
    'gain_loss': 0, 'gain_loss_pct': 0, 'rsi': None,
    'trailing_stop_data': None, 'mom_data': None,
    'effective_stop': None, 'display_stop': None,
    'stop_breach': None, 'rr_now': None,
    'market': 'SET',
}


class TheOriginalBugTests(unittest.TestCase):
    """ยืนยันว่าอาการที่เจอเกิดจากกลไกนี้จริง ไม่ใช่เดา"""

    def test_filter_argument_on_a_none_value_raises(self):
        tpl = Template('{{ item.effective_stop|default:item.trailing_stop_data.trailing_stop }}')
        with self.assertRaises(VariableDoesNotExist):
            tpl.render(Context({'item': ERROR_ROW}))

    def test_the_same_lookup_as_a_plain_variable_does_not_raise(self):
        # เทมเพลตเดิมก่อนแก้เขียนแบบนี้ จึงไม่เคยพัง — ความต่างอยู่ที่ตำแหน่ง ไม่ใช่ค่า
        tpl = Template('{{ item.trailing_stop_data.trailing_stop|floatformat:2 }}')
        self.assertEqual(tpl.render(Context({'item': ERROR_ROW})), '')


class TheFixTests(unittest.TestCase):
    def test_display_stop_renders_on_an_error_row(self):
        tpl = Template('{{ item.display_stop|floatformat:2 }}')
        self.assertEqual(tpl.render(Context({'item': ERROR_ROW})), '')

    def test_display_stop_renders_a_real_number(self):
        row = dict(ERROR_ROW, display_stop=12.345)
        tpl = Template('{{ item.display_stop|floatformat:2 }}')
        self.assertEqual(tpl.render(Context({'item': row})), '12.35')

    def test_conditions_on_the_nullable_keys_stay_safe(self):
        tpl = Template('{% if item.stop_breach.over_limit %}X{% else %}-{% endif %}'
                       '{% if item.rr_now.rr %}Y{% else %}-{% endif %}')
        self.assertEqual(tpl.render(Context({'item': ERROR_ROW})), '--')


class NoTemplateRepeatsTheMistakeTests(unittest.TestCase):
    """กวาดทุกเทมเพลต ไม่ใช่แค่ไฟล์ที่พังวันนี้"""

    ARG = re.compile(r'\|[a-z_]+:([a-zA-Z_][a-zA-Z0-9_.]*)')

    def test_no_filter_argument_dereferences_a_nullable_key(self):
        offenders = []
        for path in sorted(ROOT.glob('stocks/templates/**/*.html')):
            text = path.read_text(encoding='utf-8')
            for lineno, line in enumerate(text.splitlines(), 1):
                for arg in self.ARG.findall(line):
                    parts = arg.split('.')
                    # ต้องมีชั้นต่อจากคีย์ถึงจะอันตราย — arg ที่จบที่คีย์เองไม่พัง
                    for key in NULLABLE_KEYS:
                        if key in parts and parts.index(key) < len(parts) - 1:
                            offenders.append(f'{path.relative_to(ROOT)}:{lineno} -> {arg}')
        self.assertEqual(offenders, [],
                         'อาร์กิวเมนต์ของ filter ไม่ถูก Django จับ VariableDoesNotExist '
                         'ให้คิดค่าในวิวแล้วส่งมาเป็นคีย์ชั้นเดียวแทน:\n  '
                         + '\n  '.join(offenders))

    def test_the_line_that_broke_is_actually_fixed(self):
        text = TEMPLATE.read_text(encoding='utf-8')
        self.assertNotIn('default:item.trailing_stop_data.trailing_stop', text)
        self.assertIn('item.display_stop', text)


class ViewSuppliesEveryKeyTests(unittest.TestCase):
    """แถว error ต้องมีคีย์ครบ ไม่งั้นเจอปัญหาเดิมซ้ำจากคีย์ตัวอื่น"""

    def _append_dicts(self):
        tree = ast.parse(VIEW.read_text(encoding='utf-8'))
        found = []
        for node in ast.walk(tree):
            if (isinstance(node, ast.Call)
                    and isinstance(node.func, ast.Attribute)
                    and node.func.attr == 'append'
                    and isinstance(node.func.value, ast.Name)
                    and node.func.value.id == 'items'
                    and node.args and isinstance(node.args[0], ast.Dict)):
                found.append({k.value for k in node.args[0].keys
                              if isinstance(k, ast.Constant)})
        return found

    def test_there_are_two_shapes_of_row(self):
        self.assertEqual(len(self._append_dicts()), 2,
                         'คาดว่ามีแถวปกติกับแถว error อย่างละชุด')

    def test_error_row_carries_the_keys_the_template_needs(self):
        error_row = min(self._append_dicts(), key=len)
        required = {'display_stop', 'effective_stop', 'stop_breach', 'rr_now'}
        missing = required - error_row
        self.assertEqual(missing, set(), f'แถว error ขาดคีย์: {sorted(missing)}')

    def test_display_stop_falls_back_to_the_trailing_stop(self):
        # ต้องยังโชว์เลขเดิมได้ ถ้ายังไม่เคยล็อก stop ไว้กับไม้นี้
        src = VIEW.read_text(encoding='utf-8')
        self.assertIn("'display_stop': _eff_stop or _trail_candidate", src)


if __name__ == '__main__':
    unittest.main(verbosity=2)
