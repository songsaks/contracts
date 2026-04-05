import os
import yfinance as yf
import pandas as pd
import pandas_ta as ta
from crewai import Agent, Task, Crew, Process
from django.conf import settings

# ======================================================================
# CrewAI Stock Analysis System (Momentum & Deep Dive) - Final Stable Version
# ======================================================================

class MomentumCrew:
    def __init__(self, symbol):
        self.symbol = symbol
        
        # 1. Set required environment variables for CrewAI to auto-initialize Gemini
        # CrewAI 0.28+ prefers these for automatic LLM setup via LiteLLM/LangChain
        os.environ["GOOGLE_API_KEY"] = settings.GEMINI_API_KEY
        os.environ["GEMINI_API_KEY"] = settings.GEMINI_API_KEY
        
        # We pass the model name as a string to avoid Pydantic validation issues with LLM objects
        self.llm_name = "gemini/gemini-3-flash-preview"

    def get_stock_data_tool(self, symbol):
        """Custom tool for agents to fetch technical indicators."""
        try:
            ticker = yf.Ticker(symbol)
            hist = ticker.history(period="1y")
            if hist.empty:
                return "Result: No historical data found. Symbol might be invalid."
            
            # Indicators
            hist['EMA50'] = ta.ema(hist['Close'], length=50)
            hist['EMA200'] = ta.ema(hist['Close'], length=200)
            hist['RSI'] = ta.rsi(hist['Close'], length=14)
            
            last = hist.iloc[-1]
            summary = {
                "Symbol": symbol,
                "Price": round(float(last['Close']), 2),
                "RSI": round(float(last['RSI']), 2) if not pd.isna(last['RSI']) else "N/A",
                "EMA50": round(float(last.get('EMA50', 0)), 2),
                "EMA200": round(float(last.get('EMA200', 0)), 2),
                "Volume_Ratio": round(float(last['Volume'] / max(hist['Volume'].mean(), 1)), 2),
                "Status": "Uptrend" if (last.get('EMA200') and last['Close'] > last['EMA200']) else "Neutral/Downtrend"
            }
            return f"Market Data Summary for {symbol}: {summary}"
        except Exception as e:
            return f"Tool Error: {str(e)}"

    def run_analysis(self):
        # 1. Define Agents (Passing model name as STRING)
        
        technical_analyst = Agent(
            role='Senior Technical Analyst',
            goal=f'Analyze price trends and supply/demand for {self.symbol}',
            backstory="Experienced with candlestick patterns and momentum indicators like RSI and EMA.",
            verbose=True,
            allow_delegation=False,
            llm=self.llm_name # Using string to trigger CrewAI auto-init
        )

        researcher = Agent(
            role='Market Catalyst Researcher',
            goal=f'Identify news and events driving {self.symbol}',
            backstory="Specialist in interpreting market news and business growth catalysts.",
            verbose=True,
            allow_delegation=False,
            llm=self.llm_name
        )

        risk_manager = Agent(
            role='Trading Risk Manager',
            goal=f'Formulate a precise entry and exit plan for {self.symbol}',
            backstory="Prioritizes capital preservation and disciplined risk/reward ratios.",
            verbose=True,
            allow_delegation=False,
            llm=self.llm_name
        )

        # 2. Define Tasks
        task_technical = Task(
            description=f"Analyze the technical state of {self.symbol}. Data: {self.get_stock_data_tool(self.symbol)}",
            expected_output="A report identifying the trend quality and critical support/resistance levels.",
            agent=technical_analyst
        )

        task_news = Task(
            description=f"Identify the latest sentiment and news for {self.symbol}. Search for catalysts.",
            expected_output="A summary of the current market story and sentiment direction.",
            agent=researcher
        )

        task_risk = Task(
            description=f"Combine all data to create a final Thai-language investment plan (Entry, SL, Target).",
            expected_output="A professional recommendation report in Thai language with clear action steps.",
            agent=risk_manager
        )

        # 3. Form and Execute the Crew
        crew = Crew(
            agents=[technical_analyst, researcher, risk_manager],
            tasks=[task_technical, task_news, task_risk],
            process=Process.sequential,
            verbose=True
        )

        try:
            result = crew.kickoff()
            return str(result)
        except Exception as e:
            return f"Crew execution failed: {str(e)}"
