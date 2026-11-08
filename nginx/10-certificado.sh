#!/bin/sh
# Gera um certificado autoassinado na primeira execução, caso a TI não tenha colocado
# o certificado institucional em nginx/certs/servidor.crt e servidor.key.
set -eu
DIR=/etc/nginx/certs
CRT="$DIR/servidor.crt"
KEY="$DIR/servidor.key"
if [ -s "$CRT" ] && [ -s "$KEY" ]; then
  echo "[certificado] Usando certificado existente em $DIR"
  exit 0
fi
NOME="${SERVIDOR_NOME:-agenda.local}"
SAN="DNS:${NOME},DNS:localhost"
if [ -n "${SERVIDOR_IP:-}" ]; then SAN="$SAN,IP:${SERVIDOR_IP}"; fi
echo "[certificado] Gerando certificado autoassinado para $SAN (validade 825 dias)"
umask 077
openssl req -x509 -nodes -newkey rsa:3072 -sha256 -days 825 \
  -keyout "$KEY" -out "$CRT" \
  -subj "/C=BR/O=Nova Agenda 2027/CN=${NOME}" \
  -addext "subjectAltName=${SAN}" \
  -addext "keyUsage=digitalSignature,keyEncipherment" \
  -addext "extendedKeyUsage=serverAuth" >/dev/null 2>&1
chmod 600 "$KEY"
chmod 644 "$CRT"
