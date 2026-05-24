#!/usr/bin/env bash
# Weekly restore-test. Validates the backup is actually restorable.
set -euo pipefail

SANDBOX=/tmp/pgbackrest-restore-test
SANDBOX_PORT=15432

echo "[restore-test] starting at $(date -u +%FT%TZ)"
rm -rf "$SANDBOX"
mkdir -p "$SANDBOX"

pgbackrest --stanza=interactome --pg1-path="$SANDBOX" --log-level-console=info restore

# Start a sandbox postgres on the restored data dir.
echo "host all all 127.0.0.1/32 trust" >> "$SANDBOX/pg_hba.conf"
echo "port = $SANDBOX_PORT" >> "$SANDBOX/postgresql.conf"
echo "unix_socket_directories = '/tmp'" >> "$SANDBOX/postgresql.conf"

su postgres -c "pg_ctl -D $SANDBOX -l /tmp/restore-test.log -w start" || {
    echo "[restore-test] FAILED to start sandbox postgres"
    cat /tmp/restore-test.log || true
    exit 1
}

# shellcheck disable=SC2064
trap 'su postgres -c "pg_ctl -D '"$SANDBOX"' stop -m immediate" || true' EXIT

# Basic sanity: corpus_paper must have rows after restore.
PAPER_COUNT=$(su postgres -c "psql -h 127.0.0.1 -p $SANDBOX_PORT -d interactome -tAc 'SELECT count(*) FROM corpus_paper'")
echo "[restore-test] corpus_paper rows: $PAPER_COUNT"

if [ "$PAPER_COUNT" -lt 1 ]; then
    echo "[restore-test] FAILED: corpus_paper is empty after restore"
    exit 1
fi

EDGE_COUNT=$(su postgres -c "psql -h 127.0.0.1 -p $SANDBOX_PORT -d interactome -tAc 'SELECT count(*) FROM graph_edge'")
echo "[restore-test] graph_edge rows: $EDGE_COUNT"

echo "[restore-test] PASSED at $(date -u +%FT%TZ)"
