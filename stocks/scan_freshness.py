"""
อายุของผลสแกน — ผลสแกนไม่ควรมีอายุอมตะ

ปัญหาเดิม: ทุกที่ที่ใช้ผลสแกนเขียนว่า `.order_by('-scan_run').first()` เฉยๆ
ไม่มีเงื่อนไขอายุเลย ถ้าสแกนครั้งล่าสุดเมื่อ 3 สัปดาห์ก่อน หน้าพอร์ตจะโชว์
SL / TP / คะแนน / ป้าย "ขึ้นแรง" ชุดนั้นเหมือนเป็นข้อมูลสดๆ และ alert engine
ก็ยิงแจ้งเตือน "เข้าโซนซื้อแล้ว" จากโซนที่คำนวณไว้ตั้งแต่เดือนก่อน

โมดูลนี้เป็นฟังก์ชันล้วน ไม่แตะ DB และไม่ยิงเน็ต

นโยบายที่ใช้ แยกตามว่าข้อมูลเก่าอันตรายแค่ไหน:
  - หน้าจอที่ "แสดงผล"  → ยังโชว์ได้ แต่ต้องติดป้ายอายุกำกับ (ไม่ลบข้อมูลทิ้ง)
  - ทางที่ "ตัดสินใจ"    → ไม่ใช้เลย (alert, stop loss, prefill ขนาดไม้)
    เงียบดีกว่าแจ้งเตือนผิด เพราะผู้ใช้เอาไปสั่งซื้อขายจริง
"""
from datetime import timedelta

from django.utils import timezone as dj_timezone

# ผลสแกนเก่ากว่านี้ถือว่า "ไม่สดแล้ว" (วันตามปฏิทิน ไม่ใช่วันทำการ)
# 7 วันครอบคลุมสุดสัปดาห์ + วันหยุดยาวได้ โดยที่โซน demand/supply ยังไม่ล้าสมัยเกินไป
SCAN_STALE_AFTER_DAYS = 7

# เกินช่วงนี้ถือว่าเก่ามากจนไม่ควรเอามาประกอบการตัดสินใจใดๆ แม้แต่การแสดงผล
SCAN_ANCIENT_AFTER_DAYS = 30


def scan_age_days(scan_run, now=None):
    """อายุของผลสแกนเป็นวัน — คืน None ถ้าไม่มีเวลากำกับ"""
    if not scan_run:
        return None
    now = now or dj_timezone.now()
    try:
        delta = now - scan_run
    except TypeError:
        # เทียบ naive กับ aware ไม่ได้ — ไม่เดา ถือว่าประเมินอายุไม่ได้
        return None
    return max(int(delta.total_seconds() // 86400), 0)


def is_stale(scan_run, max_age_days=SCAN_STALE_AFTER_DAYS, now=None):
    """
    เก่าเกินกำหนดหรือยัง

    ไม่มี scan_run = ถือว่าเก่า (True) เพราะพิสูจน์ไม่ได้ว่าสด
    ในเรื่องที่เอาไปสั่งซื้อขาย การเดาว่า "น่าจะสด" อันตรายกว่าการเดาว่า "น่าจะเก่า"
    """
    age = scan_age_days(scan_run, now=now)
    if age is None:
        return True
    return age > max_age_days


def freshness_label(scan_run, now=None):
    """ข้อความสั้นๆ สำหรับติดกำกับบนหน้าจอ"""
    age = scan_age_days(scan_run, now=now)
    if age is None:
        return 'ไม่ทราบวันที่สแกน'
    if age == 0:
        return 'สแกนวันนี้'
    if age == 1:
        return 'สแกนเมื่อวาน'
    return f'สแกนเมื่อ {age} วันก่อน'


def annotate(obj, scan_run=None, now=None):
    """
    ติดข้อมูลอายุลงบน object ที่จะส่งเข้า template

    ตั้ง .scan_age_days / .is_scan_stale / .scan_freshness_label
    คืน obj ตัวเดิมเพื่อให้เขียนต่อกันได้ ถ้า obj เป็น None จะคืน None เฉยๆ
    """
    if obj is None:
        return None
    run = scan_run if scan_run is not None else getattr(obj, 'scan_run', None)
    age = scan_age_days(run, now=now)
    try:
        obj.scan_age_days = age
        obj.is_scan_stale = is_stale(run, now=now)
        obj.scan_freshness_label = freshness_label(run, now=now)
    except AttributeError:
        pass          # object ที่ตั้ง attribute ไม่ได้ (เช่น namedtuple) ข้ามไป
    return obj


def fresh_only(candidate, max_age_days=SCAN_STALE_AFTER_DAYS, now=None):
    """
    คืน candidate ถ้ายังสด ไม่งั้นคืน None

    ใช้กับทางที่ตัดสินใจ (alert / stop loss / ขนาดไม้) ซึ่งข้อมูลเก่าทำให้
    ระบบสั่งจากโซนที่ไม่มีอยู่จริงแล้ว
    """
    if candidate is None:
        return None
    if is_stale(getattr(candidate, 'scan_run', None), max_age_days=max_age_days, now=now):
        return None
    return candidate


def fresh_cutoff(max_age_days=SCAN_STALE_AFTER_DAYS, now=None):
    """เวลาที่เก่าที่สุดที่ยังนับว่าสด — ใช้ใส่ queryset filter(scan_run__gte=...)"""
    now = now or dj_timezone.now()
    return now - timedelta(days=max_age_days)
