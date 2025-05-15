import pickle

from huey import Huey

from itou.pg_storage.models import Task
from itou.pg_storage.storage import PostgresStorage


postgres_huey = Huey(
    storage_class=PostgresStorage,
    immediate=False,
    immediate_use_memory=False,
    blocking=False,
    name="test_pg_huey",
)


@postgres_huey.task()
def pg_task(a, b):
    print("Executing pg_task", a, b)
    return a + b


def test_huey_task_postgres():
    result = pg_task(1, 2)
    stored_task = Task.objects.get()
    message = pickle.loads(stored_task.data)
    assert message.args == (1, 2)
    assert message.id == result.id

    executed_task = postgres_huey.execute(result.task)
    assert executed_task == 3
    assert Task.objects.count() == 0
