"""Tests for Instagram profile + post parsing."""

from __future__ import annotations

import json as jsonlib

import pytest

from social_cli import instagram
from tests.conftest import FakeResponse


def _profile_payload() -> dict:
    return {
        "data": {
            "user": {
                "username": "instagram",
                "full_name": "Instagram",
                "id": "25025320",
                "is_private": False,
                "is_verified": True,
                "biography": "bio",
                "external_url": "https://help.instagram.com/",
                "edge_followed_by": {"count": 685_000_000},
                "edge_follow": {"count": 198},
                "edge_owner_to_timeline_media": {
                    "count": 8000,
                    "edges": [
                        {
                            "node": {
                                "__typename": "GraphImage",
                                "shortcode": "ABC123",
                                "taken_at_timestamp": 1779307307,
                                "edge_liked_by": {"count": 50000},
                                "edge_media_to_comment": {"count": 900},
                                "edge_media_to_caption": {
                                    "edges": [{"node": {"text": "hello!"}}]
                                },
                                "is_video": False,
                                "display_url": "https://img/ABC.jpg",
                                "thumbnail_src": "https://img/ABC_thumb.jpg",
                                "dimensions": {"width": 1080, "height": 1080},
                                "accessibility_caption": "a photo of a cat",
                                "thumbnail_resources": [
                                    {"src": "https://img/ABC_150.jpg", "config_width": 150},
                                    {"src": "https://img/ABC_240.jpg", "config_width": 240},
                                ],
                            }
                        },
                        {
                            "node": {
                                "__typename": "GraphVideo",
                                "shortcode": "DEF456",
                                "taken_at_timestamp": 1779217102,
                                "edge_liked_by": {"count": 100},
                                "edge_media_to_comment": {"count": 5},
                                "edge_media_to_caption": {"edges": []},
                                "is_video": True,
                                "display_url": "https://img/DEF.jpg",
                                "video_url": "https://v/DEF.mp4",
                                "video_view_count": 7777,
                                "dimensions": {"width": 1080, "height": 1920},
                                "product_type": "clips",
                            }
                        },
                        {
                            "node": {
                                "__typename": "GraphSidecar",
                                "shortcode": "GHI789",
                                "taken_at_timestamp": 1779100000,
                                "edge_liked_by": {"count": 10},
                                "edge_media_to_comment": {"count": 1},
                                "edge_media_to_caption": {
                                    "edges": [{"node": {"text": "carousel"}}]
                                },
                                "is_video": False,
                                "display_url": "https://img/GHI_cover.jpg",
                                "edge_sidecar_to_children": {
                                    "edges": [
                                        {
                                            "node": {
                                                "id": "1",
                                                "is_video": False,
                                                "display_url": "https://img/GHI_1.jpg",
                                                "dimensions": {"width": 1, "height": 1},
                                            }
                                        },
                                        {
                                            "node": {
                                                "id": "2",
                                                "is_video": True,
                                                "display_url": "https://img/GHI_2.jpg",
                                                "video_url": "https://v/GHI_2.mp4",
                                                "dimensions": {"width": 1, "height": 1},
                                            }
                                        },
                                    ]
                                },
                            }
                        },
                    ],
                },
                "profile_pic_url_hd": "https://img/hd.jpg",
                "profile_pic_url": "https://img/sd.jpg",
                "category_name": None,
            }
        }
    }


def test_profile_parses_counts_and_recent_posts(patch_get):
    patch_get(instagram, lambda url, kwargs: FakeResponse(_json=_profile_payload()))
    out = instagram.profile("@instagram")
    assert out["username"] == "instagram"
    assert out["followers"] == 685_000_000
    assert out["following"] == 198
    assert out["is_verified"] is True
    assert out["profile_pic"] == "https://img/hd.jpg"
    assert len(out["recent_posts"]) == 3
    p0, p1, p2 = out["recent_posts"]
    # Photo post
    assert p0["shortcode"] == "ABC123"
    assert p0["caption"] == "hello!"
    assert p0["display_url"] == "https://img/ABC.jpg"
    assert p0["accessibility_caption"] == "a photo of a cat"
    assert len(p0["thumbnail_variants"]) == 2
    assert p0["dimensions"] == {"width": 1080, "height": 1080}
    assert p0["children"] == []
    # Video / reel
    assert p1["caption"] is None
    assert p1["video_url"] == "https://v/DEF.mp4"
    assert p1["video_view_count"] == 7777
    assert p1["product_type"] == "clips"
    # Carousel
    assert p2["type"] == "GraphSidecar"
    assert len(p2["children"]) == 2
    assert p2["children"][0]["display_url"] == "https://img/GHI_1.jpg"
    assert p2["children"][1]["video_url"] == "https://v/GHI_2.mp4"


def test_profile_sends_app_id_header(patch_get):
    seen = {}

    def factory(url, kwargs):
        seen["headers"] = kwargs.get("headers") or {}
        seen["params"] = kwargs.get("params") or {}
        return FakeResponse(_json=_profile_payload())

    patch_get(instagram, factory)
    instagram.profile("instagram")
    assert seen["headers"].get("X-IG-App-ID") == "936619743392459"
    assert seen["params"].get("username") == "instagram"


