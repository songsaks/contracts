"""คอมเมนต์ในเทมเพลตต้องไม่รั่วออกมาเป็นข้อความบนหน้าเว็บ

อาการจริง: แถบเตือนบนหน้าพอร์ตแสดงข้อความนี้ให้ผู้ใช้เห็นเต็มๆ

    🩸 มีไม้หลุดจุดตัดขาดทุนแล้ว — จัดการก่อนเปิดไม้ใหม่
    {# ราคาต่ำกว่า stop ที่ล็อกไว้ = ตามกติกาของพอร์ตเองควรออกไปแล้ว ... #}

สาเหตุ: `{# ... #}` ของ Django ใช้ได้ **บรรทัดเดียว** เท่านั้น ถ้าเขียนข้ามบรรทัด
ตัว lexer จะไม่จับคู่ให้ ทั้งก้อนจึงถูกมองเป็นข้อความธรรมดาแล้วพิมพ์ออกมา
ไม่มี error ไม่มีอะไรเตือน — หน้าเว็บขึ้นปกติ แค่มีโค้ดโผล่มาให้ผู้ใช้อ่าน

หลายบรรทัดต้องใช้ {% comment %}...{% endcomment %} หรือคอมเมนต์ HTML

รันจาก repo root: python3 scratch/test_template_comments.py
"""
import re
import sys
import unittest
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT))

import django  # noqa: E402
from django.conf import settings  # noqa: E402

if not settings.configured:
    settings.configure(
        DEBUG=False, SECRET_KEY='x',
        INSTALLED_APPS=['django.contrib.contenttypes', 'django.contrib.auth'],
        TEMPLATES=[{'BACKEND': 'django.template.backends.django.DjangoTemplates',
                    'DIRS': [], 'APP_DIRS': False, 'OPTIONS': {}}],
        USE_TZ=True,
    )
    django.setup()

from django.template import Context, Template  # noqa: E402

TEMPLATES = sorted(ROOT.glob('stocks/templates/**/*.html'))


def multiline_comments(src):
    """คืน (บรรทัดที่เริ่ม, ข้อความต้นๆ) ของทุก {# ... #} ที่ข้ามบรรทัด"""
    out = []
    for m in re.finditer(r'\{#', src):
        start = m.start()
        end = src.find('#}', start)
        seg = src[start:end + 2] if end != -1 else src[start:start + 120]
        if '\n' in seg:
            out.append((src[:start].count('\n') + 1, seg.split('\n')[0][:70]))
    return out


class TheMechanismTests(unittest.TestCase):
    """พิสูจน์ว่า Django ทำแบบนี้จริง ไม่ได้เดา"""

    def test_a_single_line_comment_disappears(self):
        out = Template('A{# ซ่อนไว้ #}B').render(Context({}))
        self.assertEqual(out, 'AB')

    def test_a_multi_line_comment_is_printed_verbatim(self):
        out = Template('A{# ซ่อน\nไว้ #}B').render(Context({}))
        self.assertIn('{#', out, 'ถ้าอันนี้ไม่ผ่าน แปลว่า Django เปลี่ยนพฤติกรรมแล้ว')
        self.assertIn('ซ่อน', out)

    def test_the_multi_line_form_that_does_work(self):
        out = Template('A{% comment %}ซ่อน\nไว้{% endcomment %}B').render(Context({}))
        self.assertEqual(out, 'AB')

    def test_an_html_comment_survives_django_but_is_hidden_by_the_browser(self):
        # เลือกวิธีนี้ในเทมเพลต: Django ไม่แตะ เบราว์เซอร์ไม่แสดง คนอ่านโค้ดยังเห็น
        out = Template('A<!-- ซ่อน\nไว้ -->B').render(Context({}))
        self.assertIn('<!--', out)
        self.assertNotIn('{#', out)


class NoTemplateLeaksACommentTests(unittest.TestCase):
    def test_no_multi_line_django_comment_anywhere(self):
        offenders = []
        for path in TEMPLATES:
            for line, head in multiline_comments(path.read_text(encoding='utf-8')):
                offenders.append(f'{path.relative_to(ROOT)}:{line}  {head}...')
        self.assertEqual(offenders, [],
                         'คอมเมนต์ {# #} ข้ามบรรทัดจะถูกพิมพ์ออกหน้าเว็บ — '
                         'ใช้ {% comment %} หรือ <!-- --> แทน:\n  '
                         + '\n  '.join(offenders))

    def test_the_banner_that_leaked_is_clean(self):
        src = (ROOT / 'stocks' / 'templates' / 'stocks'
               / 'portfolio.html').read_text(encoding='utf-8')
        self.assertNotIn('{# ราคาต่ำกว่า stop', src)
        self.assertIn('ราคาต่ำกว่า stop ที่ล็อกไว้', src, 'เจตนาของโค้ดต้องยังอธิบายไว้')


if __name__ == '__main__':
    unittest.main(verbosity=2)
