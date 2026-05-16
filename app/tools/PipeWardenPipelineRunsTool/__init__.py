"""PipeWarden Pipeline Runs Tool.

Fetches recent pipeline runs from a PipeWarden instance, cross-platform
across GitHub Actions, GitLab CI/CD, Bitbucket Pipelines, Jenkins, Azure
DevOps, and CircleCI. Useful when investigating an incident that may
correlate with a recent failed or hung CI/CD run.
"""

from __future__ import annotations

from typing import Any

from app.integrations.pipewarden import (
    build_pipewarden_config,
    list_pipeline_runs,
    pipewarden_config_from_env,
)
from app.tools.tool_decorator import tool


def _pw_available(sources: dict[str, dict]) -> bool:
    pw = sources.get("pipewarden", {})
    if not (pw.get("api_key") or pipewarden_config_from_env() is not None):
        return False
    return bool(pw.get("connection"))


def _resolve_config(
    base_url: str | None,
    api_key: str | None,
) -> Any:
    if base_url or api_key:
        return build_pipewarden_config({"base_url": base_url or "", "api_key": api_key or ""})
    return pipewarden_config_from_env()


def _list_pipewarden_pipeline_runs_extract_params(sources: dict[str, dict]) -> dict[str, Any]:
    pw = sources.get("pipewarden", {})
    return {
        "connection": pw.get("connection", ""),
        "repo": pw.get("repo"),
        "branch": pw.get("branch"),
        "limit": pw.get("limit", 10),
        "base_url": pw.get("base_url"),
        "api_key": pw.get("api_key"),
    }


@tool(
    name="list_pipewarden_pipeline_runs",
    description=(
        "List recent pipeline runs for a PipeWarden connection. Works across all "
        "six supported CI/CD platforms (GitHub Actions, GitLab CI/CD, Bitbucket, "
        "Jenkins, Azure DevOps, CircleCI)."
    ),
    source="pipewarden",
    surfaces=("investigation", "chat"),
    use_cases=[
        "Correlating an incident with a recent failed CI/CD run",
        "Inspecting pipeline run history for a specific repo or branch",
        "Cross-platform comparison of pipeline behavior",
    ],
    requires=["connection"],
    input_schema={
        "type": "object",
        "properties": {
            "connection": {"type": "string"},
            "repo": {"type": "string"},
            "branch": {"type": "string"},
            "limit": {"type": "integer", "default": 10},
            "base_url": {"type": "string"},
            "api_key": {"type": "string"},
        },
        "required": ["connection"],
    },
    is_available=_pw_available,
    extract_params=_list_pipewarden_pipeline_runs_extract_params,
)
def list_pipewarden_pipeline_runs(
    connection: str,
    repo: str | None = None,
    branch: str | None = None,
    limit: int = 10,
    base_url: str | None = None,
    api_key: str | None = None,
    **_kwargs: Any,
) -> dict[str, Any]:
    """Fetch recent pipeline runs from PipeWarden."""
    config = _resolve_config(base_url, api_key)
    if config is None:
        return {
            "source": "pipewarden",
            "available": False,
            "error": "PipeWarden integration is not configured.",
            "runs": [],
        }
    runs = list_pipeline_runs(
        config=config,
        connection=connection,
        repo=repo,
        branch=branch,
        limit=limit,
    )
    return {
        "source": "pipewarden",
        "available": True,
        "connection": connection,
        "count": len(runs),
        "runs": runs,
    }
