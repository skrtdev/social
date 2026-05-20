"""Tests for Facebook OG-metadata parsing."""

from __future__ import annotations

import pytest

from social_cli import facebook
from tests.conftest import FakeResponse


def _meta(props: dict[str, str]) -> str:
    tags = "\n".join(
        f'<meta property="{k}" content="{v}">' for k, v in props.items()
    )
    return f"<html><head>{tags}</head><body></body></html>"


def test_profile_extracts_og_tags(patch_get):
    html = (
        "<html><head>"
        '<title>Mark Zuckerberg | Facebook</title>'
        '<meta property="og:url" content="https://www.facebook.com/zuck">'
        '<meta property="og:title" content="Mark Zuckerberg">'
        '<meta property="og:description" content="Mark Zuckerberg. 121,000,000 likes.">'
        '<meta property="og:image" content="https://img/z.jpg">'
        '<meta property="og:type" content="profile">'
        "</head><body>"
        "<p>121,000,000 likes</p>"
        "<p>3,500,000 followers</p>"
        "</body></html>"
    )
    patch_get(facebook, lambda url, kwargs: FakeResponse(text=html))
    out = facebook.profile("zuck")
    assert out["username"] == "zuck"
    assert out["name"] == "Mark Zuckerberg"
    assert out["url"] == "https://www.facebook.com/zuck"
    assert out["image"] == "https://img/z.jpg"
    assert out["type"] == "profile"
    assert "121,000,000" in (out["likes_text"] or "")
    assert "3,500,000" in (out["followers_text"] or "")


def test_profile_strips_at_and_slashes(patch_get):
    seen = {}

    def factory(url, kwargs):
        seen["url"] = url
        return FakeResponse(text=_meta({"og:title": "X"}))

    patch_get(facebook, factory)
    facebook.profile("@some.page/")
    assert seen["url"].endswith("/some.page")


def test_profile_followers_regex_requires_a_digit(patch_get):
    """Regression: '.followers' (just a dot) should not match."""
    html = _meta({"og:title": "x"}) + "<p>.followers everywhere</p>"
    patch_get(facebook, lambda url, kwargs: FakeResponse(text=html))
    out = facebook.profile("page")
    assert out["followers_text"] is None


def test_post_accepts_full_url(patch_get):
    seen = {}
    html = _meta(
        {
            "og:url": "https://www.facebook.com/zuck/posts/123",
            "og:type": "article",
            "og:title": "A post",
            "og:description": "post body",
            "og:image": "https://img/p.jpg",
            "article:published_time": "2026-04-01T10:00:00+0000",
        }
    )

    def factory(url, kwargs):
        seen["url"] = url
        return FakeResponse(text=html)

    patch_get(facebook, factory)
    out = facebook.post("https://www.facebook.com/zuck/posts/123")
    assert seen["url"] == "https://www.facebook.com/zuck/posts/123"
    assert out["title"] == "A post"
    assert out["type"] == "article"
    assert out["image"] == "https://img/p.jpg"
    assert out["published_time"] == "2026-04-01T10:00:00+0000"


def test_post_accepts_bare_path(patch_get):
    seen = {}
    patch_get(
        facebook,
        lambda url, kwargs: (seen.setdefault("url", url), FakeResponse(text=_meta({"og:title": "t"})))[1],
    )
    facebook.post("zuck/posts/123")
    assert seen["url"] == "https://www.facebook.com/zuck/posts/123"


def test_meta_parsing_unescapes_entities(patch_get):
    html = '<html><meta property="og:title" content="A &amp; B"></html>'
    patch_get(facebook, lambda url, kwargs: FakeResponse(text=html))
    out = facebook.profile("page")
    assert out["name"] == "A & B"


