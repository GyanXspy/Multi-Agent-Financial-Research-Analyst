"""
Coordinator Agent — Central orchestrator that interprets user queries,
identifies the target ticker, runs specialized worker agents in parallel,
aggregates results, and invokes the Thesis Writer for final report generation.

Production features:
- Resilient LLM calls with timeouts and retries
- Cached results via Redis (with in-memory fallback)
"""

import asyncio
import logging
import re
from typing import Any, Dict

from langchain_google_genai import ChatGoogleGenerativeAI

from app.agents.financial_data import FinancialDataAgent
from app.agents.news import NewsAgent
from app.agents.filings import FilingsAgent
from app.agents.peer_comparison import PeerComparisonAgent
from app.agents.thesis_writer import ThesisWriterAgent
from app.config import settings
from app.resilience import resilient_ainvoke

logger = logging.getLogger(__name__)

# Valid Yahoo Finance ticker shape: optional ^ prefix (indices), then
# uppercase letters/digits/dots/hyphens, max 12 chars (e.g. AAPL, RELIANCE.NS, ^GSPC)
TICKER_RE = re.compile(r"^\^?[A-Z0-9.\-]{1,12}$")


class CoordinatorAgent:
    """
    Primary entry point for the multi-agent research pipeline.

    Workflow:
    1. Extract ticker symbol from natural language query.
    2. Launch 4 worker agents in parallel.
    3. Aggregate outputs (with partial failure tolerance).
    4. Pass aggregated data to ThesisWriterAgent.
    5. Return the final structured response.
    """

    def __init__(self):
        self.llm = ChatGoogleGenerativeAI(
            model=settings.COORDINATOR_MODEL,
            google_api_key=settings.GEMINI_API_KEY,
            temperature=0.1,
            max_retries=settings.LLM_MAX_RETRIES,
        )
        self.financial_agent = FinancialDataAgent()
        self.news_agent = NewsAgent()
        self.filings_agent = FilingsAgent()
        self.peer_agent = PeerComparisonAgent()
        self.thesis_agent = ThesisWriterAgent()

    async def run(self, query: str) -> Dict[str, Any]:
        """
        Full pipeline execution: identify ticker → gather data → generate report.
        Returns a dict with 'symbol', 'data', 'report', and optional 'errors'.
        """
        logger.info("CoordinatorAgent: starting pipeline for query: %s", query)

        # Step 1: Extract ticker symbol
        symbol = await self.identify_ticker(query)
        logger.info("CoordinatorAgent: identified ticker → %s", symbol)

        # Step 2: Run all worker agents in parallel
        tasks = [
            self.financial_agent.collect(symbol),
            self.news_agent.collect(symbol),
            self.filings_agent.collect(symbol),
            self.peer_agent.collect(symbol),
        ]

        results = await asyncio.gather(*tasks, return_exceptions=True)

        # Step 3: Aggregate with partial failure tolerance
        errors: Dict[str, str] = {}

        def _safe_result(idx: int, name: str) -> Dict:
            if isinstance(results[idx], Exception):
                logger.error("CoordinatorAgent: %s agent failed: %s", name, results[idx])
                errors[name] = str(results[idx])
                return {}
            return results[idx]

        aggregated_data = {
            "symbol": symbol,
            "financials": _safe_result(0, "financial_data"),
            "news": _safe_result(1, "news"),
            "filings": _safe_result(2, "filings"),
            "peers": _safe_result(3, "peer_comparison"),
        }

        logger.info(
            "CoordinatorAgent: data aggregation complete — %d/%d agents succeeded",
            4 - len(errors), 4,
        )

        # Step 4: Generate the final report
        final_report = await self.thesis_agent.generate_report(aggregated_data)

        return {
            "symbol": symbol,
            "data": aggregated_data,
            "report": final_report,
            "errors": errors if errors else None,
        }

    async def identify_ticker(self, query: str) -> str:
        """
        Use the LLM to extract a stock ticker symbol from a natural language query.
        Raises ValueError if the resolved symbol is not a plausible ticker — this
        guards against prompt injection and LLM refusals leaking into API calls.
        """
        prompt = f"""Extract the stock ticker symbol from this query.

Query: "{query}"

Rules:
- Return ONLY the uppercase ticker symbol, nothing else.
- For Indian stocks on NSE, append '.NS' (e.g., RELIANCE.NS).
- For Indian stocks on BSE, append '.BO' (e.g., RELIANCE.BO).
- For US stocks, return the bare symbol (e.g., AAPL, TSLA, MSFT).
- For market indices, use the Yahoo Finance index ticker (e.g., ^NSEI for Nifty 50, ^BSESN for Sensex, ^GSPC for S&P 500, ^IXIC for Nasdaq).
- If a company name is given instead of a ticker, resolve it to the most common ticker.

Examples:
- "Analyze Apple" → AAPL
- "Research Reliance Industries" → RELIANCE.NS
- "TSLA valuation" → TSLA
- "What about Infosys?" → INFY.NS
- "Nifty 50 analysis" → ^NSEI
- "S&P 500 index" → ^GSPC

Return only the ticker symbol:"""

        response = await resilient_ainvoke(
            self.llm, prompt, timeout=30, label="CoordinatorAgent.identify_ticker"
        )
        symbol = response.content.strip().upper()

        # Clean up any extra formatting the LLM might add
        symbol = symbol.replace('"', "").replace("'", "").replace("`", "").strip()

        # Take first word if LLM returned extra text
        if " " in symbol:
            symbol = symbol.split()[0]

        if not TICKER_RE.match(symbol):
            logger.warning("CoordinatorAgent: rejected invalid ticker %r for query %r", symbol, query)
            raise ValueError(
                "Could not resolve a valid stock ticker from your query. "
                "Try a specific company name or ticker symbol (e.g. 'AAPL' or 'Analyze Reliance')."
            )

        logger.info("CoordinatorAgent: resolved ticker → %s", symbol)
        return symbol
