"""X (Twitter) lookups using the public syndication endpoints.

These endpoints back the embed widgets and do not require auth, but they only
expose public accounts and a limited slice of fields.
"""

from __future__ import annotations

import json
import math
import re
from typing import Any

from .http import get

SYNDICATION_PROFILE = "https://syndication.twitter.com/srv/timeline-profile/screen-name/{username}"
SYNDICATION_TWEET = "https://cdn.syndication.twimg.com/tweet-result"

_NEXT_DATA_RE = re.compile(
    r'<script id="__NEXT_DATA__" type="application/json">(.*?)</script>',
    re.DOTALL,
)


def _tweet_token(tweet_id: str) -> str:
    """Replicates the JS token used by twitter embeds."""
    n = int(tweet_id) / 1e15 * math.pi
    base36 = ""
    int_part = int(n)
    while int_part > 0:
        int_part, rem = divmod(int_part, 36)
        base36 = "0123456789abcdefghijklmnopqrstuvwxyz"[rem] + base36
    frac = n - int(n)
    frac_part = ""
    for _ in range(13):
        frac *= 36
        digit = int(frac)
        frac -= digit
        frac_part += "0123456789abcdefghijklmnopqrstuvwxyz"[digit]
    raw = (base36 or "0") + "." + frac_part
    return re.sub(r"(0+|\.)", "", raw)


def _extract_next_data(html: str) -> dict[str, Any]:
    m = _NEXT_DATA_RE.search(html)
    if not m:
        raise RuntimeError("Could not find embedded profile data; account may be private or blocked.")
    return json.loads(m.group(1))


def profile(username: str) -> dict[str, Any]:
    username = username.lstrip("@")
    resp = get(SYNDICATION_PROFILE.format(username=username))
    data = _extract_next_data(resp.text)
    timeline = data.get("props", {}).get("pageProps", {}).get("timeline", {})
    entries = timeline.get("entries", []) or []
    user: dict[str, Any] = {}
    for entry in entries:
        content = entry.get("content", {})
        tweet = content.get("tweet") or content.get("retweet")
        if tweet and tweet.get("user"):
            user = tweet["user"]
            break
    tweets_preview = []
    for entry in entries[:10]:
        t = entry.get("content", {}).get("tweet")
        if not t:
            continue
        tweets_preview.append(
            {
                "id": t.get("id_str") or t.get("id"),
                "created_at": t.get("created_at"),
                "text": t.get("text"),
                "favorite_count": t.get("favorite_count"),
                "reply_count": t.get("conversation_count"),
                "media": _normalize_media(t.get("mediaDetails") or []),
                "photo_urls": [p.get("url") for p in (t.get("photos") or []) if p.get("url")],
            }
        )
    return {
        "username": user.get("screen_name", username),
        "name": user.get("name"),
        "id": user.get("id_str"),
        "verified": user.get("verified"),
        "description": user.get("description"),
        "followers": user.get("followers_count"),
        "following": user.get("friends_count"),
        "tweets": user.get("statuses_count"),
        "location": user.get("location"),
        "url": user.get("url"),
        "profile_image": user.get("profile_image_url_https"),
        "profile_banner": user.get("profile_banner_url"),
        "recent_tweets": tweets_preview,
    }


def _normalize_media(media_details: list[dict[str, Any]]) -> list[dict[str, Any]]:
    """Expand X mediaDetails into a flat list with MP4 variants for videos/GIFs."""
    out = []
    for m in media_details or []:
        mtype = m.get("type")
        info = m.get("original_info") or {}
        entry: dict[str, Any] = {
            "type": mtype,
            "thumbnail": m.get("media_url_https"),
            "width": info.get("width"),
            "height": info.get("height"),
            "alt_text": m.get("ext_alt_text"),
        }
        if mtype in ("video", "animated_gif"):
            vi = m.get("video_info") or {}
            variants = [
                {
                    "url": v.get("url"),
                    "content_type": v.get("content_type"),
                    "bitrate": v.get("bitrate"),
                }
                for v in (vi.get("variants") or [])
            ]
            mp4s = [v for v in variants if v["content_type"] == "video/mp4" and v.get("bitrate")]
            best = max(mp4s, key=lambda v: v["bitrate"], default=None)
            entry["variants"] = variants
            entry["best_mp4"] = best["url"] if best else None
            entry["duration_ms"] = vi.get("duration_millis")
            entry["aspect_ratio"] = vi.get("aspect_ratio")
        out.append(entry)
    return out


def tweet(tweet_id: str) -> dict[str, Any]:
    params = {
        "id": tweet_id,
        "token": _tweet_token(tweet_id),
        "lang": "en",
        "features": (
            "tfw_timeline_list:;tfw_follower_count_sunset:true;"
            "tfw_tweet_edit_backend:on;tfw_refsrc_session:on;"
            "tfw_show_business_verified_badge:on;"
            "tfw_show_birdwatch_pivots_enabled:on;"
        ),
    }
    resp = get(SYNDICATION_TWEET, params=params)
    data = resp.json()
    user = data.get("user") or {}
    photos = data.get("photos") or []
    return {
        "id": data.get("id_str") or tweet_id,
        "created_at": data.get("created_at"),
        "text": data.get("text"),
        "lang": data.get("lang"),
        "favorite_count": data.get("favorite_count"),
        "conversation_count": data.get("conversation_count"),
        "view_count": (data.get("view_count_info") or {}).get("count"),
        "possibly_sensitive": data.get("possibly_sensitive"),
        "author": {
            "screen_name": user.get("screen_name"),
            "name": user.get("name"),
            "verified": user.get("verified"),
            "id": user.get("id_str"),
            "profile_image": user.get("profile_image_url_https"),
        },
        "media": _normalize_media(data.get("mediaDetails") or []),
        "photo_urls": [p.get("url") for p in photos if p.get("url")],
        "entities": {
            "hashtags": [h.get("text") for h in ((data.get("entities") or {}).get("hashtags") or [])],
            "urls": [u.get("expanded_url") for u in ((data.get("entities") or {}).get("urls") or [])],
            "mentions": [
                m.get("screen_name") for m in ((data.get("entities") or {}).get("user_mentions") or [])
            ],
        },
    }
