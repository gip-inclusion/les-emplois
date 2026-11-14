import re

import xworkflows
from django.contrib import admin, messages
from django.http import HttpResponseRedirect
from django.urls import reverse
from django.utils.html import format_html
from django.utils.safestring import mark_safe
from django_otp.plugins.otp_totp.models import TOTPDevice

from itou.otp.enums import RESET_REQUEST_TRANSITION_NAMES, ResetRequestTransition
from itou.otp.models import ItouTOTPDevice, ResetRequest, ResetRequestTransitionLog
from itou.utils.admin import ItouModelAdmin, ItouTabularInline, PkSupportRemarkInline, ReadonlyMixin
from itou.utils.perms.middleware import (
    get_active_company_memberships,
    get_active_institution_memberships,
    get_active_prescriber_memberships,
)


@admin.register(ItouTOTPDevice)
class ItouTOTPDeviceAdmin(ReadonlyMixin, ItouModelAdmin):
    list_display = ("user", "enabled", "created_at", "last_used_at")
    list_select_related = ("user",)

    def get_fields(self, request, obj=None):
        fields = super().get_fields(request, obj=obj)
        fields.remove("key")
        fields.insert(0, "created_at")
        return fields

    @admin.display(description="activé", boolean=True)
    def enabled(self, obj):
        return obj.disabled_at is None


class ResetRequestTransitionsInline(ReadonlyMixin, ItouTabularInline):
    model = ResetRequestTransitionLog
    extra = 0
    fields = ("transition_display", "from_state_display", "to_state_display", "timestamp", "user", "msg")
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


HIDDEN_TRANSITIONS = {
    # Only the user can reset devices, not even a superuser:
    ResetRequestTransition.RESET_DEVICES,
}


@admin.register(ResetRequest)
class ResetRequestAdmin(ItouModelAdmin):
    save_on_top = False
    change_form_template = "admin/otp/resetrequest/change_form.html"
    list_display = ("user", "state", "created_at", "updated_at")
    fields = ("user", "structure", "state", "created_at", "updated_at")
    readonly_fields = fields
    inlines = (PkSupportRemarkInline, ResetRequestTransitionsInline)
    list_filter = ["state", "created_at"]
    search_fields = ["user__email", "user__full_name_search_vector"]

    def structure(self, obj):
        links = []

        def org_link(org, admin):
            link = format_html('<a href="{}">{}</a>', reverse(admin, args=(org.pk,)), org.name)
            if hasattr(org, "phone") and org.phone:
                link += format_html(' (<a href="tel:{}">{}</a>)', re.sub(r"\s", "", org.phone), org.phone)
            return link

        for membership in get_active_company_memberships(obj.user):
            links.append(org_link(membership.company, "admin:companies_company_change"))
        for membership in get_active_prescriber_memberships(obj.user):
            links.append(org_link(membership.organization, "admin:prescribers_prescriberorganization_change"))
        for membership in get_active_institution_memberships(obj.user):
            links.append(org_link(membership.institution, "admin:institutions_institution_change"))
        return mark_safe(", ".join(links))

    def response_change(self, request, obj):
        for transition in obj.state.transitions():
            if transition.name not in HIDDEN_TRANSITIONS and f"transition_{transition.name}" in request.POST:
                try:
                    getattr(obj, transition.name)(user=request.user, msg="From /admin/")
                except xworkflows.AbortTransition as e:
                    self.message_user(request, e, messages.ERROR)
                return HttpResponseRedirect(request.get_full_path())

        return super().response_change(request, obj)

    def has_add_permission(self, *args, **kwargs):
        return False

    def has_delete_permission(self, *args, **kwargs):
        return False

    def render_change_form(self, request, context, *, obj=None, **kwargs):
        if obj:
            context.update(
                {
                    "available_transitions": [
                        {"name": transition.name, "label": RESET_REQUEST_TRANSITION_NAMES[transition.name]}
                        for transition in obj.state.transitions()
                        if getattr(obj, transition.name).is_available() and transition.name not in HIDDEN_TRANSITIONS
                    ],
                    "request_is_suspicious": obj.is_suspicious,
                }
            )
        return super().render_change_form(request, context, **kwargs)


admin.site.unregister(TOTPDevice)
