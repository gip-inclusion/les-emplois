import factory
import factory.fuzzy
from django.conf import settings

from itou.pg_storage.models import Task


class TaskFactory(factory.django.DjangoModelFactory):
    class Meta:
        model = Task

    queue = settings.HUEY["name"]
    priority = 0
    data = factory.fuzzy.FuzzyText(length=10).fuzz().encode("utf-8")
