#!/usr/bin/env bash
# Backup diario do sync.db (copia consistente via API de backup do SQLite, com a app
# rodando) e, aos domingos, dos PDFs/fotos. Guarda 14 dias. Roda como root via
# /etc/cron.d/apiclickup e usa o python3 do sistema (so precisa do modulo sqlite3).
set -euo pipefail

BASE=/opt/apiclickup
DATA="$BASE/app/data"
DEST="$BASE/backups"
STAMP=$(date +%F)

mkdir -p "$DEST"

/usr/bin/python3 - <<PY
import sqlite3

src = sqlite3.connect("$DATA/sync.db")
dst = sqlite3.connect("$DEST/sync-$STAMP.db")
with dst:
    src.backup(dst)
dst.close()
src.close()
PY

if [ "$(date +%u)" = "7" ]; then
    tar -czf "$DEST/arquivos-$STAMP.tar.gz" -C "$DATA" documents uploads
fi

find "$DEST" -type f -mtime +14 -delete
echo "backup ok: $STAMP"
