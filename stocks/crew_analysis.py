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

    def __init__(self, symbol, scan_data=None):
        self.symbol    = symbol
        self.scan_data = scan_data or {}
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
ราคาปัจจุบัน: {sd.get('price', 'N/A')} บาท
Technical Score: {sd.get('technical_score', 'N/A')}/100
RSI (14): {sd.get('rsi', 'N/A')}
ADX (14): {sd.get('adx', 'N/A')}
MFI (14): {sd.get('mfi', 'N/A')}
RVOL: {sd.get('rvol', 'N/A')}x

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
                "คุณอ่าน RVOL และ Volume Acceleration เพื่อบอกว่าเงินใหญ่กำลังสะสมหรือกระจายหุ้น "
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
3. **Target 1 (Conservative, R:R 1.5:1)**: ราคา ฿X.XX
4. **Target 2 (Aggressive, R:R 2.5:1–3:1)**: ราคา ฿X.XX
5. **Position Size**: พอร์ต 100,000 บาท Risk 1% → ซื้อกี่หุ้น?
6. **สรุป R:R**: Entry ฿___ → Stop ฿___ → Target ฿___ = R:R 1:___""",
            agent=risk_expert,
            expected_output="ตาราง Risk Management ชัดเจน ระบุราคาตัวเลขครบทุกจุด"
        )

        # ── Task 3 ────────────────────────────────────────────────────
        task3 = Task(
            description=f"""วิเคราะห์ Smart Money และสรุปขั้นสุดท้ายสำหรับ {self.symbol}:

{context}

เขียนรายงานสุดท้ายเป็นภาษาไทย:
1. **Smart Money Signal**: RVOL {sd.get('rvol','N/A')}x และ Volume 5d/20d = {extra.get('vol_5v20','N/A')}x → เงินใหญ่สะสม หรือกระจายหุ้น?
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
                quant['ATR_14_baht'] = _f(atr_val)

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
            'Market_Cap_MTHB':     _f((info.get('marketCap') or 0) / 1e6),
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

        tech_str  = "\n".join([f"  {k}: {v}" for k, v in technical.items()])
        fund_str  = "\n".join([f"  {k}: {v}" for k, v in fundamental.items()])
        quant_str = "\n".join([f"  {k}: {v}" for k, v in quant.items()]) if quant else "  (ข้อมูลไม่เพียงพอ)"
        news_str  = (
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
with quantitative analysis and fundamental research. Analyze {self.symbol} and produce a complete
investment report IN THAI LANGUAGE.

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
- Price Momentum (1M/3M/6M) เทียบกับตลาด — หุ้นนี้แรงหรืออ่อนกว่า SET?
- Volatility Regime — ความผันผวนสูง/ต่ำกว่าปกติ เหมาะ swing หรือ position trade?
- Risk per trade (ATR%) — ถ้าซื้อ 100,000 บาท ควร stop ที่เท่าไหร่?
- Sharpe Proxy — risk-adjusted return ดีแค่ไหน
- Volume Trend — สถาบันกำลังสะสมหรือลดหุ้น?
- Max Drawdown 6M — ความเสี่ยงขาลงสูงสุดที่เคยเจอ

## 4. ปัจจัยพื้นฐานและข่าว (Fundamentals & Sentiment)
- Catalyst หลักที่ขับเคลื่อนหุ้น
- ความแข็งแกร่งของ Fundamental (PE, ROE, Growth)
- Analyst consensus และ target price
- Red flags (ถ้ามี)

## 5. คำแนะนำหลัก (Main Recommendation)
ซื้อ / รอดูก่อน / หลีกเลี่ยง — พร้อมเหตุผล 3 ข้อ
(อ้างอิงทั้ง technical + quantitative + fundamental)

## 6. จุดซื้อที่เหมาะสม (Entry Zone)
- ช่วงราคาที่เหมาะสม พร้อมเหตุผล

## 7. จุด Stop Loss และเป้าหมายกำไร
- Stop Loss: ไม่เกิน 7-8% จาก entry (Minervini rule) — คำนวณจาก ATR ด้วย
- Target 1 (Conservative): ฿X.XX
- Target 2 (Aggressive): ฿X.XX
- Risk per unit (Entry - SL): ฿X.XX
- R:R Ratio: 1:X.X

## 8. ความเสี่ยงสำคัญ (Key Risks)
ระบุ 3 ปัจจัยเสี่ยงที่ต้องติดตาม

## 9. ระยะเวลาที่แนะนำ
Swing (2-8 สัปดาห์) หรือ Position (3-6 เดือน) — อ้างอิง Volatility และ ATR%

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
