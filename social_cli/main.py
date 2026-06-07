"""Typer CLI entry point.

Layout:
    social x profile @user
    social x tweet 1734567890123456789
    social instagram profile user
    social instagram post SHORTCODE
    social facebook profile some.page
    social facebook post https://www.facebook.com/.../posts/...
    social linkedin profile some-person
    social linkedin business openai
"""

from __future__ import annotations

import json as jsonlib
import os
import sys
from pathlib import Path
from typing import Any, Callable

import typer
from rich.console import Console
from rich.table import Table

from . import facebook, instagram, linkedin, x
from .http import FetchError

DEFAULT_INSTALL_DIR = Path.home() / ".local" / "bin"

_ROOT_HELP = """\
Fetch public profile and post info from X, Instagram, Facebook, and LinkedIn.

Uses each platform's public, unauthenticated endpoints (X syndication,
Instagram web_profile_info / OpenGraph, Facebook OpenGraph, LinkedIn logged-out
pages / guest jobs). No API keys required — but data is limited to what those
surfaces expose, and the platforms rate-limit aggressively.

Examples:

  social x profile jack
  social x tweet 20
  social instagram profile instagram
  social instagram post DYkrf_cS9-t
  social facebook profile zuck
  social facebook post https://www.facebook.com/zuck/posts/...
  social facebook photos facebook --all --limit 100   # needs \\[browser]
  social linkedin profile some-person
  social linkedin business openai
  social linkedin company-jobs linkedin --limit 25
  social linkedin jobs "founding engineer" --location "San Francisco"
  social linkedin search "openai" --type companies

Global flags:
  -j / --json   Emit raw JSON instead of a rich table (works on any subcommand).

Listing commands (fb photos / videos / posts) also accept:
  -n / --limit N  Cap the number of items returned.
  -a / --all      Drive headless Chromium (Playwright) to scroll for more
                  than the server-rendered first batch. Requires the optional
                  \\[browser] extra:
                      pip install '.\\[browser]' && playwright install chromium

Setup:
  social install     Symlink the binary onto your PATH (default ~/.local/bin).
  social uninstall   Remove that symlink.
"""

_X_HELP = """\
X / Twitter lookups via the public syndication endpoints.

  profile  — bio, counts, profile/banner images, recent tweets with media
  tweet    — full tweet incl. video MP4 variants, entities, view count
"""

_IG_HELP = """\
Instagram lookups via web_profile_info and post LD+JSON/OpenGraph.

  profile  — bio, counts, recent posts with display_url + video_url +
             carousel children + thumbnail variants
  post     — single post by shortcode or URL (image, video, carousel)
"""

_FB_HELP = """\
Facebook lookups via OpenGraph metadata + page-feed scraping.

  profile  — name, description, image, og:image variants
  post     — title, description, og:image[*], og:video[*] variants
  photos   — recent photos from /photos (CDN URL + asset fbid + permalink)
  videos   — recent native MP4 URLs from /videos
  posts    — best-effort scrape of post permalinks (logged-out is thin)

`photos` and `videos` accept -n/--limit and -a/--all. Without --all they
return the ~10 items FB server-renders. With --all they drive a headless
Chromium (requires the optional \\[browser] extra) to scroll past the login
modal and collect older items up to --limit.

Note: Facebook Groups always require login and are not supported.
For richer page data, use the Graph API with a token.
"""

_LI_HELP = """\
LinkedIn lookups via public logged-out pages and guest jobs endpoints.

  profile   — public person profile metadata (name, headline, image, orgs)
  company   — public company/business page metadata
  business  — alias for company
  company-jobs   — jobs rendered on a public company jobs page
  company-posts  — best-effort public company activity/post links
  school    — public school page metadata
  post      — public feed update metadata by URL / URN / activity id
  job       — single job by numeric id or /jobs/view/... URL
  jobs      — guest job search cards with company, location, listed date
  search    — best-effort public search over people, companies, posts, jobs

LinkedIn exposes very little to logged-out visitors outside jobs, so profile,
company, school, post, and non-job search data is best-effort and may be
sign-in gated.
"""

app = typer.Typer(
    no_args_is_help=True,
    add_completion=False,
    help=_ROOT_HELP,
)
x_app = typer.Typer(no_args_is_help=True, help=_X_HELP)
ig_app = typer.Typer(no_args_is_help=True, help=_IG_HELP)
fb_app = typer.Typer(no_args_is_help=True, help=_FB_HELP)
li_app = typer.Typer(no_args_is_help=True, help=_LI_HELP)
app.add_typer(x_app, name="x")
app.add_typer(ig_app, name="instagram")
app.add_typer(fb_app, name="facebook")
app.add_typer(li_app, name="linkedin")

