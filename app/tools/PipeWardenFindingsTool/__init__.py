"""PipeWarden Findings Tool.

Fetches recent security findings (heuristic + Claude AI + DLP scanner +
OPA policy results) from a PipeWarden instance so OpenSRE can use them
as evidence during pipeline incident investigations.
"""

from __future__ import annotations

from typing import Any

from app.integrations.pipewarden import (
    build_pipewarden_config,
    list_findings,
    pipewarden_config_from_env,
)
from app.tools.tool_decorator import tool


def _pw_available(sources: dict[str, dict]) -> bool:
    pw = sources.get("pipewarden", {})
    return bool(pw.get("api_key") or pipewarden_config_from_env() is not None)


def _resolve_config(
    base_url: str | None,
    api_key: str | None,
) -> Any:
    if base_url or api_key:
        return build_pipewarden_config({"base_url": base_url or "", "api_key": api_key or ""})
    return pipewarden_config_from_env()


def _list_pipewarden_findings_extract_params(sources: dict[str, dict]) -> dict[str, Any]:
    pw = sources.get("pipewarden", {})
    return {
        "severity": pw.get("severity"),
        "connection": pw.get("connection"),
        "limit": pw.get("limit", 50),
        "base_url": pw.get("base_url"),
        "api_key": pw.get("api_key"),
    }


@tool(
    name="list_pipewarden_findings",
    description=(
        "List recent security findings from PipeWarden (heuristic, Claude AI, DLP, "
        "and OPA policy results). Supports filtering by severity and connection."
    ),
    source="pipewarden",
    surfaces=("investigation", "chat"),
    use_cases=[
        "Checking whether a CI/CD pipeline incident correlates with recent security findings",
        "Reviewing leaked secrets or DLP matches before approving a deploy",
        "Cross-referencing failed pipeline runs with policy violations",
    ],
    requires=[],
    input_schema={
        "type": "object",
        "properties": {
            "severity": {
                "type": "string",
                "enum": ["info", "low", "medium", "high", "critical"],
            },
            "connection": {"type": "string"},
            "limit": {"type": "integer", "default": 50},
            "base_url": {"type": "string"},
            "api_key": {"type": "string"},
        },
        "required": [],
    },
    is_available=_pw_available,
    extract_params=_list_pipewarden_findings_extract_params,
)
def list_pipewarden_findings(
    severity: str | None = None,
    connection: str | None = None,
    limit: int = 50,
    base_url: str | None = None,
    api_key: str | None = None,
    **_kwargs: Any,
) -> dict[str, Any]:
    """Fetch recent findings from PipeWarden."""
    config = _resolve_config(base_url, api_key)
    if config is None:
        return {
            "source": "pipewarden",
            "available": False,
            "error": "PipeWarden integration is not configured.",
            "findings": [],
        }
    findings = list_findings(
        config=config,
        severity=severity,
        connection=connection,
        limit=limit,
    )
    return {
        "source": "pipewarden",
        "available": True,
        "count": len(findings),
        "findings": findings,
    }
