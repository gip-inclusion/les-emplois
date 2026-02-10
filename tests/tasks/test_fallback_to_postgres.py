import pytest
from django.core.management import call_command
from huey.contrib.djhuey import HUEY
from redis.exceptions import RedisError

from itou.tasks.models import Task


@pytest.fixture(autouse=True)
def defer_huey():
    orig_immediate = HUEY.immediate
    HUEY.immediate = False
    assert HUEY.immediate != orig_immediate
    yield
    HUEY.immediate = orig_immediate


@pytest.fixture(autouse=True)
def flush_huey(defer_huey):
    HUEY.storage.flush_queue()


def test_queue_task(django_capture_on_commit_callbacks, mocker):
    mocker.patch("huey.storage.RedisStorage.enqueue", side_effect=RedisError)

    executed = []

    def fake_task(*args, **kwargs):
        executed.append((args, kwargs))

    task = HUEY.task()(fake_task)
    with django_capture_on_commit_callbacks(execute=True):
        task(1, 2, a=None)
    task = Task.objects.get()
    data = HUEY.serializer.deserialize(task.data)
    assert data.name == "test_fallback_to_postgres.fake_task"
    assert data.args == (1, 2)
    del data.kwargs["sentry_headers"]
    assert data.kwargs == {"a": None}

    mocker.patch("huey.storage.RedisStorage.put_data", side_effect=RedisError)
    with pytest.raises(RedisError):
        with django_capture_on_commit_callbacks(execute=True):
            call_command("requeue_tasks")

    mocker.stopall()
    with django_capture_on_commit_callbacks(execute=True):
        call_command("requeue_tasks")
    assert HUEY.storage.queue_size() == 1
    HUEY.execute(HUEY.dequeue())
    assert executed == [((1, 2), {"a": None})]
    assert Task.objects.exists() is False
