"""Tests for shared PipeWarden integration helpers."""

from __future__ import annotations

from typing import Any

import httpx
import pytest

from app.integrations.pipewarden import (
    DEFAULT_PIPEWARDEN_BASE_URL,
    PipewardenConfig,
    build_pipewarden_config,
    list_findings,
    list_pipeline_runs,
    pipewarden_config_from_env,
    validate_pipewarden_config,
)


class _FakeResponse:
    def __init__(self, payload: Any, status_code: int = 200) -> None:
        self._payload = payload
        self.status_code = status_code
        self.text = ""

    def raise_for_status(self) -> None:
        if self.status_code >= 400:
            raise httpx.HTTPStatusError(
                "error",
                request=httpx.Request("GET", "https://pipewarden.local"),
                response=httpx.Response(self.status_code),
            )

    def json(self) -> Any:
        return self._payload


def _make_config(**kwargs: Any) -> PipewardenConfig:
    return PipewardenConfig.model_validate({"api_key": "pw_test", **kwargs})


def test_default_base_url_when_missing() -> None:
    config = build_pipewarden_config({})
    assert config.api_base_url == DEFAULT_PIPEWARDEN_BASE_URL.rstrip("/")
    assert config.auth_headers == {"Accept": "application/json"}


def test_auth_headers_include_bearer_when_api_key_set() -> None:
    config = _make_config()
    assert config.auth_headers["Authorization"] == "Bearer pw_test"


def test_config_from_env_returns_none_when_unset(monkeypatch: pytest.MonkeyPatch) -> None:
    monkeypatch.delenv("PIPEWARDEN_API_KEY", raising=False)
    monkeypatch.delenv("PIPEWARDEN_BASE_URL", raising=False)
    assert pipewarden_config_from_env() is None


def test_config_from_env_picks_up_keys(monkeypatch: pytest.MonkeyPatch) -> None:
    monkeypatch.setenv("PIPEWARDEN_API_KEY", "pw_envkey")
    monkeypatch.setenv("PIPEWARDEN_BASE_URL", "https://pw.example.com")
    config = pipewarden_config_from_env()
    assert config is not None
    assert config.api_key == "pw_envkey"
    assert config.api_base_url == "https://pw.example.com"


def test_validate_pipewarden_config_ok(monkeypatch: pytest.MonkeyPatch) -> None:
    def fake_request(method: str, url: str, **_: Any) -> _FakeResponse:
        assert url.endswith("/health")
        return _FakeResponse({"status": "ok", "database": True})

    monkeypatch.setattr(httpx, "request", fake_request)
    result = validate_pipewarden_config(_make_config())
    assert result.ok is True
    assert "successful" in result.detail


def test_validate_pipewarden_config_bad_status(monkeypatch: pytest.MonkeyPatch) -> None:
    def fake_request(method: str, url: str, **_: Any) -> _FakeResponse:
        return _FakeResponse({"status": "degraded"})

    monkeypatch.setattr(httpx, "request", fake_request)
    result = validate_pipewarden_config(_make_config())
    assert result.ok is False
    assert "did not report ok" in result.detail


def test_list_findings_passes_filters(monkeypatch: pytest.MonkeyPatch) -> None:
    captured: dict[str, Any] = {}

    def fake_request(method: str, url: str, **kwargs: Any) -> _FakeResponse:
        captured["url"] = url
        captured["params"] = kwargs.get("params")
        return _FakeResponse(
            {"findings": [{"id": 1, "severity": "high"}, {"id": 2, "severity": "high"}]}
        )

    monkeypatch.setattr(httpx, "request", fake_request)
    findings = list_findings(
        config=_make_config(), severity="high", connection="prod-github", limit=10
    )
    assert len(findings) == 2
    assert captured["url"].endswith("/api/v1/findings")
    assert ("severity", "high") in captured["params"]
    assert ("connection", "prod-github") in captured["params"]
    assert ("limit", 10) in captured["params"]


def test_list_findings_accepts_bare_list_payload(monkeypatch: pytest.MonkeyPatch) -> None:
    def fake_request(method: str, url: str, **_: Any) -> _FakeResponse:
        return _FakeResponse([{"id": 5}, "not-a-dict", {"id": 6}])

    monkeypatch.setattr(httpx, "request", fake_request)
    findings = list_findings(config=_make_config())
    assert [f["id"] for f in findings] == [5, 6]


def test_list_pipeline_runs_requires_connection(monkeypatch: pytest.MonkeyPatch) -> None:
    captured: dict[str, Any] = {}

    def fake_request(method: str, url: str, **kwargs: Any) -> _FakeResponse:
        captured["params"] = kwargs.get("params")
        return _FakeResponse({"runs": [{"id": "r1"}, {"id": "r2"}]})

    monkeypatch.setattr(httpx, "request", fake_request)
    runs = list_pipeline_runs(
        config=_make_config(), connection="prod-github", repo="org/repo", branch="main"
    )
    assert [r["id"] for r in runs] == ["r1", "r2"]
    assert ("connection", "prod-github") in captured["params"]
    assert ("repo", "org/repo") in captured["params"]
    assert ("branch", "main") in captured["params"]
