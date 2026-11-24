"""Optional HTTPS feeds enabled only by operator configuration."""

import json
import os
from datetime import UTC, datetime
from email.utils import parsedate_to_datetime
from urllib.parse import urlsplit

import httpx
from defusedxml import ElementTree


SOURCES = {"news.headlines": "NEWS", "market.quote": "MARKET", "lottery.draw": "LOTTERY"}


async def fetch(client, operation, key):
    prefix = f"ADSI_FEED_{SOURCES[operation]}"
    url = os.getenv(prefix + "_URL", "")
    credential = os.getenv(prefix + "_KEY", "")
    try:
        origin = urlsplit(url)
        if (origin.scheme != "https" or not origin.hostname or origin.username is not None or
                origin.fragment or origin.query):
            return None
        headers = {"Authorization": f"Bearer {credential}"} if credential else {}
        arguments = None if operation == "news.headlines" else {"key": key}
        async with client.stream("GET", url, params=arguments, headers=headers, follow_redirects=False) as response:
            response.raise_for_status()
            data = bytearray()
            async for part in response.aiter_bytes():
                data.extend(part)
                if len(data) > 200_000:
                    return None
        if operation == "news.headlines":
            return rss(data)
        payload = json.loads(data)
        return payload.get(key) if isinstance(payload, dict) else None
    except (httpx.HTTPError, ValueError, TypeError, ElementTree.ParseError):
        return None


def rss(data):
    root = ElementTree.fromstring(data)
    channel = root.find("channel")
    if channel is None:
        return None
    source = (channel.findtext("title") or "").strip()
    if not source:
        return None
    rows = []
    for item in channel.findall("item")[:60]:
        raw_time = item.findtext("pubDate")
        title = (item.findtext("title") or "").strip()
        if not raw_time or not title:
            continue
        try:
            published = parsedate_to_datetime(raw_time)
        except (TypeError, ValueError):
            continue
        if published.tzinfo is not None:
            rows.append((published, title))
    if not rows:
        return None
    published, title = max(rows)
    return {"source": source[:80], "headline": title[:160], "dataTime": published.isoformat(),
            "localTime": published.astimezone(UTC).strftime("%d %b %H:%M UTC")}
