"""Tests for the /alerts/ingest HTTP endpoint."""

from __future__ import annotations

import hashlib
import hmac
import json
from typing import Any

import pytest
from fastapi.testclient import TestClient

from app.webapp import app


def _sign(secret: str, body: bytes) -> str:
    return "sha256=" + hmac.new(secret.encode(), body, hashlib.sha256).hexdigest()


def _post(client: TestClient, body: dict[str, Any], secret: str) -> Any:
    raw = json.dumps(body).encode()
    return client.post(
        "/alerts/ingest",
        content=raw,
        headers={"Content-Type": "application/json", "X-Signature-256": _sign(secret, raw)},
    )


def test_ingest_refuses_when_secret_unset(monkeypatch: pytest.MonkeyPatch) -> None:
    monkeypatch.delenv("OPENSRE_INGEST_SECRET", raising=False)
    client = TestClient(app)
    resp = client.post(
        "/alerts/ingest", json={"alert_name": "x"}, headers={"X-Signature-256": "sha256=bad"}
    )
    assert resp.status_code == 503


def test_ingest_rejects_bad_signature(monkeypatch: pytest.MonkeyPatch) -> None:
    monkeypatch.setenv("OPENSRE_INGEST_SECRET", "topsecret")
    monkeypatch.setenv("OPENSRE_INGEST_INVESTIGATE", "false")
    client = TestClient(app)
    resp = client.post(
        "/alerts/ingest",
        json={"alert_name": "x"},
        headers={"X-Signature-256": "sha256=deadbeef"},
    )
    assert resp.status_code == 401


def test_ingest_acks_with_investigation_disabled(monkeypatch: pytest.MonkeyPatch) -> None:
    monkeypatch.setenv("OPENSRE_INGEST_SECRET", "topsecret")
    monkeypatch.setenv("OPENSRE_INGEST_INVESTIGATE", "false")
    client = TestClient(app)
    resp = _post(
        client,
        {"alert_name": "Pod CrashLoop", "severity": "high", "alert_source": "pipewarden"},
        "topsecret",
    )
    assert resp.status_code == 200
    body = resp.json()
    assert body["accepted"] is True
    assert body["alert_name"] == "Pod CrashLoop"
    assert body["severity"] == "high"
    assert body["source"] == "pipewarden"
    assert body["investigated"] is False
    assert body["root_cause"] is None


def test_ingest_runs_investigation_inline(monkeypatch: pytest.MonkeyPatch) -> None:
    monkeypatch.setenv("OPENSRE_INGEST_SECRET", "topsecret")
    monkeypatch.delenv("OPENSRE_INGEST_INVESTIGATE", raising=False)

    captured: dict[str, Any] = {}

    def fake_run(*, raw_alert: dict[str, Any], **_: Any) -> dict[str, Any]:
        captured["alert"] = raw_alert
        return {
            "report": "## RCA",
            "problem_md": "high cpu",
            "root_cause": "deploy regression in v1.2.3",
            "is_noise": False,
            "validity_score": 0.87,
        }

    import app.cli.investigation.investigate as invmod

    monkeypatch.setattr(invmod, "run_investigation_cli", fake_run)
    client = TestClient(app)
    resp = _post(client, {"alert_name": "API 500 spike", "severity": "critical"}, "topsecret")
    assert resp.status_code == 200
    body = resp.json()
    assert body["investigated"] is True
    assert body["root_cause"] == "deploy regression in v1.2.3"
    assert body["is_noise"] is False
    assert body["validity_score"] == pytest.approx(0.87)
    assert captured["alert"]["alert_name"] == "API 500 spike"


def test_ingest_records_investigation_error(monkeypatch: pytest.MonkeyPatch) -> None:
    monkeypatch.setenv("OPENSRE_INGEST_SECRET", "topsecret")
    monkeypatch.delenv("OPENSRE_INGEST_INVESTIGATE", raising=False)

    def boom(*, raw_alert: dict[str, Any], **_: Any) -> dict[str, Any]:
        raise RuntimeError("llm unavailable")

    import app.cli.investigation.investigate as invmod

    monkeypatch.setattr(invmod, "run_investigation_cli", boom)
    client = TestClient(app)
    resp = _post(client, {"alert_name": "x"}, "topsecret")
    assert resp.status_code == 200
    body = resp.json()
    assert body["investigated"] is False
    assert body["investigation_error"] == "llm unavailable"