console = Console()
err_console = Console(stderr=True)


def _render(data: dict[str, Any], as_json: bool, title: str) -> None:
    if as_json:
        typer.echo(jsonlib.dumps(data, indent=2, ensure_ascii=False, default=str))
        return
    table = Table(title=title, show_header=True, header_style="bold cyan")
    table.add_column("field", style="bold")
    table.add_column("value", overflow="fold")
    for key, value in data.items():
        if isinstance(value, (dict, list)):
            value = jsonlib.dumps(value, indent=2, ensure_ascii=False, default=str)
        table.add_row(str(key), "" if value is None else str(value))
    console.print(table)


def _run(fn: Callable[..., dict[str, Any]], *args: Any, json: bool, title: str) -> None:
    try:
        data = fn(*args)
    except FetchError as e:
        err_console.print(f"[red]HTTP {e.status} fetching {e.url}[/red]")
        raise typer.Exit(2)
    except Exception as e:  # noqa: BLE001
        err_console.print(f"[red]Error:[/red] {e}")
        raise typer.Exit(1)
    _render(data, json, title)


JsonOpt = typer.Option(False, "--json", "-j", help="Emit raw JSON instead of a table.")
AllOpt = typer.Option(
    False, "--all", "-a",
    help="Scroll a headless Chromium (Playwright) past the server-rendered "
         "first batch. Needs the \\[browser] extra. Adds ~25s of latency.",
)


@x_app.command("profile")
def x_profile(
    username: str = typer.Argument(
        ...,
        help="X / Twitter handle, with or without leading '@' (e.g. 'jack' or '@jack').",
        metavar="USERNAME",
    ),
    json: bool = JsonOpt,
) -> None:
    """Fetch an X / Twitter profile.

    Returns bio, follower/following/tweet counts, profile picture, banner image,
    and up to 10 recent tweets with their media (photos + video MP4 variants).
    Only public accounts are accessible — protected accounts return an error.

    Example:

      social x profile jack
      social x profile @elonmusk --json
    """
    _run(x.profile, username, json=json, title=f"X profile: @{username.lstrip('@')}")


@x_app.command("tweet")
def x_tweet(
    tweet_id: str = typer.Argument(
        ...,
        help="Numeric tweet ID (the digits at the end of the URL, NOT the full URL).",
        metavar="TWEET_ID",
    ),
    json: bool = JsonOpt,
) -> None:
    """Fetch a tweet by its numeric ID.

    Returns text, counts, author, media (with all video MP4 bitrate variants
    plus a 'best_mp4' convenience field), and entities (hashtags, mentions,
    expanded URLs).

    The tweet ID is the digits at the end of the URL — e.g. for
    https://x.com/jack/status/20 the ID is `20`.

    Example:

      social x tweet 20
      social x tweet 1734567890123456789 --json
    """
    _run(x.tweet, tweet_id, json=json, title=f"Tweet {tweet_id}")


@ig_app.command("profile")
def ig_profile(
    username: str = typer.Argument(
        ...,
        help="Instagram username, with or without leading '@' (e.g. 'instagram').",
        metavar="USERNAME",
    ),
    json: bool = JsonOpt,
) -> None:
    """Fetch an Instagram profile.

    Returns bio, counts, profile pic, and ~12 recent posts. Each post
    includes display_url, thumbnail_src, video_url (when applicable), all
    thumbnail resolutions, carousel children, and accessibility caption.

    Example:

      social instagram profile instagram
      social instagram profile @natgeo --json
    """
    _run(instagram.profile, username, json=json, title=f"Instagram: @{username.lstrip('@')}")


@ig_app.command("post")
def ig_post(
    shortcode: str = typer.Argument(
        ...,
        help="Post shortcode (e.g. 'DYkrf_cS9-t') or full URL "
             "(https://www.instagram.com/p/DYkrf_cS9-t/).",
        metavar="SHORTCODE",
    ),
    json: bool = JsonOpt,
) -> None:
    """Fetch an Instagram post by shortcode or URL.

    The shortcode is the path segment after /p/ in the URL. URLs are
    accepted and the shortcode is extracted automatically. Works for both
    photo posts and reels.

    When LD+JSON is available the result includes images, videos (with
    contentUrl + thumbnail + duration), and carousel detection. Otherwise
    falls back to OpenGraph metadata (which is what IG currently serves
    to logged-out scrapers).

    Example:

      social instagram post DYkrf_cS9-t
      social instagram post https://www.instagram.com/p/DYkrf_cS9-t/
    """
    _run(instagram.post, shortcode, json=json, title=f"Instagram post {shortcode}")


