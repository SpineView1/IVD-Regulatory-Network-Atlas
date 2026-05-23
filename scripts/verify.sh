#!/usr/bin/env bash
# Dockerized lint+test harness mirroring CI. Usage: bash scripts_verify.sh [pytest-args]
set -euo pipefail
NET=interactome-verify-net
PG=interactome-verify-pg
RD=interactome-verify-rd
cleanup(){ docker rm -f $PG $RD >/dev/null 2>&1 || true; docker network rm $NET >/dev/null 2>&1 || true; }
trap cleanup EXIT
cleanup
docker network create $NET >/dev/null
docker run -d --name $PG --network $NET \
  -e POSTGRES_DB=interactome_test -e POSTGRES_USER=interactome -e POSTGRES_PASSWORD=interactome \
  postgres:16-alpine >/dev/null
docker run -d --name $RD --network $NET redis:7-alpine >/dev/null
echo "waiting for postgres..."
for i in $(seq 1 30); do docker exec $PG pg_isready -U interactome >/dev/null 2>&1 && break; sleep 1; done
docker run --rm --network $NET -v "$PWD":/app -w /app \
  -e DJANGO_SETTINGS_MODULE=interactome.settings.dev \
  -e POSTGRES_DB=interactome_test -e POSTGRES_USER=interactome -e POSTGRES_PASSWORD=interactome \
  -e POSTGRES_HOST=$PG -e POSTGRES_PORT=5432 \
  -e REDIS_URL=redis://$RD:6379/0 \
  interactome-test:base bash -c "
    set -e
    poetry install --no-root >/dev/null 2>&1 || true
    echo '=== ruff ==='; poetry run ruff check . && poetry run ruff format --check .
    echo '=== mypy ==='; poetry run mypy .
    echo '=== pytest ==='; poetry run pytest ${*:-}
  "
