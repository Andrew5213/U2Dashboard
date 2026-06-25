#!/usr/bin/env python3
"""Popula o cache do ClickUp manualmente. Use na primeira execução ou para forçar refresh."""
import argparse
import asyncio
import sys
import os

sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))

from src.core.database import AsyncSessionLocal, init_db
from src.core.logging import setup_logging
from src.services.cache_service import CacheService


async def main(space_id: str) -> None:
    setup_logging()
    await init_db()

    print(f"Iniciando cache refresh para space {space_id}...")
    async with AsyncSessionLocal() as db:
        summary = await CacheService(db).refresh_cache_full(space_id, trigger="startup")

    print(f"\n✅ Cache populado!")
    print(f"   Folders : {summary.folders_updated}")
    print(f"   Listas  : {summary.lists_updated}")
    print(f"   Tasks   : {summary.tasks_updated}")
    print(f"   Tempo   : {summary.duration_seconds:.1f}s")
    if summary.errors:
        print(f"\n⚠️  {len(summary.errors)} erro(s):")
        for err in summary.errors[:10]:
            print(f"   - {err}")


if __name__ == "__main__":
    parser = argparse.ArgumentParser(description="Popular cache do ClickUp")
    parser.add_argument("--space-id", required=True, help="ID do space ClickUp")
    args = parser.parse_args()
    asyncio.run(main(args.space_id))
