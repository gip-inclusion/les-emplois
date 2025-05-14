import logging

from django.db import transaction
from django.utils import timezone
from huey.constants import EmptyData as BaseEmptyData
from huey.storage import BaseStorage


logger = logging.getLogger(__name__)


class EmptyData(BaseEmptyData):
    def __new__(cls, *args, **kwargs):
        return None


# note vincentporte 2025-05
# find a smarter way to deal with datetime and timestamp between
# huey and djange
def convert_naive_dt_to_aware_ts(dt):
    if timezone.is_aware(dt):
        datetime = dt
    else:
        datetime = timezone.make_aware(dt, timezone.get_current_timezone())
    return datetime.timestamp()


# note vincentporte 2025-05
# don't like the way models are imported in the class methods …
# temp fix to prevent `django.core.exceptions.AppRegistryNotReady: Apps aren't loaded yet` error


class PostgresStorage(BaseStorage):
    def __init__(self, name, **kwargs):
        self.queue_name = name
        logger.info(f"Initialized PostgresStorage with queue name: {self.queue_name}")

    def enqueue(self, data, priority=0):
        """
        Given an opaque chunk of data, add it to the queue.

        :param bytes data: Task data.
        :param float priority: Priority, higher priorities processed first.
        :return: No return value.
        """
        from itou.pg_storage.models import Task

        priority = priority if priority else 0
        Task.objects.create(queue=self.queue_name, data=data, priority=priority)
        logger.info(f"Enqueued task data: {data} with priority: {priority}")

    def dequeue(self):
        """
        Atomically remove data from the queue. If no data is available, no data
        is returned.

        :return: Opaque binary task data or None if queue is empty.
        """
        from itou.pg_storage.models import Task

        with transaction.atomic():
            task = Task.objects.select_for_update().filter(queue=self.queue_name).order_by("-priority", "id").first()
            if task:
                task_data = task.data
                task.delete()
                logger.info(f"Dequeued task data: {task_data}")
                return task_data
        logger.info("No task data to dequeue.")
        return EmptyData()

    def queue_size(self):
        """
        Return the length of the queue.

        :return: Number of tasks.
        """
        from itou.pg_storage.models import Task

        return Task.objects.filter(queue=self.queue_name).count()

    def enqueued_items(self, limit=None):
        """
        Non-destructively read the given number of tasks from the queue. If no
        limit is specified, all tasks will be read.

        :param int limit: Restrict the number of tasks returned.
        :return: A list containing opaque binary task data.
        """
        from itou.pg_storage.models import Task

        tasks = list(
            Task.objects.filter(queue=self.queue_name).order_by("-priority", "id").values_list("data", flat=True)
        )
        if limit:
            tasks = tasks[:limit]
        return tasks

    def flush_queue(self):
        """
        Remove all data from the queue.

        :return: No return value.
        """
        from itou.pg_storage.models import Task

        Task.objects.filter(queue=self.queue_name).delete()

    def add_to_schedule(self, data, ts):
        """
        Add the given task data to the schedule, to be executed at the given
        timestamp.

        :param bytes data: Task data.
        :param datetime ts: Timestamp at which task should be executed.
        :return: No return value.
        """
        from itou.pg_storage.models import Schedule

        ts = convert_naive_dt_to_aware_ts(ts)  # to be fixed

        Schedule.objects.create(queue=self.queue_name, data=data, timestamp=ts)

    def read_schedule(self, ts):
        """
        Read all tasks from the schedule that should be executed at or before
        the given timestamp. Once read, the tasks are removed from the
        schedule.

        :param datetime ts: Timestamp
        :return: List containing task data for tasks which should be executed
                 at or before the given timestamp.
        """
        from itou.pg_storage.models import Schedule

        ts = convert_naive_dt_to_aware_ts(ts)  # to be fixed

        with transaction.atomic():
            tasks = (
                Schedule.objects.select_for_update()
                .filter(queue=self.queue_name, timestamp__lte=ts)
                .order_by("timestamp")
            )
            tasks_datas = list(tasks.values_list("data", flat=True))
            tasks.delete()
            return tasks_datas

    def schedule_size(self):
        """
        :return: The number of tasks currently in the schedule.
        """
        from itou.pg_storage.models import Schedule

        return Schedule.objects.filter(queue=self.queue_name).count()

    def scheduled_items(self, limit=None):
        """
        Non-destructively read the given number of tasks from the schedule.

        :param int limit: Restrict the number of tasks returned.
        :return: List of tasks that are in schedule, in order from soonest to
                 latest.
        """
        from itou.pg_storage.models import Schedule

        tasks = list(
            Schedule.objects.filter(queue=self.queue_name).order_by("timestamp").values_list("data", flat=True)
        )
        if limit:
            tasks = tasks[:limit]
        return tasks

    def flush_schedule(self):
        """
        Delete all scheduled tasks.

        :return: No return value.
        """
        from itou.pg_storage.models import Schedule

        Schedule.objects.filter(queue=self.queue_name).delete()

    def put_data(self, key, value, is_result=False):
        """
        Store an arbitrary key/value pair.

        :param bytes key: lookup key
        :param bytes value: value
        :param bool is_result: indicate if we are storing a (volatile) task
            result versus metadata like a task revocation key or lock.
        :return: No return value.
        """
        # note : `is_result` seems not to be used in SQL implementations
        from itou.pg_storage.models import KV

        KV.objects.update_or_create(queue=self.queue_name, key=key, defaults={"value": value})

    def peek_data(self, key):
        """
        Non-destructively read the value at the given key, if it exists.

        :param bytes key: Key to read.
        :return: Associated value, if key exists, or ``EmptyData``.
        """
        from itou.pg_storage.models import KV

        try:
            return KV.objects.get(queue=self.queue_name, key=key).value
        except KV.DoesNotExist:
            return EmptyData()

    def pop_data(self, key):
        """
        Destructively read the value at the given key, if it exists.

        :param bytes key: Key to read.
        :return: Associated value, if key exists, or ``EmptyData``.
        """
        from itou.pg_storage.models import KV

        with transaction.atomic():
            try:
                kv = KV.objects.select_for_update().get(queue=self.queue_name, key=key)
                value = kv.value
                kv.delete()
                return value
            except KV.DoesNotExist:
                return EmptyData()

    def delete_data(self, key):
        """
        Delete the value at the given key, if it exists.

        :param bytes key: Key to delete.
        :return: boolean success or failure.
        """
        from itou.pg_storage.models import KV

        with transaction.atomic():
            try:
                kv = KV.objects.select_for_update().get(queue=self.queue_name, key=key)
                kv.delete()
                return True
            except KV.DoesNotExist:
                return EmptyData()

    def has_data_for_key(self, key):
        """
        Return whether there is data for the given key.

        :return: Boolean value.
        """
        from itou.pg_storage.models import KV

        return KV.objects.filter(queue=self.queue_name, key=key).exists()

    def put_if_empty(self, key, value):
        return super().put_if_empty(key, value)

    def result_store_size(self):
        """
        :return: Number of key/value pairs in the result store.
        """
        from itou.pg_storage.models import KV

        return KV.objects.filter(queue=self.queue_name).count()

    def result_items(self):
        """
        Non-destructively read all the key/value pairs from the data-store.

        :return: Dictionary mapping all key/value pairs in the data-store.
        """
        from itou.pg_storage.models import KV

        return {key: value for key, value in KV.objects.filter(queue=self.queue_name).values_list("key", "value")}

    def flush_results(self):
        """
        Delete all key/value pairs from the data-store.

        :return: No return value.
        """
        from itou.pg_storage.models import KV

        KV.objects.filter(queue=self.queue_name).delete()

    def flush_all(self):
        return super().flush_all()
