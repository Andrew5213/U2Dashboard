"""
Script para registrar o webhook do ClickUp apontando para este servidor.

Uso:
    python scripts/register_webhook.py --space-id <SPACE_ID> --url https://seu-dominio.com/webhooks/clickup
"""
import asyncio
import argparse
import sys
import os

sys.path.insert(0, os.path.join(os.path.dirname(__file__), ".."))

from src.services.clickup_client import ClickUpClient

EVENTS = [
    "taskStatusUpdated",
    "taskUpdated",
    "taskAssigneeUpdated",
    "taskDueDateUpdated",
    "taskCreated",
    "taskDeleted",
]


async def main(space_id: str, endpoint_url: str) -> None:
    async with ClickUpClient() as client:
        result = await client.create_webhook(space_id, endpoint_url, EVENTS)
        print("Webhook criado com sucesso!")
        print(f"  ID: {result.get('id')}")
        print(f"  Endpoint: {endpoint_url}")
        print(f"  Eventos: {', '.join(EVENTS)}")


if __name__ == "__main__":
    parser = argparse.ArgumentParser()
    parser.add_argument("--space-id", required=True)
    parser.add_argument("--url", required=True)
    args = parser.parse_args()
    asyncio.run(main(args.space_id, args.url))
