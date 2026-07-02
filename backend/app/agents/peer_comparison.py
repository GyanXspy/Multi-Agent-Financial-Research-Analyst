"""
Peer Comparison Agent — Identifies industry peers and computes
relative valuation metrics for competitive analysis.
"""

import asyncio
import logging
from typing import Any, Dict, List, Optional

import yfinance as yf

logger = logging.getLogger(__name__)


def _fetch_info(symbol: str) -> Dict:
    """Blocking yfinance info fetch — always call via asyncio.to_thread."""
    return yf.Ticker(symbol).info or {}

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

    async def collect(self, symbol: str) -> Dict[str, Any]:
        """
        Identify peers and fetch comparable financial metrics.
        Peer lookups run concurrently in worker threads.

        Returns a dict with 'sector', 'target' metrics, and 'peers' list.
        """
        logger.info("PeerComparisonAgent: collecting peers for %s", symbol)

        try:
            main_info = await asyncio.to_thread(_fetch_info, symbol)
        except Exception as e:
            logger.error("PeerComparisonAgent: failed to fetch info for %s: %s", symbol, e)
            return {"sector": "Unknown", "target": {}, "peers": [], "error": str(e)}

        sector = main_info.get("sector", "Unknown")
        industry = main_info.get("industry", "Unknown")

        # Get target company metrics
        target_metrics = self._extract_metrics(main_info, symbol)

        # Get peer symbols — exclude the target company
        peer_symbols = self._get_peers(sector, symbol)

        # Fetch all peers concurrently
        async def fetch_peer(peer_sym: str) -> Optional[Dict[str, Any]]:
            try:
                peer_info = await asyncio.to_thread(_fetch_info, peer_sym)
                metrics = self._extract_metrics(peer_info, peer_sym)
                return metrics if metrics.get("market_cap") else None
            except Exception as e:
                logger.warning("PeerComparisonAgent: failed to fetch peer %s: %s", peer_sym, e)
                return None

        peer_results = await asyncio.gather(*(fetch_peer(p) for p in peer_symbols))
        peers_data = [p for p in peer_results if p is not None]

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
