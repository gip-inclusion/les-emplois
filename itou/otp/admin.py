from django.contrib import admin
from django_otp.plugins.otp_totp import admin as django_otp_admin
from django_otp.plugins.otp_totp.models import TOTPDevice


class TOTPDeviceAdmin(django_otp_admin.TOTPDeviceAdmin):
    def has_delete_permission(self, request, obj=None):
        return False

    def has_change_permission(self, request, obj=None):
        return False

    def has_add_permission(self, request):
        return False


admin.site.unregister(TOTPDevice)
admin.site.register(TOTPDevice, TOTPDeviceAdmin)
