#!/usr/bin/env bash
# =============================================================================
# Instalação da Nova Agenda 2027 numa VM Linux com Docker
# Uso:  sudo ./scripts/instalar.sh
# =============================================================================
set -euo pipefail
cd "$(dirname "$0")/.."

vermelho() { printf '\033[31m%s\033[0m\n' "$*"; }
verde()    { printf '\033[32m%s\033[0m\n' "$*"; }

command -v docker >/dev/null || { vermelho "Docker não encontrado. Veja o README, seção 3."; exit 1; }
docker compose version >/dev/null 2>&1 || { vermelho "Plugin 'docker compose' não encontrado. Veja o README, seção 3."; exit 1; }

# 1. Arquivo de configuração
if [ ! -f .env ]; then
  cp .env.example .env
  chmod 600 .env
  read -rp "Nome do servidor na Intranet (ex.: agenda.hospital.local): " NOME || true
  read -rp "IP fixo da VM (ex.: 10.0.0.25, pode deixar vazio): " IP || true
  [ -n "${NOME:-}" ] && sed -i "s|^SERVIDOR_NOME=.*|SERVIDOR_NOME=${NOME}|" .env
  [ -n "${IP:-}" ] && sed -i "s|^SERVIDOR_IP=.*|SERVIDOR_IP=${IP}|" .env
  verde "✔ .env criado (revise-o se quiser mudar portas, backup ou sessão)."
fi

# 2. Senha do banco (aleatória, 48 caracteres) — nunca é exibida
mkdir -p secrets backups importacao
chmod 700 secrets
if [ ! -s secrets/db_password.txt ]; then
  ( umask 077; tr -dc 'A-Za-z0-9' < /dev/urandom | head -c 48 > secrets/db_password.txt )
  verde "✔ Senha do banco gerada em secrets/db_password.txt"
fi
# Legível dentro dos contêineres; protegida no host pela pasta secrets/ (700)
chmod 644 secrets/db_password.txt
chmod 700 backups

# 3. Construção e início
docker compose build --pull
docker compose up -d

echo "Aguardando os serviços ficarem prontos..."
for _ in $(seq 1 60); do
  if docker compose ps --format '{{.Service}} {{.Health}}' 2>/dev/null | grep -q '^app healthy'; then break; fi
  sleep 3
done
docker compose ps

# 4. Primeiro administrador
if ! docker compose exec -T app python -c "
from app.db import SessionLocal
from app.models import Usuario
from sqlalchemy import select, func
with SessionLocal() as db:
    raise SystemExit(0 if db.execute(select(func.count(Usuario.id)).where(Usuario.perfil=='ADMIN')).scalar() else 1)
" 2>/dev/null; then
  echo
  read -rp "Login do primeiro administrador (ex.: admin.ti): " ADM
  read -rp "Nome completo do administrador: " ADMNOME
  docker compose exec -T app python -m app.cli criar-admin --usuario "${ADM:-admin.ti}" --nome "${ADMNOME:-Administrador}"
fi

NOME_FINAL="$(grep '^SERVIDOR_NOME=' .env | cut -d= -f2)"
verde "✔ Instalação concluída. Acesse: https://${NOME_FINAL}"
