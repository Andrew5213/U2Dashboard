import asyncio
import pytest
from src.services.event_broadcaster import EventBroadcaster


@pytest.fixture
def broadcaster() -> EventBroadcaster:
    return EventBroadcaster()


@pytest.mark.asyncio
async def test_subscribe_adds_queue(broadcaster):
    q = await broadcaster.subscribe()
    assert broadcaster.subscriber_count == 1
    await broadcaster.unsubscribe(q)


@pytest.mark.asyncio
async def test_unsubscribe_removes_queue(broadcaster):
    q = await broadcaster.subscribe()
    await broadcaster.unsubscribe(q)
    assert broadcaster.subscriber_count == 0


@pytest.mark.asyncio
async def test_publish_delivers_to_all(broadcaster):
    q1 = await broadcaster.subscribe()
    q2 = await broadcaster.subscribe()
    event = {"type": "taskUpdated", "task_id": "abc"}
    await broadcaster.publish(event)
    assert q1.get_nowait() == event
    assert q2.get_nowait() == event
    await broadcaster.unsubscribe(q1)
    await broadcaster.unsubscribe(q2)


@pytest.mark.asyncio
async def test_publish_to_no_subscribers(broadcaster):
    await broadcaster.publish({"type": "test"})  # não deve lançar exceção


@pytest.mark.asyncio
async def test_full_queue_removed(broadcaster):
    q = await broadcaster.subscribe()
    # Enche a fila até o limite
    for i in range(100):
        q.put_nowait({"i": i})
    # A próxima publicação deve remover o subscriber com fila cheia
    await broadcaster.publish({"type": "overflow"})
    assert broadcaster.subscriber_count == 0


@pytest.mark.asyncio
async def test_multiple_events(broadcaster):
    q = await broadcaster.subscribe()
    for i in range(5):
        await broadcaster.publish({"i": i})
    results = []
    while not q.empty():
        results.append(q.get_nowait())
    assert len(results) == 5
    assert results[0]["i"] == 0
    assert results[4]["i"] == 4
    await broadcaster.unsubscribe(q)


@pytest.mark.asyncio
async def test_unsubscribe_idempotent(broadcaster):
    q = await broadcaster.subscribe()
    await broadcaster.unsubscribe(q)
    await broadcaster.unsubscribe(q)  # segunda vez não deve lançar exceção
    assert broadcaster.subscriber_count == 0
