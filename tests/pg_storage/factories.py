import factory
import factory.fuzzy

from itou.pg_storage.models import Task


QUEUE_NAME = "test_queue"


class TaskFactory(factory.django.DjangoModelFactory):
    class Meta:
        model = Task

    queue = QUEUE_NAME
    priority = 0
    data = factory.fuzzy.FuzzyText(length=10).fuzz().encode("utf-8")