@fb_app.command("profile")
def fb_profile(
    username: str = typer.Argument(
        ...,
        help="Facebook page username or ID (e.g. 'zuck' or 'facebook').",
        metavar="USERNAME",
    ),
    json: bool = JsonOpt,
) -> None:
    """Fetch a Facebook profile or page (public OpenGraph metadata).

    Returns name, description, og:image (and all og:image variants with
    width/height), plus loose follower/likes counts grepped from the
    rendered HTML.

    Example:

      social facebook profile zuck
      social facebook profile facebook --json
    """
    _run(facebook.profile, username, json=json, title=f"Facebook: {username}")


@fb_app.command("post")
def fb_post(
    url: str = typer.Argument(
        ...,
        help="Full Facebook URL (https://www.facebook.com/...) OR a bare path "
             "like 'user/posts/123' / 'user/videos/456'.",
        metavar="URL_OR_PATH",
    ),
    json: bool = JsonOpt,
) -> None:
    """Fetch a Facebook post by URL (public OpenGraph metadata).

    Returns og:title, og:description, all og:image variants, and all
    og:video variants (with their type/width/height/secure_url).

    Both full URLs and bare paths are accepted:

      social facebook post https://www.facebook.com/zuck/posts/123
      social facebook post zuck/posts/123
    """
    _run(facebook.post, url, json=json, title="Facebook post")


@fb_app.command("photos")
def fb_photos(
    username: str = typer.Argument(
        ...,
        help="Facebook Page username/slug (e.g. 'facebook').",
        metavar="USERNAME",
    ),
    limit: int = typer.Option(24, "--limit", "-n", help="Max photos to return."),
    all_: bool = AllOpt,
    json: bool = JsonOpt,
) -> None:
    """List recent photos from a public Facebook Page.

    Each photo entry has:
      fbid       — the asset fbid (extracted from the CDN URL itself)
      asset_id   — internal asset id
      url        — direct CDN image URL
      permalink  — https://www.facebook.com/photo/?fbid=<fbid>

    Returned in document order (roughly newest-first). The response
    includes a `mode` field of "http" or "browser" so you can tell which
    path produced the data.

    Default (HTTP): one request → the ~10 photos FB server-renders.
    With --all: scrolls a headless Chromium until --limit is reached.
    Requires the \\[browser] extra (see `social --help`).

    Examples:

      social facebook photos facebook
      social facebook photos facebook --all --limit 100
      social facebook photos zuck -n 50 -a -j
    """
    _run(
        lambda u: facebook.photos(u, limit=limit, all=all_),
        username, json=json, title=f"Photos: {username}",
    )


@fb_app.command("videos")
def fb_videos(
    username: str = typer.Argument(
        ...,
        help="Facebook Page username/slug.",
        metavar="USERNAME",
    ),
    limit: int = typer.Option(24, "--limit", "-n", help="Max videos to return."),
    all_: bool = AllOpt,
    json: bool = JsonOpt,
) -> None:
    """List recent native MP4 video URLs from a public Facebook Page.

    Returns the actual playable MP4 URLs (the same ones the FB player
    streams). Titles / durations / dates are not reliably extractable
    from the obfuscated React payload — use the Graph API for those.

    Default (HTTP): one request → the ~10 videos FB server-renders.
    With --all: scrolls a headless Chromium until --limit is reached.
    Requires the \\[browser] extra.

    Examples:

      social facebook videos facebook
      social facebook videos facebook --all --limit 50
    """
    _run(
        lambda u: facebook.videos(u, limit=limit, all=all_),
        username, json=json, title=f"Videos: {username}",
    )


@fb_app.command("posts")
def fb_posts(
    username: str = typer.Argument(
        ...,
        help="Facebook Page username/slug.",
        metavar="USERNAME",
    ),
    json: bool = JsonOpt,
) -> None:
    """Best-effort: list post permalinks visible on a public Page.

    Facebook does not server-render the main post feed for logged-out
    visitors, so this usually returns very little (often just a pinned
    or cover post). The response includes an explicit `note` field
    flagging this.

    `--all` is NOT supported here: even with a real browser, FB does not
    expose the post feed to logged-out scrollers. For real post coverage
    you need either auth cookies or the Graph API with a token.

    Example:

      social facebook posts facebook
    """
    _run(facebook.posts, username, json=json, title=f"Posts: {username}")


