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
PHOTOS_URL = "https://www.facebook.com/{username}/photos"
VIDEOS_URL = "https://www.facebook.com/{username}/videos"
POST_URL_PREFIX = "https://www.facebook.com/"

# CDN URLs embed an asset_id and an fbid like:
#   .../t39.30808-6/<asset_id>_<fbid>_<rest>.jpg
_PHOTO_CDN_RE = re.compile(
    r'https://[^"\\\s<>]*scontent[^"\\\s<>]*/(\d{6,})_(\d{10,})_[^"\\\s<>]+\.(?:jpg|jpeg|webp|png)',
    re.IGNORECASE,
)
# Native MP4 playable URL inside the videos page JSON.
_PLAYABLE_URL_RE = re.compile(r'"playable_url(?:_quality_hd)?":"([^"]+\.mp4[^"]*)"')
# Video IDs in the same payload, in document order.
_VIDEO_ID_RE = re.compile(r'"video_id":"(\d{10,})"')
# Post fbids in the main page HTML — used by the best-effort posts() scraper.
_POST_FBID_RE = re.compile(r'fbid=(\d{12,})')

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


def _photo_permalink(fbid: str) -> str:
    return f"https://www.facebook.com/photo/?fbid={fbid}"


def _extract_photos_from_html(html: str) -> list[dict[str, str]]:
    """Parse the CDN photo URLs out of any chunk of FB HTML."""
    out: list[dict[str, str]] = []
    seen: set[str] = set()
    for m in _PHOTO_CDN_RE.finditer(html):
        fbid = m.group(2)
        if fbid in seen:
            continue
        seen.add(fbid)
        out.append(
            {
                "fbid": fbid,
                "asset_id": m.group(1),
                "url": m.group(0),
                "permalink": _photo_permalink(fbid),
            }
        )
    return out


def photos(
    username: str,
    limit: int = 24,
    *,
    all: bool = False,
) -> dict[str, Any]:
    """List recent photos from a public Page's /photos grid.

    Returns up to ~10–24 unique photos: the CDN image URL, the asset fbid
    extracted from that URL, and a viewer permalink. The order matches
    document order on the page (roughly newest-first).

    When `all=True`, drives a headless Chromium via Playwright to scroll the
    page and collect older photos beyond the initial server-rendered batch.
    Requires the optional `[browser]` extra.
    """
    username = username.lstrip("@").strip("/")
    url = PHOTOS_URL.format(username=username)
    if all:
        from .browser import scroll_collect
        items = scroll_collect(
            url, _extract_photos_from_html, key="fbid", max_items=limit,
        )
        return {
            "username": username,
            "source": url,
            "mode": "browser",
            "count": len(items),
            "photos": items,
        }
    resp = get(url, headers=_fb_headers())
    items = _extract_photos_from_html(resp.text)[:limit]
    return {
        "username": username,
        "source": url,
        "mode": "http",
        "count": len(items),
        "photos": items,
    }


def _decode_json_url(s: str) -> str:
    """JSON strings escape forward slashes as `\\/`; un-escape and \\u00XX."""
    return s.replace("\\/", "/").encode("utf-8").decode("unicode_escape", errors="replace")


def _extract_videos_from_html(html: str) -> list[dict[str, str]]:
    out: list[dict[str, str]] = []
    seen: set[str] = set()
    for m in _PLAYABLE_URL_RE.finditer(html):
        decoded = _decode_json_url(m.group(1))
        if decoded in seen:
            continue
        seen.add(decoded)
        out.append({"playable_url": decoded})
    return out


def videos(
    username: str,
    limit: int = 24,
    *,
    all: bool = False,
) -> dict[str, Any]:
    """List recent native video MP4 URLs from a public Page's /videos page.

    Returns playable URLs (the actual MP4 files) and any video IDs in the
    same payload. Titles / durations / dates are not reliably extractable
    without authentication.

    When `all=True`, drives a headless Chromium to scroll for older videos.
    Requires the optional `[browser]` extra.
    """
    username = username.lstrip("@").strip("/")
    url = VIDEOS_URL.format(username=username)
    if all:
        from .browser import scroll_collect
        items = scroll_collect(
            url, _extract_videos_from_html, key="playable_url", max_items=limit,
        )
        return {
            "username": username,
            "source": url,
            "mode": "browser",
            "count": len(items),
            "playable_urls": [i["playable_url"] for i in items],
        }
    resp = get(url, headers=_fb_headers())
    text = resp.text
    playable = [i["playable_url"] for i in _extract_videos_from_html(text)][:limit]
    video_ids = list(dict.fromkeys(_VIDEO_ID_RE.findall(text)))[:limit]
    return {
        "username": username,
        "source": url,
        "mode": "http",
        "count": len(playable),
        "video_ids": video_ids,
        "playable_urls": playable,
    }


def posts(username: str, limit: int = 24) -> dict[str, Any]:
    """Best-effort: list post permalinks visible on the public Page.

    Facebook does not render the main feed to logged-out visitors, so this
    typically returns very little (often just the pinned/cover post). For
    real post coverage, use the Graph API with an access token.
    """
    username = username.lstrip("@").strip("/")
    url = PROFILE_URL.format(username=username)
    resp = get(url, headers=_fb_headers())
    text = resp.text
    seen: set[str] = set()
    items: list[dict[str, str]] = []
    # Look for post permalink paths first (most reliable when present).
    path_re = re.compile(
        rf'/{re.escape(username)}/(posts|videos|photos)/([A-Za-z0-9]+)'
    )
    for m in path_re.finditer(text):
        kind, ident = m.group(1), m.group(2)
        key = f"{kind}:{ident}"
        if key in seen:
            continue
        seen.add(key)
        items.append(
            {
                "kind": kind,
                "id": ident,
                "permalink": f"https://www.facebook.com/{username}/{kind}/{ident}",
            }
        )
        if len(items) >= limit:
            break
    # Fallback: bare fbids on the main page.
    if not items:
        for fbid in dict.fromkeys(_POST_FBID_RE.findall(text)):
            items.append(
                {
                    "kind": "photo",
                    "id": fbid,
                    "permalink": _photo_permalink(fbid),
                }
            )
            if len(items) >= limit:
                break
    return {
        "username": username,
        "source": url,
        "count": len(items),
        "note": (
            "Facebook does not server-render the post feed for logged-out "
            "visitors; results are limited."
        ),
        "posts": items,
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
