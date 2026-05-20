"""Instagram lookups via the public web_profile_info / oembed endpoints.

These endpoints are unofficial and may rate-limit aggressively. For private
accounts or richer post data, real credentials are required.
"""

from __future__ import annotations

import html as html_mod
import json
import re
from typing import Any

from .http import get

WEB_PROFILE = "https://i.instagram.com/api/v1/users/web_profile_info/"
POST_PAGE = "https://www.instagram.com/p/{shortcode}/"

_IG_APP_ID = "936619743392459"  # public web app id used by instagram.com itself

_SHARED_DATA_RE = re.compile(
    r'<script[^>]*type="application/ld\+json"[^>]*>(.*?)</script>', re.DOTALL
)
_META_RE = re.compile(
    r'<meta\s+(?:property|name)="([^"]+)"\s+content="([^"]*)"', re.IGNORECASE
)
_IG_LIKES_RE = re.compile(r'([\d,.]+)\s*likes?', re.IGNORECASE)
_IG_COMMENTS_RE = re.compile(r'([\d,.]+)\s*comments?', re.IGNORECASE)


def _caption_text(node: dict[str, Any]) -> str | None:
    edges = (node.get("edge_media_to_caption") or {}).get("edges") or []
    if not edges:
        return None
    return (edges[0].get("node") or {}).get("text")


def _summarize_feed_node(n: dict[str, Any]) -> dict[str, Any]:
    """Flatten one timeline node into something users actually want."""
    is_carousel = n.get("__typename") == "GraphSidecar" or "edge_sidecar_to_children" in n
    children: list[dict[str, Any]] = []
    if is_carousel:
        for c in (n.get("edge_sidecar_to_children") or {}).get("edges", []) or []:
            cn = c.get("node") or {}
            children.append(
                {
                    "id": cn.get("id"),
                    "is_video": cn.get("is_video"),
                    "display_url": cn.get("display_url"),
                    "video_url": cn.get("video_url"),
                    "dimensions": cn.get("dimensions"),
                    "accessibility_caption": cn.get("accessibility_caption"),
                }
            )
    return {
        "shortcode": n.get("shortcode"),
        "taken_at": n.get("taken_at_timestamp"),
        "likes": (n.get("edge_liked_by") or {}).get("count"),
        "comments": (n.get("edge_media_to_comment") or {}).get("count"),
        "caption": _caption_text(n),
        "is_video": n.get("is_video"),
        "type": n.get("__typename"),
        "product_type": n.get("product_type"),
        "display_url": n.get("display_url"),
        "thumbnail_src": n.get("thumbnail_src"),
        "video_url": n.get("video_url"),
        "video_view_count": n.get("video_view_count"),
        "dimensions": n.get("dimensions"),
        "accessibility_caption": n.get("accessibility_caption"),
        "thumbnail_variants": n.get("thumbnail_resources") or [],
        "children": children,
    }


def _ig_headers() -> dict[str, str]:
    return {
        "X-IG-App-ID": _IG_APP_ID,
        "Accept": "*/*",
        "Accept-Language": "en-US,en;q=0.9",
        "Referer": "https://www.instagram.com/",
        "Sec-Fetch-Site": "same-site",
    }


def profile(username: str) -> dict[str, Any]:
    username = username.lstrip("@")
    resp = get(WEB_PROFILE, params={"username": username}, headers=_ig_headers())
    data = resp.json().get("data", {}).get("user")
    if not data:
        raise RuntimeError(f"No profile data returned for {username!r}.")
    edges = (
        data.get("edge_owner_to_timeline_media", {}).get("edges", []) or []
    )
    recent_posts = [_summarize_feed_node(e.get("node") or {}) for e in edges]
    return {
        "username": data.get("username"),
        "full_name": data.get("full_name"),
        "id": data.get("id"),
        "is_private": data.get("is_private"),
        "is_verified": data.get("is_verified"),
        "biography": data.get("biography"),
        "external_url": data.get("external_url"),
        "followers": (data.get("edge_followed_by") or {}).get("count"),
        "following": (data.get("edge_follow") or {}).get("count"),
        "posts": (data.get("edge_owner_to_timeline_media") or {}).get("count"),
        "profile_pic": data.get("profile_pic_url_hd") or data.get("profile_pic_url"),
        "category": data.get("category_name"),
        "recent_posts": recent_posts,
    }


