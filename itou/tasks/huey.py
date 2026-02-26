import warnings

from django.db import transaction
from django.db.models.base import Coalesce
from django.utils.functional import cached_property
from django.utils.timezone import is_naive, make_aware
from huey import Huey
from huey.constants import EmptyData
from huey.storage import BaseStorage

from itou.utils.db import UniqueViolationError, maybe_unique_violation


class DatabaseStorage(BaseStorage):
    # Inspired from huey.contrib.sql_huey.SqlStorage.

    def __init__(self, name="huey", **storage_kwargs):
        self.name = name

    @cached_property
    def KV(self):
        from itou.tasks.models import KV

        return KV

    @cached_property
    def Schedule(self):
        from itou.tasks.models import Schedule

        return Schedule

    @cached_property
    def Task(self):
        from itou.tasks.models import Task

        return Task

    @property
    def schedule_qs(self):
        return self.Schedule.objects.filter(queue=self.name).order_by("timestamp", "created_at")

    @property
    def task_qs(self):
        return (
            self.Task.objects.filter(queue=self.name)
            .annotate(priority_non_zero=Coalesce("priority", 0))
            .order_by(
                "-priority_non_zero",
                "created_at",
            )
        )

    def enqueue(self, data, priority=None):
        if priority is not None:
            # Huey supports float priorities, but floating point types aren’t
            # such a good idea in PostgreSQL:
            # https://www.postgresql.org/docs/current/datatype-numeric.html#DATATYPE-FLOAT:~:text=Comparing%20two%20floating%2Dpoint%20values%20for%20equality%20might%20not%20always%20work%20as%20expected
            assert isinstance(priority, int)
        self.Task.objects.create(queue=self.name, data=data, priority=priority)

    def dequeue(self):
        with transaction.atomic():
            task = self.task_qs.select_for_update(of={"self"}, skip_locked=True).first()
            if task:
                task.delete()
                return task.data
        return None

    def queue_size(self):
        return self.task_qs.count()

    def enqueued_items(self, limit=None):
        return list(self.task_qs.values_list("data", flat=True)[:limit])

    def flush_queue(self):
        self.task_qs.delete()

    def add_to_schedule(self, data, ts):
        if is_naive(ts):
            warnings.warn("TODO")
            ts = make_aware(ts)
        self.Schedule.objects.create(queue=self.name, data=data, timestamp=ts)

    def read_schedule(self, ts):
        if is_naive(ts):
            warnings.warn("TODO")
            ts = make_aware(ts)
        with transaction.atomic():
            data = []
            to_delete = []
            for schedule in self.schedule_qs.filter(timestamp__lte=ts).select_for_update(
                of={"self"}, skip_locked=True
            ):
                data.append(schedule.data)
                to_delete.append(schedule.pk)
            self.schedule_qs.filter(pk__in=to_delete).delete()
        return data

    def schedule_size(self):
        return self.schedule_qs.count()

    def scheduled_items(self, limit=None):
        return list(self.schedule_qs.values_list("data", flat=True)[:limit])

    def flush_schedule(self):
        self.schedule_qs.delete()

    def put_data(self, key, value, is_result=False):
        self.KV.objects.bulk_create(
            [self.KV(key=key, value=value, is_result=is_result)],
            update_conflicts=True,
            update_fields=["value"],
            unique_fields=["key"],
        )

    def peek_data(self, key):
        try:
            return self.KV.objects.get(key=key).value
        except self.KV.DoesNotExist:
            return EmptyData

    def pop_data(self, key):
        with transaction.atomic():
            try:
                kv = self.KV.objects.select_for_update(of={"self"}, skip_locked=True).filter(key=key).get()
            except self.KV.DoesNotExist:
                return EmptyData
            else:
                kv.delete()
                return kv.value

    def delete_data(self, key):
        num_delete, _delete_details = self.KV.objects.filter(key=key).delete()
        return bool(num_delete)

    def has_data_for_key(self, key):
        return self.KV.objects.filter(key=key).exists()

    def put_if_empty(self, key, value):
        with transaction.atomic():
            try:
                with maybe_unique_violation(self.KV, "tasks_kv_key_uniq"):
                    self.KV.objects.create(key=key, value=value)
                    return True
            except UniqueViolationError:
                return False

    def result_store_size(self):
        return self.KV.objects.count()

    def result_items(self):
        return dict(self.KV.objects.values_list("key", "value"))

    def flush_results(self):
        self.KV.objects.all().delete()


class ItouHuey(Huey):
    storage_class = DatabaseStorage
