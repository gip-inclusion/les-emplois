import uuid
from datetime import timedelta

from django.db import transaction
from django.utils import timezone
from huey.contrib.djhuey import HUEY
from redis.exceptions import RedisError
from sentry_sdk.crons import monitor

from itou.tasks.models import Task
from itou.utils.command import BaseCommand


class Command(BaseCommand):
    ATOMIC_HANDLE = False
    help = """\
    Queue Huey tasks that could not be scheduled.

    Band-aid until the tasks storage is moved to the database.
    """

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
        tasks = Task.objects.order_by("created_at")[:1_000]
        if tasks:
            try:
                # Do not requeue if the HUEY.storage is not writable.
                self.validate_storage()
            except RedisError:
                if tasks[0].created_at <= timezone.now() - timedelta(hours=3):
                    raise
                self.logger.info("Redis is unavailable and the first task is not old enough, not requeuing tasks.")
                return

            for task in tasks:
                # There’s no atomicity guarantee between Redis and PostgreSQL.
                # Process tasks one by one to avoid requeuing a bunch of tasks
                # multiple times when this commands is interrupted (deploy, …).
                with transaction.atomic():
                    # Evaluate the queryset to take the lock.
                    task = Task.objects.filter(pk=task.pk).select_for_update(skip_locked=True, of={"self"}).first()
                    if task:
                        self.logger.info("Requeuing task %d.", task.pk)
                        # A task might be queued twice because the enqueue
                        # succeeded and the delete() didn’t get executed
                        # (interruption by e.g. a deploy).
                        HUEY.storage.enqueue(task.data)
                        task.delete()

    def validate_storage(self):
        key = str(uuid.uuid4())
        HUEY.storage.put_data(key, "test")
        HUEY.storage.pop_data(key)
