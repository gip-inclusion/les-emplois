import xworkflows
from django.contrib import admin, messages
from django.contrib.admin.utils import display_for_value
from django.http import HttpResponseRedirect
from django_otp.plugins.otp_totp.models import TOTPDevice

from itou.otp.enums import RESET_REQUEST_TRANSITION_NAMES, ResetRequestTransition
from itou.otp.models import Itou2FAResetRequest, Itou2FAResetRequestTransitionLog, ItouTOTPDevice
from itou.utils.admin import ItouModelAdmin, ItouTabularInline, PkSupportRemarkInline, ReadonlyMixin


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


class Itou2FAResetRequestTransitionsInline(ReadonlyMixin, ItouTabularInline):
    model = Itou2FAResetRequestTransitionLog
    extra = 0
    fields = ("transition_display", "from_state_display", "to_state_display", "timestamp", "user")
    readonly_fields = fields

    @admin.display(description="transition")
    def transition_display(self, obj):
        return RESET_REQUEST_TRANSITION_NAMES[obj.transition]

    @admin.display(description="statut initial")
    def from_state_display(self, obj):
        return obj.get_modified_object().state.workflow.states[obj.from_state].title

    @admin.display(description="statut final")
    def to_state_display(self, obj):
        return obj.get_modified_object().state.workflow.states[obj.to_state].title


@admin.register(Itou2FAResetRequest)
class Itou2FAResetRequestAdmin(ItouModelAdmin):
    save_on_top = False
    change_form_template = "admin/otp/change_form.html"
    list_display = ("user", "state", "created_at", "updated_at")
    fields = ("user", "state", "created_at", "updated_at")
    readonly_fields = fields
    inlines = (PkSupportRemarkInline, Itou2FAResetRequestTransitionsInline)

    def response_change(self, request, obj):
        for transition in obj.state.transitions():
            if f"transition_{transition.name}" in request.POST:
                try:
                    getattr(obj, transition.name)(actor=request.user, msg="From /admin/")
                except xworkflows.AbortTransition as e:
                    self.message_user(request, e, messages.ERROR)
                return HttpResponseRedirect(request.get_full_path())

        return super().response_change(request, obj)

    def has_add_permission(self, *args, **kwargs):
        return False

    def render_change_form(self, request, context, *, obj=None, **kwargs):
        if obj:
            hidden_transitions = {
                # Only the user can reset divices, not even a superuser:
                ResetRequestTransition.RESET_DEVICES,
            }

            context.update(
                {
                    "available_transitions": [
                        {"name": transition.name, "label": RESET_REQUEST_TRANSITION_NAMES[transition.name]}
                        for transition in obj.state.transitions()
                        if getattr(obj, transition.name).is_available() and transition.name not in hidden_transitions
                    ]
                }
            )
        return super().render_change_form(request, context, **kwargs)


admin.site.unregister(TOTPDevice)
