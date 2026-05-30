import os
import concurrent.futures
import pandas as pd
import pandas_ta as ta
import yfinance as yf
from yahooquery import Ticker as YQTicker
from django.conf import settings


# ======================================================================
# MomentumShortTermCrew — CrewAI Multi-Agent (Short-Term Focus)
# ======================================================================

class MomentumShortTermCrew:
    """
    CrewAI 3-agent analysis for short-term momentum trading (2-6 weeks).

    Agents:
      1. Short-Term Momentum Technician  — Breakout quality, entry timing
      2. Risk & Entry Expert             — ATR stop, exact prices, R:R
      3. Smart Money & Catalyst Scout    — Volume flow, sector, catalyst + final verdict

    Uses pre-computed scan_data from MomentumCandidate to avoid redundant fetches,
    then fetches only minimal extra data (MACD, BB, momentum %, news).
    """

    def __init__(self, symbol, scan_data=None, market='SET'):
        self.symbol    = symbol
        self.market    = market
        self.scan_data = scan_data or {}
        
        self.benchmark_name = "SET Index" if market == 'SET' else "S&P 500 / Nasdaq"
        self.currency       = "บาท" if market == 'SET' else "USD"
        self.curr_sym       = "฿" if market == 'SET' else "$"

        if self.market == 'US':
            self.yf_symbol = symbol
        else:
            self.yf_symbol = (
                symbol if ('.' in symbol or '=' in symbol or '-' in symbol)
                else f"{symbol}.BK"
            )
        os.environ["GEMINI_API_KEY"] = settings.GEMINI_API_KEY

    # ------------------------------------------------------------------
    def _get_extra_data(self):
        """Fetch lightweight extra data: MACD, BB position, momentum %, news."""
        try:
            ticker = yf.Ticker(self.yf_symbol)
            hist   = ticker.history(period="3mo")
            if hist.empty:
                return {}

            if isinstance(hist.columns, pd.MultiIndex):
                hist.columns = [col[0] for col in hist.columns]
            hist   = hist.loc[:, ~hist.columns.duplicated()]
            closes = hist['Close'].dropna()
            n      = len(closes)
            result = {}

            # MACD
            try:
                macd_df = ta.macd(closes)
                if macd_df is not None and not macd_df.empty:
                    m_col = next((c for c in macd_df.columns if c.startswith('MACD_') and 'MACDs' not in c and 'MACDh' not in c), None)
                    s_col = next((c for c in macd_df.columns if c.startswith('MACDs_')), None)
                    if m_col and s_col:
                        mv = float(macd_df[m_col].iloc[-1])
                        sv = float(macd_df[s_col].iloc[-1])
                        if not (pd.isna(mv) or pd.isna(sv)):
                            result['macd']         = round(mv, 3)
                            result['macd_signal']  = round(sv, 3)
                            result['macd_bullish'] = mv > sv
            except Exception:
                pass

            # Bollinger Band %B position
            try:
                bb_df = ta.bbands(closes, length=20, std=2)
                if bb_df is not None and not bb_df.empty:
                    u = next((c for c in bb_df.columns if 'BBU' in c), None)
                    l = next((c for c in bb_df.columns if 'BBL' in c), None)
                    if u and l:
                        price = float(closes.iloc[-1])
                        bbu   = float(bb_df[u].iloc[-1])
                        bbl   = float(bb_df[l].iloc[-1])
                        if bbu > bbl:
                            result['bb_position'] = round((price - bbl) / (bbu - bbl) * 100, 1)
            except Exception:
                pass

            # Short-term momentum
            if n >= 22:
                result['momentum_1m'] = round(
                    (closes.iloc[-1] - closes.iloc[-22]) / closes.iloc[-22] * 100, 1)
            if n >= min(n, 66):
                result['momentum_3m'] = round(
                    (closes.iloc[-1] - closes.iloc[-min(n, 66)]) / closes.iloc[-min(n, 66)] * 100, 1)

            # Volume acceleration (5-day vs 20-day)
            vols = hist['Volume'].dropna()
            if len(vols) >= 20:
                v5  = float(vols.tail(5).mean())
                v20 = float(vols.tail(20).mean())
                result['vol_5v20'] = round(v5 / v20, 2) if v20 > 0 else 1.0

            # Recent news headlines
            result['news'] = []
            try:
                raw_news = ticker.news or []
                for n_item in raw_news[:4]:
                    c     = n_item.get('content') or n_item
                    title = c.get('title', '') if isinstance(c, dict) else n_item.get('title', '')
                    if title:
                        result['news'].append(title)
            except Exception:
                pass

            return result
        except Exception:
            return {}

    # ------------------------------------------------------------------
    def run_analysis(self):
        """
        Run CrewAI sequential 3-agent analysis.
        Returns a combined markdown string (Thai language).
        """
        from crewai import Agent, Task, Crew, Process
        from crewai.llm import LLM

        llm   = LLM(model="gemini/gemini-2.5-flash", api_key=settings.GEMINI_API_KEY)
        extra = self._get_extra_data()
        sd    = self.scan_data

        # ── Build shared context block ────────────────────────────────
        news_text = '; '.join(extra.get('news', [])) or 'ไม่มีข้อมูล'
        context = f"""
หุ้น: {self.symbol}
ราคาปัจจุบัน: {sd.get('price', 'N/A')} {self.currency}
Technical Score: {sd.get('technical_score', 'N/A')}/100
Relative Strength vs {self.benchmark_name}: {sd.get('rs_rating', 'N/A')}
ADX (14): {sd.get('adx', 'N/A')}
MFI (14): {sd.get('mfi', 'N/A')}
RVOL: {sd.get('rvol', 'N/A')}x
CMF (Chaikin Money Flow): {sd.get('cmf', 'N/A')}
Volume Surge: {sd.get('volume_surge', 'N/A')}

Demand Zone: {sd.get('demand_zone_end', 'N/A')} – {sd.get('demand_zone_start', 'N/A')} บาท
Supply Zone: {sd.get('supply_zone_end', 'N/A')} – {sd.get('supply_zone_start', 'N/A')} บาท
Risk/Reward Ratio: 1:{sd.get('risk_reward_ratio', 'N/A')}
Zone Proximity: {sd.get('zone_proximity', 'N/A')}% ห่างจาก Demand Zone

EPS Growth: {sd.get('eps_growth', 'N/A')}%
Revenue Growth: {sd.get('rev_growth', 'N/A')}%
Sector: {sd.get('sector', 'N/A')}
52W High: {sd.get('year_high', 'N/A')} บาท  |  Upside to High: {sd.get('upside_to_high', 'N/A')}%

MACD: {extra.get('macd', 'N/A')} (Signal: {extra.get('macd_signal', 'N/A')}) → {'🟢 Bullish Cross' if extra.get('macd_bullish') else '🔴 Bearish / Below Signal'}
Bollinger Band Position: {extra.get('bb_position', 'N/A')}%  (0%=Lower Band, 100%=Upper Band)
Momentum 1M: {extra.get('momentum_1m', 'N/A')}%
Momentum 3M: {extra.get('momentum_3m', 'N/A')}%
Volume Acceleration (5d/20d): {extra.get('vol_5v20', 'N/A')}x
ข่าวล่าสุด: {news_text}
"""

        # ── Agent 1 : Short-Term Momentum Technician ──────────────────
        technician = Agent(
            role="Short-Term Momentum Technical Analyst",
            goal=(
                "วิเคราะห์คุณภาพ Breakout/Momentum ระยะสั้น 2-6 สัปดาห์ "
                "และหาจังหวะ Entry ที่มีความเสี่ยงต่ำที่สุด"
            ),
            backstory=(
                "คุณเป็นนักวิเคราะห์เทคนิคผู้เชี่ยวชาญด้าน Short-term Momentum Trading "
                "ตามแนวทาง Mark Minervini (SEPA) และ William O'Neil (CAN SLIM) "
                "เชี่ยวชาญการอ่านสัญญาณ Breakout, VCP (Volatility Contraction Pattern), "
                "Price-Volume relationship, และ Stage Analysis "
                "คุณมองหาหุ้นที่มีคุณภาพ Breakout สูง เข้าใกล้ Base ต่ำสุด ความเสี่ยงต่ำ"
            ),
            llm=llm,
            verbose=False,
            allow_delegation=False,
        )

        # ── Agent 2 : Risk & Entry Specialist ────────────────────────
        risk_expert = Agent(
            role="Risk Management & Precision Entry Expert",
            goal=(
                "คำนวณจุด Entry ที่แม่นยำ, Stop Loss ตาม ATR และ Demand Zone, "
                "พร้อม R:R ≥ 2:1 สำหรับ Short-term Trade"
            ),
            backstory=(
                "คุณเป็นผู้เชี่ยวชาญด้าน Risk Management ระดับ Professional "
                "ใช้ ATR-based stop loss, Supply & Demand Zone, และ Fibonacci Retracement "
                "เพื่อกำหนด Entry/Stop/Target ที่แม่นยำ "
                "กฎหลัก: Stop Loss ห้ามเกิน 7-8% จาก Entry, R:R ≥ 2:1 ทุก Trade "
                "และคำนวณ Position Size จากพอร์ต 100,000 บาท Risk 1% ต่อ Trade"
            ),
            llm=llm,
            verbose=False,
            allow_delegation=False,
        )

        # ── Agent 3 : Smart Money & Catalyst Scout ───────────────────
        catalyst_scout = Agent(
            role="Smart Money Flow & Catalyst Scout",
            goal=(
                "ตรวจสอบ Institutional Volume, Sector Rotation, และ Catalyst "
                "ที่จะขับเคลื่อนราคาในระยะ 2-6 สัปดาห์ พร้อมสรุป Final Verdict"
            ),
            backstory=(
                "คุณเป็นผู้เชี่ยวชาญด้านการอ่านเงิน Smart Money, Sector Rotation "
                "และการหา Catalyst ที่ซ่อนอยู่ "
                "เชี่ยวชาญ Volume Accumulation vs Distribution, Relative Strength vs SET Index "
                "คุณอ่าน RVOL, Volume Surge และ CMF (Chaikin Money Flow) เพื่อบอกว่าเงินใหญ่กำลังสะสมหรือกระจายหุ้น "
                "และสรุป Final Verdict ที่ชัดเจน Action-oriented พร้อมเหตุผล"
            ),
            llm=llm,
            verbose=False,
            allow_delegation=False,
        )

        # ── Task 1 ────────────────────────────────────────────────────
        task1 = Task(
            description=f"""วิเคราะห์คุณภาพ Momentum ระยะสั้นของ {self.symbol}:

{context}

เขียนรายงานเป็นภาษาไทย ครอบคลุม:
1. **Stage Analysis**: หุ้นอยู่ใน Stage 1/2/3/4? (Stage 2 = Uptrend เท่านั้น)
2. **Breakout Quality**: กำลัง Breakout ใหม่ / Consolidating หลัง Breakout / Pullback to Support?
3. **Momentum Strength**: RSI {sd.get('rsi','N/A')}, ADX {sd.get('adx','N/A')}, MACD, Momentum 1M/3M บ่งชี้ว่าอะไร?
4. **Entry Timing**: ตอนนี้เข้าซื้อได้เลย / รอ Pullback ไป Demand Zone / ยังไม่ถึงเวลา?
5. **Breakout Score**: 0-100 พร้อมเหตุผลสั้นๆ""",
            agent=technician,
            expected_output="รายงาน Technical ระยะสั้น 5 หัวข้อ ภาษาไทย กระชับชัดเจน"
        )

        # ── Task 2 ────────────────────────────────────────────────────
        task2 = Task(
            description=f"""คำนวณ Risk Management สำหรับ {self.symbol}:

{context}

เขียนตาราง Risk Management เป็นภาษาไทย:
1. **Best Entry Zone**: ช่วงราคาเข้าที่ดีที่สุด (อ้างอิง Demand Zone และ Context จาก Agent 1)
2. **Stop Loss**: คำนวณจาก Demand Zone ล่างสุด — ห้ามเกิน 7-8% จาก Entry
3. **Target 1 (Conservative)**: {self.curr_sym}X.XX
4. **Target 2 (Aggressive)**: {self.curr_sym}X.XX
5. **Position Size**: พอร์ต {('100,000 บาท' if self.market == 'SET' else '$10,000 USD')} Risk 1% → ซื้อกี่หุ้น?
6. **สรุป R:R**: Entry {self.curr_sym}___ → Stop {self.curr_sym}___ → Target {self.curr_sym}___ = R:R 1:___""",
            agent=risk_expert,
            expected_output="ตาราง Risk Management ชัดเจน ระบุราคาตัวเลขครบทุกจุด"
        )

        # ── Task 3 ────────────────────────────────────────────────────
        task3 = Task(
            description=f"""วิเคราะห์ Smart Money และสรุปขั้นสุดท้ายสำหรับ {self.symbol}:

{context}

เขียนรายงานสุดท้ายเป็นภาษาไทย:
1. **Smart Money Signal**: RVOL {sd.get('rvol','N/A')}x, Volume Surge {sd.get('volume_surge','N/A')}, CMF {sd.get('cmf','N/A')}, และ Volume 5d/20d = {extra.get('vol_5v20','N/A')}x → เงินใหญ่สะสม หรือกระจายหุ้น?
2. **Sector Momentum**: Sector {sd.get('sector','N/A')} ตอนนี้ร้อนแรงหรืออ่อนแรง?
3. **Catalyst**: Catalyst อะไรที่อาจขับเคลื่อนราคาใน 2-6 สัปดาห์ข้างหน้า? (EPS Growth {sd.get('eps_growth','N/A')}%, Rev Growth {sd.get('rev_growth','N/A')}%)
4. **⚠️ Key Risks**: 3 ปัจจัยเสี่ยงสำคัญ
5. **🎯 FINAL VERDICT**:
   - **BUY NOW** / **WAIT FOR PULLBACK** / **AVOID** — เลือก 1 อย่างชัดเจน
   - เหตุผล 3 ข้อหลัก (Technical + Smart Money + Catalyst)
   - ระยะเวลาที่คาดหวัง: __ สัปดาห์""",
            agent=catalyst_scout,
            expected_output="รายงาน Smart Money + Final Verdict ชัดเจน Action-oriented"
        )

        crew = Crew(
            agents=[technician, risk_expert, catalyst_scout],
            tasks=[task1, task2, task3],
            process=Process.sequential,
            verbose=False,
        )

        result = crew.kickoff()
        return str(result)


