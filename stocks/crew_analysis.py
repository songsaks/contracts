import os
import pandas as pd
import pandas_ta as ta
from crewai import Agent, Task, Crew, Process
from django.conf import settings

# ======================================================================
# CrewAI Stock Analysis System — Minervini/O'Neil Momentum Style
# ======================================================================

class MomentumCrew:
    def __init__(self, symbol):
        self.symbol = symbol
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
        """Fetch comprehensive technical + fundamental + news data via utils."""
        try:
            from .utils import get_stock_data
            data = get_stock_data(self.yf_symbol)
        except Exception:
            data = {}

        history     = data.get('history', pd.DataFrame())
        info        = data.get('info', {})
        news        = data.get('news', [])
        yq          = data.get('yq_data', {})

        if history.empty:
            return {}, [], {}

        # Add ADX(14)
        try:
            adx_df = ta.adx(history['High'], history['Low'], history['Close'], length=14)
            if adx_df is not None and not adx_df.empty:
                history = pd.concat([history, adx_df], axis=1)
        except Exception:
            pass

        # Add EMA50 / EMA200 if missing
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
        technical, news_list, fundamental = self._get_rich_data()

        tech_str  = "\n".join([f"  {k}: {v}" for k, v in technical.items()])
        fund_str  = "\n".join([f"  {k}: {v}" for k, v in fundamental.items()])
        news_str  = (
            "\n".join([f"  - {n.get('title','')}" for n in news_list])
            if news_list else "  (No recent news available)"
        )

        # ── Agents ──────────────────────────────────────────────────────
        technical_analyst = Agent(
            role="Senior Technical Analyst (Minervini/O'Neil Style)",
            goal=f"Analyze price action, momentum, and trend quality for {self.symbol}",
            backstory=(
                "Expert in Stage Analysis, EMA trend structure, RS Rating momentum, "
                "ADX trend strength, and volume/price confirmation. "
                "Follows Minervini VCP and O'Neil CANSLIM methodology."
            ),
            verbose=True,
            allow_delegation=False,
            llm=self.llm_name,
        )

        researcher = Agent(
            role="Market Intelligence Researcher",
            goal=f"Interpret business catalysts, news sentiment and fundamentals for {self.symbol}",
            backstory=(
                "Specialist in reading earnings catalysts, sector rotation themes, "
                "analyst sentiment, and translating news into market impact. "
                "Determines whether the fundamental story supports or contradicts the chart."
            ),
            verbose=True,
            allow_delegation=False,
            llm=self.llm_name,
        )

        risk_manager = Agent(
            role="Trading Risk Manager & Portfolio Strategist",
            goal=f"Create a precise, actionable investment plan for {self.symbol} in Thai language",
            backstory=(
                "Prioritizes capital preservation with strict risk/reward discipline. "
                "Applies Minervini's rule: Stop Loss max 7-8% below entry. "
                "Delivers clear Entry Zone, Stop Loss, and 2 profit targets with R:R ratio."
            ),
            verbose=True,
            allow_delegation=False,
            llm=self.llm_name,
        )

        # ── Tasks ───────────────────────────────────────────────────────
        task_technical = Task(
            description=(
                f"Analyze the technical state of {self.symbol} using this real market data:\n\n"
                f"TECHNICAL DATA:\n{tech_str}\n\n"
                f"Your analysis must cover:\n"
                f"1. Trend Stage (Stage 1 Base / Stage 2 Uptrend / Stage 3 Top / Stage 4 Decline)\n"
                f"2. Momentum quality: RSI zone (>70 overbought, <30 oversold, 50-70 ideal), "
                f"   MACD crossover status (bullish/bearish/divergence)\n"
                f"3. ADX strength: >25 = strong trend, <20 = weak/sideways\n"
                f"4. Volume confirmation: is volume expanding on up-days?\n"
                f"5. Key levels: EMA50/EMA200 as dynamic support/resistance, "
                f"   52-week high as supply zone, 52-week low as downside risk\n"
                f"6. Breakout potential: how far from 52-week high? Is this early or late stage?"
            ),
            expected_output=(
                "A structured technical report: Trend Stage, Momentum quality, "
                "ADX strength, Volume confirmation, Key levels, and Breakout assessment."
            ),
            agent=technical_analyst,
        )

        task_news = Task(
            description=(
                f"Analyze the business context and market sentiment for {self.symbol}.\n\n"
                f"FUNDAMENTAL DATA:\n{fund_str}\n\n"
                f"RECENT NEWS HEADLINES:\n{news_str}\n\n"
                f"Your analysis must cover:\n"
                f"1. What is the primary business catalyst driving this stock? "
                f"   (earnings beat, expansion, sector tailwind, contract win, etc.)\n"
                f"2. Are fundamentals strong? Assess PE vs growth (PEG), ROE, revenue/earnings growth trend\n"
                f"3. Analyst consensus: is target price above or below current price?\n"
                f"4. Overall sentiment: Bullish / Neutral / Bearish — and key reason\n"
                f"5. Any red flags: high PE with no growth, declining ROE, negative news?"
            ),
            expected_output=(
                "Business intelligence report: primary catalyst, fundamental strength assessment, "
                "analyst sentiment, overall verdict (Bullish/Neutral/Bearish), and red flags."
            ),
            agent=researcher,
        )

        task_risk = Task(
            description=(
                f"Synthesize all technical and fundamental analysis to create a complete "
                f"investment plan for {self.symbol}. Write ENTIRELY IN THAI LANGUAGE.\n\n"
                f"รายงานต้องประกอบด้วย:\n"
                f"1. **สรุปภาพรวม**: Bull case คืออะไร / Bear case คืออะไร\n"
                f"2. **คำแนะนำหลัก**: ซื้อ / รอดูก่อน / หลีกเลี่ยง — พร้อมเหตุผล 2-3 ข้อ\n"
                f"3. **จุดซื้อที่เหมาะสม (Entry Zone)**: ระบุช่วงราคา\n"
                f"4. **จุด Stop Loss**: ไม่เกิน 7-8% ต่ำกว่า entry ตาม Minervini rules\n"
                f"5. **เป้าหมายกำไร**: Target 1 (conservative) และ Target 2 (aggressive)\n"
                f"6. **Risk/Reward Ratio**: คำนวณจาก entry, SL, T1\n"
                f"7. **ความเสี่ยงสำคัญ**: ระบุ 2-3 ปัจจัยเสี่ยงที่ต้องติดตาม\n"
                f"8. **ระยะเวลาการลงทุนที่แนะนำ**: Swing (2-8 สัปดาห์) / Position (3-6 เดือน)"
            ),
            expected_output=(
                "แผนการลงทุนภาษาไทยที่ครบถ้วน มีตัวเลข Entry/SL/Target ที่ชัดเจน "
                "R:R ratio และเหตุผลที่อิงจากข้อมูล Technical + Fundamental จริง"
            ),
            agent=risk_manager,
        )

        # ── Crew ────────────────────────────────────────────────────────
        crew = Crew(
            agents=[technical_analyst, researcher, risk_manager],
            tasks=[task_technical, task_news, task_risk],
            process=Process.sequential,
            verbose=True,
        )

        try:
            result = crew.kickoff()
            return str(result)
        except Exception as e:
            return f"Crew execution failed: {str(e)}"
