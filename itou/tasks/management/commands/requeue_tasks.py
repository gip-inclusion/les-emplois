import uuid
from functools import partial

from django.db import transaction
from huey.contrib.djhuey import HUEY
from sentry_sdk.crons import monitor

from itou.tasks.models import Task
from itou.utils.command import BaseCommand


class Command(BaseCommand):
    ATOMIC_HANDLE = True
    help = "Queue Huey tasks that could not be scheduled."

    @monitor(
        monitor_slug="requeue_tasks",
        monitor_config={
            "schedule": {"type": "crontab", "value": "45 * * * *"},
            "checkin_margin": 5,
            "max_runtime": 10,
            "failure_issue_threshold": 2,
            "recovery_threshold": 1,
            "timezone": "UTC",
        },
    )
    def handle(self, *args, **options):
        # Do not try requeuing if the HUEY.storage is not writable.
        self.validate_storage()

        tasks = Task.objects.select_for_update()[:1_000]
        to_delete = []
        for task in tasks:
            transaction.on_commit(partial(HUEY.storage.enqueue, task.data))
            to_delete.append(task.pk)
        Task.objects.filter(pk__in=to_delete).delete()

    def validate_storage(self):
        key = str(uuid.uuid4())
        storage = HUEY.storage
        storage.put_data(key, "test")
        storage.pop_data(key)
