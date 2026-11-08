# Backup automático do PostgreSQL (pg_dump) agendado via cron
FROM postgres:16-alpine
RUN apk add --no-cache tzdata
COPY backup.sh /usr/local/bin/backup.sh
COPY entrypoint.sh /usr/local/bin/entrypoint-backup.sh
RUN chmod 0755 /usr/local/bin/backup.sh /usr/local/bin/entrypoint-backup.sh
ENTRYPOINT ["/usr/local/bin/entrypoint-backup.sh"]
