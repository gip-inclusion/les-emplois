import datetime

import factory

from itou.cnav.enums import CNAVRecordOrigin
from itou.cnav.models import CNAVRecord
from tests.users.factories import JobSeekerProfileFactory


class CNAVRecordFactory(factory.django.DjangoModelFactory):
    class Meta:
        model = CNAVRecord

    profile = factory.SubFactory(JobSeekerProfileFactory)
    origin = factory.fuzzy.FuzzyChoice(CNAVRecordOrigin.values)

    input_birthdate = factory.fuzzy.FuzzyDate(datetime.date(1968, 1, 1), datetime.date(1999, 12, 31))
