import threading

import pytest
from django.db import connection
from django.test import TransactionTestCase

from itou.pg_storage.models import Task
from itou.pg_storage.storage import PostgresStorage
from tests.pg_storage.factories import QUEUE_NAME, TaskFactory


@pytest.fixture(name="pg_storage")
def pg_storage_fixture():
    storage = PostgresStorage(name=QUEUE_NAME)
    return storage


class TestPostgresStorageEnqueue:
    @pytest.mark.parametrize("priority", [None, 0, 1])
    def test_enqueue_with_priority(self, pg_storage, priority):
        data = b"test_data"
        pg_storage.enqueue(data, priority=priority)

        task = Task.objects.get()
        assert task.data == data
        assert task.priority == (priority if priority is not None else 0)
        assert task.queue == QUEUE_NAME


class TestPostgresStorageDequeue(TransactionTestCase):
    def setUp(self):
        self.storage = PostgresStorage(name=QUEUE_NAME)
        self.task = TaskFactory()

    def test_locked_task_not_returned_twice(self):
        results = []

        def dequeue_task():
            try:
                results.append(self.storage.dequeue())
            finally:
                connection.close()

        thread1 = threading.Thread(target=dequeue_task)
        thread2 = threading.Thread(target=dequeue_task)
        thread1.start()
        thread2.start()
        thread1.join()
        thread2.join()

        assert results == [self.task.data, None]

    def test_task_is_deleted(self):
        assert self.storage.dequeue() == self.task.data
        assert not Task.objects.all().exists()

    def test_empty_queue(self):
        other_storage = PostgresStorage(name="other_queue")
        assert other_storage.dequeue() is None

    def test_tasks_are_dequeued_by_priority(self):
        higher_task = TaskFactory(priority=1)

        assert [self.storage.dequeue() for _ in range(2)] == [higher_task.data, self.task.data]

    def test_tasks_are_dequeued_by_id(self):
        later_task = TaskFactory()

        assert [self.storage.dequeue() for _ in range(2)] == [self.task.data, later_task.data]


class TestPostgresStorageQueueSize:
    @pytest.mark.parametrize("tasks_count", [0, 1, 2])
    @pytest.mark.parametrize("tasks_in_other_queue_count", [0, 1])
    def test_count_tasks_in_queue(self, pg_storage, tasks_count, tasks_in_other_queue_count):
        TaskFactory.create_batch(tasks_count)
        TaskFactory.create_batch(tasks_in_other_queue_count, queue="other_queue")
        assert pg_storage.queue_size() == tasks_count
