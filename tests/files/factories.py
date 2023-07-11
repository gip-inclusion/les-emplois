import datetime

import factory
from django.utils import timezone

from itou.files.models import File


class FileFactory(factory.django.DjangoModelFactory):
    key = factory.Faker("file_path", absolute=False, depth=2)
    last_modified = factory.LazyFunction(timezone.now)

    class Meta:
        model = File

    class Params:
        for_snapshot = factory.Trait(
            key="f0r_5n4p5h07",
            last_modified=datetime.datetime(2000, 1, 1, tzinfo=datetime.UTC),
        )
