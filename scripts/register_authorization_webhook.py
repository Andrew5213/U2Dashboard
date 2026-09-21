"""
Registra o webhook do Space de Autorizações de Serviço.

Endpoint separado do webhook principal de propósito: /webhooks/clickup empurra
todo evento para o SyncService (Airbox) e para o cache do dashboard.

Uso:
    python scripts/register_authorization_webhook.py --url https://seu-dominio.com/webhooks/autorizacoes
"""
import argparse
import asyncio
import os
import sys

sys.path.insert(0, os.path.join(os.path.dirname(__file__), ".."))

from src.core.config import settings
from src.services.clickup_client import ClickUpClient

EVENTS = ["taskCreated"]


async def main(space_id: str, endpoint_url: str) -> None:
    if not space_id:
        raise SystemExit(
            "Informe --space-id ou preencha AUTHORIZATION_SPACE_ID no .env"
        )

    async with ClickUpClient() as client:
        result = await client.create_webhook(space_id, endpoint_url, EVENTS)

    print("Webhook de autorizações criado!")
    print(f"  ID:       {result.get('id')}")
    print(f"  Space:    {space_id}")
    print(f"  Endpoint: {endpoint_url}")
    print(f"  Eventos:  {', '.join(EVENTS)}")
    secret = (result.get("webhook") or {}).get("secret") or result.get("secret")
    if secret:
        print(f"\nCole no .env:\n  AUTHORIZATION_WEBHOOK_SECRET={secret}")


if __name__ == "__main__":
    parser = argparse.ArgumentParser()
    parser.add_argument("--space-id", default=settings.authorization_space_id)
    parser.add_argument("--url", required=True)
    args = parser.parse_args()
    asyncio.run(main(args.space_id, args.url))
