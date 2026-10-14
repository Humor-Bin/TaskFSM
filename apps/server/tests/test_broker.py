import asyncio
import threading

import pytest

from taskfsm.realtime.broker import InMemoryBroker


@pytest.mark.asyncio
async def test_broker_accepts_publish_from_worker_thread():
    broker = InMemoryBroker()
    async with broker.subscribe() as queue:
        thread = threading.Thread(target=lambda: broker.publish({'type': 'task.updated'}))
        thread.start(); thread.join()
        item = await asyncio.wait_for(queue.get(), timeout=1)
        assert item == {'type': 'task.updated'}
    assert broker.subscriber_count == 0
