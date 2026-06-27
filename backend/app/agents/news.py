"""
News Agent — Retrieves real-time financial news by scraping RSS feeds using BeautifulSoup,
filters for financial materiality using an LLM, and tags catalyst sentiment.
"""

import json
import logging
import urllib.parse
from typing import Any, Dict, List

import httpx
from bs4 import BeautifulSoup
from langchain_google_genai import ChatGoogleGenerativeAI

from app.config import settings

logger = logging.getLogger(__name__)


class NewsAgent:
    """Fetches and filters financially material news for a given stock."""

    def __init__(self):
        self.llm = ChatGoogleGenerativeAI(
            model=settings.NEWS_MODEL,
            google_api_key=settings.GEMINI_API_KEY,
            temperature=0.1,
            max_retries=3,
        )

    async def collect(self, symbol: str) -> Dict[str, Any]:
        """
        Fetch recent news articles for the symbol and filter for materiality.

        Returns a dict with key 'articles' containing a list of material articles,
        each with title, summary, url, source, and catalyst sentiment.
        """
        logger.info("NewsAgent: fetching news for %s", symbol)

        # Strip exchange suffixes for cleaner search queries (e.g., RELIANCE.NS → RELIANCE)
        search_term = symbol.split(".")[0]

        try:
            # Use Google News RSS for real-time news (free, no API key needed)
            encoded_query = urllib.parse.quote(f"{search_term} stock financial news")
            url = f"https://news.google.com/rss/search?q={encoded_query}&hl=en-US&gl=US&ceid=US:en"

            async with httpx.AsyncClient(timeout=settings.NEWS_API_TIMEOUT) as client:
                response = await client.get(url)
                response.raise_for_status()
                
                # Parse the XML/RSS feed using BeautifulSoup
                soup = BeautifulSoup(response.text, features="html.parser")
                items = soup.find_all("item")
                
                articles = []
                # Limit to 15 most recent articles
                for item in items[:15]:
                    title = item.find("title").text if item.find("title") else ""
                    link = item.find("link").text if item.find("link") else ""
                    pub_date = item.find("pubdate").text if item.find("pubdate") else ""
                    source = item.find("source").text if item.find("source") else "Unknown"
                    
                    articles.append({
                        "title": title,
                        "description": "", # RSS descriptions are often messy HTML, we'll let LLM infer from title
                        "url": link,
                        "source": source,
                        "publishedAt": pub_date,
                    })
                    
        except httpx.TimeoutException:
            logger.warning("NewsAgent: News request timed out for %s", symbol)
            return {"articles": [], "error": "News request timed out"}
        except Exception as e:
            logger.error("NewsAgent: failed to fetch news for %s: %s", symbol, e)
            return {"articles": [], "error": str(e)}

        if not articles:
            logger.info("NewsAgent: no articles found for %s", symbol)
            return {"articles": []}

        # Format articles for LLM filtering
        formatted_articles = articles

        # Use LLM to filter for financially material news
        filtered = await self._filter_material_news(formatted_articles, search_term)

        logger.info("NewsAgent: completed for %s — %d material articles", symbol, len(filtered))
        return {"articles": filtered}

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
            response = await self.llm.ainvoke(prompt)
            content = response.content.strip()

            # Strip markdown code fences if present
            if content.startswith("```"):
                content = content.split("\n", 1)[1]  # remove first line
                content = content.rsplit("```", 1)[0]  # remove closing fence
                content = content.strip()

            return json.loads(content)
        except (json.JSONDecodeError, Exception) as e:
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
