from django.db import models
from django.utils import timezone


class Task(models.Model):
    data = models.BinaryField()

    created_at = models.DateTimeField(default=timezone.now)
