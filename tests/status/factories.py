import factory
from django.utils import timezone

from itou.status import models


class ProbeStatusFactory(factory.django.DjangoModelFactory):
    class Meta:
        model = models.ProbeStatus

    class Params:
        with_success = factory.Trait(
            last_success_at=factory.Faker("date_time_this_month", tzinfo=timezone.get_default_timezone()),
            last_success_info=factory.Faker("sentence"),
        )
        with_failure = factory.Trait(
            last_failure_at=factory.Faker("date_time_this_month", tzinfo=timezone.get_default_timezone()),
            last_failure_info=factory.Faker("sentence"),
        )

    name = factory.Faker("uuid4")
