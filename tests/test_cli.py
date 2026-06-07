"""End-to-end CLI tests via typer's CliRunner."""

from __future__ import annotations

import json as jsonlib

from typer.testing import CliRunner

from social_cli import facebook, instagram, linkedin, main, x
from tests.conftest import FakeResponse

runner = CliRunner()


def test_root_shows_subcommands():
    result = runner.invoke(main.app, ["--help"])
    assert result.exit_code == 0
    assert "x" in result.stdout
    assert "instagram" in result.stdout
    assert "facebook" in result.stdout
    assert "linkedin" in result.stdout


def test_x_profile_json(monkeypatch):
    payload = (
        '<html><script id="__NEXT_DATA__" type="application/json">'
        + jsonlib.dumps(
            {
                "props": {
                    "pageProps": {
                        "timeline": {
                            "entries": [
                                {
                                    "content": {
                                        "tweet": {
                                            "id_str": "1",
                                            "text": "hi",
                                            "user": {
                                                "screen_name": "alice",
                                                "name": "Alice",
                                                "followers_count": 5,
                                            },
                                        }
                                    }
                                }
                            ]
                        }
                    }
                }
            }
        )
        + "</script></html>"
    )
    monkeypatch.setattr(x, "get", lambda url, **kw: FakeResponse(text=payload))
    result = runner.invoke(main.app, ["x", "profile", "alice", "--json"])
    assert result.exit_code == 0, result.stdout
    data = jsonlib.loads(result.stdout)
    assert data["username"] == "alice"
    assert data["followers"] == 5


def test_instagram_post_table(monkeypatch):
    ld = {
        "url": "https://www.instagram.com/p/ABC/",
        "articleBody": "cap",
        "interactionStatistic": [],
        "author": {"alternateName": "@bob", "name": "Bob"},
        "image": [],
    }
    html = (
        '<html><script type="application/ld+json">'
        + jsonlib.dumps(ld)
        + "</script></html>"
    )
    monkeypatch.setattr(instagram, "get", lambda url, **kw: FakeResponse(text=html))
    result = runner.invoke(main.app, ["instagram", "post", "ABC"])
    assert result.exit_code == 0, result.stdout
    assert "ABC" in result.stdout
    assert "cap" in result.stdout


def test_facebook_profile_handles_404(monkeypatch):
    from social_cli.http import FetchError

    def boom(url, **kw):
        raise FetchError(url, 404, "not found")

    monkeypatch.setattr(facebook, "get", boom)
    result = runner.invoke(main.app, ["facebook", "profile", "missing"])
    assert result.exit_code == 2
    assert "404" in result.stderr or "404" in result.stdout


def test_linkedin_business_json(monkeypatch):
    monkeypatch.setattr(
        linkedin,
        "business",
        lambda company_name: {
            "type": "organization",
            "slug": company_name,
            "name": "OpenAI",
        },
    )
    result = runner.invoke(main.app, ["linkedin", "business", "openai", "--json"])
    assert result.exit_code == 0, result.stdout
    data = jsonlib.loads(result.stdout)
    assert data["type"] == "organization"
    assert data["slug"] == "openai"
    assert data["name"] == "OpenAI"


def test_linkedin_jobs_json_passes_options(monkeypatch):
    seen = {}

    def fake_jobs(keywords, *, location=None, limit=25):
        seen["keywords"] = keywords
        seen["location"] = location
        seen["limit"] = limit
        return {
            "query": keywords,
            "location": location,
            "count": 0,
            "jobs": [],
        }

    monkeypatch.setattr(linkedin, "jobs", fake_jobs)
    result = runner.invoke(
        main.app,
        ["linkedin", "jobs", "founding engineer", "--location", "Remote", "--limit", "2", "--json"],
    )
    assert result.exit_code == 0, result.stdout
    data = jsonlib.loads(result.stdout)
    assert data["query"] == "founding engineer"
    assert data["location"] == "Remote"
    assert seen == {"keywords": "founding engineer", "location": "Remote", "limit": 2}


def test_linkedin_company_jobs_json_passes_limit(monkeypatch):
    seen = {}

    def fake_company_jobs(company_name, *, limit=25):
        seen["company_name"] = company_name
        seen["limit"] = limit
        return {
            "type": "company_jobs",
            "slug": company_name,
            "count": 0,
            "jobs": [],
        }

    monkeypatch.setattr(linkedin, "company_jobs", fake_company_jobs)
    result = runner.invoke(
        main.app,
        ["linkedin", "company-jobs", "linkedin", "--limit", "3", "--json"],
    )
    assert result.exit_code == 0, result.stdout
    data = jsonlib.loads(result.stdout)
    assert data["type"] == "company_jobs"
    assert seen == {"company_name": "linkedin", "limit": 3}


