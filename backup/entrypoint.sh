#!/bin/sh
set -eu
CRON="${BACKUP_CRON:-0 0 * * *}"
mkdir -p /backups
echo "$CRON /usr/local/bin/backup.sh >> /proc/1/fd/1 2>&1" > /etc/crontabs/root
echo "[backup] Agendado: '$CRON' (fuso ${TZ:-UTC}). Retenção: ${BACKUP_RETENCAO_DIAS:-30} dias."
exec crond -f -l 8
