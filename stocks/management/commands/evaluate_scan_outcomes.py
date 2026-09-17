"""
เติมผลลัพธ์ล่วงหน้าให้ ScanOutcome — "หุ้นที่สแกนเจอวันนั้น สุดท้ายเป็นยังไง"

รันวันละครั้งหลังตลาดปิดก็พอ (ข้อมูลเป็นแท่ง Daily):
    python manage.py evaluate_scan_outcomes

ตัวเลือก:
    --market SET|US   จำกัดตลาด
    --days 90         ย้อนหลังกี่วัน (default 90)
    --batch 40        ดึงราคากี่ symbol ต่อหนึ่ง request
    --dry-run         คำนวณให้ดูแต่ไม่เขียน DB
"""
import time
from datetime import timedelta

from django.core.management.base import BaseCommand
from django.utils import timezone

from stocks.models import ScanOutcome
from stocks.scan_outcomes import (EVALUATION_WINDOW_DAYS, MAX_HORIZON,
                                  STATUS_COMPLETE, evaluate_forward)


def _to_yf_symbol(symbol, market):
    """SET ต้องเติม .BK ส่วนตลาดอื่นใช้ตามที่กรอก (ตรงกับ alert_engine._to_yf_symbol)"""
    s = (symbol or '').strip().upper()
    if market == 'SET' and not s.endswith('.BK'):
        return f"{s}.BK"
    return s


class Command(BaseCommand):
    help = 'เติม forward return / MFE / MAE / TP-SL ให้ผลสแกนที่เก็บไว้'

    def add_arguments(self, parser):
        parser.add_argument('--market', type=str, default=None, help='SET หรือ US (ไม่ใส่ = ทั้งหมด)')
        parser.add_argument('--days', type=int, default=EVALUATION_WINDOW_DAYS,
                            help=f'ย้อนหลังกี่วัน (default {EVALUATION_WINDOW_DAYS})')
        parser.add_argument('--batch', type=int, default=40, help='กี่ symbol ต่อ request')
        parser.add_argument('--dry-run', action='store_true', help='ไม่เขียน DB')

    def handle(self, *args, **opts):
        import pandas as pd
        import yfinance as yf

        market = opts.get('market')
        days = max(int(opts.get('days') or EVALUATION_WINDOW_DAYS), MAX_HORIZON)
        batch_size = max(int(opts.get('batch') or 40), 1)
        dry_run = bool(opts.get('dry_run'))

        cutoff = timezone.now().date() - timedelta(days=days)

        # แถวที่ยังวัดไม่ครบเท่านั้น — complete แล้วไม่ต้องแตะอีก ผลไม่เปลี่ยนย้อนหลัง
        qs = ScanOutcome.objects.exclude(status=STATUS_COMPLETE).filter(scan_date__gte=cutoff)
        if market:
            qs = qs.filter(market=market)
        pending = list(qs.order_by('scan_date'))

        if not pending:
            self.stdout.write(self.style.SUCCESS('ไม่มีรายการที่ต้องเติมผล'))
            return

        oldest = min(r.scan_date for r in pending)
        # เผื่อวันหยุด/วันไม่มีเทรด ให้ดึงกว้างกว่าหน้าต่างที่ต้องการพอสมควร
        start = oldest - timedelta(days=5)
        end = timezone.now().date() + timedelta(days=1)

        by_market = {}
        for row in pending:
            by_market.setdefault(row.market, []).append(row)

        total_updated = 0
        total_failed = 0

        for mkt, rows in by_market.items():
            symbols = sorted({_to_yf_symbol(r.symbol, mkt) for r in rows})
            self.stdout.write(f"[{mkt}] {len(rows)} รายการ / {len(symbols)} symbol "
                              f"(ตั้งแต่ {oldest})")

            frames = {}
            for i in range(0, len(symbols), batch_size):
                chunk = symbols[i:i + batch_size]
                try:
                    df = yf.download(chunk, start=start, end=end, interval='1d',
                                     progress=False, group_by='ticker', threads=True,
                                     auto_adjust=False)
                except Exception as e:
                    self.stderr.write(self.style.WARNING(f"  ดึงราคาไม่สำเร็จ {chunk[:3]}...: {e}"))
                    continue

                if df is None or df.empty:
                    continue
                for sym in chunk:
                    try:
                        sub = df[sym] if len(chunk) > 1 else df
                        sub = sub.dropna(subset=['Close'])
                        if len(sub):
                            frames[sym] = sub
                    except (KeyError, TypeError):
                        continue
                time.sleep(0.4)   # กัน rate limit ของ Yahoo

            to_save = []
            for row in rows:
                sub = frames.get(_to_yf_symbol(row.symbol, mkt))
                if sub is None or sub.empty:
                    total_failed += 1
                    continue

                # เอาเฉพาะแท่ง *หลัง* วันที่สแกน — แท่งของวันสแกนเองคือราคาที่เห็นตอนตัดสินใจ
                idx = pd.to_datetime(sub.index).date
                mask = [d > row.scan_date for d in idx]
                after = sub[mask]
                if after.empty:
                    continue

                result = evaluate_forward(
                    row.price_at_scan, row.stop_loss, row.target_price,
                    after['High'].tolist(), after['Low'].tolist(), after['Close'].tolist(),
                )
                if not result['bars_evaluated']:
                    continue

                for field, value in result.items():
                    setattr(row, field, value)
                row.evaluated_at = timezone.now()
                to_save.append(row)

            if to_save and not dry_run:
                ScanOutcome.objects.bulk_update(to_save, [
                    'price_d5', 'price_d10', 'price_d20',
                    'ret_d5', 'ret_d10', 'ret_d20',
                    'mfe_pct', 'mae_pct', 'first_hit', 'r_multiple',
                    'bars_evaluated', 'status', 'evaluated_at',
                ], batch_size=200)
            total_updated += len(to_save)

            done = sum(1 for r in to_save if r.status == STATUS_COMPLETE)
            self.stdout.write(f"  อัปเดต {len(to_save)} รายการ (ครบ 20 แท่งแล้ว {done})")

        prefix = '[dry-run] ' if dry_run else ''
        self.stdout.write(self.style.SUCCESS(
            f"{prefix}เสร็จ — อัปเดต {total_updated} รายการ"
            + (f" / ดึงราคาไม่ได้ {total_failed}" if total_failed else "")
        ))
