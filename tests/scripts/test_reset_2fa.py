from io import StringIO

from django.core import management

from itou.otp.models import ItouStaticDevice, ItouStaticToken, ItouTOTPDevice
from tests.otp.factories import ItouStaticTokenFactory, ItouTOTPDeviceFactory
from tests.users.factories import ItouStaffFactory


def run_command(*args, **kwargs):
    out = StringIO()
    err = StringIO()

    management.call_command("reset_2fa", *args, stdout=out, stderr=err, **kwargs)

    return out.getvalue(), err.getvalue()


def test_reset_2fa():
    user = ItouStaffFactory()
    ItouTOTPDeviceFactory(user=user)
    ItouStaticTokenFactory(user=user)

    run_command(user.email, "--wet-run")

    assert ItouTOTPDevice.objects.count() == 0
    assert ItouStaticToken.objects.count() == 0
    assert ItouStaticDevice.objects.count() == 0
