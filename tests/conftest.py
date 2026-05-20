"""Shared test helpers: a fake curl_cffi response and a patch fixture."""

from __future__ import annotations

import json as jsonlib
from dataclasses import dataclass, field
from typing import Any

import pytest


@dataclass
class FakeResponse:
    text: str = ""
    status_code: int = 200
    _json: Any = None
    headers: dict[str, str] = field(default_factory=dict)

    def json(self) -> Any:
        if self._json is not None:
            return self._json
        return jsonlib.loads(self.text)


@pytest.fixture
def patch_get(monkeypatch):
    """Patch `get` inside a target module with a function that returns FakeResponse."""

    def _patch(module, response_factory):
        def fake_get(url, **kwargs):
            resp = response_factory(url, kwargs)
            if isinstance(resp, FakeResponse):
                return resp
            return FakeResponse(**resp) if isinstance(resp, dict) else resp

        monkeypatch.setattr(module, "get", fake_get)

    return _patch