def test_linkedin_company_posts_json_passes_limit(monkeypatch):
    seen = {}

    def fake_company_posts(company_name, *, limit=25):
        seen["company_name"] = company_name
        seen["limit"] = limit
        return {
            "type": "company_posts",
            "slug": company_name,
            "count": 0,
            "posts": [],
        }

    monkeypatch.setattr(linkedin, "company_posts", fake_company_posts)
    result = runner.invoke(
        main.app,
        ["linkedin", "company-posts", "openai", "-n", "4", "--json"],
    )
    assert result.exit_code == 0, result.stdout
    data = jsonlib.loads(result.stdout)
    assert data["type"] == "company_posts"
    assert seen == {"company_name": "openai", "limit": 4}


def test_x_profile_runtime_error_exits_1(monkeypatch):
    monkeypatch.setattr(x, "get", lambda url, **kw: FakeResponse(text="<html></html>"))
    result = runner.invoke(main.app, ["x", "profile", "ghost"])
    assert result.exit_code == 1


# ----------------------------------------------------------------- install/uninstall


def _fake_entrypoint(tmp_path):
    """Create a fake `social` script that _entrypoint_path() will resolve to."""
    src = tmp_path / "venv" / "bin" / "social"
    src.parent.mkdir(parents=True)
    src.write_text("#!/usr/bin/env python3\n")
    src.chmod(0o755)
    return src


def test_install_creates_symlink(tmp_path, monkeypatch):
    src = _fake_entrypoint(tmp_path)
    target = tmp_path / "bin"
    monkeypatch.setattr(main, "_entrypoint_path", lambda: src)
    result = runner.invoke(main.app, ["install", "--target", str(target)])
    assert result.exit_code == 0, result.stdout
    link = target / "social"
    assert link.is_symlink()
    assert link.resolve() == src.resolve()
    assert "Linked" in result.stdout


def test_install_idempotent_when_link_already_correct(tmp_path, monkeypatch):
    src = _fake_entrypoint(tmp_path)
    target = tmp_path / "bin"
    target.mkdir()
    (target / "social").symlink_to(src)
    monkeypatch.setattr(main, "_entrypoint_path", lambda: src)
    result = runner.invoke(main.app, ["install", "--target", str(target)])
    assert result.exit_code == 0
    assert "Already installed" in result.stdout


def test_install_refuses_existing_link_without_force(tmp_path, monkeypatch):
    src = _fake_entrypoint(tmp_path)
    other = tmp_path / "other-social"
    other.write_text("#!/bin/sh\n")
    target = tmp_path / "bin"
    target.mkdir()
    (target / "social").symlink_to(other)
    monkeypatch.setattr(main, "_entrypoint_path", lambda: src)
    result = runner.invoke(main.app, ["install", "--target", str(target)])
    assert result.exit_code == 1
    assert "already exists" in result.stderr


def test_install_force_replaces_existing(tmp_path, monkeypatch):
    src = _fake_entrypoint(tmp_path)
    other = tmp_path / "other-social"
    other.write_text("#!/bin/sh\n")
    target = tmp_path / "bin"
    target.mkdir()
    (target / "social").symlink_to(other)
    monkeypatch.setattr(main, "_entrypoint_path", lambda: src)
    result = runner.invoke(main.app, ["install", "--target", str(target), "--force"])
    assert result.exit_code == 0
    assert (target / "social").resolve() == src.resolve()


def test_install_warns_when_target_not_on_path(tmp_path, monkeypatch):
    src = _fake_entrypoint(tmp_path)
    target = tmp_path / "definitely-not-on-path"
    monkeypatch.setattr(main, "_entrypoint_path", lambda: src)
    monkeypatch.setenv("PATH", "/usr/bin:/bin")
    result = runner.invoke(main.app, ["install", "--target", str(target)])
    assert result.exit_code == 0
    assert "not on $PATH" in result.stdout


def test_install_custom_name(tmp_path, monkeypatch):
    src = _fake_entrypoint(tmp_path)
    target = tmp_path / "bin"
    monkeypatch.setattr(main, "_entrypoint_path", lambda: src)
    result = runner.invoke(
        main.app, ["install", "--target", str(target), "--name", "sox"]
    )
    assert result.exit_code == 0
    assert (target / "sox").is_symlink()


def test_uninstall_removes_symlink(tmp_path):
    src = tmp_path / "social"
    src.write_text("")
    target = tmp_path / "bin"
    target.mkdir()
    (target / "social").symlink_to(src)
    result = runner.invoke(main.app, ["uninstall", "--target", str(target)])
    assert result.exit_code == 0
    assert not (target / "social").exists()


def test_uninstall_refuses_real_file(tmp_path):
    target = tmp_path / "bin"
    target.mkdir()
    (target / "social").write_text("not a symlink")
    result = runner.invoke(main.app, ["uninstall", "--target", str(target)])
    assert result.exit_code == 1
    # Real file is preserved.
    assert (target / "social").exists()


def test_uninstall_when_missing_exits_1(tmp_path):
    result = runner.invoke(
        main.app, ["uninstall", "--target", str(tmp_path / "nope")]
    )
    assert result.exit_code == 1
