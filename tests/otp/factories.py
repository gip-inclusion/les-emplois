import uuid

import factory

from itou.otp.models import ItouTOTPDevice
from tests.users.factories import ItouStaffFactory


class ItouTOTPDeviceFactory(factory.django.DjangoModelFactory):
    class Meta:
        model = ItouTOTPDevice

    user = factory.SubFactory(ItouStaffFactory)
    name = factory.LazyFunction(uuid.uuid4)
