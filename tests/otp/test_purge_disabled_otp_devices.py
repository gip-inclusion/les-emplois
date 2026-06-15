import datetime

from django.test.testcases import call_command
from django.utils import timezone
from pytest_django.asserts import assertQuerySetEqual

from itou.otp.models import ItouTOTPDevice
from tests.otp.factories import ItouTOTPDeviceFactory


class TestCommand:
    def setup_method(self):
        self.not_disabled = ItouTOTPDeviceFactory(disabled_at=None)
        self.disabled_too_recently = ItouTOTPDeviceFactory(disabled_at=timezone.now() - datetime.timedelta(days=30))
        self.disabled_long_ago = ItouTOTPDeviceFactory(disabled_at=timezone.now() - datetime.timedelta(days=91))

    def test_wet_run(self, caplog):
        assert ItouTOTPDevice.objects.count() == 3
        call_command("purge_disabled_otp_devices", wet_run=True)
        assert ItouTOTPDevice.objects.count() == 2
        assertQuerySetEqual(
            ItouTOTPDevice.objects.all(),
            [self.not_disabled, self.disabled_too_recently],
            ordered=False,
        )
        assert caplog.messages[0] == "1 disabled TOTP devices have been purged"

    def test_dry_run(self, caplog):
        assert ItouTOTPDevice.objects.count() == 3
        call_command("purge_disabled_otp_devices", wet_run=False)
        assert ItouTOTPDevice.objects.count() == 3
        assert caplog.messages[0] == "1 disabled TOTP devices would be purged"
