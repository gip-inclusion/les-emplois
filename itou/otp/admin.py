from django.contrib import admin
from django_otp.plugins.otp_totp import admin as django_otp_admin
from django_otp.plugins.otp_totp.models import TOTPDevice

from itou.utils.admin import ReadonlyMixin


class TOTPDeviceAdmin(ReadonlyMixin, django_otp_admin.TOTPDeviceAdmin):
    pass


admin.site.unregister(TOTPDevice)
admin.site.register(TOTPDevice, TOTPDeviceAdmin)
