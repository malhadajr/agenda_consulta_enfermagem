#!/usr/bin/env bash
# Cria um novo administrador com senha temporária.  Uso: ./scripts/criar-admin.sh login "Nome Completo"
set -euo pipefail
cd "$(dirname "$0")/.."
[ $# -ge 2 ] || { echo "Uso: $0 login \"Nome Completo\""; exit 1; }
docker compose exec -T app python -m app.cli criar-admin --usuario "$1" --nome "$2"
