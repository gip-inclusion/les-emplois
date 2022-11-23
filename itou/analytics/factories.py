import factory

from .models import Datum


class DatumFactory(factory.django.DjangoModelFactory):
    value = factory.Faker("pyint")

    class Meta:
        model = Datum
