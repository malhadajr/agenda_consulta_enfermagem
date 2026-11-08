#!/usr/bin/env bash
# Roda a suíte de testes automatizados (funcionais e de segurança) num contêiner descartável.
set -euo pipefail
cd "$(dirname "$0")/.."
docker build --build-arg INSTALAR_TESTES=1 -t nova-agenda-2027/app:testes ./app
docker run --rm --network none -e DATABASE_URL=sqlite:////tmp/teste.db nova-agenda-2027/app:testes python -m pytest -q -p no:cacheprovider tests