@li_app.command("profile")
def li_profile(
    username: str = typer.Argument(
        ...,
        help="LinkedIn public profile slug or URL.",
        metavar="USERNAME_OR_URL",
    ),
    json: bool = JsonOpt,
) -> None:
    """Fetch a public LinkedIn person profile.

    Returns the public name, headline, description, image, current company,
    education, followers/connections text when present, and the canonical URL.

    Example:

      social linkedin profile some-person
      social linkedin profile https://www.linkedin.com/in/some-person/ --json
    """
    _run(linkedin.profile, username, json=json, title=f"LinkedIn profile: {username}")


@li_app.command("company")
def li_company(
    company_name: str = typer.Argument(
        ...,
        help="LinkedIn company slug or URL.",
        metavar="COMPANY_OR_URL",
    ),
    json: bool = JsonOpt,
) -> None:
    """Fetch a public LinkedIn company page.

    Returns business metadata such as description, industry, company size,
    headquarters, followers text, image/logo, and links to jobs/posts.

    Example:

      social linkedin company openai
      social linkedin company https://www.linkedin.com/company/openai/ --json
    """
    _run(linkedin.company, company_name, json=json, title=f"LinkedIn company: {company_name}")


@li_app.command("business")
def li_business(
    company_name: str = typer.Argument(
        ...,
        help="LinkedIn business/company slug or URL.",
        metavar="BUSINESS_OR_URL",
    ),
    json: bool = JsonOpt,
) -> None:
    """Alias for `social linkedin company`."""
    _run(linkedin.business, company_name, json=json, title=f"LinkedIn business: {company_name}")


@li_app.command("company-jobs")
def li_company_jobs(
    company_name: str = typer.Argument(
        ...,
        help="LinkedIn company slug or URL.",
        metavar="COMPANY_OR_URL",
    ),
    limit: int = typer.Option(25, "--limit", "-n", help="Max job cards to return."),
    json: bool = JsonOpt,
) -> None:
    """List jobs rendered on a public LinkedIn company jobs page.

    Example:

      social linkedin company-jobs linkedin
      social linkedin company-jobs https://www.linkedin.com/company/linkedin/ -n 50 --json
    """
    _run(
        lambda c: linkedin.company_jobs(c, limit=limit),
        company_name,
        json=json,
        title=f"LinkedIn company jobs: {company_name}",
    )


@li_app.command("company-posts")
def li_company_posts(
    company_name: str = typer.Argument(
        ...,
        help="LinkedIn company slug or URL.",
        metavar="COMPANY_OR_URL",
    ),
    limit: int = typer.Option(25, "--limit", "-n", help="Max post links to return."),
    json: bool = JsonOpt,
) -> None:
    """Best-effort public LinkedIn company activity/post links.

    LinkedIn commonly redirects company activity to sign-in for logged-out
    visitors, so this command returns whatever post links are public plus a
    note describing the limitation.
    """
    _run(
        lambda c: linkedin.company_posts(c, limit=limit),
        company_name,
        json=json,
        title=f"LinkedIn company posts: {company_name}",
    )


@li_app.command("school")
def li_school(
    school_name: str = typer.Argument(
        ...,
        help="LinkedIn school slug or URL.",
        metavar="SCHOOL_OR_URL",
    ),
    json: bool = JsonOpt,
) -> None:
    """Fetch a public LinkedIn school page."""
    _run(linkedin.school, school_name, json=json, title=f"LinkedIn school: {school_name}")


@li_app.command("post")
def li_post(
    url_or_urn: str = typer.Argument(
        ...,
        help="LinkedIn feed update URL, URN, or bare numeric activity id.",
        metavar="URL_OR_URN",
    ),
    json: bool = JsonOpt,
) -> None:
    """Fetch a public LinkedIn feed post/update."""
    _run(linkedin.post, url_or_urn, json=json, title="LinkedIn post")


@li_app.command("job")
def li_job(
    job_id_or_url: str = typer.Argument(
        ...,
        help="LinkedIn numeric job id or /jobs/view/... URL.",
        metavar="JOB_ID_OR_URL",
    ),
    json: bool = JsonOpt,
) -> None:
    """Fetch one LinkedIn job posting."""
    _run(linkedin.job, job_id_or_url, json=json, title=f"LinkedIn job: {job_id_or_url}")


@li_app.command("jobs")
def li_jobs(
    keywords: str = typer.Argument(
        ...,
        help="Job search keywords.",
        metavar="KEYWORDS",
    ),
    location: str | None = typer.Option(None, "--location", "-l", help="Optional job search location."),
    limit: int = typer.Option(25, "--limit", "-n", help="Max job cards to return."),
    json: bool = JsonOpt,
) -> None:
    """Search LinkedIn public guest job cards."""
    _run(
        lambda q: linkedin.jobs(q, location=location, limit=limit),
        keywords,
        json=json,
        title=f"LinkedIn jobs: {keywords}",
    )


