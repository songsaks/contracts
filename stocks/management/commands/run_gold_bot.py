import time
import datetime
from django.core.management.base import BaseCommand
from stocks.models import TradingAccount, BotActivity, TradeOrder
from stocks.trading_bridge import RobotBridge
import yfinance as yf
import pandas_ta as ta

import pandas as pd

class Command(BaseCommand):
    help = 'Runs the Gold Trading Robot (Server-Side) 24/7'

    def handle(self, *args, **options):
        self.stdout.write(self.style.SUCCESS('--- Gold Robot Server Engine Started ---'))
        symbol = "GC=F" # Default Gold Futures for stability
        
        while True:
            try:
                # 1. Update Heartbeat
                activity, created = BotActivity.objects.get_or_create(bot_name="Gold Server Bot")
                activity.status = "ACTIVE"
                activity.message = f"Scanning {symbol} at {datetime.datetime.now().strftime('%H:%M:%S')}"
                activity.save()

                # 2. Fetch Data
                df = yf.download(symbol, period='1y', interval='1d', progress=False, auto_adjust=True)
                if df.empty:
                    time.sleep(60)
                    continue
                
                # Handle MultiIndex if present
                if isinstance(df.columns, pd.MultiIndex):
                    df.columns = df.columns.get_level_values(0)

                # 3. Compute Turtle Logic
                df['dc20_upper'] = df['High'].rolling(20).max()
                df = df.dropna(subset=['dc20_upper'])
                
                last_price = float(df['Close'].iloc[-1])
                upper20 = float(df['dc20_upper'].iloc[-2]) 
                
                # 4. Check for Breakout
                if last_price >= upper20:
                    self.stdout.write(self.style.WARNING(f"BREAKOUT DETECTED: {last_price} >= {upper20}"))
                    
                    # 5. Execute Trade for ALL active trading accounts
                    accounts = TradingAccount.objects.filter(is_active=True)
                    for acc in accounts:
                        # Check if we already traded today for this symbol
                        today = datetime.date.today()
                        existing = TradeOrder.objects.filter(
                            account=acc, 
                            symbol=symbol, 
                            created_at__date=today,
                            strategy__icontains="Turtle (Server)"
                        ).exists()

                        if not existing:
                            self.stdout.write(self.style.SUCCESS(f"Executing Trade for Account: {acc.account_id}"))
                            bridge = RobotBridge(acc)
                            # Minimal lot 0.01 for safety
                            res = bridge.execute_market_order(symbol, "BUY", 0.01, comment="Turtle (Server Bot)")
                            
                            activity.message = f"EXECUTED BUY 0.01 {symbol} @ {last_price} for Account {acc.account_id}"
                            activity.save()
                        else:
                            self.stdout.write(self.style.NOTICE(f"Trade already exists for {acc.account_id} today."))

                else:
                    self.stdout.write(self.style.NOTICE(f"Price: {last_price} | Breakout At: {upper20} | Status: Neutral"))

            except Exception as e:
                self.stdout.write(self.style.ERROR(f"ERROR: {str(e)}"))
                if 'activity' in locals():
                    activity.status = "ERROR"
                    activity.message = str(e)
                    activity.save()

            # Wait 60 seconds for next cycle
            time.sleep(60)
