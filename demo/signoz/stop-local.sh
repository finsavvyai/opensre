#!/usr/bin/env bash
# demo/signoz/stop-local.sh
# Tear down the local SigNoz stack.

set -euo pipefail

SIGNOZ_DIR="${SIGNOZ_DIR:-/tmp/signoz}"
COMPOSE_DIR="$SIGNOZ_DIR/deploy/docker/clickhouse-setup"

if [[ -d "$COMPOSE_DIR" ]]; then
    cd "$COMPOSE_DIR"
    echo "Stopping SigNoz ..."
    docker compose down
    echo "SigNoz stopped."
else
    echo "SigNoz compose directory not found at $COMPOSE_DIR"
    exit 1
fi
