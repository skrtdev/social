"""Playwright-backed scroll-and-collect helper.

Optional dependency: install with `pip install '.[browser]'` followed by
`playwright install chromium`. The functions in this module raise
`BrowserUnavailable` with a clear message when Playwright isn't installed.

Each scroll is followed by a network-idle wait, then we re-run the extractor
to harvest items that just appeared. We stop when we've collected `max_items`
or when `max_idle_scrolls` consecutive scrolls produce no new items.
"""

from __future__ import annotations

from typing import Callable


class BrowserUnavailable(RuntimeError):
    """Raised when Playwright isn't installed or its browser isn't downloaded."""


_INSTALL_HINT = (
    "Playwright isn't installed. Install with:\n"
    "  pip install '.[browser]' && playwright install chromium"
)

# Playwright's default UA contains "HeadlessChrome" which FB blocks. Spoof a
# standard desktop Chrome on macOS so we look like a regular visitor.
_DEFAULT_UA = (
    "Mozilla/5.0 (Macintosh; Intel Mac OS X 10_15_7) "
    "AppleWebKit/537.36 (KHTML, like Gecko) "
    "Chrome/131.0.0.0 Safari/537.36"
)


def _require_playwright():
    try:
        from playwright.sync_api import sync_playwright  # noqa: F401
    except ImportError as e:
        raise BrowserUnavailable(_INSTALL_HINT) from e
    return sync_playwright


def _is_facebook(url: str) -> bool:
    return "facebook.com" in url


def _prime_facebook(page) -> None:
    """Visit fb.com homepage, decline optional cookies. Sets the `datr` cookie
    FB requires before letting you scroll past the first batch."""
    try:
        page.goto("https://www.facebook.com/", wait_until="domcontentloaded", timeout=20000)
    except Exception:
        return
    page.wait_for_timeout(2000)
    for label in (
        "Decline optional cookies",
        "Only allow essential cookies",
        "Allow all cookies",
    ):
        try:
            page.get_by_role("button", name=label).first.click(timeout=2000)
            break
        except Exception:
            continue
    page.wait_for_timeout(2000)


def _dismiss_login_modal(page) -> None:
    """FB pops a 'Log in or sign up' modal on Pages.

    The visible Close [X] button is intercepted by other DOM nodes ~50% of
    the time, so we just press Escape — that always dismisses the dialog
    without race conditions.
    """
    page.keyboard.press("Escape")


def scroll_collect(
    url: str,
    extractor: Callable[[str], list[dict]],
    *,
    key: str = "url",
    max_items: int = 200,
    max_idle_scrolls: int = 4,
    scroll_pause_ms: int = 2500,
    settle_ms: int = 4000,
    viewport: tuple[int, int] = (1280, 1800),
    user_agent: str | None = None,
    headless: bool = True,
) -> list[dict]:
    """Open `url` in headless Chromium, scroll, and collect items.

    `extractor(html)` is called against the current page HTML and must return
    a list of dicts. Items are deduped on `dict[key]`. We collect across
    scrolls, so virtualized items that leave the DOM stay in the result.

    Stops when `max_items` items are collected or after `max_idle_scrolls`
    consecutive scrolls that produce no new items.
    """
    sync_playwright = _require_playwright()
    try:
        from playwright.sync_api import TimeoutError as PWTimeout
    except ImportError:  # pragma: no cover
        PWTimeout = Exception

    seen: set = set()
    items: list[dict] = []

    with sync_playwright() as p:
        browser = p.chromium.launch(headless=headless)
        context = browser.new_context(
            viewport={"width": viewport[0], "height": viewport[1]},
            user_agent=user_agent or _DEFAULT_UA,
            locale="en-US",
        )
        page = context.new_page()
        if _is_facebook(url):
            _prime_facebook(page)
        page.goto(url, wait_until="domcontentloaded", timeout=30000)
        # FB / IG never reach networkidle (they poll constantly), so we just
        # use a generous fixed wait for the modal/initial grid to render.
        page.wait_for_timeout(settle_ms)
        if _is_facebook(url):
            _dismiss_login_modal(page)
            page.wait_for_timeout(1500)

        idle = 0
        while len(items) < max_items and idle < max_idle_scrolls:
            new = extractor(page.content())
            added = 0
            for entry in new:
                k = entry.get(key)
                if k is None or k in seen:
                    continue
                seen.add(k)
                items.append(entry)
                added += 1
                if len(items) >= max_items:
                    break
            idle = 0 if added else idle + 1
            if len(items) >= max_items:
                break
            # End key is the most reliable scroll trigger across FB / IG.
            page.keyboard.press("End")
            page.wait_for_timeout(scroll_pause_ms)

        context.close()
        browser.close()

    return items[:max_items]
