from huey import Huey
from huey.storage import RedisStorage


class RedisStorageWithFallback(RedisStorage):
    def enqueue(self, data, priority=None):
        try:
            super().enqueue(data, priority=priority)
        except Exception:
            from itou.tasks.models import Task

            Task.objects.create(data=data, priority=priority)


class ItouHuey(Huey):
    storage_class = RedisStorageWithFallback
