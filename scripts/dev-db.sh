#!/usr/bin/env bash
# Start the local (non-Docker) Postgres used for development in cloud sessions, if it isn't running.
# Data lives in ./.pgdata (git-ignored). With Docker, use `docker compose up -d` instead.
set -euo pipefail
PGDATA="$(cd "$(dirname "$0")/.." && pwd -P)/.pgdata"
PGDATA="$(readlink -f "$PGDATA")"
BIN=/usr/lib/postgresql/16/bin
if pg_isready -q -h /tmp -p 5433; then exit 0; fi
sudo -u postgres "$BIN/pg_ctl" -D "$PGDATA" -o "-p 5433 -k /tmp" -l "$PGDATA/server.log" -w start >/dev/null
echo "Postgres started on port 5433"
