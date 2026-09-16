"""
ตัวกลางสำหรับ pandas_ta — เลือกแพ็กเกจที่ติดตั้งอยู่จริงให้อัตโนมัติ

ทำไมต้องมี: โปรเจกต์ pin `pandas-ta==0.3.14b1` ไว้ แต่แพ็กเกจนั้น
**ถูกถอดออกจาก PyPI ไปแล้ว** เหลือแค่ 0.4.x ซึ่งต้องการ Python >= 3.12
`pip install -r requirements.txt` จากเครื่องเปล่าจึงล้มที่บรรทัดนั้น:

    ERROR: Could not find a version that satisfies the requirement
           pandas-ta==0.3.14b1 (from versions: none)

ซ้ำร้าย 0.3.14b1 ตัวจริงยัง import ไม่ผ่านกับ numpy 2.x ด้วย (เรียก np.NaN
ซึ่งถูกถอดไปใน numpy 2.0) ทั้งที่ requirements.txt pin numpy==2.2.6 ไว้
แปลว่าคู่ที่ pin ไว้ใช้ด้วยกันไม่ได้ตั้งแต่แรก

ทางออกที่เลือก: pandas-ta-classic ซึ่ง fork ออกมาจาก 0.3.14b1 ตัวนั้นพอดี
(รุ่นแรกของ fork คือ 0.3.14b1 เลข version เดียวกัน) แก้เรื่อง numpy 2 ให้ใน
0.3.14b2 และแก้ ta.mfi() ที่พังกับ pandas 3.x ให้ใน 0.3.78 (จึง pin ตัวนั้น)
ยังอยู่บน PyPI และรองรับ Python >= 3.10

ตรวจแล้วว่าค่าตรงกัน: เทียบ ema / sma / rsi / atr / adx / macd / mfi / bbands
ระหว่าง pandas-ta-classic 0.3.78 กับ pandas-ta 0.4.71b0 ได้ค่าเท่ากันทุกตัว
(ต่างกันแค่ระดับ 1e-8 ซึ่งเป็น floating point ปกติ) ยกเว้น bbands ที่ 0.4.x
เปลี่ยนวิธีคิดส่วนเบี่ยงเบนมาตรฐาน ทำให้แถบบน/ล่างต่างไปจริง — อีกเหตุผลที่ไม่ย้ายไป 0.4.x
และเทียบ 0.3.14b2 (ใกล้ตัวที่ pin เดิมที่สุดเท่าที่ยังหาได้) กับ 0.3.78 แล้ว
ค่าตรงกัน 16/16 ต่างแค่ mfi ที่รุ่นเก่าพัง จึงเป็นการอัปเกรดล้วน ไม่มีค่าไหนเปลี่ยน

ลองตัวที่ requirements.txt pin ไว้ก่อน แล้วค่อยตกไปที่ชื่อเดิม เพื่อให้เครื่องที่
ยังไม่ได้อัปเดตแพ็กเกจรันโค้ดชุดนี้ได้ต่อโดยไม่พัง — จะได้ไม่ต้องอัปแพ็กเกจกับ
deploy โค้ดพร้อมกันในนาทีเดียว

วิธีใช้ (แทนที่ `import pandas_ta as ta`):

    from stocks.pandas_ta_compat import ta

โมดูลนี้ไม่พึ่ง Django จึง import จากสคริปต์นอกโปรเจกต์ได้ด้วย
"""

_BACKENDS = ('pandas_ta_classic', 'pandas_ta')

ta = None
backend_name = None
_errors = {}

for _name in _BACKENDS:
    try:
        ta = __import__(_name)
        backend_name = _name
        break
    except Exception as exc:          # ImportError รวมถึงเคส numpy 2 ที่หา np.NaN ไม่เจอ
        _errors[_name] = f'{type(exc).__name__}: {exc}'

if ta is None:
    raise ImportError(
        'ไม่พบไลบรารี pandas_ta ที่ใช้งานได้ — ติดตั้งด้วย\n'
        '    pip install "pandas-ta-classic==0.3.78"\n'
        'รายละเอียดที่ลองแล้วไม่สำเร็จ:\n'
        + '\n'.join(f'  {k}: {v}' for k, v in _errors.items())
    )


def backend_version():
    """เวอร์ชันของไลบรารีที่ใช้อยู่จริง — ใช้ตอน debug ว่าเครื่องนี้รันตัวไหน"""
    return getattr(ta, 'version', None) or getattr(ta, '__version__', 'unknown')


__all__ = ['ta', 'backend_name', 'backend_version']
