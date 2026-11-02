"""Worker do cronograma: uma lista que grava datas de que outra depende avisa essa outra
(o webhook do ClickUp só chega à lista onde a gravação aconteceu)."""
import asyncio

import pytest

from src.core.config import settings
from src.services.schedule_service import ScheduleRunSummary
from src.workers import schedule_worker


@pytest.fixture
def lists(monkeypatch):
    monkeypatch.setattr(settings, "schedule_enabled", True)
    monkeypatch.setattr(settings, "schedule_list_ids", "STUDIO,CTP")
    monkeypatch.setattr(settings, "schedule_debounce_seconds", 0)
    calls: list[str] = []

    async def recalculate(self, list_id, dry_run=False, rebaseline=False):
        calls.append(list_id)
        linked = ["CTP", "OUTRA"] if list_id == "STUDIO" else []
        return ScheduleRunSummary(list_id=list_id, dry_run=dry_run, writes=3, linked_lists=linked)

    monkeypatch.setattr(schedule_worker.ScheduleService, "recalculate", recalculate)
    monkeypatch.setattr(schedule_worker, "AsyncSessionLocal", _Dummy)
    monkeypatch.setattr(schedule_worker, "ClickUpClient", _Dummy)
    yield calls
    schedule_worker._pending.clear()


class _Dummy:
    async def __aenter__(self):
        return self

    async def __aexit__(self, *exc):
        return False


async def _settle():
    for _ in range(5):
        await asyncio.sleep(0)
        await asyncio.gather(*schedule_worker._pending.values(), return_exceptions=True)


async def test_a_list_that_wrote_dates_recalculates_the_lists_waiting_on_it(lists):
    await schedule_worker.run_recalculation("STUDIO")
    await _settle()

    assert lists == ["STUDIO", "CTP"]                  # "OUTRA" não é gerida pelo motor


async def test_a_dry_run_does_not_wake_the_other_lists(lists):
    await schedule_worker.run_recalculation("STUDIO", dry_run=True)
    await _settle()

    assert lists == ["STUDIO"]
