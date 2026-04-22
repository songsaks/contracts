import time
import datetime
from django.core.management.base import BaseCommand
from stocks.models import TradingAccount, BotActivity, TradeOrder
from stocks.trading_bridge import RobotBridge
import yfinance as yf
import pandas_ta as ta

import pandas as pd

from django.utils import timezone

class Command(BaseCommand):
    help = 'Runs the Gold Trading Robot (Server-Side) 24/7'

    def handle(self, *args, **options):
        self.stdout.write(self.style.SUCCESS('--- Gold Robot Server Engine Started ---'))
        symbol = "GC=F" # Default Gold Futures for stability
        
        while True:
            try:
                # 1. Update Heartbeat
                now = timezone.now()
                activity, created = BotActivity.objects.get_or_create(bot_name="Gold Server Bot")
                activity.status = "ACTIVE"
                activity.message = f"Scanning {symbol} at {now.strftime('%H:%M:%S')}"
                activity.save()

                # 2. Fetch Data
                df = yf.download(symbol, period='1y', interval='1d', progress=False, auto_adjust=True)
                if df.empty:
                    time.sleep(60)
                    continue
                
                # Handle MultiIndex if present
                if isinstance(df.columns, pd.MultiIndex):
                    df.columns = df.columns.get_level_values(0)

                # 3. Compute Professional Indicators
                df['dc20_upper'] = df['High'].rolling(20).max()
                df['ema200'] = ta.ema(df['Close'], length=200)
                df['rsi'] = ta.rsi(df['Close'], length=14)
                df['atr'] = ta.atr(df['High'], df['Low'], df['Close'], length=20)
                
                df = df.dropna(subset=['dc20_upper', 'ema200', 'rsi'])
                
                last_price = float(df['Close'].iloc[-1])
                upper20 = float(df['dc20_upper'].iloc[-2]) 
                last_ema200 = float(df['ema200'].iloc[-1])
                last_rsi = float(df['rsi'].iloc[-1])
                last_atr = float(df['atr'].iloc[-1])
                
                # 4. Smart Signal Logic
                is_breakout = last_price >= upper20
                is_uptrend = last_price > last_ema200
                is_not_overbought = last_rsi < 70
                
                should_buy = is_breakout and is_uptrend and is_not_overbought
                
                status_msg = f"Price: {last_price:.2f} | EMA200: {last_ema200:.2f} | RSI: {last_rsi:.1f}"
                self.stdout.write(self.style.NOTICE(status_msg))

                if should_buy:
                    self.stdout.write(self.style.WARNING(f"BULLISH SIGNAL: All filters passed!"))
                    
                    # 5. Execute Trade for ALL active trading accounts
                    accounts = TradingAccount.objects.filter(is_active=True)
                    for acc in accounts:
                        # Check if we already traded today
                        today = datetime.date.today()
                        existing = TradeOrder.objects.filter(
                            account=acc, 
                            symbol=symbol, 
                            created_at__date=today,
                            strategy__icontains="Turtle Pro"
                        ).exists()

                        if not existing:
                            self.stdout.write(self.style.SUCCESS(f"Executing Trade for Account: {acc.account_id}"))
                            bridge = RobotBridge(acc)
                            
                            # Calculate SL based on 2x ATR
                            sl_price = last_price - (2 * last_atr)
                            
                            res = bridge.execute_market_order(
                                symbol, "BUY", 0.01, 
                                comment=f"Turtle Pro (RSI:{last_rsi:.0f})",
                                stop_loss=sl_price
                            )
                            
                            activity.message = f"EXECUTED BUY 0.01 {symbol} @ {last_price:.2f} (SL: {sl_price:.2f})"
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

            # Wait 30 seconds for next cycle
            time.sleep(30)