def test_profile_groups_multiple_og_image_variants(patch_get):
    """FB emits og:image once per variant followed by og:image:* sub-tags."""
    html = (
        "<html><head>"
        '<meta property="og:title" content="Page">'
        '<meta property="og:image" content="https://img/a.jpg">'
        '<meta property="og:image:width" content="1200">'
        '<meta property="og:image:height" content="630">'
        '<meta property="og:image" content="https://img/b.jpg">'
        '<meta property="og:image:width" content="600">'
        '<meta property="og:image:height" content="315">'
        "</head></html>"
    )
    patch_get(facebook, lambda url, kwargs: FakeResponse(text=html))
    out = facebook.profile("page")
    # First-wins single image
    assert out["image"] == "https://img/a.jpg"
    # All variants grouped with their dimensions
    assert len(out["images"]) == 2
    assert out["images"][0] == {"url": "https://img/a.jpg", "width": "1200", "height": "630"}
    assert out["images"][1] == {"url": "https://img/b.jpg", "width": "600", "height": "315"}


def test_post_extracts_og_video_variants(patch_get):
    html = (
        "<html><head>"
        '<meta property="og:title" content="Vid">'
        '<meta property="og:type" content="video.other">'
        '<meta property="og:video" content="https://v/clip.mp4">'
        '<meta property="og:video:url" content="https://v/clip.mp4">'
        '<meta property="og:video:secure_url" content="https://v/clip.mp4">'
        '<meta property="og:video:type" content="video/mp4">'
        '<meta property="og:video:width" content="1280">'
        '<meta property="og:video:height" content="720">'
        "</head></html>"
    )
    patch_get(facebook, lambda url, kwargs: FakeResponse(text=html))
    out = facebook.post("https://www.facebook.com/x/videos/1")
    assert out["video"] == "https://v/clip.mp4"
    assert out["video_secure_url"] == "https://v/clip.mp4"
    assert out["video_type"] == "video/mp4"
    assert out["video_width"] == "1280"
    assert out["video_height"] == "720"
    assert out["videos"][0] == {
        "url": "https://v/clip.mp4",
        "secure_url": "https://v/clip.mp4",
        "type": "video/mp4",
        "width": "1280",
        "height": "720",
    }


def test_photos_extracts_unique_fbids_and_urls(patch_get):
    """Each photo CDN URL embeds /<asset_id>_<fbid>_... — extract both."""
    html = (
        "<html><body>"
        # Same fbid appears twice in the HTML (different sizes) but should dedupe.
        'src="https://scontent.example.fbcdn.net/v/t39/100100100_4242424242420_a.jpg"'
        'src="https://scontent.example.fbcdn.net/v/t39/100100100_4242424242420_b.jpg"'
        'src="https://scontent.example.fbcdn.net/v/t39/200200200_5353535353530_c.jpg"'
        'src="https://scontent.example.fbcdn.net/v/t39/300300300_6464646464640_d.webp"'
        "</body></html>"
    )
    patch_get(facebook, lambda url, kwargs: FakeResponse(text=html))
    out = facebook.photos("pg")
    assert out["count"] == 3
    fbids = [p["fbid"] for p in out["photos"]]
    assert fbids == ["4242424242420", "5353535353530", "6464646464640"]
    # Order preserved; first occurrence wins.
    assert out["photos"][0]["asset_id"] == "100100100"
    assert out["photos"][0]["url"].endswith("_a.jpg")
    assert out["photos"][0]["permalink"] == "https://www.facebook.com/photo/?fbid=4242424242420"


def test_photos_respects_limit(patch_get):
    html = "".join(
        f'<img src="https://scontent.fbcdn.net/v/t39/{i*1000000}_{i*100000000000}_x.jpg">'
        for i in range(1, 6)
    )
    patch_get(facebook, lambda url, kwargs: FakeResponse(text=html))
    out = facebook.photos("pg", limit=3)
    assert out["count"] == 3


def test_photos_uses_photos_subpath(patch_get):
    seen = {}

    def factory(url, kwargs):
        seen["url"] = url
        return FakeResponse(text="")

    patch_get(facebook, factory)
    facebook.photos("@somepage/")
    assert seen["url"] == "https://www.facebook.com/somepage/photos"


