#!/usr/bin/env bash
# demo/signoz/start-local.sh
# Start a local SigNoz stack for demo / integration testing.
#
# This uses the official SigNoz Docker Compose setup.
# See: https://signoz.io/docs/install/docker/

set -euo pipefail

cd "$(dirname "$0")"

SIGNOZ_DIR="${SIGNOZ_DIR:-/tmp/signoz}"

if [[ ! -d "$SIGNOZ_DIR" ]]; then
    echo "Cloning SigNoz into $SIGNOZ_DIR ..."
    git clone --depth 1 https://github.com/SigNoz/signoz.git "$SIGNOZ_DIR"
fi

cd "$SIGNOZ_DIR/deploy/docker/clickhouse-setup"

echo "Starting SigNoz (ClickHouse + Query Service + Frontend)..."
docker compose up -d

echo ""
echo "SigNoz should be available shortly at:"
echo "  UI:    http://localhost:3301"
echo "  ClickHouse HTTP: http://localhost:8123"
echo "  ClickHouse Native: localhost:9000"
echo ""
echo "To verify:"
echo "  docker compose ps"
echo "  docker logs -f clickhouse-setup-clickhouse-1"
