from django.contrib import admin
from django.contrib.admin.utils import display_for_value
from django_otp.plugins.otp_totp.models import TOTPDevice

from itou.otp.models import ItouTOTPDevice
from itou.utils.admin import ItouModelAdmin, ReadonlyMixin


@admin.register(ItouTOTPDevice)
class ItouTOTPDeviceAdmin(ReadonlyMixin, ItouModelAdmin):
    list_display = ("user", "enabled", "created_at", "last_used_at")
    list_select_related = ("user",)

    def get_fields(self, request, obj=None):
        fields = super().get_fields(request, obj=obj)
        fields.remove("key")
        fields.insert(0, "created_at")
        return fields

    @admin.display(description="activé")
    def enabled(self, obj):
        return display_for_value(
            obj.disabled_at is None,
            empty_value_display="unused kwarg",
            boolean=True,
        )


admin.site.unregister(TOTPDevice)
