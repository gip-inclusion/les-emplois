from django.utils import timezone

from itou.otp.utils import get_user_devices
from tests.otp.factories import ItouTOTPDeviceFactory
from tests.users.factories import ItouStaffFactory


def test_get_user_devices():
    user1 = ItouStaffFactory()
    user2 = ItouStaffFactory()
    deviceB = ItouTOTPDeviceFactory(user=user1, disabled_at=None, name="b")
    deviceA = ItouTOTPDeviceFactory(user=user1, disabled_at=None, name="a")
    ItouTOTPDeviceFactory(user=user1, disabled_at=timezone.now())
    ItouTOTPDeviceFactory(user=user2, disabled_at=None)

    assert get_user_devices(user1) == [deviceA, deviceB]
