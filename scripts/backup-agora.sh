#!/usr/bin/env bash
# Faz um backup imediato (além do automático diário).
set -euo pipefail
cd "$(dirname "$0")/.."
docker compose exec -T backup /usr/local/bin/backup.sh
ls -lh backups | tail -n 5
