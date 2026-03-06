from django.conf import settings
from django.db import models
from django.utils import timezone


class BaseTask(models.Model):
    queue = models.CharField(default=settings.HUEY["name"])
    data = models.BinaryField()
    created_at = models.DateTimeField(
        default=timezone.now,
        verbose_name="date de création",
    )

    class Meta:
        abstract = True
        indexes = [
            models.Index("created_at", name="tasks_%(class)s_created_at_idx"),
        ]


class Task(BaseTask):
    priority = models.BigIntegerField(
        blank=True,
        null=True,
        verbose_name="priorité",
    )

    class Meta(BaseTask.Meta):
        indexes = BaseTask.Meta.indexes + [
            models.Index(
                "priority",
                condition=models.Q(priority__isnull=False),
                name="tasks_priority_not_null_idx",
            ),
        ]


class Schedule(BaseTask):
    timestamp = models.DateTimeField(
        blank=True,
        null=True,
        verbose_name="exécution le",
    )

    class Meta(BaseTask.Meta):
        indexes = BaseTask.Meta.indexes + [
            models.Index(
                "timestamp",
                condition=models.Q(timestamp__isnull=False),
                name="tasks_timestamp_not_null_idx",
            ),
        ]


class KV(models.Model):
    key = models.BinaryField(verbose_name="clé")
    value = models.BinaryField(verbose_name="valeur")
    is_result = models.BooleanField(default=False, verbose_name="résultat")

    class Meta:
        constraints = [
            models.UniqueConstraint("key", name="tasks_kv_key_uniq"),
        ]