def test_videos_extracts_playable_mp4_urls(patch_get):
    # JSON-style escaped URLs, as embedded in FB's React payload.
    html = (
        '<script>'
        '{"playable_url":"https:\\/\\/video.example.fbcdn.net\\/v\\/clip1.mp4?bitrate=500"}'
        '{"playable_url_quality_hd":"https:\\/\\/video.example.fbcdn.net\\/v\\/clip2.mp4"}'
        # Duplicate should dedupe.
        '{"playable_url":"https:\\/\\/video.example.fbcdn.net\\/v\\/clip1.mp4?bitrate=500"}'
        '{"video_id":"1234567890123"}'
        '{"video_id":"9876543210987"}'
        '</script>'
    )
    patch_get(facebook, lambda url, kwargs: FakeResponse(text=html))
    out = facebook.videos("pg")
    assert out["count"] == 2
    assert "https://video.example.fbcdn.net/v/clip1.mp4?bitrate=500" in out["playable_urls"]
    assert "https://video.example.fbcdn.net/v/clip2.mp4" in out["playable_urls"]
    assert out["video_ids"] == ["1234567890123", "9876543210987"]


def test_videos_uses_videos_subpath(patch_get):
    seen = {}
    patch_get(
        facebook,
        lambda url, kwargs: (seen.setdefault("url", url), FakeResponse(text=""))[1],
    )
    facebook.videos("somepage")
    assert seen["url"] == "https://www.facebook.com/somepage/videos"


def test_posts_finds_permalink_paths(patch_get):
    html = (
        '<a href="/facebook/posts/abc123">post</a>'
        '<a href="/facebook/videos/v777">vid</a>'
        '<a href="/facebook/photos/p888">pho</a>'
        # Duplicate should dedupe.
        '<a href="/facebook/posts/abc123">again</a>'
    )
    patch_get(facebook, lambda url, kwargs: FakeResponse(text=html))
    out = facebook.posts("facebook")
    assert out["count"] == 3
    kinds = {p["kind"] for p in out["posts"]}
    assert kinds == {"posts", "videos", "photos"}
    assert any(
        p["permalink"] == "https://www.facebook.com/facebook/posts/abc123"
        for p in out["posts"]
    )


def test_posts_falls_back_to_fbids(patch_get):
    """When no permalink paths are server-rendered, surface bare fbids."""
    html = '<a href="/somelink?fbid=123456789012345&foo=bar">x</a>' \
           'href="/x?fbid=987654321098765"'
    patch_get(facebook, lambda url, kwargs: FakeResponse(text=html))
    out = facebook.posts("page")
    assert out["count"] == 2
    fbids = [p["id"] for p in out["posts"]]
    assert "123456789012345" in fbids
    assert "987654321098765" in fbids
    assert all(p["kind"] == "photo" for p in out["posts"])


def test_posts_includes_note_about_logged_out_limitation(patch_get):
    patch_get(facebook, lambda url, kwargs: FakeResponse(text=""))
    out = facebook.posts("page")
    assert "logged-out" in out["note"]


def test_post_groups_multiple_og_video_tags(patch_get):
    """Some FB pages emit multiple og:video tags (e.g., one per format)."""
    html = (
        "<html><head>"
        '<meta property="og:video" content="https://v/a.mp4">'
        '<meta property="og:video:type" content="video/mp4">'
        '<meta property="og:video" content="https://v/b.webm">'
        '<meta property="og:video:type" content="video/webm">'
        "</head></html>"
    )
    patch_get(facebook, lambda url, kwargs: FakeResponse(text=html))
    out = facebook.post("anything")
    assert len(out["videos"]) == 2
    assert out["videos"][0]["url"] == "https://v/a.mp4"
    assert out["videos"][0]["type"] == "video/mp4"
    assert out["videos"][1]["url"] == "https://v/b.webm"
    assert out["videos"][1]["type"] == "video/webm"
