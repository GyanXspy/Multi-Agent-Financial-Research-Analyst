"""
Filings Agent — Fetches and analyzes corporate disclosures (SEC EDGAR filings).
Extracts MD&A and Risk Factors sections, summarises with LLM.

NOTE: For MVP, this agent uses SEC EDGAR's full-text search API. If filings
are not found (e.g., for non-US stocks), it returns a graceful fallback.
"""

import json
import logging
import time
from typing import Any, Dict, Optional

import httpx
from bs4 import BeautifulSoup
from langchain_google_genai import ChatGoogleGenerativeAI

from app.config import settings

logger = logging.getLogger(__name__)

# SEC EDGAR requires a User-Agent header with your identity
SEC_HEADERS = {
    "User-Agent": "MultiAgentFinancialAnalyst research@example.com",
    "Accept-Encoding": "gzip, deflate",
}

# Module-level cache for the SEC ticker→CIK map (~15 MB download otherwise
# repeated on every request). Refreshed once per 24 hours.
_CIK_CACHE: Dict[str, Any] = {"map": None, "fetched_at": 0.0}
_CIK_TTL_SECONDS = 24 * 3600


async def _get_cik_map(client: httpx.AsyncClient) -> Dict[str, str]:
    """Return {TICKER: zero-padded CIK} using a 24h in-memory cache."""
    now = time.time()
    if _CIK_CACHE["map"] is not None and now - _CIK_CACHE["fetched_at"] < _CIK_TTL_SECONDS:
        return _CIK_CACHE["map"]

    resp = await client.get("https://www.sec.gov/files/company_tickers.json")
    resp.raise_for_status()
    data = resp.json()

    cik_map = {
        entry.get("ticker", "").upper(): str(entry["cik_str"]).zfill(10)
        for entry in data.values()
        if entry.get("ticker")
    }
    _CIK_CACHE["map"] = cik_map
    _CIK_CACHE["fetched_at"] = now
    logger.info("FilingsAgent: refreshed SEC CIK map (%d tickers)", len(cik_map))
    return cik_map


class FilingsAgent:
    """Downloads and analyzes SEC filings (10-K, 10-Q) for a given ticker."""

    def __init__(self):
        self.llm = ChatGoogleGenerativeAI(
            model=settings.FILINGS_MODEL,
            google_api_key=settings.GEMINI_API_KEY,
            temperature=0.1,
            max_retries=3,
        )

    async def collect(self, symbol: str) -> Dict[str, Any]:
        """
        Fetch and analyze the latest SEC filing for the given symbol.

        Returns a dict with 'summary', 'risks', 'strategic_shifts', and 'source'.
        """
        logger.info("FilingsAgent: collecting filings for %s", symbol)

        # Strip exchange suffixes for EDGAR lookup (e.g., AAPL, not AAPL.NS)
        clean_symbol = symbol.split(".")[0]

        try:
            filing_text = await self._fetch_latest_filing(clean_symbol)
        except Exception as e:
            logger.warning("FilingsAgent: could not fetch filing for %s: %s", symbol, e)
            return {
                "summary": f"No SEC filings available for {symbol}. This may be a non-US listed company.",
                "risks": [],
                "strategic_shifts": [],
                "source": "N/A",
            }

        if not filing_text or len(filing_text.strip()) < 200:
            logger.info("FilingsAgent: insufficient filing content for %s", symbol)
            return {
                "summary": f"Filing content for {symbol} was too short to analyze meaningfully.",
                "risks": [],
                "strategic_shifts": [],
                "source": "SEC EDGAR",
            }

        # Summarize the filing using LLM
        analysis = await self._summarize_filing(filing_text[:15000], clean_symbol)
        logger.info("FilingsAgent: completed analysis for %s", symbol)
        return analysis

    async def _fetch_latest_filing(self, symbol: str) -> str:
        """
        Fetch the latest 10-K or 10-Q filing text from SEC EDGAR.
        Resolves the CIK from the (cached) SEC ticker map, then downloads
        the most recent 10-K/10-Q primary document.
        """
        async with httpx.AsyncClient(timeout=settings.EDGAR_TIMEOUT, headers=SEC_HEADERS) as client:
            # Step 1: Resolve CIK from cached ticker map
            cik_map = await _get_cik_map(client)
            cik: Optional[str] = cik_map.get(symbol.upper())

            if not cik:
                raise ValueError(f"CIK not found for symbol {symbol}")

            # Step 2: Get recent filings
            filings_url = f"https://data.sec.gov/submissions/CIK{cik}.json"
            filings_resp = await client.get(filings_url)
            filings_resp.raise_for_status()
            filings_data = filings_resp.json()

            recent = filings_data.get("filings", {}).get("recent", {})
            forms = recent.get("form", [])
            accession_numbers = recent.get("accessionNumber", [])
            primary_docs = recent.get("primaryDocument", [])

            # Find first 10-K or 10-Q
            filing_url = None
            for i, form in enumerate(forms):
                if form in ("10-K", "10-Q"):
                    accession = accession_numbers[i].replace("-", "")
                    doc = primary_docs[i]
                    filing_url = f"https://www.sec.gov/Archives/edgar/data/{cik.lstrip('0')}/{accession}/{doc}"
                    break

            if not filing_url:
                raise ValueError(f"No 10-K/10-Q filings found for {symbol}")

            # Step 3: Download and parse the filing HTML
            filing_resp = await client.get(filing_url)
            filing_resp.raise_for_status()

            soup = BeautifulSoup(filing_resp.text, "html.parser")

            # Extract text content (strip HTML tags)
            text = soup.get_text(separator="\n", strip=True)
            return text

    async def _summarize_filing(self, text: str, symbol: str) -> Dict[str, Any]:
        """Use LLM to extract key insights from filing text."""
        prompt = f"""You are a senior financial analyst reviewing the latest SEC filing for {symbol}.

Analyze the following filing excerpt and extract:

1. **Summary**: A concise 3-4 sentence overview of the company's disclosed financial position and strategic direction.
2. **Key Risks**: A list of the top 3-5 risks mentioned in the filing (emerging risks, regulatory concerns, market threats).
3. **Strategic Shifts**: Year-over-year changes in strategy, new initiatives, or management priorities.

Filing excerpt:
{text}

Return your analysis as a structured JSON object (no markdown fences):
{{
  "summary": "...",
  "risks": ["risk1", "risk2", "risk3"],
  "strategic_shifts": ["shift1", "shift2"],
  "source": "SEC EDGAR"
}}"""

        try:
            response = await self.llm.ainvoke(prompt)
            content = response.content.strip()

            # Strip markdown code fences if present
            if content.startswith("```"):
                content = content.split("\n", 1)[1]
                content = content.rsplit("```", 1)[0]
                content = content.strip()

            return json.loads(content)
        except Exception as e:
            logger.warning("FilingsAgent: LLM summary parsing failed: %s", e)
            return {
                "summary": f"Filing was retrieved for {symbol} but LLM analysis encountered an error.",
                "risks": [],
                "strategic_shifts": [],
                "source": "SEC EDGAR",
            }
