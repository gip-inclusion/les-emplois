import uuid

import factory

from itou.otp.models import ItouStaticDevice, ItouStaticToken, ItouTOTPDevice
from tests.users.factories import ItouStaffFactory, UserFactory


class ItouTOTPDeviceFactory(factory.django.DjangoModelFactory):
    class Meta:
        model = ItouTOTPDevice

    user = factory.SubFactory(ItouStaffFactory)
    name = factory.LazyFunction(uuid.uuid4)


class ItouStaticDeviceFactory(factory.django.DjangoModelFactory):
    class Meta:
        model = ItouStaticDevice

    user = factory.SubFactory(UserFactory)


class ItouStaticTokenFactory(factory.django.DjangoModelFactory):
    class Meta:
        model = ItouStaticToken

    class Params:
        user = factory.SubFactory(UserFactory)

    device = factory.SubFactory(
        ItouStaticDeviceFactory,
        user=factory.SelfAttribute("..user"),
    )
