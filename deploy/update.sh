#!/usr/bin/env bash
# Atualiza a app: puxa o codigo, reconstroi a imagem e recria o conteiner.
# Uso (como root):  bash /opt/apiclickup/bin/update.sh
set -euo pipefail

cd /opt/apiclickup/app

sudo -u apiclickup git pull --ff-only
docker compose up -d --build

status=starting
for _ in $(seq 1 30); do
    status=$(docker inspect -f '{{.State.Health.Status}}' apiclickup 2>/dev/null || echo starting)
    [ "$status" = "healthy" ] && break
    sleep 3
done

if [ "$status" != "healthy" ]; then
    echo "ATENCAO: conteiner nao ficou saudavel (status: $status). Ultimas linhas do log:"
    docker compose logs --tail 40 app
    exit 1
fi

curl -fsS http://127.0.0.1:8001/health && echo
docker image prune -f >/dev/null
echo "atualizacao concluida"