@li_app.command("search")
def li_search(
    query: str = typer.Argument(
        ...,
        help="Search query.",
        metavar="QUERY",
    ),
    kind: str = typer.Option(
        "all",
        "--type",
        "-t",
        help="Search type: all, people, companies, businesses, schools, posts, content, jobs.",
    ),
    location: str | None = typer.Option(None, "--location", "-l", help="Location for --type jobs."),
    limit: int = typer.Option(10, "--limit", "-n", help="Max results to return."),
    json: bool = JsonOpt,
) -> None:
    """Best-effort public LinkedIn search.

    Non-job search pages are often sign-in gated, so this command returns
    whatever public links LinkedIn renders for logged-out users. For jobs,
    it uses LinkedIn's guest job search endpoint.
    """
    _run(
        lambda q: linkedin.search(q, kind=kind, location=location, limit=limit),
        query,
        json=json,
        title=f"LinkedIn search: {query}",
    )


def _entrypoint_path() -> Path:
    """Resolve the actual `social` script in the current venv."""
    # sys.argv[0] is the script being invoked; resolve through any existing symlink.
    candidate = Path(sys.argv[0]).resolve()
    if candidate.exists() and candidate.name in {"social", "social.exe"}:
        return candidate
    # Fallback: look next to the active python interpreter.
    sibling = Path(sys.executable).parent / "social"
    if sibling.exists():
        return sibling.resolve()
    raise FileNotFoundError("Could not locate the `social` entrypoint to symlink.")


@app.command("install")
def install_cmd(
    target: Path = typer.Option(
        DEFAULT_INSTALL_DIR,
        "--target", "-t",
        help="Directory to place the symlink in.",
    ),
    name: str = typer.Option("social", "--name", "-n", help="Symlink name."),
    force: bool = typer.Option(False, "--force", "-f", help="Replace an existing symlink."),
) -> None:
    """Symlink the `social` binary into a directory on your PATH.

    By default this links into `~/.local/bin` so the command works from any
    shell. The link points at the venv-bound entrypoint, so dependencies
    resolve correctly no matter where you invoke it from.

    Examples:

      social install                       # default ~/.local/bin
      social install -t /usr/local/bin     # custom target dir
      social install -n soc                # custom symlink name
      social install --force               # replace an existing link
    """
    try:
        source = _entrypoint_path()
    except FileNotFoundError as e:
        err_console.print(f"[red]{e}[/red]")
        raise typer.Exit(1)

    target.mkdir(parents=True, exist_ok=True)
    link = target / name

    if link.is_symlink() or link.exists():
        existing = link.resolve() if link.is_symlink() else link
        if existing == source and not force:
            console.print(f"[green]Already installed:[/green] {link} -> {source}")
            return
        if not force:
            err_console.print(
                f"[red]{link} already exists[/red] (-> {existing}). Use --force to replace."
            )
            raise typer.Exit(1)
        link.unlink()

    link.symlink_to(source)
    console.print(f"[green]Linked[/green] {link} -> {source}")

    path_entries = os.environ.get("PATH", "").split(os.pathsep)
    if str(target) not in path_entries:
        console.print(
            f"[yellow]Note:[/yellow] {target} is not on $PATH. "
            f"Add it to your shell rc: [bold]export PATH=\"{target}:$PATH\"[/bold]"
        )


@app.command("uninstall")
def uninstall_cmd(
    target: Path = typer.Option(
        DEFAULT_INSTALL_DIR, "--target", "-t",
        help="Directory the symlink lives in.",
    ),
    name: str = typer.Option(
        "social", "--name", "-n", help="Symlink name to remove.",
    ),
) -> None:
    """Remove the symlink created by `social install`.

    Refuses to delete the target if it's a real file rather than a symlink,
    so you can't accidentally nuke an unrelated binary at that path.
    """
    link = target / name
    if not link.is_symlink():
        err_console.print(
            f"[red]{link} is not a symlink[/red] "
            f"({'missing' if not link.exists() else 'real file — refusing to delete'})."
        )
        raise typer.Exit(1)
    link.unlink()
    console.print(f"[green]Removed[/green] {link}")


def main() -> None:  # pragma: no cover
    app()


if __name__ == "__main__":  # pragma: no cover
    sys.exit(app() or 0)