# ======================================================================
# USMomentumShortTermCrew — CrewAI Multi-Agent (US Market Focus)
# ======================================================================

class USMomentumShortTermCrew:
    """
    CrewAI 3-agent analysis for short-term US momentum trading (1-4 weeks).
    Agents:
      1. US Technical Momentum Analyst   — Stage 2, RS Rating, Breakout quality
      2. US Risk & Entry Specialist      — ATR stop, position sizing in USD, R:R
      3. US Market Context Scout         — Fed policy, sector rotation, earnings catalyst + verdict
    """

    def __init__(self, symbol, scan_data=None):
        self.symbol    = symbol
        self.scan_data = scan_data or {}
        os.environ["GEMINI_API_KEY"] = settings.GEMINI_API_KEY

    # ------------------------------------------------------------------
    def _get_extra_data(self):
        """Fetch lightweight extra: MACD, BB, momentum vs SPY, news."""
        try:
            import concurrent.futures as _cf

            ticker = yf.Ticker(self.symbol)
            spy_t  = yf.Ticker("SPY")

            def _hist():
                return ticker.history(period="3mo")

            def _spy():
                return spy_t.history(period="3mo")

            hist = spy_hist = pd.DataFrame()
            with _cf.ThreadPoolExecutor(max_workers=2) as ex:
                fh = ex.submit(_hist)
                fs = ex.submit(_spy)
                hist     = fh.result(timeout=20)
                spy_hist = fs.result(timeout=20)

            if hist.empty:
                return {}

            if isinstance(hist.columns, pd.MultiIndex):
                hist.columns = [col[0] for col in hist.columns]
            hist = hist.loc[:, ~hist.columns.duplicated()]
            closes = hist['Close'].dropna()
            n = len(closes)
            result = {}

            # MACD
            try:
                macd_df = ta.macd(closes)
                if macd_df is not None and not macd_df.empty:
                    m_col = next((c for c in macd_df.columns if c.startswith('MACD_') and 'MACDs' not in c and 'MACDh' not in c), None)
                    s_col = next((c for c in macd_df.columns if c.startswith('MACDs_')), None)
                    if m_col and s_col:
                        mv = float(macd_df[m_col].iloc[-1])
                        sv = float(macd_df[s_col].iloc[-1])
                        if not (pd.isna(mv) or pd.isna(sv)):
                            result['macd']         = round(mv, 3)
                            result['macd_signal']  = round(sv, 3)
                            result['macd_bullish'] = mv > sv
            except Exception:
                pass

            # Bollinger Band %B
            try:
                bb_df = ta.bbands(closes, length=20, std=2)
                if bb_df is not None and not bb_df.empty:
                    u = next((c for c in bb_df.columns if 'BBU' in c), None)
                    l = next((c for c in bb_df.columns if 'BBL' in c), None)
                    if u and l:
                        price = float(closes.iloc[-1])
                        bbu   = float(bb_df[u].iloc[-1])
                        bbl   = float(bb_df[l].iloc[-1])
                        if bbu > bbl:
                            result['bb_position'] = round((price - bbl) / (bbu - bbl) * 100, 1)
            except Exception:
                pass

            # Momentum vs SPY
            if n >= 22:
                result['momentum_1m'] = round((closes.iloc[-1] - closes.iloc[-22]) / closes.iloc[-22] * 100, 1)
            if n >= min(n, 66):
                result['momentum_3m'] = round((closes.iloc[-1] - closes.iloc[-min(n, 66)]) / closes.iloc[-min(n, 66)] * 100, 1)

            # SPY comparison
            if not spy_hist.empty:
                if isinstance(spy_hist.columns, pd.MultiIndex):
                    spy_hist.columns = [col[0] for col in spy_hist.columns]
                sc = spy_hist['Close'].dropna()
                if len(sc) >= 22 and n >= 22:
                    result['spy_1m'] = round((sc.iloc[-1] - sc.iloc[-22]) / sc.iloc[-22] * 100, 1)
                    result['rel_strength_1m'] = round(result['momentum_1m'] - result['spy_1m'], 1)

            # Volume acceleration
            vols = hist['Volume'].dropna()
            if len(vols) >= 20:
                v5  = float(vols.tail(5).mean())
                v20 = float(vols.tail(20).mean())
                result['vol_5v20'] = round(v5 / v20, 2) if v20 > 0 else 1.0

            # News
            result['news'] = []
            try:
                raw_news = ticker.news or []
                for n_item in raw_news[:4]:
                    c     = n_item.get('content') or n_item
                    title = c.get('title', '') if isinstance(c, dict) else n_item.get('title', '')
                    if title:
                        result['news'].append(title)
            except Exception:
                pass

            return result
        except Exception:
            return {}

    # ------------------------------------------------------------------
    def run_analysis(self):
        """Run CrewAI sequential 3-agent analysis for US market. Returns markdown (Thai)."""
        from crewai import Agent, Task, Crew, Process
        from crewai.llm import LLM

        llm   = LLM(model="gemini/gemini-2.5-flash", api_key=settings.GEMINI_API_KEY)
        extra = self._get_extra_data()
        sd    = self.scan_data

        news_text = '; '.join(extra.get('news', [])) or 'No recent news'
        macd_status = '🟢 Bullish Cross' if extra.get('macd_bullish') else ('🔴 Bearish' if extra.get('macd_bullish') is False else 'N/A')
        rel_str = f"{extra.get('rel_strength_1m', 'N/A'):+.1f}% vs SPY" if isinstance(extra.get('rel_strength_1m'), (int, float)) else 'N/A'

        context = f"""
Stock: {self.symbol}
Current Price: ${sd.get('price', 'N/A')}
Technical Score: {sd.get('technical_score', 'N/A')}/100
RS Rating (vs Nasdaq/S&P): {sd.get('rs_rating', 'N/A')}/99
Stage 2 (Weinstein): {'✅ YES' if sd.get('stage2') else '❌ NO'}
MACD Crossover (recent): {'✅ YES' if sd.get('macd_crossover') else '❌ NO'}
BB Squeeze: {'✅ YES — Volatility Contraction' if sd.get('bb_squeeze') else '❌ NO'}

RSI (14): {sd.get('rsi', 'N/A')}
ADX (14): {sd.get('adx', 'N/A')}
MFI (14): {sd.get('mfi', 'N/A')}
RVOL: {sd.get('rvol', 'N/A')}x  (RVOL Bullish: {'YES' if sd.get('rvol_bullish') else 'NO'})

Demand Zone: ${sd.get('demand_zone_end', 'N/A')} – ${sd.get('demand_zone_start', 'N/A')}
Supply Zone: ${sd.get('supply_zone_start', 'N/A')}
Risk/Reward: 1:{sd.get('risk_reward_ratio', 'N/A')}
Zone Proximity: {sd.get('zone_proximity', 'N/A')}% above Demand Zone

52W High: ${sd.get('year_high', 'N/A')}  |  Upside to High: {sd.get('upside_to_high', 'N/A')}%
Sector: {sd.get('sector', 'N/A')}
Rel Return 1M vs Index: {sd.get('rel_1m', 'N/A')}%
Rel Return 3M vs Index: {sd.get('rel_3m', 'N/A')}%

Extra data:
MACD: {extra.get('macd', 'N/A')} / Signal: {extra.get('macd_signal', 'N/A')} → {macd_status}
Bollinger Band Position: {extra.get('bb_position', 'N/A')}% (0%=lower band, 100%=upper band)
Stock 1M Return: {extra.get('momentum_1m', 'N/A')}%  |  SPY 1M: {extra.get('spy_1m', 'N/A')}%  → RS: {rel_str}
Volume Acceleration (5d/20d): {extra.get('vol_5v20', 'N/A')}x
Recent Headlines: {news_text}
"""

        # ── Agent 1 : US Technical Momentum Analyst ───────────────────
        technician = Agent(
            role="US Market Short-Term Momentum Technical Analyst",
            goal=(
                "วิเคราะห์คุณภาพ Breakout และ Momentum ระยะสั้น 1-4 สัปดาห์ของหุ้น US "
                "โดยใช้ Minervini Stage 2, CAN SLIM, และ RS Rating เป็นหลัก"
            ),
            backstory=(
                "คุณเป็นผู้เชี่ยวชาญด้านหุ้น US ที่ใช้แนวทาง Mark Minervini (SEPA) และ William O'Neil (CAN SLIM) "
                "เชี่ยวชาญการอ่าน Stage 2 Weinstein, Volatility Contraction Pattern (VCP), "
                "RS Rating (Relative Strength vs Nasdaq/S&P 500), Pivot Point Breakout, "
                "และ High Volume Tight Areas (HVTA) "
                "คุณประเมิน Breakout Quality จาก Volume Confirmation, ADX, และ Price Action "
                "เน้นหุ้นที่มี RS Rating ≥ 80 และอยู่ใน Stage 2 เท่านั้น"
            ),
            llm=llm,
            verbose=False,
            allow_delegation=False,
        )

        # ── Agent 2 : US Risk & Entry Specialist ──────────────────────
        risk_expert = Agent(
            role="US Market Risk Management & Entry Timing Expert",
            goal=(
                "คำนวณ Entry ที่แม่นยำ, ATR-based Stop Loss, และ R:R สำหรับ US market "
                "โดยคำนึงถึงความเสี่ยงพิเศษของ US เช่น Earnings Date และ Fed Events"
            ),
            backstory=(
                "คุณเป็น Risk Manager ที่เชี่ยวชาญ US stock market โดยเฉพาะ "
                "ใช้ Daily/Weekly ATR สำหรับ position sizing, "
                "ตรวจสอบ Earnings Date ก่อนเข้า Trade เพื่อหลีกเลี่ยง Gap Risk, "
                "และคำนวณ Position Size แบบ Fixed % Risk (1-2% per trade) "
                "กฎหลัก: Stop Loss ≤ 7-8% จาก Entry, R:R ≥ 2:1, "
                "ไม่เข้าหุ้นภายใน 2 สัปดาห์ก่อน Earnings ถ้า RS < 85"
            ),
            llm=llm,
            verbose=False,
            allow_delegation=False,
        )

        # ── Agent 3 : US Market Context Scout ────────────────────────
        market_scout = Agent(
            role="US Market Context & Catalyst Intelligence Scout",
            goal=(
                "วิเคราะห์ภาพรวมตลาด US, Sector Rotation, นโยบาย Fed, "
                "และ Catalyst ที่จะขับเคลื่อนราคาในระยะ 1-4 สัปดาห์ พร้อม Final Verdict"
            ),
            backstory=(
                "คุณเป็นผู้เชี่ยวชาญด้าน US Market Macro Context และ Sector Intelligence "
                "ติดตาม Fed Rate decisions, CPI/PCE data, Earnings Season, "
                "Sector Rotation (Growth vs Value, Tech vs Energy), "
                "และ Institutional Fund Flow (13F filings awareness) "
                "คุณผสาน Technical + Macro + Catalyst เพื่อตัดสินใจ BUY/WAIT/AVOID "
                "ที่ชัดเจนและ Action-oriented เสมอ"
            ),
            llm=llm,
            verbose=False,
            allow_delegation=False,
        )

        # ── Task 1 ────────────────────────────────────────────────────
        task1 = Task(
            description=f"""Analyze short-term US momentum quality for {self.symbol}:

{context}

Write in Thai language, covering:
1. **Stage Analysis**: Stage 2 Weinstein ✅/❌ — อธิบายว่าทำไม
2. **RS Rating {sd.get('rs_rating','N/A')}/99**: ดีหรือไม่? มี Relative Outperformance vs SPY/QQQ ไหม?
3. **Breakout Quality**: Breakout ใหม่ / Consolidating after Breakout / Pullback to Support? Pattern ที่เห็น?
4. **Momentum Confirmation**: RSI {sd.get('rsi','N/A')}, ADX {sd.get('adx','N/A')}, MACD, Volume → ยืนยัน Momentum แค่ไหน?
5. **Entry Timing**: ตอนนี้เข้าได้เลย / รอ Pullback / ยังไม่ถึงเวลา?
6. **Breakout Quality Score**: 0-100 พร้อมเหตุผล""",
            agent=technician,
            expected_output="รายงาน Technical สั้นกระชับ 6 หัวข้อ ภาษาไทย"
        )

        # ── Task 2 ────────────────────────────────────────────────────
        task2 = Task(
            description=f"""Calculate Risk Management for US stock {self.symbol}:

{context}

Write in Thai language, provide precise Risk Management plan:
1. **Best Entry**: ช่วงราคา Entry ที่ดีที่สุด (Demand Zone / Pullback level / Breakout pivot)
2. **Stop Loss**: ATR-based + Demand Zone — ≤7-8% จาก Entry ตาม Minervini rule
3. **Earnings Risk**: ⚠️ ควรระวัง Earnings Date ไหม? (ถ้าใกล้ = ลด position size ลง 50%)
4. **Target 1 (1.5:1 R:R)**: $X.XX
5. **Target 2 (2.5:1 R:R)**: $X.XX
6. **Position Size**: Portfolio $10,000 USD, Risk 1.5% per trade → ซื้อกี่หุ้น?
7. **R:R Summary**: Entry $___  → Stop $___  → Target $___  = R:R 1:___""",
            agent=risk_expert,
            expected_output="ตาราง Risk Management ระบุราคาทุกจุดชัดเจน"
        )

        # ── Task 3 ────────────────────────────────────────────────────
        task3 = Task(
            description=f"""Analyze US Market Context and give Final Verdict for {self.symbol}:

{context}

Write in Thai language:
1. **SPY/QQQ Trend**: ตลาด US โดยรวมขาขึ้น/ลง/Sideways? เหมาะสำหรับ Momentum Buying ไหม?
2. **Sector {sd.get('sector','N/A')}**: Sector นี้ร้อนแรงหรือถูกขายทิ้ง? มี Sector Rotation เกิดขึ้นไหม?
3. **Smart Money Signal**: RVOL {sd.get('rvol','N/A')}x, MFI {sd.get('mfi','N/A')}, Volume 5d/20d = {extra.get('vol_5v20','N/A')}x → Institutional Accumulation หรือ Distribution?
4. **Catalyst 1-4 สัปดาห์**: Earnings / Product launch / Fed meeting / Macro data ที่อาจขับเคลื่อนหุ้น
5. **⚠️ Key Risks**: 3 ปัจจัยเสี่ยงหลักสำหรับ US market
6. **🎯 FINAL VERDICT**:
   - **BUY NOW** / **WAIT FOR PULLBACK** / **AVOID**
   - เหตุผล 3 ข้อ (Stage/RS + Smart Money + Macro/Catalyst)
   - Timeframe: __ สัปดาห์""",
            agent=market_scout,
            expected_output="US Market context + clear Final Verdict พร้อมเหตุผลครบถ้วน"
        )

        crew = Crew(
            agents=[technician, risk_expert, market_scout],
            tasks=[task1, task2, task3],
            process=Process.sequential,
            verbose=False,
        )

        result = crew.kickoff()
        return str(result)

