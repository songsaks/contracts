import os
import pandas as pd
import pandas_ta as ta
from django.conf import settings

# ======================================================================
# CrewAI Stock Analysis System — Minervini/O'Neil Momentum Style
# ======================================================================

class MomentumCrew:
    def __init__(self, symbol, portfolio_context=None):
        """
        portfolio_context (dict, optional): ข้อมูลพอร์ตของผู้ใช้สำหรับหุ้นตัวนี้
          {
            'entry_price':    float,  # ราคาทุนเฉลี่ย
            'quantity':       float,  # จำนวนหุ้น
            'gain_loss_pct':  float,  # % กำไร/ขาดทุน
            'gain_loss':      float,  # กำไร/ขาดทุนเป็นบาท
            'market_value':   float,  # มูลค่าตลาดปัจจุบัน
          }
        """
        self.symbol           = symbol
        self.portfolio_context = portfolio_context or {}
        # Auto-add .BK for SET stocks (no dot, no dash, no =)
        self.yf_symbol = (
            symbol if ('.' in symbol or '=' in symbol or '-' in symbol)
            else f"{symbol}.BK"
        )

        os.environ["GOOGLE_API_KEY"] = settings.GEMINI_API_KEY
        os.environ["GEMINI_API_KEY"] = settings.GEMINI_API_KEY

        self.llm_name = "gemini/gemini-2.5-flash"

    # ------------------------------------------------------------------
    def _get_rich_data(self):
        """Fetch only what's needed — fast path (2 API calls max)."""
        import yfinance as yf

        ticker  = yf.Ticker(self.yf_symbol)
        history = pd.DataFrame()
        info    = {}
        news    = []

        import concurrent.futures

        def _fetch_history():
            return ticker.history(period="6mo")

        def _fetch_info():
            try:
                return ticker.info or {}
            except Exception:
                return {}

        # Run history + info in parallel, each with timeout
        with concurrent.futures.ThreadPoolExecutor(max_workers=2) as ex:
            f_hist = ex.submit(_fetch_history)
            f_info = ex.submit(_fetch_info)
            try:
                history = f_hist.result(timeout=20)
            except Exception:
                history = pd.DataFrame()
            try:
                full_info = f_info.result(timeout=15)
            except Exception:
                full_info = {}

        # fast_info fallback for price if info empty
        try:
            fi = ticker.fast_info
            info = {
                'currentPrice': getattr(fi, 'last_price', None),
                'marketCap':    getattr(fi, 'market_cap', None),
            }
        except Exception:
            info = {}

        for k in ('longName','sector','industry','trailingPE','priceToBook',
                  'returnOnEquity','revenueGrowth','earningsGrowth',
                  'dividendYield','dividendRate','targetMeanPrice','marketCap'):
            if k in full_info:
                val = full_info[k]
                if val is None:
                    info[k] = "N/A"
                    continue
                # Pre-format percentage ratios for AI clarity
                if k in ('dividendYield', 'revenueGrowth', 'earningsGrowth', 'returnOnEquity') and isinstance(val, (int, float)):
                    info[k] = f"{val * 100:.2f}%"
                else:
                    info[k] = val
            else:
                info[k] = "N/A"

        try:
            raw_news = ticker.news or []
            for n in raw_news[:5]:
                c = n.get('content') or n
                title = c.get('title','') if isinstance(c, dict) else n.get('title','')
                if title:
                    news.append({'title': title})
        except Exception:
            pass

        if history.empty:
            return {}, [], {}

        # Flatten MultiIndex columns if present
        if isinstance(history.columns, pd.MultiIndex):
            history.columns = [col[0] for col in history.columns]
        history = history.loc[:, ~history.columns.duplicated()]

        # Add indicators
        try:
            history['RSI'] = ta.rsi(history['Close'], length=14)
        except Exception:
            pass
        try:
            macd = ta.macd(history['Close'])
            if macd is not None and not macd.empty:
                history = pd.concat([history, macd], axis=1)
        except Exception:
            pass
        try:
            adx_df = ta.adx(history['High'], history['Low'], history['Close'], length=14)
            if adx_df is not None and not adx_df.empty:
                history = pd.concat([history, adx_df], axis=1)
        except Exception:
            pass
        if 'EMA_50' not in history.columns:
            history['EMA_50'] = ta.ema(history['Close'], length=50)
        if 'EMA_200' not in history.columns:
            history['EMA_200'] = ta.ema(history['Close'], length=200)

        last = history.iloc[-1]

        def _f(val, dec=2):
            try:
                v = float(val)
                return round(v, dec) if not pd.isna(v) else 'N/A'
            except Exception:
                return 'N/A'

        price      = _f(last['Close'])
        high_52    = _f(history['High'].max())
        low_52     = _f(history['Low'].min())
        pct_from_h = round(((float(price) - float(high_52)) / float(high_52) * 100), 1) if isinstance(price, float) and isinstance(high_52, float) else 'N/A'

        adx_col = next((c for c in history.columns if c.startswith('ADX_')), None)

        price_prev = _f(history['Close'].iloc[-2]) if len(history) > 1 else price
        chg_1d = round(((float(price) - float(price_prev)) / float(price_prev) * 100), 2) if isinstance(price, float) and isinstance(price_prev, float) else 'N/A'

        technical = {
            'Symbol':             self.symbol,
            'Price':              price,
            'Change_1D_%':        chg_1d,
            'Volume_today':       int(last['Volume']) if not pd.isna(last['Volume']) else 0,
            'Volume_avg20':       _f(history['Volume'].tail(20).mean(), 0),
            'Volume_ratio_vs_avg':_f(last['Volume'] / max(float(history['Volume'].mean()), 1)),
            'RSI_14':             _f(last.get('RSI', float('nan'))),
            'MACD':               _f(last.get('MACD_12_26_9', float('nan'))),
            'MACD_Signal':        _f(last.get('MACDs_12_26_9', float('nan'))),
            'EMA_50':             _f(last.get('EMA_50', float('nan'))),
            'EMA_200':            _f(last.get('EMA_200', float('nan'))),
            'ADX_14':             _f(last[adx_col]) if adx_col else 'N/A',
            '52w_High':           high_52,
            '52w_Low':            low_52,
            'Pct_from_52w_High':  pct_from_h,
            'Trend':              (
                'UPTREND (above EMA200)' if (
                    isinstance(price, float) and
                    not pd.isna(last.get('EMA_200', float('nan'))) and
                    price > float(last['EMA_200'])
                ) else 'DOWNTREND / NEUTRAL'
            ),
        }

        fundamental = {
            'Company':             info.get('longName', self.symbol),
            'Sector':              info.get('sector', 'N/A'),
            'Industry':            info.get('industry', 'N/A'),
            'Market_Cap_MTHB':     _f((info.get('marketCap') or 0) / 1e6),
            'PE_Ratio':            _f(info.get('trailingPE')),
            'PBV':                 _f(info.get('priceToBook')),
            'ROE_%':               _f((info.get('returnOnEquity') or 0) * 100),
            'Revenue_Growth_%':    _f((info.get('revenueGrowth') or 0) * 100),
            'Earnings_Growth_%':   _f((info.get('earningsGrowth') or 0) * 100),
            'Dividend_Yield_%':    _f((info.get('dividendYield') or 0) * 100),
            'Analyst_Target_Price':_f(info.get('targetMeanPrice')),
        }

        return technical, news[:6], fundamental

    # ------------------------------------------------------------------
    def run_analysis(self):
        """
        Single Gemini API call — replaces 3-agent CrewAI sequential chain.
        ~3-5x faster: 1 LLM call instead of 3, no agent orchestration overhead.
        """
        technical, news_list, fundamental = self._get_rich_data()

        tech_str = "\n".join([f"  {k}: {v}" for k, v in technical.items()])
        fund_str = "\n".join([f"  {k}: {v}" for k, v in fundamental.items()])
        news_str = (
            "\n".join([f"  - {n.get('title', '')}" for n in news_list])
            if news_list else "  (No recent news available)"
        )

        # ── Portfolio context block ──────────────────────────────────
        pctx = self.portfolio_context
        if pctx.get('entry_price'):
            ep      = pctx['entry_price']
            qty     = pctx.get('quantity', 0)
            gl_pct  = pctx.get('gain_loss_pct', 0)
            gl_thb  = pctx.get('gain_loss', 0)
            mv      = pctx.get('market_value', 0)
            gl_sign = '+' if gl_pct >= 0 else ''
            portfolio_section = f"""

---
## ข้อมูลพอร์ตของนักลงทุน (PORTFOLIO CONTEXT)
- ราคาทุนเฉลี่ย: {ep:.2f} บาท
- จำนวนหุ้น: {qty:,.0f} หุ้น
- มูลค่าปัจจุบัน: {mv:,.0f} บาท
- กำไร/ขาดทุน: {gl_sign}{gl_pct:.1f}% ({gl_sign}{gl_thb:,.0f} บาท)

เนื่องจากนักลงทุนถือหุ้นนี้อยู่แล้ว ให้เพิ่มหัวข้อ "**คำแนะนำสำหรับผู้ถือหุ้น**" ที่ตอบว่า:
- ควรถือต่อ / เพิ่มพอร์ต / ขายทำกำไร / ตัดขาดทุน?
- Stop Loss จากราคาทุน {ep:.2f} บาท ควรอยู่ที่เท่าไหร่?
- R/R จาก Entry {ep:.2f} ไปยัง Target คือเท่าไหร่?
"""
        else:
            portfolio_section = ""

        # ── Single comprehensive prompt ──────────────────────────────
        prompt = f"""You are a senior stock analyst combining Minervini/O'Neil momentum methodology
with fundamental analysis. Analyze {self.symbol} and produce a complete investment report IN THAI LANGUAGE.

## TECHNICAL DATA
{tech_str}

## FUNDAMENTAL DATA
{fund_str}

## RECENT NEWS
{news_str}
{portfolio_section}

---
Write a complete report in Thai with these sections (use markdown headers ##):

## 1. สรุปภาพรวม (Overview)
- Trend Stage: Stage 1/2/3/4
- Bull case และ Bear case

## 2. การวิเคราะห์ทางเทคนิค (Technical Analysis)
- แนวโน้ม EMA50/EMA200
- RSI และ MACD status
- ADX และ Volume confirmation
- ระยะห่างจาก 52-week high

## 3. ปัจจัยพื้นฐานและข่าว (Fundamentals & Sentiment)
- Catalyst หลักที่ขับเคลื่อนหุ้น
- ความแข็งแกร่งของ Fundamental (PE, ROE, Growth)
- Analyst consensus และ target price
- Red flags (ถ้ามี)

## 4. คำแนะนำหลัก (Main Recommendation)
ซื้อ / รอดูก่อน / หลีกเลี่ยง — พร้อมเหตุผล 3 ข้อ

## 5. จุดซื้อที่เหมาะสม (Entry Zone)
- ช่วงราคาที่เหมาะสม พร้อมเหตุผล

## 6. จุด Stop Loss และเป้าหมายกำไร
- Stop Loss: ไม่เกิน 7-8% จาก entry (Minervini rule)
- Target 1 (Conservative): ฿X.XX
- Target 2 (Aggressive): ฿X.XX
- Risk per unit (Entry - SL): ฿X.XX
- R:R Ratio: 1:X.X

## 7. ความเสี่ยงสำคัญ (Key Risks)
ระบุ 3 ปัจจัยเสี่ยงที่ต้องติดตาม

## 8. ระยะเวลาที่แนะนำ
Swing (2-8 สัปดาห์) หรือ Position (3-6 เดือน) — พร้อมเหตุผล

Be specific with numbers. Use actual prices from the data provided."""

        # ── Call Gemini directly via new google-genai SDK ───────────
        try:
            from google import genai as _genai
            from google.genai import types as _gtypes
            import os as _os

            # Ensure only GEMINI_API_KEY is used (suppress GOOGLE_API_KEY conflict)
            _os.environ.pop('GOOGLE_API_KEY', None)

            client = _genai.Client(api_key=settings.GEMINI_API_KEY)
            response = client.models.generate_content(
                model='gemini-2.5-flash',
                contents=prompt,
                config=_gtypes.GenerateContentConfig(
                    temperature=0.4,
                    max_output_tokens=8192,
                ),
            )
            return response.text
        except Exception as e:
            return f"Analysis failed: {str(e)}"
