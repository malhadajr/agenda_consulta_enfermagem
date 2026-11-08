#!/usr/bin/env bash
# Importa o .xlsx exportado da planilha Google "Nova Agenda 2027" (veja README, seção 7).
# Uso: ./scripts/importar-planilha.sh importacao/planilha.xlsx [--gravar]
#   sem --gravar : apenas SIMULA e mostra o relatório (nada é gravado)
set -euo pipefail
cd "$(dirname "$0")/.."
ARQ="${1:-}"
[ -f "$ARQ" ] || { echo "Coloque o arquivo na pasta importacao/ e informe: $0 importacao/arquivo.xlsx"; exit 1; }
case "$(realpath "$ARQ")" in "$(realpath importacao)"/*) ;; *) echo "O arquivo precisa estar dentro da pasta importacao/"; exit 1;; esac
chmod 644 "$ARQ"
DENTRO="/importacao/$(basename "$ARQ")"
if [ "${2:-}" = "--gravar" ]; then
  docker compose exec -T app python -m app.cli importar-planilha "$DENTRO"
  echo "Lembre-se de apagar $ARQ (contém dados pessoais)."
else
  docker compose exec -T app python -m app.cli importar-planilha "$DENTRO" --simular
  echo "Se o relatório estiver correto, rode novamente com --gravar"
fi
