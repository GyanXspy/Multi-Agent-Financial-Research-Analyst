"""
Financial Data Agent — Retrieves quantitative financial information
from Yahoo Finance (yfinance) and computes valuation & operational metrics.

All yfinance calls are blocking, so they run in a worker thread via
asyncio.to_thread — this keeps the multi-agent fan-out genuinely parallel.
"""

import asyncio
import logging
from typing import Any, Dict

import yfinance as yf

logger = logging.getLogger(__name__)


def _fetch_all(symbol: str) -> Dict[str, Any]:
    """Blocking bundle: info, 1y history, and financial statements in one thread hop."""
    ticker = yf.Ticker(symbol)
    return {
        "info": ticker.info,
        "history": ticker.history(period="1y"),
        "income_stmt": ticker.income_stmt,
        "balance_sheet": ticker.balance_sheet,
    }


class FinancialDataAgent:
    """Fetches stock prices, financial statements, and computes key ratios."""

    async def collect(self, symbol: str) -> Dict[str, Any]:
        """
        Collect financial data for the given ticker symbol.

        Returns a dictionary containing current price, valuation metrics,
        operational metrics, and recent price history.
        """
        logger.info("FinancialDataAgent: collecting data for %s", symbol)

        try:
            bundle = await asyncio.to_thread(_fetch_all, symbol)
        except Exception as e:
            logger.error("FinancialDataAgent: failed to fetch data for %s: %s", symbol, e)
            return {"error": str(e)}

        info = bundle["info"] or {}
        history = bundle["history"]
        income_stmt = bundle["income_stmt"]
        balance_sheet = bundle["balance_sheet"]

        # --- Valuation Metrics (directly from info) ---
        pe_ratio = info.get("trailingPE")
        pb_ratio = info.get("priceToBook")
        market_cap = info.get("marketCap")
        eps = info.get("trailingEps")
        ev_ebitda = info.get("enterpriseToEbitda")

        # --- Operational Metrics (prefer statement-level calculation, fallback to info) ---
        revenue = None
        net_income = None
        roe = None
        ebitda_margin = None

        try:
            if income_stmt is not None and not income_stmt.empty:
                revenue = income_stmt.loc["Total Revenue"].iloc[0] if "Total Revenue" in income_stmt.index else None
                net_income = income_stmt.loc["Net Income"].iloc[0] if "Net Income" in income_stmt.index else None
                ebitda = income_stmt.loc["EBITDA"].iloc[0] if "EBITDA" in income_stmt.index else None

                if ebitda and revenue:
                    ebitda_margin = round((ebitda / revenue) * 100, 2)

            if balance_sheet is not None and not balance_sheet.empty:
                equity = (
                    balance_sheet.loc["Stockholders Equity"].iloc[0]
                    if "Stockholders Equity" in balance_sheet.index
                    else None
                )
                if net_income and equity and equity != 0:
                    roe = round((net_income / equity) * 100, 2)
        except Exception as e:
            logger.warning("FinancialDataAgent: statement parsing failed for %s, using info fallback: %s", symbol, e)

        # Fallback to info dict if statements didn't yield values
        if revenue is None:
            revenue = info.get("totalRevenue")
        if net_income is None:
            net_income = info.get("netIncomeToCommon")
        if roe is None:
            roe_raw = info.get("returnOnEquity")
            roe = round(roe_raw * 100, 2) if roe_raw is not None else None
        if ebitda_margin is None:
            margin_raw = info.get("ebitdaMargins")
            ebitda_margin = round(margin_raw * 100, 2) if margin_raw is not None else None

        # --- Price History (1 year, weekly closes ≈ 52 points — chart-friendly) ---
        price_history = []
        history_dates = []
        if history is not None and not history.empty:
            weekly = history["Close"].resample("W").last().dropna()
            price_history = [round(float(p), 2) for p in weekly.tolist()]
            history_dates = [d.strftime("%Y-%m-%d") for d in weekly.index]

        result = {
            "company_name": info.get("shortName", symbol),
            "current_price": info.get("currentPrice") or info.get("regularMarketPrice"),
            "currency": info.get("currency", "USD"),
            "market_cap": market_cap,
            "pe_ratio": pe_ratio,
            "pb_ratio": pb_ratio,
            "ev_ebitda": ev_ebitda,
            "roe": roe,
            "ebitda_margin": ebitda_margin,
            "revenue": revenue,
            "net_income": net_income,
            "eps": eps,
            "dividend_yield": info.get("dividendYield"),
            "fifty_two_week_high": info.get("fiftyTwoWeekHigh"),
            "fifty_two_week_low": info.get("fiftyTwoWeekLow"),
            "sector": info.get("sector"),
            "industry": info.get("industry"),
            "price_history_1y": price_history,
            "price_history_dates": history_dates,
        }

        logger.info("FinancialDataAgent: completed for %s — price=%s", symbol, result["current_price"])
        return result
