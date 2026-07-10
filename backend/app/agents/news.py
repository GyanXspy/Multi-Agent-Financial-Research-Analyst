"""
News Agent — Retrieves recent financial news, filters for financial
materiality using an LLM, and tags catalyst sentiment.

Production features:
- Redis caching (prevents redundant NewsAPI / LLM calls)
- Resilient LLM calls with timeouts and retries
- Request coalescing for concurrent requests on same symbol

Data sources (in priority order):
1. NewsAPI (https://newsapi.org) — primary, requires NEWS_API_KEY.
2. Google News RSS — free fallback when the key is missing or NewsAPI fails.
"""

import json
import logging
import urllib.parse
from typing import Any, Dict, List

import httpx
from bs4 import BeautifulSoup
from langchain_google_genai import ChatGoogleGenerativeAI

from app import cache
from app.config import settings
from app.resilience import resilient_ainvoke

logger = logging.getLogger(__name__)

MAX_ARTICLES = 15


class NewsAgent:
    """Fetches and filters financially material news for a given stock."""

    def __init__(self):
        self.llm = ChatGoogleGenerativeAI(
            model=settings.NEWS_MODEL,
            google_api_key=settings.GEMINI_API_KEY,
            temperature=0.1,
            max_retries=settings.LLM_MAX_RETRIES,
        )

    async def collect(self, symbol: str) -> Dict[str, Any]:
        """
        Fetch recent news articles for the symbol and filter for materiality.
        Results are cached in Redis to prevent redundant API and LLM calls.

        Returns a dict with key 'articles' (list of material articles with
        title, summary, url, source, catalyst) and 'provider' (which source was used).
        """
        cache_key = f"news:{symbol}"

        async def _fetch():
            return await self._collect_uncached(symbol)

        return await cache.get_or_set(cache_key, settings.CACHE_TTL_NEWS, _fetch)

    async def _collect_uncached(self, symbol: str) -> Dict[str, Any]:
        """Core collection logic — fetches from news sources and filters with LLM."""
        logger.info("NewsAgent: fetching news for %s", symbol)

        # Strip exchange suffixes for cleaner search queries (e.g., RELIANCE.NS → RELIANCE)
        search_term = symbol.split(".")[0].lstrip("^")

        articles: List[Dict] = []
        provider = "none"

        # ── Primary: NewsAPI ──
        if settings.NEWS_API_KEY:
            try:
                articles = await self._fetch_newsapi(search_term)
                provider = "newsapi"
            except Exception as e:
                logger.warning("NewsAgent: NewsAPI failed for %s (%s), falling back to RSS", symbol, e)

        # ── Fallback: Google News RSS ──
        if not articles:
            try:
                articles = await self._fetch_google_rss(search_term)
                provider = "google_rss"
            except Exception as e:
                logger.error("NewsAgent: all news sources failed for %s: %s", symbol, e)
                return {"articles": [], "provider": "none", "error": str(e)}

        if not articles:
            logger.info("NewsAgent: no articles found for %s", symbol)
            return {"articles": [], "provider": provider}

        # Use LLM to filter for financially material news
        filtered = await self._filter_material_news(articles, search_term)

        logger.info("NewsAgent: completed for %s — %d material articles via %s", symbol, len(filtered), provider)
        return {"articles": filtered, "provider": provider}

    async def _fetch_newsapi(self, search_term: str) -> List[Dict]:
        """Fetch recent articles from NewsAPI. API key sent via header, not URL."""
        url = "https://newsapi.org/v2/everything"
        params = {
            "q": f'"{search_term}" AND (stock OR shares OR earnings OR revenue)',
            "sortBy": "publishedAt",
            "language": "en",
            "pageSize": MAX_ARTICLES,
        }
        headers = {"X-Api-Key": settings.NEWS_API_KEY}

        async with httpx.AsyncClient(timeout=settings.NEWS_API_TIMEOUT) as client:
            response = await client.get(url, params=params, headers=headers)
            response.raise_for_status()
            payload = response.json()

        if payload.get("status") != "ok":
            raise RuntimeError(f"NewsAPI error: {payload.get('message', 'unknown')}")

        return [
            {
                "title": a.get("title") or "",
                "description": (a.get("description") or "")[:300],
                "url": a.get("url") or "",
                "source": (a.get("source") or {}).get("name", "Unknown"),
                "publishedAt": a.get("publishedAt") or "",
            }
            for a in payload.get("articles", [])[:MAX_ARTICLES]
            if a.get("title") and a.get("title") != "[Removed]"
        ]

    async def _fetch_google_rss(self, search_term: str) -> List[Dict]:
        """Fetch recent articles from Google News RSS (no API key required)."""
        encoded_query = urllib.parse.quote(f"{search_term} stock financial news")
        url = f"https://news.google.com/rss/search?q={encoded_query}&hl=en-US&gl=US&ceid=US:en"

        async with httpx.AsyncClient(timeout=settings.NEWS_API_TIMEOUT) as client:
            response = await client.get(url)
            response.raise_for_status()

        # RSS is XML — parse with the xml parser, not the html one
        soup = BeautifulSoup(response.text, features="xml")
        items = soup.find_all("item")

        articles = []
        for item in items[:MAX_ARTICLES]:
            title = item.find("title").text if item.find("title") else ""
            link = item.find("link").text if item.find("link") else ""
            pub_date = item.find("pubDate").text if item.find("pubDate") else ""
            source = item.find("source").text if item.find("source") else "Unknown"
            if title:
                articles.append({
                    "title": title,
                    "description": "",  # RSS descriptions are messy HTML; LLM infers from title
                    "url": link,
                    "source": source,
                    "publishedAt": pub_date,
                })
        return articles

    async def _filter_material_news(self, articles: List[Dict], company: str) -> List[Dict]:
        """Use Gemini to classify articles by financial materiality and catalyst sentiment."""
        prompt = f"""You are a financial news analyst. Analyze the following news articles about {company}.

For each article, determine if it is financially material (relevant to investment decisions).
Filter out clickbait, rumors, duplicates, and non-material articles.
For material articles, classify the catalyst sentiment as positive, negative, or neutral.

Articles:
{json.dumps(articles, indent=2)}

Return ONLY a valid JSON array (no markdown fences, no explanation) with this schema:
[
  {{
    "title": "Article headline",
    "summary": "One-sentence summary of the key financial implication",
    "url": "Original article URL",
    "source": "Publication name",
    "catalyst": "positive|negative|neutral"
  }}
]

If no articles are material, return an empty array: []"""

        try:
            response = await resilient_ainvoke(
                self.llm, prompt, timeout=60, label="NewsAgent.filter"
            )
            content = response.content.strip()

            # Strip markdown code fences if present
            if content.startswith("```"):
                content = content.split("\n", 1)[1]  # remove first line
                content = content.rsplit("```", 1)[0]  # remove closing fence
                content = content.strip()

            parsed = json.loads(content)
            if not isinstance(parsed, list):
                raise ValueError("LLM returned non-list JSON")
            return parsed
        except Exception as e:
            logger.warning("NewsAgent: LLM filtering failed, returning raw articles: %s", e)
            # Fallback: return articles without LLM filtering
            return [
                {
                    "title": a.get("title", ""),
                    "summary": a.get("description", ""),
                    "url": a.get("url", ""),
                    "source": a.get("source", ""),
                    "catalyst": "neutral",
                }
                for a in articles[:5]
            ]
