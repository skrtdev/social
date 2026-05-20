"""Typer CLI entry point.

Layout:
    social x profile @user
    social x tweet 1734567890123456789
    social instagram profile user
    social instagram post SHORTCODE
    social facebook profile some.page
    social facebook post https://www.facebook.com/.../posts/...
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

from . import facebook, instagram, x
from .http import FetchError

DEFAULT_INSTALL_DIR = Path.home() / ".local" / "bin"

app = typer.Typer(
    no_args_is_help=True,
    add_completion=False,
    help="Fetch public profile and post info from X, Instagram, and Facebook.",
)
x_app = typer.Typer(no_args_is_help=True, help="X / Twitter lookups.")
ig_app = typer.Typer(no_args_is_help=True, help="Instagram lookups.")
fb_app = typer.Typer(no_args_is_help=True, help="Facebook lookups.")
app.add_typer(x_app, name="x")
app.add_typer(ig_app, name="instagram")
app.add_typer(fb_app, name="facebook")

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


@x_app.command("profile")
def x_profile(username: str, json: bool = JsonOpt) -> None:
    """Fetch an X / Twitter profile."""
    _run(x.profile, username, json=json, title=f"X profile: @{username.lstrip('@')}")


@x_app.command("tweet")
def x_tweet(tweet_id: str, json: bool = JsonOpt) -> None:
    """Fetch a tweet by its numeric ID."""
    _run(x.tweet, tweet_id, json=json, title=f"Tweet {tweet_id}")


@ig_app.command("profile")
def ig_profile(username: str, json: bool = JsonOpt) -> None:
    """Fetch an Instagram profile."""
    _run(instagram.profile, username, json=json, title=f"Instagram: @{username.lstrip('@')}")


@ig_app.command("post")
def ig_post(shortcode: str, json: bool = JsonOpt) -> None:
    """Fetch an Instagram post by shortcode or URL."""
    _run(instagram.post, shortcode, json=json, title=f"Instagram post {shortcode}")


@fb_app.command("profile")
def fb_profile(username: str, json: bool = JsonOpt) -> None:
    """Fetch a Facebook profile/page (public OG metadata)."""
    _run(facebook.profile, username, json=json, title=f"Facebook: {username}")


@fb_app.command("post")
def fb_post(url: str, json: bool = JsonOpt) -> None:
    """Fetch a Facebook post by URL (public OG metadata)."""
    _run(facebook.post, url, json=json, title="Facebook post")


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
    target: Path = typer.Option(DEFAULT_INSTALL_DIR, "--target", "-t"),
    name: str = typer.Option("social", "--name", "-n"),
) -> None:
    """Remove the symlink created by `social install`."""
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
