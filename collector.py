"""Signal Scout – RSS feed collector."""

import logging
import re
from datetime import datetime, timedelta

import feedparser

logger = logging.getLogger(__name__)


def fetch_feeds(feeds, max_age_days=7):
    """Fetch items from a list of RSS/Atom feeds.

    Returns a list of dicts with keys:
        title, url, source, published_at, snippet
    """
    cutoff = datetime.utcnow() - timedelta(days=max_age_days)
    items = []

    for feed_cfg in feeds:
        try:
            feed = feedparser.parse(feed_cfg["url"])
            source = feed_cfg["name"]

            for entry in feed.entries:
                published = _parse_date(entry)
                if published and published < cutoff:
                    continue

                title = entry.get("title", "").strip()
                url = entry.get("link", "").strip()
                snippet = entry.get("summary", entry.get("description", ""))
                snippet = _strip_html(snippet)[:500]

                if not url or not title:
                    continue

                items.append(
                    {
                        "title": title,
                        "url": url,
                        "source": source,
                        "published_at": (
                            published.isoformat()
                            if published
                            else datetime.utcnow().isoformat()
                        ),
                        "snippet": snippet,
                    }
                )
        except Exception as exc:
            logger.warning("Failed to fetch feed '%s': %s", feed_cfg["name"], exc)

    return items


def _parse_date(entry):
    """Best-effort date extraction from a feed entry."""
    for field in ("published_parsed", "updated_parsed"):
        val = entry.get(field)
        if val:
            try:
                return datetime(*val[:6])
            except (TypeError, ValueError):
                continue
    return None


def _strip_html(text):
    """Remove HTML tags and collapse whitespace."""
    text = re.sub(r"<[^>]+>", " ", text)
    return re.sub(r"\s+", " ", text).strip()
