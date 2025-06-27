from django.db import models


class KV(models.Model):
    queue = models.CharField()
    key = models.CharField()
    value = models.BinaryField()

    class Meta:
        constraints = [models.UniqueConstraint(fields=["queue", "key"], name="unique_queue_key")]


class Schedule(models.Model):
    queue = models.CharField()
    data = models.BinaryField()
    timestamp = models.IntegerField()

    class Meta:
        indexes = [
            models.Index(fields=["queue", "timestamp"], name="queue_timestamp_idx"),
        ]


class Task(models.Model):
    queue = models.CharField()
    data = models.BinaryField()
    priority = models.DecimalField(default=0, max_digits=4, decimal_places=2)

    class Meta:
        indexes = [
            models.Index(fields=["priority", "id"], name="priority_id_idx"),
        ]
