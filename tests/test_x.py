"""Tests for X (Twitter) profile + tweet parsing."""

from __future__ import annotations

import json as jsonlib

import pytest

from social_cli import x
from tests.conftest import FakeResponse


def _profile_html() -> str:
    payload = {
        "props": {
            "pageProps": {
                "timeline": {
                    "entries": [
                        {
                            "content": {
                                "tweet": {
                                    "id_str": "1700000000000000001",
                                    "created_at": "2024-01-01T00:00:00Z",
                                    "text": "first tweet",
                                    "favorite_count": 10,
                                    "conversation_count": 2,
                                    "mediaDetails": [
                                        {
                                            "type": "photo",
                                            "media_url_https": "https://img/p1.jpg",
                                            "original_info": {"width": 800, "height": 600},
                                        }
                                    ],
                                    "user": {
                                        "screen_name": "jack",
                                        "name": "jack",
                                        "id_str": "12",
                                        "verified": True,
                                        "description": "bio",
                                        "followers_count": 1000,
                                        "friends_count": 100,
                                        "statuses_count": 5000,
                                        "location": "SF",
                                        "url": "https://example.com",
                                        "profile_image_url_https": "https://img/u.jpg",
                                        "profile_banner_url": "https://img/banner.jpg",
                                    },
                                }
                            }
                        },
                        {
                            "content": {
                                "tweet": {
                                    "id_str": "1700000000000000002",
                                    "created_at": "2024-01-02T00:00:00Z",
                                    "text": "second tweet",
                                    "favorite_count": 3,
                                    "conversation_count": 0,
                                }
                            }
                        },
                    ]
                }
            }
        }
    }
    return (
        "<html><body>"
        f'<script id="__NEXT_DATA__" type="application/json">{jsonlib.dumps(payload)}</script>'
        "</body></html>"
    )


def test_profile_parses_user_and_recent_tweets(patch_get):
    patch_get(x, lambda url, kwargs: FakeResponse(text=_profile_html()))
    out = x.profile("@jack")
    assert out["username"] == "jack"
    assert out["followers"] == 1000
    assert out["following"] == 100
    assert out["verified"] is True
    assert len(out["recent_tweets"]) == 2
    assert out["recent_tweets"][0]["id"] == "1700000000000000001"
    assert out["recent_tweets"][0]["favorite_count"] == 10
    assert out["recent_tweets"][0]["media"][0]["thumbnail"] == "https://img/p1.jpg"
    assert out["profile_banner"] == "https://img/banner.jpg"


def test_profile_strips_leading_at(patch_get):
    seen = {}

    def factory(url, kwargs):
        seen["url"] = url
        return FakeResponse(text=_profile_html())

    patch_get(x, factory)
    x.profile("@jack")
    assert seen["url"].endswith("/screen-name/jack")


def test_profile_raises_when_no_embedded_data(patch_get):
    patch_get(x, lambda url, kwargs: FakeResponse(text="<html>no data here</html>"))
    with pytest.raises(RuntimeError, match="embedded profile data"):
        x.profile("ghost")


def test_tweet_returns_normalized_fields(patch_get):
    tweet_payload = {
        "id_str": "1734567890123456789",
        "created_at": "2024-02-02T12:34:56Z",
        "text": "hello world",
        "lang": "en",
        "favorite_count": 42,
        "conversation_count": 7,
        "view_count_info": {"count": "1234"},
        "user": {
            "screen_name": "alice",
            "name": "Alice",
            "verified": False,
            "id_str": "99",
        },
        "mediaDetails": [
            {
                "type": "photo",
                "media_url_https": "https://img/1.jpg",
                "original_info": {"width": 800, "height": 600},
            },
            {"type": "video", "media_url_https": "https://img/2.jpg"},
        ],
    }
    patch_get(x, lambda url, kwargs: FakeResponse(_json=tweet_payload))
    out = x.tweet("1734567890123456789")
    assert out["id"] == "1734567890123456789"
    assert out["text"] == "hello world"
    assert out["favorite_count"] == 42
    assert out["view_count"] == "1234"
    assert out["author"]["screen_name"] == "alice"
    assert len(out["media"]) == 2
    assert out["media"][0]["type"] == "photo"
    assert out["media"][0]["thumbnail"] == "https://img/1.jpg"
    assert out["media"][0]["width"] == 800
    assert out["media"][0]["height"] == 600


