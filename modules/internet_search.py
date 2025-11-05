"""Minimal web search helper for Advanced Access mode."""

from __future__ import annotations

import json
import urllib.parse
import urllib.request
from typing import List, Dict

from urllib.parse import urlparse


def _extract_domain(url: str) -> str:
    try:
        parsed = urlparse(url)
        return parsed.netloc or parsed.path.split("/")[0]
    except Exception:
        return ""


def search_web(query: str, max_results: int = 3) -> List[Dict[str, str]]:
    query = (query or "").strip()
    if not query:
        return []

    params = {
        "q": query,
        "format": "json",
        "no_html": "1",
        "skip_disambig": "1",
    }
    url = "https://api.duckduckgo.com/?" + urllib.parse.urlencode(params)
    req = urllib.request.Request(url, headers={"User-Agent": "NousAI/1.0"})

    try:
        with urllib.request.urlopen(req, timeout=10) as response:
            payload = response.read().decode("utf-8", errors="ignore")
    except Exception:
        return []

    try:
        data = json.loads(payload)
    except json.JSONDecodeError:
        return []

    results: List[Dict[str, str]] = []

    def add_result(item: Dict[str, str]):
        title = item.get("Text") or item.get("Heading") or item.get("FirstURL")
        url = item.get("FirstURL") or ""
        snippet = item.get("Result") or item.get("Text") or ""
        if not title:
            return
        results.append(
            {
                "title": title.strip(),
                "url": url.strip(),
                "snippet": snippet.strip(),
                "domain": _extract_domain(url),
            }
        )

    for entry in data.get("RelatedTopics", []):
        if len(results) >= max_results:
            break
        if "Topics" in entry:
            for sub in entry.get("Topics", []):
                add_result(sub)
                if len(results) >= max_results:
                    break
        else:
            add_result(entry)

    if len(results) < max_results:
        for entry in data.get("Results", []):
            add_result(entry)
            if len(results) >= max_results:
                break

    return results[:max_results]


__all__ = ["search_web"]

