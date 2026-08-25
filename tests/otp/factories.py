import uuid

import factory

from itou.otp.models import Itou2FAResetRequest, ItouTOTPDevice
from tests.users.factories import ItouStaffFactory


class ItouTOTPDeviceFactory(factory.django.DjangoModelFactory):
    class Meta:
        model = ItouTOTPDevice

    user = factory.SubFactory(ItouStaffFactory)
    name = factory.LazyFunction(uuid.uuid4)


class Itou2FAResetRequestFactory(factory.django.DjangoModelFactory):
    class Meta:
        model = Itou2FAResetRequest
