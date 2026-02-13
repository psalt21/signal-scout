"""Signal Scout – LLM summarization (with no-key fallback)."""

import json
import logging

import requests

logger = logging.getLogger(__name__)


def summarize_items(items, topic_name, keywords, api_key, api_url, model):
    """Summarize a batch of items.  Returns a list of result dicts.

    Each result: {id, summary, why_it_matters, tags, relevance_score}
    """
    if not api_key:
        logger.info("No LLM API key – using keyword-only fallback.")
        return _fallback_summarize(items, keywords)

    results = []
    for item in items:
        try:
            data = _call_llm(item, topic_name, keywords, api_key, api_url, model)
            results.append({"id": item["id"], **data})
        except Exception as exc:
            logger.warning("LLM call failed for item %s: %s", item["id"], exc)
            results.append(
                {
                    "id": item["id"],
                    "summary": (item.get("snippet") or "")[:200],
                    "why_it_matters": "Summary unavailable (LLM error).",
                    "tags": _keyword_tags(item, keywords),
                    "relevance_score": _keyword_score(item, keywords),
                }
            )
    return results


# ── LLM call ─────────────────────────────────────────────────────────────────

def _call_llm(item, topic_name, keywords, api_key, api_url, model):
    prompt = (
        f'You are a content curator for the topic: "{topic_name}".\n'
        f"Keywords of interest: {', '.join(keywords)}\n\n"
        f"Given this article:\n"
        f"Title: {item['title']}\n"
        f"Source: {item['source']}\n"
        f"Snippet: {(item.get('snippet') or 'N/A')[:400]}\n\n"
        "Respond with ONLY valid JSON (no markdown fences):\n"
        "{\n"
        '  "summary": "1-2 sentence summary",\n'
        '  "why_it_matters": "1 sentence on relevance to the topic",\n'
        '  "tags": ["tag1", "tag2", "tag3"],\n'
        '  "relevance_score": 50\n'
        "}"
    )

    resp = requests.post(
        api_url,
        headers={
            "Authorization": f"Bearer {api_key}",
            "Content-Type": "application/json",
        },
        json={
            "model": model,
            "messages": [{"role": "user", "content": prompt}],
            "temperature": 0.3,
            "max_tokens": 300,
        },
        timeout=30,
    )
    resp.raise_for_status()

    content = resp.json()["choices"][0]["message"]["content"].strip()

    # Strip optional markdown fences
    if content.startswith("```"):
        content = content.split("\n", 1)[-1]
        if content.endswith("```"):
            content = content[:-3]
        content = content.strip()

    data = json.loads(content)
    return {
        "summary": str(data.get("summary", ""))[:500],
        "why_it_matters": str(data.get("why_it_matters", ""))[:300],
        "tags": list(data.get("tags", []))[:6],
        "relevance_score": max(0, min(100, int(data.get("relevance_score", 50)))),
    }


# ── No-key fallback ─────────────────────────────────────────────────────────

def _fallback_summarize(items, keywords):
    return [
        {
            "id": item["id"],
            "summary": (item.get("snippet") or "No summary available.")[:200],
            "why_it_matters": "Matched by keyword relevance (no LLM key set).",
            "tags": _keyword_tags(item, keywords),
            "relevance_score": _keyword_score(item, keywords),
        }
        for item in items
    ]


def _keyword_tags(item, keywords):
    text = f"{item.get('title', '')} {item.get('snippet', '')}".lower()
    return [kw for kw in keywords if kw.lower() in text][:6]


def _keyword_score(item, keywords):
    text = f"{item.get('title', '')} {item.get('snippet', '')}".lower()
    hits = sum(1 for kw in keywords if kw.lower() in text)
    return min(100, hits * 15 + 10)
