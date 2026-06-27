"""
Peer Comparison Agent — Identifies industry peers and computes
relative valuation metrics for competitive analysis.
"""

import logging
from typing import Any, Dict, List

import yfinance as yf
from langchain_google_genai import ChatGoogleGenerativeAI

from app.config import settings

logger = logging.getLogger(__name__)

# Sector → default peer tickers mapping
SECTOR_PEERS: Dict[str, List[str]] = {
    "Technology": ["AAPL", "MSFT", "GOOGL", "AMZN", "META", "NVDA"],
    "Financial Services": ["JPM", "BAC", "WFC", "C", "GS", "MS"],
    "Consumer Cyclical": ["TSLA", "AMZN", "HD", "NKE", "MCD", "SBUX"],
    "Healthcare": ["JNJ", "UNH", "PFE", "ABBV", "MRK", "LLY"],
    "Communication Services": ["GOOGL", "META", "DIS", "NFLX", "CMCSA", "T"],
    "Consumer Defensive": ["PG", "KO", "PEP", "WMT", "COST", "CL"],
    "Energy": ["XOM", "CVX", "COP", "SLB", "EOG", "MPC"],
    "Industrials": ["GE", "CAT", "BA", "HON", "UPS", "RTX"],
    "Basic Materials": ["LIN", "APD", "SHW", "ECL", "FCX", "NEM"],
    "Real Estate": ["PLD", "AMT", "CCI", "EQIX", "SPG", "O"],
    "Utilities": ["NEE", "DUK", "SO", "D", "AEP", "EXC"],
}


class PeerComparisonAgent:
    """Evaluates a company's performance relative to industry competitors."""

    def __init__(self):
        self.llm = ChatGoogleGenerativeAI(
            model=settings.FINANCIAL_MODEL,
            google_api_key=settings.GEMINI_API_KEY,
            temperature=0.1,
            max_retries=3,
        )

    async def collect(self, symbol: str) -> Dict[str, Any]:
        """
        Identify peers and fetch comparable financial metrics.

        Returns a dict with 'sector', 'target' metrics, and 'peers' list.
        """
        logger.info("PeerComparisonAgent: collecting peers for %s", symbol)

        try:
            main_ticker = yf.Ticker(symbol)
            main_info = main_ticker.info
        except Exception as e:
            logger.error("PeerComparisonAgent: failed to fetch info for %s: %s", symbol, e)
            return {"sector": "Unknown", "target": {}, "peers": [], "error": str(e)}

        sector = main_info.get("sector", "Unknown")
        industry = main_info.get("industry", "Unknown")

        # Get target company metrics
        target_metrics = self._extract_metrics(main_info, symbol)

        # Get peer symbols — exclude the target company
        peer_symbols = self._get_peers(sector, symbol)

        # Fetch metrics for each peer
        peers_data = []
        for peer_sym in peer_symbols:
            try:
                peer_ticker = yf.Ticker(peer_sym)
                peer_info = peer_ticker.info
                peer_metrics = self._extract_metrics(peer_info, peer_sym)
                if peer_metrics.get("market_cap"):  # Only include if we got real data
                    peers_data.append(peer_metrics)
            except Exception as e:
                logger.warning("PeerComparisonAgent: failed to fetch peer %s: %s", peer_sym, e)
                continue

        result = {
            "sector": sector,
            "industry": industry,
            "target": target_metrics,
            "peers": peers_data,
        }

        logger.info(
            "PeerComparisonAgent: completed for %s — sector=%s, %d peers fetched",
            symbol, sector, len(peers_data),
        )
        return result

    def _extract_metrics(self, info: Dict, symbol: str) -> Dict[str, Any]:
        """Extract standardised comparison metrics from a yfinance info dict."""
        roe_raw = info.get("returnOnEquity")
        margin_raw = info.get("profitMargins")

        return {
            "ticker": symbol,
            "name": info.get("shortName", symbol),
            "market_cap": info.get("marketCap"),
            "pe_ratio": info.get("trailingPE"),
            "ev_ebitda": info.get("enterpriseToEbitda"),
            "pb_ratio": info.get("priceToBook"),
            "roe": round(roe_raw * 100, 2) if roe_raw is not None else None,
            "net_margin": round(margin_raw * 100, 2) if margin_raw is not None else None,
            "revenue_growth": info.get("revenueGrowth"),
            "current_price": info.get("currentPrice") or info.get("regularMarketPrice"),
        }

    def _get_peers(self, sector: str, current_symbol: str) -> List[str]:
        """Look up peer symbols from sector map, excluding the current symbol."""
        clean_symbol = current_symbol.split(".")[0].upper()
        peers = SECTOR_PEERS.get(sector, ["AAPL", "MSFT", "GOOGL", "AMZN"])
        return [p for p in peers if p.upper() != clean_symbol][:4]
