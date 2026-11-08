#!/usr/bin/env bash
# Restaura um backup .dump SUBSTITUINDO todos os dados atuais.
# Uso: ./scripts/restaurar-backup.sh backups/nova_agenda_AAAA-MM-DD_HHMM.dump
set -euo pipefail
cd "$(dirname "$0")/.."
ARQ="${1:-}"
[ -f "$ARQ" ] || { echo "Informe o arquivo: $0 backups/nova_agenda_....dump"; exit 1; }
if [ -f "${ARQ}.sha256" ]; then
  (cd "$(dirname "$ARQ")" && sha256sum -c "$(basename "$ARQ").sha256") || { echo "Arquivo corrompido (checksum)."; exit 1; }
fi
read -rp "ATENÇÃO: os dados atuais serão substituídos por $ARQ. Digite RESTAURAR para continuar: " OK
[ "$OK" = "RESTAURAR" ] || { echo "Cancelado."; exit 1; }
echo "Fazendo backup de segurança do estado atual antes de restaurar..."
docker compose exec -T backup /usr/local/bin/backup.sh
docker compose stop app nginx
NOME="$(basename "$ARQ")"
docker compose exec -T backup sh -c "PGPASSWORD=\$(cat /run/secrets/db_password) pg_restore -h db -U nova_agenda -d nova_agenda --clean --if-exists --no-owner /backups/${NOME}"
docker compose start app nginx
echo "Restauração concluída."
