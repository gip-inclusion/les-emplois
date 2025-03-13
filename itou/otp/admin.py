from django.contrib import admin
from django_otp.plugins.otp_totp import admin as django_otp_admin
from django_otp.plugins.otp_totp.models import TOTPDevice

from itou.utils.admin import ReadonlyMixin


class TOTPDeviceAdmin(django_otp_admin.TOTPDeviceAdmin, ReadonlyMixin):
    pass


admin.site.unregister(TOTPDevice)
admin.site.register(TOTPDevice, TOTPDeviceAdmin)