def test_tweet_extracts_video_mp4_variants(patch_get):
    tweet_payload = {
        "id_str": "999",
        "text": "video",
        "user": {"screen_name": "u"},
        "mediaDetails": [
            {
                "type": "video",
                "media_url_https": "https://img/thumb.jpg",
                "ext_alt_text": "a clip",
                "original_info": {"width": 1280, "height": 720},
                "video_info": {
                    "aspect_ratio": [16, 9],
                    "duration_millis": 30000,
                    "variants": [
                        {"content_type": "application/x-mpegURL", "url": "https://v/playlist.m3u8"},
                        {"bitrate": 832000, "content_type": "video/mp4", "url": "https://v/low.mp4"},
                        {"bitrate": 2176000, "content_type": "video/mp4", "url": "https://v/hi.mp4"},
                        {"bitrate": 1280000, "content_type": "video/mp4", "url": "https://v/med.mp4"},
                    ],
                },
            }
        ],
    }
    patch_get(x, lambda url, kwargs: FakeResponse(_json=tweet_payload))
    out = x.tweet("999")
    m = out["media"][0]
    assert m["type"] == "video"
    assert m["thumbnail"] == "https://img/thumb.jpg"
    assert m["duration_ms"] == 30000
    assert m["aspect_ratio"] == [16, 9]
    assert m["alt_text"] == "a clip"
    # Best MP4 = highest bitrate
    assert m["best_mp4"] == "https://v/hi.mp4"
    # All variants preserved, including HLS
    assert len(m["variants"]) == 4
    assert any(v["content_type"] == "application/x-mpegURL" for v in m["variants"])


def test_tweet_extracts_animated_gif_variant(patch_get):
    payload = {
        "id_str": "1",
        "text": "gif",
        "user": {"screen_name": "u"},
        "mediaDetails": [
            {
                "type": "animated_gif",
                "media_url_https": "https://img/g.jpg",
                "video_info": {
                    "variants": [
                        {"bitrate": 0, "content_type": "video/mp4", "url": "https://v/g.mp4"}
                    ]
                },
            }
        ],
    }
    patch_get(x, lambda url, kwargs: FakeResponse(_json=payload))
    out = x.tweet("1")
    # bitrate 0 is falsy and should not become best_mp4
    assert out["media"][0]["type"] == "animated_gif"
    assert out["media"][0]["best_mp4"] is None
    assert out["media"][0]["variants"][0]["url"] == "https://v/g.mp4"


def test_tweet_entities_extracted(patch_get):
    payload = {
        "id_str": "1",
        "text": "hi @bob #tag https://x.com",
        "user": {"screen_name": "u"},
        "entities": {
            "hashtags": [{"text": "tag"}],
            "urls": [{"expanded_url": "https://expanded.example/"}],
            "user_mentions": [{"screen_name": "bob"}],
        },
    }
    patch_get(x, lambda url, kwargs: FakeResponse(_json=payload))
    out = x.tweet("1")
    assert out["entities"]["hashtags"] == ["tag"]
    assert out["entities"]["mentions"] == ["bob"]
    assert out["entities"]["urls"] == ["https://expanded.example/"]


def test_tweet_token_is_deterministic_and_url_safe():
    token = x._tweet_token("1734567890123456789")
    assert token  # non-empty
    assert "." not in token
    assert "0" not in token  # 0s are stripped by the regex
    # Same input -> same token
    assert token == x._tweet_token("1734567890123456789")
    # Different input -> different token
    assert token != x._tweet_token("1700000000000000001")
