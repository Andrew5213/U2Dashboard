"""Cliente do ClickUp: paginação da leitura de tarefas."""
from src.services.clickup_client import ClickUpClient


async def _pages(monkeypatch, pages):
    asked: list[str] = []

    async def fake_get(self, path, params=None):
        asked.append(params["page"])
        return pages[int(params["page"])]

    monkeypatch.setattr(ClickUpClient, "_get", fake_get)
    async with ClickUpClient() as client:
        tasks = await client.get_tasks("L1")
    return tasks, asked


async def test_reading_stops_at_the_last_page(monkeypatch):
    """O ClickUp diz qual é a última página — pedir a seguinte, vazia, custava uma ida ao
    servidor a mais em cada leitura (2026-11-08: metade das leituras de um recálculo)."""
    tasks, asked = await _pages(monkeypatch, [{"tasks": [{"id": "a"}], "last_page": False},
                                              {"tasks": [{"id": "b"}], "last_page": True}])

    assert [t["id"] for t in tasks] == ["a", "b"]
    assert asked == ["0", "1"]


async def test_without_the_flag_it_reads_until_an_empty_page(monkeypatch):
    tasks, asked = await _pages(monkeypatch, [{"tasks": [{"id": "a"}]}, {"tasks": []}])

    assert [t["id"] for t in tasks] == ["a"]
    assert asked == ["0", "1"]
