#!/bin/sh
# Gera um dump completo do banco, confere se o arquivo é legível e apaga cópias antigas.
set -eu
umask 077
export PGPASSWORD="$(cat "${DB_PASSWORD_FILE:-/run/secrets/db_password}")"
HOST="${DB_HOST:-db}"; BANCO="${DB_NAME:-nova_agenda}"; USUARIO="${DB_USER:-nova_agenda}"
RET="${BACKUP_RETENCAO_DIAS:-30}"
DATA="$(date +%Y-%m-%d_%H%M)"
DESTINO="/backups/nova_agenda_${DATA}.dump"
TMP="${DESTINO}.parcial"

echo "[backup] $(date '+%d/%m/%Y %H:%M:%S') iniciando -> $DESTINO"
pg_dump -h "$HOST" -U "$USUARIO" -d "$BANCO" -Fc -Z 6 -f "$TMP"
pg_restore --list "$TMP" > /dev/null            # valida o arquivo gerado
mv "$TMP" "$DESTINO"
sha256sum "$DESTINO" > "${DESTINO}.sha256"
echo "[backup] concluído: $(du -h "$DESTINO" | cut -f1)"

find /backups -maxdepth 1 -name 'nova_agenda_*.dump*' -mtime +"$RET" -print -delete | sed 's/^/[backup] removido (antigo): /' || true
unset PGPASSWORD
