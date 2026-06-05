from django.contrib import admin
from django_otp.plugins.otp_totp.models import TOTPDevice

from itou.otp.models import ItouTOTPDevice
from itou.utils.admin import ItouModelAdmin, ReadonlyMixin


@admin.register(ItouTOTPDevice)
class ItouTOTPDeviceAdmin(ReadonlyMixin, ItouModelAdmin):
    pass  # FIXME


admin.site.unregister(TOTPDevice)
