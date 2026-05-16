from __future__ import annotations

import asyncio
import hashlib
import hmac
import logging
import os
from typing import Any

from fastapi import FastAPI, Header, HTTPException, Request, Response, status
from pydantic import BaseModel, ValidationError

from app.alerts import normalize_alert_payload
from app.config import LLMSettings, get_environment
from app.utils.sentry_sdk import init_sentry
from app.version import get_version

_log = logging.getLogger(__name__)

init_sentry(entrypoint="webapp")


class HealthResponse(BaseModel):
    ok: bool
    version: str
    llm_configured: bool
    env: str


app = FastAPI()


def _llm_configured() -> bool:
    try:
        LLMSettings.from_env()
    except ValidationError:
        return False
    return True


def get_health_response() -> HealthResponse:
    llm_configured = _llm_configured()

    return HealthResponse(
        ok=llm_configured,
        version=get_version(),
        llm_configured=llm_configured,
        env=get_environment().value,
    )


@app.get("/", response_model=HealthResponse)
@app.get("/health", response_model=HealthResponse)
@app.get("/ok", response_model=HealthResponse)
def health(response: Response) -> HealthResponse:
    health_response = get_health_response()
    response.status_code = (
        status.HTTP_200_OK if health_response.ok else status.HTTP_503_SERVICE_UNAVAILABLE
    )
    return health_response


class AlertIngestResponse(BaseModel):
    accepted: bool
    schema_version: str
    alert_name: str | None
    severity: str | None
    source: str | None
    investigated: bool = False
    root_cause: str | None = None
    is_noise: bool | None = None
    validity_score: float | None = None
    investigation_error: str | None = None


def _verify_signature(secret: str, body: bytes, header: str | None) -> bool:
    if not header:
        return False
    expected = hmac.new(secret.encode(), body, hashlib.sha256).hexdigest()
    candidate = header.removeprefix("sha256=").strip()
    return hmac.compare_digest(expected, candidate)


@app.post("/alerts/ingest", response_model=AlertIngestResponse)
async def alerts_ingest(
    request: Request,
    x_signature_256: str | None = Header(default=None, alias="X-Signature-256"),
) -> AlertIngestResponse:
    """Ingest an OpenSRE alert envelope from an external source.

    Authentication is HMAC-SHA256: callers sign the raw request body with
    ``OPENSRE_INGEST_SECRET`` and pass the hex digest in ``X-Signature-256``.
    When the secret is unset the endpoint refuses every request.
    """
    secret = os.getenv("OPENSRE_INGEST_SECRET", "").strip()
    if not secret:
        raise HTTPException(
            status_code=status.HTTP_503_SERVICE_UNAVAILABLE,
            detail="OPENSRE_INGEST_SECRET is not configured",
        )
    body = await request.body()
    if not _verify_signature(secret, body, x_signature_256):
        raise HTTPException(
            status_code=status.HTTP_401_UNAUTHORIZED,
            detail="invalid signature",
        )
    try:
        payload: Any = await request.json()
    except Exception as err:
        raise HTTPException(status_code=400, detail=f"invalid JSON: {err}") from err
    if not isinstance(payload, dict):
        raise HTTPException(status_code=400, detail="payload must be a JSON object")

    normalized = normalize_alert_payload(payload)
    canonical = normalized.get("canonical_alert", {})

    investigated = False
    root_cause: str | None = None
    is_noise: bool | None = None
    validity_score: float | None = None
    investigation_error: str | None = None

    # Investigation is opt-out so the ingest can be used as ack-only by
    # setting OPENSRE_INGEST_INVESTIGATE=false. Default is investigate inline.
    if os.getenv("OPENSRE_INGEST_INVESTIGATE", "true").strip().lower() not in {
        "false",
        "0",
        "no",
    }:
        try:
            from app.cli.investigation.investigate import run_investigation_cli

            result: dict[str, Any] = await asyncio.to_thread(
                run_investigation_cli, raw_alert=payload
            )
            investigated = True
            root_cause = result.get("root_cause")
            is_noise = result.get("is_noise")
            score = result.get("validity_score")
            if isinstance(score, (int, float)):
                validity_score = float(score)
        except Exception as err:  # pragma: no cover — investigation paths are deep
            _log.warning("inline investigation failed: %s", err)
            investigation_error = str(err)

    return AlertIngestResponse(
        accepted=True,
        schema_version=canonical.get("schema", "opensre.alert.v1"),
        alert_name=canonical.get("alert_name"),
        severity=canonical.get("severity"),
        source=canonical.get("alert_source"),
        investigated=investigated,
        root_cause=root_cause,
        is_noise=is_noise,
        validity_score=validity_score,
        investigation_error=investigation_error,
    )