def test_profile_raises_on_missing_user(patch_get):
    patch_get(instagram, lambda url, kwargs: FakeResponse(_json={"data": {}}))
    with pytest.raises(RuntimeError, match="No profile data"):
        instagram.profile("ghost")


def _post_html(ld_obj) -> str:
    return (
        "<html><body>"
        f'<script type="application/ld+json" data-sjs>{jsonlib.dumps(ld_obj)}</script>'
        "</body></html>"
    )


def test_post_parses_ld_json(patch_get):
    ld = {
        "url": "https://www.instagram.com/p/ABC123/",
        "articleBody": "caption text",
        "uploadDate": "2026-03-01T12:00:00+00:00",
        "interactionStatistic": [
            {"interactionType": "https://schema.org/LikeAction", "userInteractionCount": 1234},
            {"interactionType": "https://schema.org/CommentAction", "userInteractionCount": 56},
        ],
        "author": {
            "alternateName": "@alice",
            "name": "Alice",
            "url": "https://www.instagram.com/alice/",
        },
        "image": [{"url": "https://img/1.jpg"}, {"url": "https://img/2.jpg"}],
    }
    patch_get(instagram, lambda url, kwargs: FakeResponse(text=_post_html(ld)))
    out = instagram.post("https://www.instagram.com/p/ABC123/")
    assert out["source"] == "ld+json"
    assert out["shortcode"] == "ABC123"
    assert out["caption"] == "caption text"
    assert out["likes"] == 1234
    assert out["comments"] == 56
    assert out["author"]["username"] == "alice"
    assert out["images"] == ["https://img/1.jpg", "https://img/2.jpg"]
    assert out["videos"] == []
    assert out["is_carousel"] is True
    assert out["media"] == ["https://img/1.jpg", "https://img/2.jpg"]


def test_post_ld_json_with_video_and_carousel(patch_get):
    ld = {
        "url": "https://www.instagram.com/p/XYZ/",
        "articleBody": "mixed media post",
        "interactionStatistic": [],
        "author": {"alternateName": "@u", "name": "U"},
        "image": [{"url": "https://img/cover.jpg"}],
        "video": [
            {
                "contentUrl": "https://v/clip.mp4",
                "thumbnailUrl": "https://img/clip_thumb.jpg",
                "duration": "PT0M30S",
                "width": 1280,
                "height": 720,
            }
        ],
    }
    patch_get(instagram, lambda url, kwargs: FakeResponse(text=_post_html(ld)))
    out = instagram.post("XYZ")
    assert out["is_carousel"] is True
    assert out["images"] == ["https://img/cover.jpg"]
    assert out["videos"][0]["url"] == "https://v/clip.mp4"
    assert out["videos"][0]["thumbnail"] == "https://img/clip_thumb.jpg"
    assert out["videos"][0]["duration"] == "PT0M30S"
    assert "https://v/clip.mp4" in out["media"]


def test_post_ld_json_single_video_object(patch_get):
    """video can be a single dict instead of a list."""
    ld = {
        "url": "https://www.instagram.com/p/V/",
        "articleBody": "",
        "interactionStatistic": [],
        "author": {},
        "image": [],
        "video": {"contentUrl": "https://v/solo.mp4"},
    }
    patch_get(instagram, lambda url, kwargs: FakeResponse(text=_post_html(ld)))
    out = instagram.post("V")
    assert out["videos"][0]["url"] == "https://v/solo.mp4"
    assert out["is_carousel"] is False


def test_post_accepts_bare_shortcode(patch_get):
    seen = {}

    def factory(url, kwargs):
        seen["url"] = url
        return FakeResponse(text=_post_html({"url": "x", "image": []}))

    patch_get(instagram, factory)
    instagram.post("ABC123")
    assert "/p/ABC123/" in seen["url"]


def test_post_handles_list_ld_json(patch_get):
    ld_list = [{"url": "https://www.instagram.com/p/X/", "articleBody": "from list"}]
    patch_get(instagram, lambda url, kwargs: FakeResponse(text=_post_html(ld_list)))
    out = instagram.post("X")
    assert out["caption"] == "from list"


def test_post_raises_when_no_structured_data(patch_get):
    patch_get(instagram, lambda url, kwargs: FakeResponse(text="<html></html>"))
    with pytest.raises(RuntimeError, match="post data"):
        instagram.post("ABC123")


def test_post_falls_back_to_og_metadata(patch_get):
    """When LD+JSON is absent (current IG behavior), parse OG meta tags."""
    html = (
        "<html><head>"
        '<meta property="og:url" content="https://www.instagram.com/p/ZZZ/">'
        '<meta property="og:title" content="Alice on Instagram: hello world">'
        '<meta property="og:description" content="123 likes, 4 comments - alice on March 1, 2026">'
        '<meta property="og:image" content="https://img/zzz.jpg">'
        "</head></html>"
    )
    patch_get(instagram, lambda url, kwargs: FakeResponse(text=html))
    out = instagram.post("ZZZ")
    assert out["source"] == "og"
    assert out["shortcode"] == "ZZZ"
    assert out["likes"] == "123"
    assert out["comments"] == "4"
    assert "hello world" in (out["caption"] or "")
    assert out["author"]["username"] == "Alice"
    assert out["media"] == ["https://img/zzz.jpg"]
