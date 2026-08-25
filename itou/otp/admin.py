import xworkflows
from django.contrib import admin
from django.contrib.admin.utils import display_for_value
from django.http import HttpResponseForbidden, HttpResponseRedirect
from django.urls import path, reverse
from django_otp.plugins.otp_totp.models import TOTPDevice

from itou.otp.models import Itou2FAResetRequest, ItouTOTPDevice
from itou.utils.admin import ItouModelAdmin, PkSupportRemarkInline, ReadonlyMixin


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


@admin.register(Itou2FAResetRequest)
class Itou2FAResetRequestAdmin(ItouModelAdmin):
    save_on_top = False
    change_form_template = "admin/otp/change_form.html"
    list_display = ("user", "state", "created_at", "updated_at")
    readonly_fields = ("user", "state")
    inlines = (PkSupportRemarkInline,)

    def accept_reset_request(self, request, pk):
        obj = Itou2FAResetRequest.objects.get(pk=pk)
        try:
            obj.accept(user=request.user)
        except xworkflows.ForbiddenTransition:
            return HttpResponseForbidden()
        return HttpResponseRedirect(reverse("admin:otp_itou2faresetrequest_changelist"))

    def deny_reset_request(self, request, pk):
        obj = Itou2FAResetRequest.objects.get(pk=pk)
        try:
            obj.deny(user=request.user)
        except xworkflows.ForbiddenTransition:
            return HttpResponseForbidden()
        return HttpResponseRedirect(reverse("admin:otp_itou2faresetrequest_changelist"))

    def get_urls(self):
        return [
            path(
                "accept-2fa-reset-request/<int:pk>",
                self.admin_site.admin_view(self.accept_reset_request),
                name="2fa_reset_request_accept",
            ),
            path(
                "deny-2fa-reset-request/<int:pk>",
                self.admin_site.admin_view(self.deny_reset_request),
                name="2fa_reset_request_deny",
            ),
        ] + super().get_urls()


admin.site.unregister(TOTPDevice)
