"""Shared PipeWarden integration helpers.

PipeWarden is a DevSecOps pipeline orchestrator that scans CI/CD pipelines
across GitHub Actions, GitLab CI/CD, Bitbucket Pipelines, Jenkins, Azure
DevOps, and CircleCI. This module wires PipeWarden's REST API into OpenSRE so
investigations can pull recent security findings and pipeline run history as
evidence.
"""

from __future__ import annotations

import logging
import os
from dataclasses import dataclass
from typing import Any

import httpx
from pydantic import Field, field_validator

from app.integrations._validation_helpers import report_validation_failure
from app.strict_config import StrictConfigModel

logger = logging.getLogger(__name__)

DEFAULT_PIPEWARDEN_BASE_URL = "http://localhost:8080"


class PipewardenConfig(StrictConfigModel):
    """Normalized PipeWarden connection settings."""

    base_url: str = DEFAULT_PIPEWARDEN_BASE_URL
    api_key: str = ""
    timeout_seconds: float = Field(default=15.0, gt=0)

    @field_validator("base_url", mode="before")
    @classmethod
    def _normalize_base_url(cls, value: Any) -> str:
        normalized = str(value or DEFAULT_PIPEWARDEN_BASE_URL).strip()
        return normalized or DEFAULT_PIPEWARDEN_BASE_URL

    @property
    def api_base_url(self) -> str:
        return self.base_url.rstrip("/")

    @property
    def auth_headers(self) -> dict[str, str]:
        headers = {"Accept": "application/json"}
        if self.api_key:
            headers["Authorization"] = f"Bearer {self.api_key}"
        return headers


@dataclass(frozen=True)
class PipewardenValidationResult:
    """Result of validating a PipeWarden integration."""

    ok: bool
    detail: str


def build_pipewarden_config(raw: dict[str, Any] | None) -> PipewardenConfig:
    """Build a normalized PipeWarden config object from env/store data."""
    return PipewardenConfig.model_validate(raw or {})


def pipewarden_config_from_env() -> PipewardenConfig | None:
    """Load a PipeWarden config from env vars.

    Returns ``None`` when neither ``PIPEWARDEN_API_KEY`` nor an explicit
    base URL is set, signalling the integration is not configured.
    """
    api_key = os.getenv("PIPEWARDEN_API_KEY", "").strip()
    base_url = os.getenv("PIPEWARDEN_BASE_URL", "").strip()
    if not api_key and not base_url:
        return None
    return build_pipewarden_config(
        {
            "base_url": base_url or DEFAULT_PIPEWARDEN_BASE_URL,
            "api_key": api_key,
        }
    )


def _request_json(
    config: PipewardenConfig,
    method: str,
    path: str,
    *,
    params: list[tuple[str, str | int | float | bool | None]] | None = None,
    json: dict | None = None,
) -> Any:
    url = f"{config.api_base_url}{path}"
    response = httpx.request(
        method,
        url,
        json=json,
        headers=config.auth_headers,
        params=params,
        timeout=config.timeout_seconds,
    )
    response.raise_for_status()
    return response.json()


def validate_pipewarden_config(config: PipewardenConfig) -> PipewardenValidationResult:
    """Validate PipeWarden connectivity by hitting the health endpoint."""
    try:
        payload = _request_json(config, "GET", "/health")
        ok = bool(payload.get("status") == "ok") if isinstance(payload, dict) else False
        if not ok:
            return PipewardenValidationResult(
                ok=False, detail=f"PipeWarden /health did not report ok: {payload!r}"
            )
        return PipewardenValidationResult(
            ok=True, detail=f"PipeWarden connectivity successful at {config.api_base_url}"
        )
    except httpx.HTTPStatusError as err:
        detail = err.response.text.strip() or str(err)
        return PipewardenValidationResult(
            ok=False, detail=f"PipeWarden validation failed: {detail}"
        )
    except Exception as err:
        report_validation_failure(
            err,
            logger=logger,
            integration="pipewarden",
            method="validate_pipewarden_config",
        )
        return PipewardenValidationResult(ok=False, detail=f"PipeWarden validation failed: {err}")


def list_findings(
    *,
    config: PipewardenConfig,
    severity: str | None = None,
    connection: str | None = None,
    limit: int = 50,
) -> list[dict[str, Any]]:
    """List recent security findings from PipeWarden."""
    params: list[tuple[str, str | int | float | bool | None]] = [("limit", limit)]
    if severity:
        params.append(("severity", severity))
    if connection:
        params.append(("connection", connection))
    payload = _request_json(config, "GET", "/api/v1/findings", params=params)
    if isinstance(payload, dict):
        items = payload.get("findings") or payload.get("items") or []
    else:
        items = payload if isinstance(payload, list) else []
    return [item for item in items if isinstance(item, dict)]


def list_pipeline_runs(
    *,
    config: PipewardenConfig,
    connection: str,
    repo: str | None = None,
    branch: str | None = None,
    limit: int = 10,
) -> list[dict[str, Any]]:
    """List recent pipeline runs for a PipeWarden connection."""
    params: list[tuple[str, str | int | float | bool | None]] = [
        ("connection", connection),
        ("limit", limit),
    ]
    if repo:
        params.append(("repo", repo))
    if branch:
        params.append(("branch", branch))
    payload = _request_json(config, "GET", "/api/v1/pipelines", params=params)
    if isinstance(payload, dict):
        items = payload.get("runs") or payload.get("pipelines") or payload.get("items") or []
    else:
        items = payload if isinstance(payload, list) else []
    return [item for item in items if isinstance(item, dict)]
