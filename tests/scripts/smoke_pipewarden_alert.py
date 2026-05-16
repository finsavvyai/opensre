"""Live smoke test for the PipeWarden → OpenSRE bridge.

Fires one signed alert at a running OpenSRE webapp using the exact wire
format PipeWarden's ``internal/webhooks/opensre_sender.go`` produces.

Usage
-----

In one terminal, boot OpenSRE locally::

    export OPENSRE_INGEST_SECRET=$(openssl rand -hex 32)
    export OPENSRE_INGEST_INVESTIGATE=true
    export ANTHROPIC_API_KEY=...   # or your provider's key
    export LLM_PROVIDER=anthropic
    uv run uvicorn app.webapp:app --host 127.0.0.1 --port 8765

In another, with the same ``OPENSRE_INGEST_SECRET`` exported::

    uv run python tests/scripts/smoke_pipewarden_alert.py

Exit codes::

    0  investigation ran inline, root_cause returned
    2  bridge accepted the alert but the LLM call failed (credits, network, …)
    3  bridge rejected the payload (signature, schema, …)
    4  non-JSON response from the server

Override the target with ``OPENSRE_SMOKE_URL=http://host:port/alerts/ingest``
and the alert with ``OPENSRE_SMOKE_ALERT_JSON=/path/to/alert.json``.
"""

from __future__ import annotations

import hashlib
import hmac
import json
import os
import sys
import time
import urllib.error
import urllib.request

DEFAULT_URL = "http://127.0.0.1:8765/alerts/ingest"

DEFAULT_ALERT = {
    "alert_name": "AWS access key leaked in workflow",
    "alert_source": "pipewarden",
    "severity": "high",
    "pipeline_name": "prod-github",
    "title": "AWS access key leaked in workflow",
    "labels": {
        "connection": "prod-github",
        "run_id": "9912334-smoke",
        "category": "secret_leak",
        "file": ".github/workflows/deploy.yml",
    },
    "annotations": {
        "description": "Hard-coded AKIA... found in workflow env block",
        "remediation": "Rotate the key in IAM and move to GitHub Actions Secret",
    },
}


def _load_alert() -> dict:
    path = os.getenv("OPENSRE_SMOKE_ALERT_JSON", "").strip()
    if not path:
        return DEFAULT_ALERT
    with open(path) as fh:
        return json.load(fh)


def main() -> int:
    secret = os.getenv("OPENSRE_INGEST_SECRET", "").strip()
    if not secret:
        print("ERROR: OPENSRE_INGEST_SECRET is not set", file=sys.stderr)
        return 64
    url = os.getenv("OPENSRE_SMOKE_URL", DEFAULT_URL)

    alert = _load_alert()
    body = json.dumps(alert).encode()
    sig = "sha256=" + hmac.new(secret.encode(), body, hashlib.sha256).hexdigest()

    req = urllib.request.Request(
        url,
        data=body,
        method="POST",
        headers={
            "Content-Type": "application/json",
            "X-Signature-256": sig,
            "User-Agent": "PipeWarden/1.0",
        },
    )
    start = time.monotonic()
    try:
        with urllib.request.urlopen(req, timeout=300) as resp:
            status = resp.status
            payload = resp.read().decode()
    except urllib.error.HTTPError as err:
        status = err.code
        payload = err.read().decode()
    except urllib.error.URLError as err:
        print(f"ERROR: connection to {url} failed: {err.reason}", file=sys.stderr)
        return 65
    elapsed = time.monotonic() - start

    print(f"HTTP {status} in {elapsed:.1f}s")
    try:
        parsed = json.loads(payload)
    except json.JSONDecodeError:
        print(payload)
        return 4

    print(json.dumps(parsed, indent=2))
    if status >= 400 or not parsed.get("accepted"):
        return 3
    if parsed.get("investigated"):
        print("\nSMOKE PASS: investigation ran inline")
        return 0
    print(
        "\nSMOKE PARTIAL: bridge accepted alert but investigation did not complete.\n"
        f"  investigation_error={parsed.get('investigation_error')!r}"
    )
    return 2


if __name__ == "__main__":
    sys.exit(main())
