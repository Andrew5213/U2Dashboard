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


async def test_attachment_is_sent_as_multipart(monkeypatch):
    """O cliente principal manda Content-Type JSON em todo pedido; o anexo precisa de multipart."""
    import httpx
    from src.services import clickup_client as module
    seen = []

    def handler(request):
        seen.append(request)
        return httpx.Response(200, json={"id": "att"})

    real = httpx.AsyncClient
    monkeypatch.setattr(module.httpx, "AsyncClient",
                        lambda *a, **kw: real(*a, transport=httpx.MockTransport(handler), **kw))
    async with ClickUpClient() as client:
        result = await client.upload_attachment("T1", "foto.jpg", b"jpeg-bytes", "image/jpeg")

    request = seen[0]
    assert result == {"id": "att"}
    assert str(request.url) == "https://api.clickup.com/api/v2/task/T1/attachment"
    assert request.headers["content-type"].startswith("multipart/form-data; boundary=")
    assert b'name="attachment"; filename="foto.jpg"' in request.read()
    assert request.headers["authorization"] == "test_token"
