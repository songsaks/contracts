import os
import time
import datetime
import pandas as pd
import pandas_ta as ta
import yfinance as yf
from django.core.management.base import BaseCommand
from django.utils import timezone
from stocks.models import TradingAccount, TradeOrder, BotActivity
from stocks.trading_bridge import RobotBridge

class Command(BaseCommand):
    help = 'Run Gold Trading Bot with Multi-Strategy (Sniper/Scalper/Swing)'

    SYMBOL = "GC=F" # Gold Futures for Data
    BROKER_SYMBOL = "XAUUSD" # For MetaApi
    RISK_PER_TRADE = 0.02 # 2% per trade
    MIN_LOT = 0.01

    def update_heartbeat(self, status="ACTIVE", message=""):
        BotActivity.objects.update_or_create(
            bot_name="Gold Server Bot",
            defaults={
                'status': status,
                'last_heartbeat': timezone.now(),
                'message': message
            }
        )

    def handle(self, *args, **options):
        self.stdout.write(self.style.SUCCESS(f'--- Gold Robot [COMMANDER] Started (Risk: {self.RISK_PER_TRADE*100}%) ---'))
        
        try:
            self.update_heartbeat(status="ACTIVE", message="Bot starting up...")
            
            while True:
                try:
                    # 1. Fetch Data
                    df = yf.download(self.SYMBOL, period='1y', interval='1d', progress=False, auto_adjust=True, timeout=15)
                    if df.empty:
                        self.update_heartbeat(status="ACTIVE", message="Waiting for data from Yahoo...")
                        time.sleep(30)
                        continue
                    
                    if isinstance(df.columns, pd.MultiIndex): 
                        df.columns = df.columns.get_level_values(0)

                    # 2. Indicators
                    df['dc10_upper'] = df['High'].rolling(10).max()
                    df['dc20_upper'] = df['High'].rolling(20).max()
                    df['ema9'] = ta.ema(df['Close'], length=9)
                    df['ema200'] = ta.ema(df['Close'], length=200)
                    df['rsi'] = ta.rsi(df['Close'], length=14)
                    df['atr'] = ta.atr(df['High'], df['Low'], df['Close'], length=20)
                    
                    df = df.dropna()
                    if df.empty:
                        time.sleep(30)
                        continue

                    last_row, prev_row = df.iloc[-1], df.iloc[-2]
                    
                    curr_price = float(last_row['Close'])
                    upper10 = float(prev_row['dc10_upper'])
                    upper20 = float(prev_row['dc20_upper'])
                    ema9 = float(last_row['ema9'])
                    ema200 = float(last_row['ema200'])
                    rsi = float(last_row['rsi'])
                    atr = float(last_row['atr'])
                    
                    # 3. Strategy Logic (Long Only)
                    # A: SNIPER (EMA9 Crossover)
                    sn_buy = curr_price >= ema9 and prev_row['Close'] < prev_row['ema9'] and curr_price > ema200
                    
                    # B: SCALPER (10D High Breakout)
                    sc_buy = curr_price >= upper10 and rsi > 50 and curr_price > ema9
                    
                    # C: SWING (20D High Breakout)
                    sw_buy = curr_price >= upper20 and rsi < 70 and curr_price > ema200

                    signal_type = None
                    if sw_buy: signal_type = "SWING_20D"
                    elif sc_buy: signal_type = "SCALPER_10D"
                    elif sn_buy: signal_type = "SNIPER_EMA9"

                    if signal_type:
                        self.stdout.write(self.style.WARNING(f"SIGNAL: {signal_type} DETECTED @ {curr_price}"))
                        
                        # Execute for all active accounts
                        accounts = TradingAccount.objects.filter(is_active=True)
                        for acc in accounts:
                            # Prevent multiple trades same day same strategy
                            today = datetime.date.today()
                            already_traded = TradeOrder.objects.filter(
                                user=acc.user, symbol=self.BROKER_SYMBOL, 
                                created_at__date=today, strategy__icontains=signal_type
                            ).exists()

                            if not already_traded:
                                bridge = RobotBridge(user=acc.user)
                                balance = float(acc.balance) if acc.balance > 0 else 1000.0
                                risk_amount = balance * self.RISK_PER_TRADE
                                
                                # Set SL based on strategy
                                if signal_type == "SNIPER_EMA9": sl_mult = 0.5
                                elif signal_type == "SCALPER_10D": sl_mult = 1.0
                                else: sl_mult = 1.5
                                
                                sl_dist = sl_mult * atr
                                lots = round(max(self.MIN_LOT, risk_amount / sl_dist if sl_dist > 0 else self.MIN_LOT), 2)
                                sl_price = curr_price - sl_dist
                                
                                self.stdout.write(self.style.SUCCESS(f"Executing {signal_type} for {acc.account_name}"))
                                res = bridge.execute_trade(
                                    symbol=self.BROKER_SYMBOL, side="BUY", volume=lots,
                                    strategy=signal_type, stop_loss=sl_price
                                )
                                
                                self.update_heartbeat(status="ACTIVE", message=f"TRADE: {signal_type} BUY {lots} @ {curr_price}")
                    else:
                        self.update_heartbeat(status="ACTIVE", message=f"Watching... Price: {curr_price:.2f} | EMA9: {ema9:.2f}")

                except Exception as e:
                    import traceback
                    error_msg = f"ERROR: {str(e)}\n{traceback.format_exc()}"
                    self.stdout.write(self.style.ERROR(error_msg))
                    self.update_heartbeat(status="ERROR", message=str(e)[:200])
                    time.sleep(30)

                time.sleep(60)
                
        except Exception as e:
            self.stdout.write(self.style.ERROR(f"FATAL: {str(e)}"))
            self.update_heartbeat(status="ERROR", message=f"FATAL: {str(e)}")
