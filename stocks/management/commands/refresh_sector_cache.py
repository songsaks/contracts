"""
python manage.py refresh_sector_cache

ดึง sector จาก yfinance ครั้งเดียวสำหรับทุก ScannableSymbol
แล้วเก็บใน ScannableSymbol.sector เพื่อให้ multi_factor_scanner ไม่ต้องดึงซ้ำ
รันเดือนละครั้ง หรือหลัง refresh_set100_symbols
"""
from django.core.management.base import BaseCommand
from concurrent.futures import ThreadPoolExecutor, as_completed
import yfinance as yf


class Command(BaseCommand):
    help = 'Cache sector info สำหรับทุก ScannableSymbol (รันเดือนละครั้ง)'

    def add_arguments(self, parser):
        parser.add_argument('--workers', type=int, default=20, help='จำนวน threads (default 20)')

    def handle(self, *args, **options):
        from stocks.models import ScannableSymbol

        symbols = list(ScannableSymbol.objects.filter(is_active=True))
        self.stdout.write(f'Fetching sector for {len(symbols)} symbols...')

        def fetch_sector(sym_obj):
            try:
                info = yf.Ticker(f"{sym_obj.symbol}.BK").info or {}
                sector = info.get('sector') or info.get('industry') or 'Unknown'
                return sym_obj, sector
            except Exception:
                return sym_obj, 'Unknown'

        updated = 0
        with ThreadPoolExecutor(max_workers=options['workers']) as ex:
            futures = {ex.submit(fetch_sector, s): s for s in symbols}
            for future in as_completed(futures):
                sym_obj, sector = future.result()
                if sector and sector != sym_obj.sector:
                    sym_obj.sector = sector
                    sym_obj.save(update_fields=['sector'])
                    updated += 1

        self.stdout.write(self.style.SUCCESS(f'Done — updated {updated}/{len(symbols)} sectors'))
