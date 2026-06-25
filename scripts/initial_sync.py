"""
Executa uma sincronização inicial completa Airbox → ClickUp.

Uso:
    python scripts/initial_sync.py --space-id <CLICKUP_SPACE_ID>
"""
import asyncio
import argparse
import sys
import os

sys.path.insert(0, os.path.join(os.path.dirname(__file__), ".."))

from src.core.database import init_db, AsyncSessionLocal
from src.services.sync_service import SyncService


async def main(space_id: str) -> None:
    await init_db()
    async with AsyncSessionLocal() as db:
        service = SyncService(db)
        print(f"Iniciando sync para space {space_id}...")
        results = await service.sync_all_agreements(space_id)

    success = sum(1 for r in results if r.success)
    errors = sum(1 for r in results if not r.success)
    print(f"\nSync concluído: {success} tarefas sincronizadas, {errors} erros")

    if errors:
        print("\nErros:")
        for r in results:
            if not r.success:
                print(f"  [{r.entity_id}] {r.error}")


if __name__ == "__main__":
    parser = argparse.ArgumentParser()
    parser.add_argument("--space-id", required=True)
    args = parser.parse_args()
    asyncio.run(main(args.space_id))
