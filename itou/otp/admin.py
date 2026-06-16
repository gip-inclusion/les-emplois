from django.contrib import admin
from django_otp.plugins.otp_totp.models import TOTPDevice

from itou.otp.models import ItouTOTPDevice
from itou.utils.admin import ItouModelAdmin, ReadonlyMixin


@admin.register(ItouTOTPDevice)
class ItouTOTPDeviceAdmin(ReadonlyMixin, ItouModelAdmin):
    list_display = (
        "user",
        "created_at",
        "last_used_at",
    )
    list_select_related = ("user",)

    def get_fields(self, request, obj=None):
        fields = super().get_fields(request, obj=obj)
        fields.remove("key")
        fields.insert(0, "created_at")
        return fields


admin.site.unregister(TOTPDevice)