# ======================================================================
# TheCoreCrew — Renaissance-Style Multi-Agent (Institutional Selection)
# ======================================================================

class TheCoreCrew:
    """
    "The Core Project" — Renaissance-inspired analysis.
    Agents:
      1. Anomaly Hunter    — Deep Fundamental (WACC, PEGY) + Tech anomalies
      2. Backtest Engineer — Validate strategy with historical win rates
      3. Execution Decider — Final summary, daily report & alert logic
    """

    def __init__(self, symbol, market='SET'):
        self.symbol = symbol
        self.market = market
        
        if market == 'US':
            self.yf_symbol = symbol
        else:
            self.yf_symbol = (
                symbol if ('.' in symbol or '=' in symbol or '-' in symbol)
                else f"{symbol}.BK"
            )
        os.environ["GEMINI_API_KEY"] = settings.GEMINI_API_KEY

    def run_analysis(self):
        from crewai import Agent, Task, Crew, Process
        from crewai.llm import LLM
        from .utils import get_stock_data, calculate_valuation_metrics, auto_backtest_strategy

        llm = LLM(model="gemini/gemini-2.5-flash", api_key=settings.GEMINI_API_KEY)
        
        # 1. Fetch Rich Data
        data = get_stock_data(self.yf_symbol)
        info = data.get('info', {})
        hist = data.get('history', pd.DataFrame())
        fins = data.get('financials', pd.DataFrame())
        bs   = data.get('balance_sheet', pd.DataFrame())
        
        # 2. Compute Quant Valuation
        valuation = calculate_valuation_metrics(info, hist, fins, bs)
        
        # 3. Pre-run Backtests for different strategies
        bt_rsi = auto_backtest_strategy(hist, 'momentum_rsi')
        bt_ema = auto_backtest_strategy(hist, 'ema_cross')
        
        # Build Context
        context = f"""
หุ้น: {self.symbol}
ราคาปัจจุบัน: {info.get('currentPrice', 'N/A')} {('บาท' if self.market == 'SET' else 'USD')}
Sector: {info.get('sector', 'N/A')}
Market Cap: {valuation.get('market_cap', 'N/A')} {('ล้านบาท' if self.market == 'SET' else 'MUSD')}

[Financial Valuation Metrics]
- WACC (ต้นทุนเงินทุน): {valuation.get('wacc')}
- PEGY Ratio: {valuation.get('pegy')} (PEG + Dividend Yield)
- Cost of Equity: {valuation.get('cost_of_equity')}
- Cost of Debt: {valuation.get('cost_of_debt')}
- ROE: {info.get('returnOnEquity', 'N/A')}
- PEG: {info.get('pegRatio', 'N/A')}

[Technical Snapshot]
- RSI: {hist['RSI'].iloc[-1] if not hist.empty and 'RSI' in hist.columns else 'N/A'}
- 52W High/Low: {info.get('fiftyTwoWeekHigh')} / {info.get('fiftyTwoWeekLow')}
- Change 1M: {((hist['Close'].iloc[-1] - hist['Close'].iloc[-22])/hist['Close'].iloc[-22]*100) if len(hist)>22 else 'N/A'}%
- Market: {self.market}
- Benchmark Comparison: {("S&P 500" if self.market == "US" else "SET Index")}

[Automated Backtest Results]
1. Strategy RSI Mean Reversion: Win Rate {bt_rsi.get('win_rate_pct')}% | Return {bt_rsi.get('total_return_pct')}%
2. Strategy EMA Cross Trend: Win Rate {bt_ema.get('win_rate_pct')}% | Return {bt_ema.get('total_return_pct')}%
"""

        # --- Define Agents ---
        hunter = Agent(
            role="Anomaly Hunter (Fundamental & Tech Analyst)",
            goal=f"เฟ้นหาความผิดปกติของ {self.symbol} ทั้งเชิงมูลค่า (WACC, PEGY) และสัญญาณทางเทคนิค",
            backstory=(
                "คุณเป็นนักวิเคราะห์สไตล์ Renaissance Technologies ที่มองหาการบิดเบือนของราคา "
                "คุณตรวจสอบว่า ROE สูงกว่า WACC หรือไม่ (เพื่อดูการสร้างมูลค่าจริง) "
                "และตรวจสอบ PEGY เพื่อหาหุ้นที่เติบโตสูงแต่ราคาถูก "
                "คุณมองหา Anomaly ที่ตลาดมองข้าม"
            ),
            llm=llm,
            verbose=False
        )

        engineer = Agent(
            role="Backtest Engineer",
            goal="พิสูจน์สัญญาณซื้อขายด้วยข้อมูลย้อนหลัง และสรุปค่า Win Rate/Risk ตามสถิติจริง",
            backstory=(
                "คุณเป็น Quant Engineer ที่เชื่อถือแต่ตัวเลขสถิติ "
                "คุณจะนำผลการทดสอบ RSI Momentum และ EMA Cross มาประเมินว่า "
                "ในอดีตหุ้นตัวนี้ตอบสนองต่อกลยุทธ์ไหนได้ดีที่สุด และ Win Rate เกิน 55% หรือไม่"
            ),
            llm=llm,
            verbose=False
        )

        decider = Agent(
            role="Execution Decider",
            goal="สรุป Action Plan ขั้นสุดท้าย และเขียนรายงาน Daily Report รูปแบบย่อยง่าย",
            backstory=(
                "คุณคือผู้นำทีมที่รวบรวมข้อมูลจาก Hunter และ Engineer "
                "คุณมีหน้าที่ตัดสินใจว่า 'วันนี้ต้องทำอะไร' และสื่อสารออกมาให้มีพลัง Action-oriented "
                "รายงานของคุณต้องสั้น กระชับ และแจ้งเตือนจุดที่ต้องโฟกัสใน Dashboard"
            ),
            llm=llm,
            verbose=False
        )

        # --- Define Tasks ---
        task_hunt = Task(
            description=f"วิเคราะห์ความผิดปกติของ {self.symbol} โดยใช้ Valuation Context:\n{context}\nระบุว่านี่คือหุ้น Undervalued ที่มีคุณภาพ (ROE > WACC) หรือไม่",
            agent=hunter,
            expected_output="รายงานวิเคราะห์ Anomaly เชิงมูลค่าและเทคนิค"
        )

        task_test = Task(
            description=f"ประเมินผล Backtest ของ {self.symbol} จากข้อมูลสถิติที่ได้รับ:\n{context}\nสรุปว่ากลยุทธ์ไหนมีโอกาสสำเร็จสูงสุดในหุ้นตัวนี้",
            agent=engineer,
            expected_output="สรุปจุดแข็งเชิงสถิติกำกับด้วย Win Rate"
        )

        task_decide = Task(
            description=f"เขียนรายงานสรุป Daily Report สำหรับ {self.symbol}:\nครอบคลุมคำแนะนำ BUY/HOLD/SELL ตารางราคาเข้า/เป้าหมาย/Stop และสิ่งที่ต้องเฝ้าระวังใน Dashboard",
            agent=decider,
            expected_output="Daily Report ภาษาไทย สไตล์คนทำงาน (Actionable Insights)"
        )

        crew = Crew(
            agents=[hunter, engineer, decider],
            tasks=[task_hunt, task_test, task_decide],
            process=Process.sequential,
            verbose=False
        )

        return str(crew.kickoff())



