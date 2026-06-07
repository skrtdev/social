# social

A small Python CLI to fetch public profile, post, business, search, and job
info from **X / Twitter**, **Instagram**, **Facebook**, and **LinkedIn**. Built
with [typer](https://typer.tiangolo.com/) and
[curl_cffi](https://github.com/yifeikong/curl_cffi) (impersonates a real Chrome
to slip past basic anti-bot filters).

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

**Optional: browser-backed pagination.** The default HTTP path returns the
first ~10 photos / videos a Page server-renders. To scroll for more, install
the `[browser]` extra and use `--all`:

```bash
.venv/bin/pip install -e '.[browser]'
.venv/bin/playwright install chromium      # ~100 MB one-time download
social facebook photos facebook --all --limit 200
```

This launches a headless Chromium, dismisses FB's login modal with ESC, and
scrolls until `--limit` items are collected (or the page runs out).

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
social facebook photos facebook             # ~10 most recent photos (HTTP)
social facebook photos facebook --all -n 200  # scroll for more (needs [browser])
social facebook videos facebook              # recent native MP4 URLs
social facebook videos facebook --all -n 100  # scroll for more
social facebook posts  facebook              # best-effort permalinks (limited)

# LinkedIn
social linkedin profile some-person
social linkedin company openai
social linkedin business openai              # alias for company
social linkedin school stanford-university
social linkedin post urn:li:activity:123456789
social linkedin job 1234567890
social linkedin jobs "founding engineer" --location "San Francisco" -n 25
social linkedin search "openai" --type companies
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

**Facebook** — OpenGraph metadata on profile/post pages with grouped
`og:image` / `og:video` variants (each with its own `width` / `height` / `type`).
Plus scraped page feeds: `photos` returns recent photos with CDN URLs +
permalinks; `videos` returns native MP4 playable URLs. Post-feed text isn't
server-rendered to logged-out visitors, so `posts` is best-effort and thin.
Groups always require login — not supported.

**LinkedIn profiles** — public logged-out person metadata: name, headline,
description, image, current company, education, followers/connections text
when present, and canonical URL.

**LinkedIn businesses / companies / schools** — public page metadata: name,
description, logo/image, website, industry, company size, headquarters, type,
founded date, specialties, followers text, and jobs/posts URLs when LinkedIn
renders them.

**LinkedIn posts** — public feed update metadata by full URL, URN, or numeric
activity id: title/text, author, published/updated time, image, and video when
OpenGraph or JSON-LD exposes it.

**LinkedIn jobs and search** — `job` fetches a single posting by id or URL using
LinkedIn's guest job endpoint with JSON-LD and criteria parsing. `jobs` returns
public guest search cards with job id, title, company, location, listed date,
salary text, image, and URL. `search` best-effort parses logged-out public
search pages for people, companies/businesses, schools, posts, and jobs.

## Caveats

These are all unauthenticated, public-only paths:

- **X** rate-limits the syndication endpoint aggressively per-IP.
- **Instagram** sometimes serves `_a=1` JSON, sometimes only OpenGraph; both
  paths are supported.
- **Facebook** gates the post feed and most reactions behind login.
- **LinkedIn** gates most non-job data behind sign-in. Jobs are the richest
  logged-out surface; profiles, businesses, posts, and search return whatever
  public metadata LinkedIn renders.

For real volume or richer fields (private accounts, full timelines, native
MP4 URLs on FB videos), use the official APIs with a token.

## Development

```bash
.venv/bin/pytest                 # unit tests, fully mocked (no network)
.venv/bin/pytest -m network      # live smoke tests against all four platforms
```

Live tests gracefully `skip` on 429s / rate-limits so they don't false-fail.
