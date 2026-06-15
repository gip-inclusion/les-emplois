from django.contrib import admin
from django_otp.plugins.otp_totp.models import TOTPDevice

from itou.otp.models import ItouTOTPDevice
from itou.utils.admin import ItouModelAdmin, ReadonlyMixin


@admin.register(ItouTOTPDevice)
class ItouTOTPDeviceAdmin(ReadonlyMixin, ItouModelAdmin):
    list_display = (
        "user",
        "last_used_at",
    )
    list_select_related = ("user",)

    def get_fields(self, request, obj=None):
        fields = super().get_fields(request, obj=obj)
        fields.remove("key")
        return fields


admin.site.unregister(TOTPDevice)
