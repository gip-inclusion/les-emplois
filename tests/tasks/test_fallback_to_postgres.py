from datetime import timedelta

import pytest
from django.core.management import call_command
from django.utils import timezone
from freezegun import freeze_time
from huey.contrib.djhuey import HUEY
from redis.exceptions import RedisError

from itou.tasks.models import Task


@pytest.fixture(autouse=True)
def defer_huey():
    # Huey bypasses storage.enqueue() when immediate.
    assert HUEY.immediate is True
    HUEY.immediate = False
    yield
    HUEY.immediate = True


@pytest.fixture(autouse=True)
def flush_huey(defer_huey):
    HUEY.storage.flush_queue()


@pytest.fixture(params=[False, True], ids=["without_sentry", "with_sentry"])
def sentry_enabled(request):
    """Run the test without a Sentry client, like the rest of the test suite, and with one, like in production.

    Its Huey integration adds a `sentry_headers` keyword argument to each task when it is enqueued, and removes it
    before the task is executed.
    """
    if request.param:
        request.getfixturevalue("sentry")
    return request.param


@pytest.fixture(name="fake_task")
def fake_task_fixture():
    executed = []

    @HUEY.task()
    def test_task(*args, **kwargs):
        executed.append((args, kwargs))

    yield test_task, executed
    test_task.unregister()


def test_redis_unavailable_stores_to_db(fake_task, mocker, sentry_enabled):
    mocker.patch("huey.storage.RedisStorage.enqueue", side_effect=RedisError)
    task, executed = fake_task

    task(1, 2, a=None)

    task = Task.objects.get()
    data = HUEY.serializer.deserialize(task.data)
    assert data.name == "test_fallback_to_postgres.test_task"
    assert data.args == (1, 2)
    if sentry_enabled:
        assert data.kwargs.pop("sentry_headers").keys() == {"baggage", "sentry-trace"}
    assert data.kwargs == {"a": None}
    assert executed == []


@pytest.mark.usefixtures("sentry_enabled")
def test_requeue(caplog, fake_task, mocker):
    mocker.patch("huey.storage.RedisStorage.enqueue", side_effect=RedisError)
    task, executed = fake_task
    task(1, 2, a=None)
    mocker.stopall()
    db_task = Task.objects.get()

    call_command("requeue_tasks")

    assert HUEY.storage.queue_size() == 1
    HUEY.execute(HUEY.dequeue())
    assert executed == [((1, 2), {"a": None})]
    assert Task.objects.exists() is False
    assert f"Requeuing task {db_task.pk}." in caplog.messages


NOT_REQUEUING_MESSAGE = "Redis is unavailable and the first task is not old enough, not requeuing tasks."


def test_redis_unavailable_with_old_task(caplog, fake_task, mocker):
    mocker.patch("huey.storage.RedisStorage.enqueue", side_effect=RedisError)
    task, executed = fake_task
    with freeze_time(timezone.now() - timedelta(hours=3, seconds=1)):
        task()
    mocker.stopall()
    mocker.patch("huey.storage.RedisStorage.put_data", side_effect=RedisError)

    with pytest.raises(RedisError):
        call_command("requeue_tasks")
    assert executed == []
    assert NOT_REQUEUING_MESSAGE not in caplog.messages


def test_redis_unavailable_with_recent_task(caplog, fake_task, mocker):
    mocker.patch("huey.storage.RedisStorage.enqueue", side_effect=RedisError)
    task, executed = fake_task
    task()
    mocker.stopall()
    mocker.patch("huey.storage.RedisStorage.put_data", side_effect=RedisError)

    # RedisError not raised.
    call_command("requeue_tasks")
    assert executed == []
    assert NOT_REQUEUING_MESSAGE in caplog.messages
