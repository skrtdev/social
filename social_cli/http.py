"""Thin curl_cffi wrapper that impersonates a modern Chrome on every request."""

from __future__ import annotations

from typing import Any

from curl_cffi import requests

DEFAULT_IMPERSONATE = "chrome124"
DEFAULT_TIMEOUT = 20


class FetchError(RuntimeError):
    def __init__(self, url: str, status: int, body: str = "") -> None:
        super().__init__(f"GET {url} -> {status}")
        self.url = url
        self.status = status
        self.body = body


def get(
    url: str,
    *,
    headers: dict[str, str] | None = None,
    params: dict[str, Any] | None = None,
    cookies: dict[str, str] | None = None,
    impersonate: str = DEFAULT_IMPERSONATE,
    timeout: int = DEFAULT_TIMEOUT,
    allow_redirects: bool = True,
) -> requests.Response:
    resp = requests.get(
        url,
        headers=headers,
        params=params,
        cookies=cookies,
        impersonate=impersonate,
        timeout=timeout,
        allow_redirects=allow_redirects,
    )
    if resp.status_code >= 400:
        raise FetchError(url, resp.status_code, resp.text[:500])
    return resp
