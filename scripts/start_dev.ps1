# ─── Servidor de desenvolvimento local (porta 8001) ──────────────────────────
# Usa .env.dev → dev.db  (isolado do ambiente de produção)
# Pré-requisito: execute scripts/seed_dev.py ao menos uma vez.

$env:APP_ENV_FILE = ".env.dev"
Write-Host "Iniciando servidor DEV em http://localhost:8001  (DB: dev.db)" -ForegroundColor Cyan
uvicorn src.main:app --reload --port 8001
