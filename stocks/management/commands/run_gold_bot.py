import time
import datetime
from django.core.management.base import BaseCommand
from stocks.models import TradingAccount, BotActivity, TradeOrder
from stocks.trading_bridge import RobotBridge
import yfinance as yf
import pandas_ta as ta
import pandas as pd
from django.utils import timezone
from decimal import Decimal

class Command(BaseCommand):
    help = 'Runs the Gold Trading Robot with Multi-Strategy (Sniper/Scalper/Swing)'

    # --- SETTINGS ---
    RISK_PER_TRADE = 0.01  
    MIN_LOT = 0.01        
    SYMBOL = "GC=F"       
    BROKER_SYMBOL = "XAUUSD" 

    def handle(self, *args, **options):
        self.stdout.write(self.style.SUCCESS(f'--- Gold Robot [COMMANDER] Started (Risk: {self.RISK_PER_TRADE*100}%) ---'))
        
        while True:
            try:
                # 1. Heartbeat
                activity, created = BotActivity.objects.get_or_create(bot_name="Gold Server Bot")
                activity.status = "ACTIVE"
                activity.save()

                # 2. Fetch Data
                df = yf.download(self.SYMBOL, period='1y', interval='1d', progress=False, auto_adjust=True, timeout=15)
                if df.empty:
                    time.sleep(30)
                    continue
                if isinstance(df.columns, pd.MultiIndex): df.columns = df.columns.get_level_values(0)

                # 3. Indicators
                df['dc10_upper'] = df['High'].rolling(10).max()
                df['dc20_upper'] = df['High'].rolling(20).max()
                df['ema9'] = ta.ema(df['Close'], length=9)
                df['ema200'] = ta.ema(df['Close'], length=200)
                df['rsi'] = ta.rsi(df['Close'], length=14)
                df['atr'] = ta.atr(df['High'], df['Low'], df['Close'], length=20)
                
                df = df.dropna()
                last_row, prev_row = df.iloc[-1], df.iloc[-2]
                
                curr_price = float(last_row['Close'])
                upper10 = float(prev_row['dc10_upper'])
                upper20 = float(prev_row['dc20_upper'])
                ema9 = float(last_row['ema9'])
                ema200 = float(last_row['ema200'])
                rsi = float(last_row['rsi'])
                atr = float(last_row['atr'])
                
                # 4. Multi-Strategy Logic
                # A: SNIPER (Ultra-fast reversal)
                sn_buy = curr_price >= ema9 and rsi > 45 and curr_price > ema200
                
                # B: SCALPER (Short-term breakout)
                sc_buy = curr_price >= upper10 and rsi > 50 and curr_price > ema9
                
                # C: SWING (Medium-term trend)
                sw_buy = curr_price >= upper20 and rsi < 70 and curr_price > ema200

                # Priority: Sniper is fastest, but Swing is most reliable.
                # If we want aggressive, we pick the first one that hits.
                signal_type = None
                if sc_buy: signal_type = "SCALPER_10D"
                elif sn_buy: signal_type = "SNIPER_EMA9"
                elif sw_buy: signal_type = "SWING_20D"

                if signal_type:
                    self.stdout.write(self.style.WARNING(f"SIGNAL: {signal_type} DETECTED @ {curr_price}"))
                    
                    accounts = TradingAccount.objects.filter(is_active=True)
                    for acc in accounts:
                        today = datetime.date.today()
                        already_traded = TradeOrder.objects.filter(
                            account=acc, symbol=self.BROKER_SYMBOL, 
                            created_at__date=today, strategy__icontains=signal_type
                        ).exists()

                        if not already_traded:
                            bridge = RobotBridge(acc)
                            balance = float(acc.balance) if acc.balance > 0 else 1000.0
                            risk_amount = balance * self.RISK_PER_TRADE
                            
                            # SL Management
                            if signal_type == "SNIPER_EMA9": sl_mult = 0.5 # Very tight
                            elif signal_type == "SCALPER_10D": sl_mult = 1.0
                            else: sl_mult = 2.0
                            
                            sl_distance = sl_mult * atr
                            suggested_lots = risk_amount / sl_distance if sl_distance > 0 else self.MIN_LOT
                            final_lots = round(max(self.MIN_LOT, min(suggested_lots, 1.0)), 2)
                            sl_price = curr_price - sl_distance
                            
                            self.stdout.write(self.style.SUCCESS(f"Executing {signal_type}: {final_lots} Lots"))

                            res = bridge.execute_market_order(
                                self.BROKER_SYMBOL, "BUY", final_lots, 
                                comment=f"Robot:{signal_type}",
                                stop_loss=sl_price
                            )
                            
                            activity.message = f"EXEC: {signal_type} BUY {final_lots} @ {curr_price:.2f}"
                            activity.save()

                else:
                    activity.message = f"Watching... Price: {curr_price:.2f} | EMA9: {ema9:.2f}"
                    activity.save()

            except Exception as e:
                self.stdout.write(self.style.ERROR(f"ERROR: {str(e)}"))
                if 'activity' in locals():
                    activity.status = "ERROR"
                    activity.message = str(e)[:200]
                    activity.save()

            time.sleep(30)
