import factory

from itou.antivirus.models import Scan
from tests.files.factories import FileFactory


class ScanFactory(factory.django.DjangoModelFactory):
    class Meta:
        model = Scan

    file = factory.SubFactory(FileFactory)