# ======================================================================
# CrewAI Stock Analysis System — Minervini/O'Neil Momentum Style
# ======================================================================

class MomentumCrew:
    def __init__(self, symbol, portfolio_context=None, strategy=None, market='SET'):
        """
        portfolio_context (dict, optional): ข้อมูลพอร์ตของผู้ใช้สำหรับหุ้นตัวนี้
          {
            'entry_price':    float,  # ราคาทุนเฉลี่ย
            'quantity':       float,  # จำนวนหุ้น
            'gain_loss_pct':  float,  # % กำไร/ขาดทุน
            'gain_loss':      float,  # กำไร/ขาดทุนเป็นบาท
            'market_value':   float,  # มูลค่าตลาดปัจจุบัน
          }
        strategy (str, optional): กลยุทธ์เฉพาะเจาะจงที่ใช้เรียก เช่น 'turtle'
        market (str, optional): ตลาดของหุ้น เช่น 'SET', 'US'
        """
        self.symbol           = symbol
        self.portfolio_context = portfolio_context or {}
        self.strategy         = strategy
        self.market           = market
        self.benchmark_name   = "SET Index" if market == 'SET' else "S&P 500 / Nasdaq"
        self.currency         = "บาท" if market == 'SET' else "USD"
        self.curr_sym         = "฿" if market == 'SET' else "$"

        # Auto-add .BK for SET stocks (no dot, no dash, no =)
        if self.market == 'US':
            self.yf_symbol = symbol
        else:
            self.yf_symbol = (
                symbol if ('.' in symbol or '=' in symbol or '-' in symbol)
                else f"{symbol}.BK"
            )

        os.environ["GOOGLE_API_KEY"] = settings.GEMINI_API_KEY
        os.environ["GEMINI_API_KEY"] = settings.GEMINI_API_KEY

        self.llm_name = "gemini/gemini-2.5-flash"

    # ------------------------------------------------------------------
    @staticmethod
    def _fmt_fundamental(k, val):
        """Format fundamental values: convert decimal ratios to percentage strings."""
        if val is None:
            return 'N/A'
        if k == 'dividendYield' and isinstance(val, (int, float)):
            # yahooquery returns dividendYield already as percentage (e.g. 3.86), not decimal
            v = val if val > 1 else val * 100
            return f"{v:.2f}%"
        if k in ('revenueGrowth', 'earningsGrowth', 'returnOnEquity') and isinstance(val, (int, float)):
            return f"{val * 100:.2f}%"
        return val

    @staticmethod
    def _yq_extract(source, sym):
        """Safely extract a symbol's dict from a yahooquery property response."""
        if isinstance(source, dict) and sym in source and isinstance(source[sym], dict):
            return source[sym]
        return {}

    # ------------------------------------------------------------------
    def _get_rich_data(self):
        """Fetch price history, yfinance info, and yahooquery fundamentals in parallel."""
        ticker    = yf.Ticker(self.yf_symbol)
        yq_ticker = YQTicker(self.yf_symbol)
        sym       = self.yf_symbol

        def _fetch_history():
            return ticker.history(period="6mo")

        def _fetch_info():
            try:
                return ticker.info or {}
            except Exception:
                return {}

        def _fetch_yq():
            """Batch yahooquery fundamentals — more reliable for Thai stocks."""
            result = {}
            # financial_data: ROE, growth, target price, analyst rec
            d = self._yq_extract(yq_ticker.financial_data, sym)
            for k in ('returnOnEquity', 'revenueGrowth', 'earningsGrowth',
                      'targetMeanPrice', 'recommendationKey'):
                if k in d:
                    result[k] = d[k]
            # summary_detail: PE, dividend, market cap
            d = self._yq_extract(yq_ticker.summary_detail, sym)
            for k, dest in (('trailingPE', 'trailingPE'), ('dividendYield', 'dividendYield'),
                            ('marketCap', 'marketCap')):
                result.setdefault(dest, d.get(k))
            # key_stats: PBV
            d = self._yq_extract(yq_ticker.key_stats, sym)
            result.setdefault('priceToBook', d.get('priceToBook'))
            # asset_profile: sector, industry
            d = self._yq_extract(yq_ticker.asset_profile, sym)
            result.setdefault('sector',   d.get('sector'))
            result.setdefault('industry', d.get('industry'))
            return result

        # Run all 3 fetches in parallel, collect results with a shared timeout
        history   = pd.DataFrame()
        full_info = {}
        yq_data   = {}
        with concurrent.futures.ThreadPoolExecutor(max_workers=3) as ex:
            futures = {
                ex.submit(_fetch_history): 'hist',
                ex.submit(_fetch_info):    'info',
                ex.submit(_fetch_yq):      'yq',
            }
            for f in concurrent.futures.as_completed(futures, timeout=25):
                key = futures[f]
                try:
                    result = f.result()
                    if key == 'hist':
                        history   = result
                    elif key == 'info':
                        full_info = result
                    else:
                        yq_data   = result
                except Exception:
                    pass

        # fast_info for current price (always available, no timeout risk)
        info = {}
        try:
            fi = ticker.fast_info
            info = {
                'currentPrice': getattr(fi, 'last_price', None),
                'marketCap':    getattr(fi, 'market_cap', None),
            }
        except Exception:
            pass

        # yahooquery fills missing, yfinance non-None values take priority
        merged = {**yq_data, **{k: v for k, v in full_info.items() if v is not None}}
        for k in ('longName', 'sector', 'industry', 'trailingPE', 'priceToBook',
                  'returnOnEquity', 'revenueGrowth', 'earningsGrowth',
                  'dividendYield', 'targetMeanPrice', 'marketCap', 'recommendationKey'):
            info[k] = self._fmt_fundamental(k, merged.get(k))

        news = []
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
            return {}, [], {}, {}

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

        # ── Turtle Trading Indicators ──────────────────────────
        # System 1: 20-day high (Breakout), 10-day low (Exit)
        # System 2: 55-day high (Breakout), 20-day low (Exit)
        try:
            history['DON_20_H'] = history['High'].rolling(window=20).max()
            history['DON_20_L'] = history['Low'].rolling(window=20).min()
            history['DON_55_H'] = history['High'].rolling(window=55).max()
            history['DON_10_L'] = history['Low'].rolling(window=10).min()
            # ATR (N) for volatility
            history['ATR_20']   = ta.atr(history['High'], history['Low'], history['Close'], length=20)
        except Exception:
            pass

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
            # Turtle Data
            'Turtle_S1_High20':   _f(last.get('DON_20_H')),
            'Turtle_S1_Exit10':   _f(last.get('DON_10_L')),
            'Turtle_S2_High55':   _f(last.get('DON_55_H')),
            'Turtle_S2_Exit20':   _f(last.get('DON_20_L')),
            'Turtle_ATR_N':       _f(last.get('ATR_20')),
        }

        # ── Quantitative Metrics ─────────────────────────────────────
        quant = {}
        try:
            closes = history['Close'].dropna()
            n = len(closes)

            # Price Momentum (trailing returns)
            if n >= 22:
                quant['Momentum_1M_%'] = _f((closes.iloc[-1] - closes.iloc[-22]) / closes.iloc[-22] * 100)
            if n >= 66:
                quant['Momentum_3M_%'] = _f((closes.iloc[-1] - closes.iloc[-66]) / closes.iloc[-66] * 100)
            if n >= 126:
                quant['Momentum_6M_%'] = _f((closes.iloc[-1] - closes.iloc[-126]) / closes.iloc[-126] * 100)

            # Historical Volatility (annualized, 20-day)
            if n >= 21:
                daily_ret = closes.pct_change().dropna()
                vol_20 = float(daily_ret.tail(20).std() * (252 ** 0.5) * 100)
                quant['Volatility_20D_Ann_%'] = _f(vol_20)

            # ATR% — risk per bar เป็น % ของราคา (position sizing guide)
            atr_s = ta.atr(history['High'], history['Low'], history['Close'], length=14)
            if atr_s is not None and not atr_s.empty and isinstance(price, float):
                atr_val = float(atr_s.iloc[-1])
                quant['ATR_14_pct'] = _f(atr_val / price * 100)
                quant[f'ATR_14_{self.currency.lower()}'] = _f(atr_val)

            # Sharpe Proxy (6M risk-adjusted momentum)
            if n >= 126:
                ret_6m = closes.pct_change().dropna().tail(126)
                vol_6m = float(ret_6m.std() * (252 ** 0.5))
                ann_ret = float((closes.iloc[-1] / closes.iloc[-126]) ** (252/126) - 1)
                quant['Sharpe_Proxy_6M'] = _f(ann_ret / vol_6m if vol_6m > 0 else 0)

            # Bollinger Band %B — ราคาอยู่ที่ไหนใน band (0%=lower, 100%=upper)
            bb_df = ta.bbands(closes, length=20, std=2)
            if bb_df is not None and not bb_df.empty:
                upper_col = next((c for c in bb_df.columns if 'BBU' in c), None)
                lower_col = next((c for c in bb_df.columns if 'BBL' in c), None)
                if upper_col and lower_col and isinstance(price, float):
                    bbu = float(bb_df[upper_col].iloc[-1])
                    bbl = float(bb_df[lower_col].iloc[-1])
                    if bbu > bbl:
                        quant['BB_Position_%'] = _f((price - bbl) / (bbu - bbl) * 100)

            # Volume Trend — RVOL 5วัน vs 20วัน (accelerating = สถาบันกำลังสะสม)
            vols = history['Volume'].dropna()
            if len(vols) >= 20:
                rvol_5  = float(vols.tail(5).mean())
                rvol_20 = float(vols.tail(20).mean())
                quant['Volume_Trend_5v20'] = _f(rvol_5 / rvol_20 if rvol_20 > 0 else 1)
                quant['Volume_Trend_Signal'] = (
                    'ACCELERATING (สถาบันสะสม)' if rvol_5 > rvol_20 * 1.2
                    else 'DECELERATING (แรงซื้อลด)' if rvol_5 < rvol_20 * 0.8
                    else 'NEUTRAL'
                )

            # Max Drawdown (6M) — วัดความเสี่ยงขาลงสูงสุด
            if n >= 66:
                roll_max = closes.tail(126).cummax()
                drawdown = (closes.tail(126) - roll_max) / roll_max * 100
                quant['Max_Drawdown_6M_%'] = _f(drawdown.min())

            # Consecutive Up/Down Days — momentum ระยะสั้น
            if n >= 5:
                daily_chg = closes.diff().tail(5)
                up_streak = 0
                for chg in reversed(daily_chg.values):
                    if chg > 0:
                        up_streak += 1
                    else:
                        break
                down_streak = 0
                for chg in reversed(daily_chg.values):
                    if chg < 0:
                        down_streak += 1
                    else:
                        break
                if up_streak > 0:
                    quant['Streak'] = f"ขึ้น {up_streak} วันติด"
                elif down_streak > 0:
                    quant['Streak'] = f"ลง {down_streak} วันติด"

        except Exception:
            pass

        fundamental = {
            'Company':             info.get('longName', self.symbol),
            'Sector':              info.get('sector', 'N/A'),
            'Industry':            info.get('industry', 'N/A'),
            f'Market_Cap_({("MUSD" if self.market == "US" else "MTHB")})': _f((info.get('marketCap') or 0) / 1e6),
            'PE_Ratio':            _f(info.get('trailingPE')),
            'PBV':                 _f(info.get('priceToBook')),
            'ROE_%':               info.get('returnOnEquity', 'N/A'),
            'Revenue_Growth_%':    info.get('revenueGrowth', 'N/A'),
            'Earnings_Growth_%':   info.get('earningsGrowth', 'N/A'),
            'Dividend_Yield_%':    info.get('dividendYield', 'N/A'),
            'Analyst_Target_Price':_f(info.get('targetMeanPrice')),
        }

        return technical, news[:6], fundamental, quant

    # ------------------------------------------------------------------
    def run_analysis(self):
        """
        Single Gemini API call — replaces 3-agent CrewAI sequential chain.
        ~3-5x faster: 1 LLM call instead of 3, no agent orchestration overhead.
        """
        technical, news_list, fundamental, quant = self._get_rich_data()

        # ── Format values with explicit currency symbol ──────────────
        PRICE_KEYS = {'Price', '52w_High', '52w_Low', 'EMA_50', 'EMA_200',
                      'Turtle_S1_High20', 'Turtle_S1_Exit10',
                      'Turtle_S2_High55', 'Turtle_S2_Exit20',
                      f'ATR_14_{self.currency.lower()}'}
        def _fmt_val(k, v):
            if k in PRICE_KEYS and isinstance(v, (int, float)):
                return f"{self.curr_sym}{v}"
            return v

        tech_str  = "\n".join([f"  {k}: {_fmt_val(k, v)}" for k, v in technical.items()])
        fund_str  = "\n".join([f"  {k}: {v}" for k, v in fundamental.items()])
        quant_str = "\n".join([f"  {k}: {v}" for k, v in quant.items()]) if quant else "  (ข้อมูลไม่เพียงพอ)"
        news_str  = (
            "\n".join([f"  - {n.get('title', '')}" for n in news_list])
            if news_list else "  (No recent news available)"
        )

        # ── Validate data quality ─────────────────────────────────────
        current_price = technical.get('Price', 'N/A')
        data_warning = ""
        if not technical or current_price in ('N/A', 0, None):
            data_warning = (
                "\n⚠️ WARNING: Market data could not be fetched. "
                "DO NOT hallucinate prices. State 'Data unavailable' where needed.\n"
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
- ราคาทุนเฉลี่ย: {ep:.2f} {self.currency}
- จำนวนหุ้น: {qty:,.0f} หุ้น
- มูลค่าปัจจุบัน: {mv:,.0f} {self.currency}
- กำไร/ขาดทุน: {gl_sign}{gl_pct:.1f}% ({gl_sign}{gl_thb:,.0f} {self.currency})

เนื่องจากนักลงทุนถือหุ้นนี้อยู่แล้ว ให้เพิ่มหัวข้อ "**คำแนะนำสำหรับผู้ถือหุ้น**" ที่ตอบว่า:
- ควรถือต่อ / เพิ่มพอร์ต / ขายทำกำไร / ตัดขาดทุน?
- Stop Loss จากราคาทุน {ep:.2f} {self.currency} ควรอยู่ที่เท่าไหร่?
- R/R จาก Entry {ep:.2f} ไปยัง Target คือเท่าไหร่?
"""
        else:
            portfolio_section = ""

        # ── Single comprehensive prompt ──────────────────────────────
        price_display = f"{self.curr_sym}{current_price}" if isinstance(current_price, (int, float)) else "N/A"
        prompt = f"""{data_warning}You are a senior stock analyst combining Minervini/O'Neil momentum methodology
with quantitative analysis and fundamental research. Analyze {self.symbol} and produce a complete
investment report IN THAI LANGUAGE.

MARKET CONTEXT (MUST FOLLOW EXACTLY):
- Market: {self.market}
- Currency: {self.currency} (symbol: {self.curr_sym})
- Current Price: {price_display}
- Benchmark: {self.benchmark_name}
- ALL prices in this report MUST use "{self.curr_sym}" prefix (e.g. {self.curr_sym}50.25)
- NEVER use "฿", "Baht", or "บาท" for {self.market} stocks
- NEVER compare to SET Index or Thai market

## TECHNICAL DATA
{tech_str}

## QUANTITATIVE METRICS
{quant_str}

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

## 3. การวิเคราะห์เชิงปริมาณ (Quantitative Analysis)
- Price Momentum (1M/3M/6M) เทียบกับตลาด — หุ้นนี้แรงหรืออ่อนกว่า {self.benchmark_name}?
- Volatility Regime — ความผันผวนสูง/ต่ำกว่าปกติ เหมาะ swing หรือ position trade?
- Risk per trade (ATR%) — ถ้าซื้อ {('100,000 บาท' if self.market == 'SET' else '$10,000 USD')} ควร stop ที่เท่าไหร่?
- Sharpe Proxy — risk-adjusted return ดีแค่ไหน
- Volume Trend — สถาบันกำลังสะสมหรือลดหุ้น?
- Max Drawdown 6M — ความเสี่ยงขาลงสูงสุดที่เคยเจอ

## 4. ปัจจัยพื้นฐานและข่าว (Fundamentals & Sentiment)
- Catalyst หลักที่ขับเคลื่อนหุ้น
- ความแข็งแกร่งของ Fundamental (PE, ROE, Growth)
- Analyst consensus และ target price
- Red flags (ถ้ามี)

## 5. การวิเคราะห์กลยุทธ์ Turtle Breakout (Turtle Trading Analysis)
- สถานะขอบเขตระยะยาว: หุ้นนี้กำลังทำ 20-Day High (S1) หรือ 55-Day High (S2) หรือไม่?
- ความแรงของการทะลุ: ปริมาณการซื้อขาย (RVOL) ยืนยันความแข็งแกร่งหรือไม่?
- ข้อมูลจุดออก (Turtle Exit): แนะนำแนวรับสำคัญและจุดหนีตามแนวทาง Turtle (10-Day Low หรือ 20-Day Low) ที่ตัวเลขเท่าใด?
- ความเหมาะสม: หุ้นนี้เหมาะกับการถือรันเทรนด์ระยะยาวแบบเต่าแค่ไหน? (High risk/High reward?)

## 6. คำแนะนำหลัก (Main Recommendation)
ซื้อ / รอดูก่อน / หลีกเลี่ยง — พร้อมเหตุผล 3 ข้อ
(Technical + Quantitative + Fundamental + Turtle)

## 7. จุดซื้อที่เหมาะสม (Entry Zone)
- ช่วงราคาที่เหมาะสม พร้อมเหตุผล

## 8. จุด Stop Loss และเป้าหมายกำไร
- Stop Loss: {self.curr_sym}X.XX (ไม่เกิน 7-8% จาก entry — คำนวณจาก ATR และ Turtle Exit ด้วย)
- Target 1 (Conservative): {self.curr_sym}X.XX
- Target 2 (Aggressive): {self.curr_sym}X.XX
- Risk per unit (Entry - SL): {self.curr_sym}X.XX
- R:R Ratio: 1:X.X

## 9. ความเสี่ยงสำคัญ (Key Risks)
ระบุ 3 ปัจจัยเสี่ยงที่ต้องติดตาม

## 10. ระยะเวลาที่แนะนำ
Swing (2-8 สัปดาห์) หรือ Position (3-6 เดือน) — อ้างอิง Volatility และ ATR%"""
        prompt += "\n\nBe specific with numbers. Use actual prices from the data provided."

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

# ======================================================================
# MacroPlaybookCrew — CrewAI Multi-Agent (Global Daily Briefing)
# ======================================================================

class MacroPlaybookCrew:
    """
    CrewAI 5-Agent analysis for Daily Playbook in Macro Menu.
    Agents:
      1. Global Macro Strategist (DXY, 10Y Yield)
      2. Thai Market Specialist (SET, local context)
      3. US Equities Analyst (S&P500, Nasdaq)
      4. Alternative Asset Expert (Crypto, Gold)
      5. Chief Investment Officer (Synthesizes all into 4 Time Periods daily plan)
    """

    def __init__(self, portfolio_data=None):
        os.environ["GEMINI_API_KEY"] = settings.GEMINI_API_KEY
        self.portfolio_data = portfolio_data or []
        
    def _fetch_asset_prices(self):
        assets = {
            'DXY': 'DX-Y.NYB',
            'US10Y': '^TNX',
            'SET': '^SET.BK',
            'S&P500': '^GSPC',
            'Nasdaq': '^IXIC',
            'Gold': 'GC=F',
            'Bitcoin': 'BTC-USD',
        }
        prices = {}
        for name, ticker in assets.items():
            try:
                t = yf.Ticker(ticker)
                hist = t.history(period="5d")
                if not hist.empty:
                    last = hist['Close'].iloc[-1]
                    prev = hist['Close'].iloc[-2] if len(hist) > 1 else last
                    chg = ((last - prev) / prev) * 100
                    prices[name] = f"Price: {last:.2f} (Chg: {chg:+.2f}%)"
                else:
                    prices[name] = "N/A"
            except:
                prices[name] = "Error fetching"
                
        # Fear & Greed Index
        try:
            import urllib.request
            import json
            req = urllib.request.Request("https://api.alternative.me/fng/?limit=1", headers={'User-Agent': 'Mozilla'})
            with urllib.request.urlopen(req, timeout=3) as resp:
                data = json.loads(resp.read().decode())
                if data and "data" in data:
                    val = data["data"][0]["value"]
                    clas = data["data"][0]["value_classification"]
                    prices['Crypto_Fear_Greed'] = f"{val}/100 ({clas})"
        except:
            prices['Crypto_Fear_Greed'] = "N/A"
            
        return prices

    def run_analysis(self):
        from crewai import Agent, Task, Crew, Process
        from crewai.llm import LLM

        llm = LLM(model="gemini/gemini-2.5-flash", api_key=settings.GEMINI_API_KEY)
        data = self._fetch_asset_prices()
        
        context_str = "\n".join([f"{k}: {v}" for k, v in data.items()])
        
        portfolio_str = "พอร์ตว่าง / ไม่มีข้อมูลหุ้นที่ถือ"
        if self.portfolio_data:
            port_items = []
            for item in self.portfolio_data:
                port_items.append(f"- {item['symbol']} ({item['market']}): ทุน {item['entry_price']} บาท/USD")
            portfolio_str = "\n".join(port_items)

        # Agents
        macro_strategist = Agent(
            role="Global Macro Strategist",
            goal="วิเคราะห์ภาพรวมเศรษฐกิจโลกจาก DXY และ US10Y เพื่อประเมิน Risk On/Off",
            backstory="นักยุทธศาสตร์เศรษฐกิจมหภาคระดับโลกที่สามารถชี้ทิศทางเงินทุนเคลื่อนย้ายได้เฉียบขาด",
            llm=llm, verbose=False, allow_delegation=False
        )

        thai_expert = Agent(
            role="Thai Equity Specialist",
            goal="วิเคราะห์สถานะของตลาด SET ว่าวันนี้ควรเน้นซื้อหุ้นแบบไหน หรือควรระวัง",
            backstory="ผู้เชี่ยวชาญตลาดหุ้นไทยที่เข้าใจ Momentum และวงจร Fund flow ต่างชาติ",
            llm=llm, verbose=False, allow_delegation=False
        )

        us_expert = Agent(
            role="US Wall Street Analyst",
            goal="รีวิวทิศทาง S&P500 และ Nasdaq คืนนี้",
            backstory="นักวิเคราะห์ Wall Street ที่เชี่ยวชาญ Sector Rotation และ Swing Trading",
            llm=llm, verbose=False, allow_delegation=False
        )

        alt_expert = Agent(
            role="Alternative Asset Expert",
            goal="ชี้เป้าความร้อนแรงของตลาด Crypto (Bitcoin) และ Gold ตามค่า Fear & Greed",
            backstory="เซียนเทรดที่อ่านอารมณ์ตลาดคริปโตเก่งมาก และจับจังหวะสวิงทองคำได้แม่นยำ",
            llm=llm, verbose=False, allow_delegation=False
        )

        cio = Agent(
            role="Chief Investment Officer (CIO)",
            goal="รวบรวมรายงานจากลูกน้อง 4 คน และผลิตเป็น 'Daily AI Playbook' ที่เข้าใจง่าย เป็น Action Plan พร้อมวิเคราะห์ Portfolio ปัจจุบันของผู้ใช้งาน",
            backstory="หัวหน้ากองทุน Private Hedge Fund ที่จะสั่งการลูกทีมเสมอ ว่าตารางงาน 4 ช่วงเวลาของวันต้องทำอะไรบ้าง และให้คำแนะนำพอร์ตฟอลิโอโดยอิงจากสภาพตลาดปัจจุบัน",
            llm=llm, verbose=False, allow_delegation=False
        )

        # Tasks
        task1 = Task(
            description=f"Market Data:\n{context_str}\n\nวิเคราะห์สภาพตลาดระดับโลก (DXY, US10Y) สรุปเป็นพารากราฟสั้นๆ พร้อมบอกว่ามันคือภาวะ Risk On หรือ Risk Off",
            agent=macro_strategist,
            expected_output="บทสรุปภาพรวมโลก"
        )
        task2 = Task(
            description=f"Market Data:\n{context_str}\n\nวิเคราะห์ตลาดหุ้นไทย (SET) ควรอำนวยความสะดวกสายเทรดเดอร์อย่างไร หุ้นใหญ่/กลาง/เล็ก ควรเล่นทรงไหน",
            agent=thai_expert,
            expected_output="กลยุทธ์ตลาดหุ้นไทย"
        )
        task3 = Task(
            description=f"Market Data:\n{context_str}\n\nให้มุมมองสำหรับคนที่จะรอเริ่มเทรดหุ้นอเมริกาคืนนี้ ดัชนีหลักกำลังบอกอะไร",
            agent=us_expert,
            expected_output="กลยุทธ์ตลาดหุ้นอเมริกา"
        )
        task4 = Task(
            description=f"Market Data:\n{context_str}\n\nแปลความหมายตลาดทองคำและคริปโต (เกจวัดความกลัวโลภคืออะไร) ควรรอหรือลุย",
            agent=alt_expert,
            expected_output="กลยุทธ์สินทรัพย์ทางเลือก"
        )
        task_cio = Task(
            description=f"""เอาผลวิเคราะห์ทั้งหมดจาก 4 Tasks ด้านบนมาเรียบเรียงใหม่ 
รวมถึงดูข้อมูล Portfolio ของเจ้านาย (User) ปัจจุบันที่กำลังถืออยู่:
{portfolio_str}

เขียนเป็น "รายงานแผนงานประจำวัน (Daily Action Playbook)" โดยแบ่งเป็น 5 บท (ภาษาไทย) ดังนี้:
1. ☀️ Pre-Market & Macro: ให้คำแนะนำภาพรวมและอารมณ์ตลาดวันนี้ สรุปสินทรัพย์ที่จะรุ่งและจะร่วง
2. 💼 My Portfolio Action: ให้คำแนะนำสั้นๆ ว่าหุ้นที่กำลังถือในเรดาร์ตัวไหนควรระวังตัวไหนควรถือต่อ (อิงจากภาพรวม Macro และตลาดวันนี้ ให้คำแนะนำกระชับ)
3. 📈 Market Open (ตลาดเปิดไทย): แนะนำ Action (ซื้อ/ขาย/ห้ามทำอะไร) สำหรับตลาดหุ้นไทยประจำวัน
4. 🛑 Market Close (ตลาดปิด): ช่วงบ่ายแก่ๆ ควรรันสแกนเนอร์และเก็บหุ้นลักษณะไหนข้ามวัน
5. 🌙 Night Routine (US & Crypto): แผนการรบช่วงกลางคืนสำหรับคริปโตและหุ้นอเมริกา
พยายามจัดรูปแบบให้สวยงามอย่างมาก (ใช้ Markdown, ไอคอน Emoji, และ Bullet Points ขีดเส้นใต้เน้นคำสำคัญ) โทนมืออาชีพ ฟันธง ไม่คลุมเครือ""",
            agent=cio,
            expected_output="Daily Playbook 5 ส่วนที่ครอบคลุมแผนแบบรายวันและพอร์ตฟอลิโอ"
        )

        crew = Crew(
            agents=[macro_strategist, thai_expert, us_expert, alt_expert, cio],
            tasks=[task1, task2, task3, task4, task_cio],
            process=Process.sequential,
            verbose=False,
        )

        result = crew.kickoff()
        return str(result)

