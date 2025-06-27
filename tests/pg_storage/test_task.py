import pickle

import pytest
from huey.contrib.djhuey import HUEY

from itou.pg_storage.models import Task


@pytest.fixture(autouse=True)
def override_huey_settings(settings):
    settings.HUEY = {
        "name": "test-queue",
        "immediate": False,
        "immediate_use_memory": False,
        "blocking": False,
        "results": True,
    }
    yield


@HUEY.task()
def pg_task(a, b):
    return a + b


def test_a_task_in_postgres_storage_queue():
    pg_task(1, 2)

    pending_task_in_db = Task.objects.get()
    assert pending_task_in_db.queue == HUEY.name

    message = pickle.loads(pending_task_in_db.data)
    assert message.args == (1, 2)

    task = HUEY.dequeue()
    assert task.args == (1, 2)


def test_empty_queue():
    task = HUEY.dequeue()
    assert task is None
