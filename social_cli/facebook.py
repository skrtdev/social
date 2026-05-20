"""Facebook lookups via OpenGraph metadata.

Facebook's authenticated APIs require a graph API token, and the web UI
aggressively gates content behind login. The most reliable unauthenticated
signal is OpenGraph metadata served on public page / post URLs, which is what
this module parses. For richer fields use the official Graph API with a token.
"""

from __future__ import annotations

import html
import re
from typing import Any

from .http import get

PROFILE_URL = "https://www.facebook.com/{username}"
POST_URL_PREFIX = "https://www.facebook.com/"

_META_RE = re.compile(
    r'<meta\s+(?:property|name)="([^"]+)"\s+content="([^"]*)"', re.IGNORECASE
)
_TITLE_RE = re.compile(r"<title[^>]*>(.*?)</title>", re.IGNORECASE | re.DOTALL)
_FOLLOWERS_RE = re.compile(r'([\d][\d,.]*)\s*(?:followers|persone seguono)', re.IGNORECASE)
_LIKES_RE = re.compile(r'([\d][\d,.]*)\s*(?:likes|mi piace)', re.IGNORECASE)


def _fb_headers() -> dict[str, str]:
    return {
        "Accept": "text/html,application/xhtml+xml,application/xml;q=0.9,*/*;q=0.8",
        "Accept-Language": "en-US,en;q=0.9",
        # Pretend to be a logged-out desktop visitor to avoid the mobile login wall.
        "Sec-Fetch-Dest": "document",
        "Sec-Fetch-Mode": "navigate",
        "Sec-Fetch-Site": "none",
        "Upgrade-Insecure-Requests": "1",
    }


def _parse_meta(text: str) -> dict[str, str]:
    """First-wins flat map, e.g. {'og:title': '...', 'og:image': '...'}."""
    metas: dict[str, str] = {}
    for key, value in _META_RE.findall(text):
        k = key.lower()
        if k not in metas:
            metas[k] = html.unescape(value)
    return metas


def _parse_meta_pairs(text: str) -> list[tuple[str, str]]:
    """All (property, content) pairs in document order — preserves duplicates."""
    return [(k.lower(), html.unescape(v)) for k, v in _META_RE.findall(text)]


def _group_og_media(pairs: list[tuple[str, str]], root: str) -> list[dict[str, str]]:
    """Group sub-properties under each `<root>` tag.

    FB / OG emit:
        og:image          <- starts a new group
        og:image:url
        og:image:secure_url
        og:image:type
        og:image:width
        og:image:height
        og:image          <- next group
        ...

    Returns one dict per `<root>` tag with all immediately-following `<root>:*`
    sub-properties folded in.
    """
    groups: list[dict[str, str]] = []
    current: dict[str, str] | None = None
    prefix = f"{root}:"
    for k, v in pairs:
        if k == root:
            current = {"url": v}
            groups.append(current)
        elif current is not None and k.startswith(prefix):
            current[k[len(prefix):]] = v
    return groups


def profile(username: str) -> dict[str, Any]:
    username = username.lstrip("@").strip("/")
    url = PROFILE_URL.format(username=username)
    resp = get(url, headers=_fb_headers())
    metas = _parse_meta(resp.text)
    pairs = _parse_meta_pairs(resp.text)
    title_match = _TITLE_RE.search(resp.text)
    followers = _FOLLOWERS_RE.search(resp.text)
    likes = _LIKES_RE.search(resp.text)
    return {
        "username": username,
        "url": metas.get("og:url") or url,
        "name": metas.get("og:title") or (html.unescape(title_match.group(1)) if title_match else None),
        "description": metas.get("og:description") or metas.get("description"),
        "image": metas.get("og:image"),
        "images": _group_og_media(pairs, "og:image"),
        "type": metas.get("og:type"),
        "followers_text": followers.group(0) if followers else None,
        "likes_text": likes.group(0) if likes else None,
    }


def post(url_or_id: str) -> dict[str, Any]:
    """Accepts a full facebook.com URL or a path like 'user/posts/123'."""
    if url_or_id.startswith("http"):
        url = url_or_id
    else:
        url = POST_URL_PREFIX + url_or_id.lstrip("/")
    resp = get(url, headers=_fb_headers())
    metas = _parse_meta(resp.text)
    pairs = _parse_meta_pairs(resp.text)
    images = _group_og_media(pairs, "og:image")
    videos = _group_og_media(pairs, "og:video")
    return {
        "url": metas.get("og:url") or url,
        "type": metas.get("og:type"),
        "title": metas.get("og:title"),
        "description": metas.get("og:description") or metas.get("description"),
        "image": metas.get("og:image"),
        "images": images,
        "video": metas.get("og:video:url") or metas.get("og:video"),
        "video_secure_url": metas.get("og:video:secure_url"),
        "video_type": metas.get("og:video:type"),
        "video_width": metas.get("og:video:width"),
        "video_height": metas.get("og:video:height"),
        "videos": videos,
        "site_name": metas.get("og:site_name"),
        "updated_time": metas.get("og:updated_time") or metas.get("article:modified_time"),
        "published_time": metas.get("article:published_time"),
    }
