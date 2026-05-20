# social

A small Python CLI to fetch public profile and post info from **X / Twitter**,
**Instagram**, and **Facebook**. Built with [typer](https://typer.tiangolo.com/)
and [curl_cffi](https://github.com/yifeikong/curl_cffi) (impersonates a real
Chrome to slip past basic anti-bot filters).

No API keys required — everything goes through the platforms' public
embed / OpenGraph surfaces. That means the data is shallower than what the
official Graph / X APIs return, but you can run it with zero setup.

## Install

```bash
git clone https://github.com/skrtdev/social.git
cd social
python3 -m venv .venv
.venv/bin/pip install -e .
```

Make `social` available system-wide:

```bash
.venv/bin/social install      # symlinks into ~/.local/bin
```

(Uses a plain `ln -s` — no pipx, no system Python pollution. `social uninstall`
removes it.)

## Usage

```bash
# X / Twitter
social x profile jack
social x tweet 20

# Instagram
social instagram profile instagram
social instagram post DYkrf_cS9-t        # bare shortcode
social instagram post https://www.instagram.com/p/DYkrf_cS9-t/

# Facebook
social facebook profile zuck
social facebook post https://www.facebook.com/zuck/posts/...
```

Add `--json` / `-j` to any command for raw JSON instead of the rich table.

## What you get back

**X tweets** — full media: thumbnail, every `video_info.variants` rendition
(MP4 bitrates + HLS), best-MP4 convenience field, duration, aspect ratio,
alt text, entities (hashtags, mentions, expanded URLs).

**Instagram profiles** — bio, counts, and the ~12 most recent posts with
`display_url`, `video_url`, every `thumbnail_resources` resolution, carousel
children (each with their own media URLs), `product_type` (so you can tell
reels apart from feed posts), accessibility captions.

**Instagram posts** — LD+JSON path with images, videos, carousel walking;
falls back to OpenGraph metadata (which is what IG currently serves to
logged-out scrapers, as of the time of writing).

**Facebook** — OpenGraph metadata. Grouped `og:image` / `og:video` tags so
each variant comes back with its own `width` / `height` / `type`. This is
genuinely the thinnest surface of the three — for richer FB data you need a
Graph API token.

## Caveats

These are all unauthenticated, public-only paths:

- **X** rate-limits the syndication endpoint aggressively per-IP.
- **Instagram** sometimes serves `_a=1` JSON, sometimes only OpenGraph; both
  paths are supported.
- **Facebook** gates the post feed and most reactions behind login.

For real volume or richer fields (private accounts, full timelines, native
MP4 URLs on FB videos), use the official APIs with a token.

## Development

```bash
.venv/bin/pytest                 # 41 unit tests, fully mocked (no network)
.venv/bin/pytest -m network      # live smoke tests against all three platforms
```

Live tests gracefully `skip` on 429s / rate-limits so they don't false-fail.
