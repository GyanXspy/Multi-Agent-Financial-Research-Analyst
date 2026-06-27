"""
Thesis Writer Agent — Synthesizes all agent outputs into a comprehensive,
structured investment research report in Markdown format.

Supports both full generation and token-by-token streaming.
"""

import logging
from typing import Any, Dict

from langchain_google_genai import ChatGoogleGenerativeAI

from app.config import settings

logger = logging.getLogger(__name__)


class ThesisWriterAgent:
    """Generates a structured equity research report from aggregated agent data."""

    def __init__(self):
        self.llm = ChatGoogleGenerativeAI(
            model=settings.THESIS_MODEL,
            google_api_key=settings.GEMINI_API_KEY,
            temperature=0.3,
            max_retries=3,
        )

    async def generate_report(self, data: Dict[str, Any]) -> str:
        """Generate the full report in one shot. Returns the complete markdown string."""
        logger.info("ThesisWriterAgent: generating report for %s", data.get("symbol"))
        prompt = self._build_prompt(data)
        response = await self.llm.ainvoke(prompt)
        logger.info("ThesisWriterAgent: report generation complete for %s", data.get("symbol"))
        return response.content

    async def stream_report(self, data: Dict[str, Any]):
        """
        Async generator that yields report text chunks in real-time.
        Used by the SSE endpoint for streaming the report to the frontend.
        """
        logger.info("ThesisWriterAgent: streaming report for %s", data.get("symbol"))
        prompt = self._build_prompt(data)

        async for chunk in self.llm.astream(prompt):
            if chunk.content:
                yield chunk.content

        logger.info("ThesisWriterAgent: streaming complete for %s", data.get("symbol"))

    def _build_prompt(self, data: Dict[str, Any]) -> str:
        """Construct the master prompt for the Thesis Writer with all collected data."""
        symbol = data.get("symbol", "UNKNOWN")

        # Extract sub-data with safe defaults
        financials = data.get("financials", {})
        news = data.get("news", {})
        filings = data.get("filings", {})
        peers = data.get("peers", {})

        return f"""You are a Senior Equity Research Analyst at a top-tier investment bank.
Produce a comprehensive, professional-grade investment research report for **{symbol}**.

Use ONLY the following collected data — do not fabricate numbers or facts.
If data is missing for a section, note it as "Data not available" rather than inventing content.

---
### COLLECTED DATA

**Financial Metrics:**
{financials}

**Recent Material News:**
{news}

**SEC Filing Analysis:**
{filings}

**Peer Comparison Data:**
{peers}

---

Format the report strictly as Markdown with the following 10 sections:

# Equity Research Report: {symbol}

## 1. Executive Summary
A concise 3-4 sentence summary: investment stance (Buy/Hold/Sell), key thesis drivers, and critical highlights.

## 2. Company Overview
Business model description, sector context, key products/services, and competitive positioning.

## 3. Financial Performance Analysis
Review of revenue trajectory, profitability margins (ROE, EBITDA margin), earnings growth, and balance sheet health. Include specific numbers from the data.

## 4. Recent News Highlights
Synthesis of material news developments. Flag positive and negative catalysts separately.

## 5. Regulatory Filing Insights
Key takeaways from SEC filings — strategic shifts, risk disclosures, and management commentary.

## 6. Peer Comparison
Present a **Markdown table** comparing the target company against peers across: P/E, EV/EBITDA, P/B, ROE, Net Margin, and Market Cap. Include a brief narrative on relative positioning.

## 7. Bull Case
3-5 specific upside factors with supporting evidence from the data.

## 8. Bear Case
3-5 specific downside risks with supporting evidence from the data.

## 9. Key Risks
A **Markdown table** covering Macroeconomic, Operational, Regulatory, and Competitive risks. Use exactly these three columns: 'Risk Category', 'Specific Risk', and 'Impact Level'. Keep row contents concise and do not use repeating characters.

## 10. Investment Conclusion
Final investment grade (Buy/Hold/Sell), target thesis summary, and valuation justification.

---
Write in a professional, analytical tone. Use bullet points and tables where appropriate.
Be specific — reference actual numbers from the collected data."""
