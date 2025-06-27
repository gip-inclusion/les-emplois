import datetime

import factory
from django.utils import timezone

from itou.files.models import File


class FileFactory(factory.django.DjangoModelFactory):
    # depth=1 means a file under a directory, eg: resume/amazing.pdf
    key = factory.Faker("file_path", absolute=False, depth=1)
    last_modified = factory.LazyFunction(timezone.now)

    class Meta:
        model = File

    class Params:
        for_snapshot = factory.Trait(
            id="e683e4dc-34b5-44c1-ad6d-2fd77835d743",
            last_modified=datetime.datetime(2000, 1, 1, tzinfo=datetime.UTC),
        )