def _parse_meta(text: str) -> dict[str, str]:
    return {
        k.lower(): html_mod.unescape(v) for k, v in _META_RE.findall(text)
    }


def post(shortcode: str) -> dict[str, Any]:
    """Fetch a post by its shortcode (the bit after /p/ in the URL).

    Tries LD+JSON first (richer fields); falls back to OpenGraph meta tags,
    which is what Instagram currently serves to logged-out scrapers.
    """
    shortcode = shortcode.strip("/").split("/")[-1]
    url = POST_PAGE.format(shortcode=shortcode)
    resp = get(url, headers=_ig_headers())
    text = resp.text

    m = _SHARED_DATA_RE.search(text)
    if m:
        ld = json.loads(m.group(1))
        if isinstance(ld, list):
            ld = ld[0]
        author = ld.get("author") or {}
        interaction = {
            i.get("interactionType", "").rsplit("/", 1)[-1]: i.get("userInteractionCount")
            for i in (ld.get("interactionStatistic") or [])
        }
        images = [
            (img.get("url") if isinstance(img, dict) else img)
            for img in (ld.get("image") or [])
        ]
        # `video` may be a single VideoObject or a list of them.
        raw_videos = ld.get("video") or []
        if isinstance(raw_videos, dict):
            raw_videos = [raw_videos]
        videos = [
            {
                "url": v.get("contentUrl"),
                "thumbnail": v.get("thumbnailUrl"),
                "duration": v.get("duration"),
                "width": v.get("width"),
                "height": v.get("height"),
            }
            for v in raw_videos
            if isinstance(v, dict)
        ]
        return {
            "shortcode": shortcode,
            "url": ld.get("url") or url,
            "caption": ld.get("articleBody") or ld.get("caption"),
            "uploaded": ld.get("uploadDate") or ld.get("datePublished"),
            "likes": interaction.get("LikeAction"),
            "comments": interaction.get("CommentAction"),
            "author": {
                "username": author.get("alternateName", "").lstrip("@") or author.get("name"),
                "name": author.get("name"),
                "url": author.get("url"),
            },
            "images": images,
            "videos": videos,
            "media": images + [v["url"] for v in videos if v["url"]],
            "is_carousel": len(images) + len(videos) > 1,
            "source": "ld+json",
        }

    metas = _parse_meta(text)
    if not metas.get("og:title") and not metas.get("og:description"):
        raise RuntimeError(
            "Could not find post data; the post may be private, removed, or login-walled."
        )
    desc = metas.get("og:description") or ""
    likes_m = _IG_LIKES_RE.search(desc)
    comments_m = _IG_COMMENTS_RE.search(desc)
    # og:title is shaped like 'Instagram on Instagram: "caption..."'
    title = metas.get("og:title") or ""
    caption = None
    if ":" in title:
        caption = title.split(":", 1)[1].strip().strip('"')
    return {
        "shortcode": shortcode,
        "url": metas.get("og:url") or url,
        "caption": caption or desc,
        "uploaded": metas.get("og:updated_time") or metas.get("article:published_time"),
        "likes": likes_m.group(1) if likes_m else None,
        "comments": comments_m.group(1) if comments_m else None,
        "author": {
            "username": (title.split(" on ", 1)[0] or "").strip() or None,
            "name": None,
            "url": None,
        },
        "media": [metas["og:image"]] if metas.get("og:image") else [],
        "source": "og",
    }
