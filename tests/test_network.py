"""Real-network smoke tests against live X, Instagram, Facebook, and LinkedIn endpoints.

Opt-in only. Run with:

    pytest -m network -v

These endpoints rate-limit and reshape often; transient HTTP errors are treated
as `skip` rather than `fail` so a flaky run does not break the suite. Hard
parsing errors still fail — those mean our code is out of date.
"""

from __future__ import annotations

import pytest

from social_cli import facebook, instagram, linkedin, x
from social_cli.http import FetchError

pytestmark = pytest.mark.network


def _skip_on_transient(err: Exception) -> None:
    """Skip on rate-limiting / blocks; re-raise real bugs."""
    if isinstance(err, FetchError) and err.status in {401, 403, 404, 429, 500, 502, 503, 999}:
        pytest.skip(f"upstream returned {err.status}; transient")
    raise err


# ---------------------------------------------------------------- X / Twitter


def test_x_profile_live():
    try:
        data = x.profile("X")
    except Exception as e:  # noqa: BLE001
        _skip_on_transient(e)
    assert data["username"].lower() == "x"
    assert isinstance(data["followers"], int)
    assert data["followers"] > 1_000_000
    assert data["id"]
    assert isinstance(data["recent_tweets"], list)


def test_x_tweet_live():
    """Tweet ID 20 is Jack's first-ever tweet — about as stable as it gets."""
    try:
        data = x.tweet("20")
    except Exception as e:  # noqa: BLE001
        _skip_on_transient(e)
    assert data["id"] == "20"
    assert "just setting up my twttr" in (data["text"] or "").lower()
    assert data["author"]["screen_name"].lower() == "jack"


# ---------------------------------------------------------------- Instagram


@pytest.fixture(scope="module")
def ig_profile_data():
    try:
        return instagram.profile("instagram")
    except Exception as e:  # noqa: BLE001
        _skip_on_transient(e)


def test_instagram_profile_live(ig_profile_data):
    assert ig_profile_data["username"] == "instagram"
    assert ig_profile_data["is_verified"] is True
    assert isinstance(ig_profile_data["followers"], int)
    assert ig_profile_data["followers"] > 100_000_000
    assert isinstance(ig_profile_data["recent_posts"], list)
    assert ig_profile_data["recent_posts"], "expected at least one recent post"
    # New: every recent post should carry a display_url, and at least one
    # post in the feed has either a video_url or carousel children.
    first = ig_profile_data["recent_posts"][0]
    assert first["display_url"].startswith("http")
    assert isinstance(first.get("thumbnail_variants"), list)
    has_rich_media = any(
        p.get("video_url") or p.get("children") for p in ig_profile_data["recent_posts"]
    )
    assert has_rich_media, "expected at least one video or carousel in @instagram's feed"


def test_instagram_post_live(ig_profile_data):
    """Use a fresh shortcode discovered from the profile, so it can't rot."""
    posts = ig_profile_data["recent_posts"]
    shortcode = next((p["shortcode"] for p in posts if p.get("shortcode")), None)
    if not shortcode:
        pytest.skip("no shortcode in the recent_posts payload")
    try:
        data = instagram.post(shortcode)
    except Exception as e:  # noqa: BLE001
        _skip_on_transient(e)
    assert data["shortcode"] == shortcode
    # IG may serve the post under /p/, /reel/, or /tv/ depending on media type.
    assert shortcode in data["url"]
    # Either LD+JSON (richer, int counts) or OG fallback (string counts).
    assert data["source"] in {"ld+json", "og"}
    assert "likes" in data and "comments" in data


# ---------------------------------------------------------------- Facebook


def test_facebook_profile_live():
    try:
        data = facebook.profile("zuck")
    except Exception as e:  # noqa: BLE001
        _skip_on_transient(e)
    assert data["username"] == "zuck"
    assert "Zuckerberg" in (data["name"] or "")
    assert (data["image"] or "").startswith("http")
    # New: grouped images list contains at least one entry whose url matches.
    assert isinstance(data["images"], list)
    assert any(img.get("url") == data["image"] for img in data["images"])


def test_facebook_post_live():
    """Use Facebook's own page — its URL is stable and serves OG metadata."""
    try:
        data = facebook.post("https://www.facebook.com/facebook")
    except Exception as e:  # noqa: BLE001
        _skip_on_transient(e)
    assert (data["url"] or "").startswith("https://www.facebook.com/")
    # Either a title or a description should be present on a public page.
    assert data["title"] or data["description"]


def test_facebook_photos_live():
    """facebook is a small public Page with a populated /photos grid."""
    try:
        data = facebook.photos("facebook")
    except Exception as e:  # noqa: BLE001
        _skip_on_transient(e)
    assert data["count"] >= 3, "expected at least 3 photos in the grid"
    first = data["photos"][0]
    assert first["fbid"].isdigit()
    assert first["url"].startswith("https://scontent")
    assert first["permalink"] == f"https://www.facebook.com/photo/?fbid={first['fbid']}"


def test_facebook_videos_live():
    try:
        data = facebook.videos("facebook")
    except Exception as e:  # noqa: BLE001
        _skip_on_transient(e)
    # If the page has any videos at all, we should pull at least one MP4 URL.
    if data["count"] == 0:
        pytest.skip("page has no videos right now")
    assert data["playable_urls"][0].startswith("https://")
    assert ".mp4" in data["playable_urls"][0]


def test_facebook_posts_live():
    try:
        data = facebook.posts("facebook")
    except Exception as e:  # noqa: BLE001
        _skip_on_transient(e)
    # Logged-out main page is thin — we just verify the structure and note.
    assert "logged-out" in data["note"]
    assert isinstance(data["posts"], list)


# ---------------------------------------------------------------- LinkedIn


def test_linkedin_company_live():
    try:
        data = linkedin.company("linkedin")
    except Exception as e:  # noqa: BLE001
        _skip_on_transient(e)
    assert data["slug"] == "linkedin"
    assert data["name"] or data["description"]
    assert (data["url"] or "").startswith("https://www.linkedin.com/company/")


def test_linkedin_jobs_live():
    try:
        data = linkedin.jobs("software engineer", location="United States", limit=1)
    except Exception as e:  # noqa: BLE001
        _skip_on_transient(e)
    if data["count"] == 0:
        pytest.skip("LinkedIn returned no logged-out guest job cards")
    first = data["jobs"][0]
    assert first["id"]
    assert first["url"].startswith("https://www.linkedin.com/jobs/view/")
    assert first["title"] or first["company"]
