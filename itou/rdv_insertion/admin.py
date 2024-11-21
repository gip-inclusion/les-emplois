import json

from django.contrib import admin
from django.db.models import Count
from django.utils.html import format_html

from itou.utils.admin import ItouModelAdmin, ItouTabularInline, ReadonlyMixin
from itou.utils.templatetags.str_filters import pluralizefr

from . import models


class InvitationInline(ItouTabularInline):
    model = models.Invitation
    extra = 0
    can_delete = False
    readonly_fields = ("type", "status", "delivered_at")
    fields = readonly_fields


@admin.register(models.InvitationRequest)
class InvitationRequestAdmin(ReadonlyMixin, ItouModelAdmin):
    list_display = (
        "reason_category",
        "job_seeker",
        "company",
        "created_at",
    )
    list_select_related = ("job_seeker", "company")
    list_display_links = ("reason_category",)
    list_filter = ("reason_category",)
    inlines = (InvitationInline,)


class ParticipationInline(ItouTabularInline):
    model = models.Participation
    extra = 0
    can_delete = False
    readonly_fields = ("job_seeker", "status", "rdv_insertion_id")


@admin.register(models.Appointment)
class AppointmentAdmin(ReadonlyMixin, ItouModelAdmin):
    list_display = (
        "company",
        "participant_info",
        "reason_category",
        "is_collective",
        "status",
        "start_at",
        "duration",
    )
    list_select_related = ("company",)
    list_display_links = ("company",)
    list_filter = ("status", "reason_category", "is_collective", "start_at")
    inlines = (ParticipationInline,)
    readonly_fields = (
        "pk",
        "company",
        "location",
        "status",
        "reason_category",
        "reason",
        "is_collective",
        "start_at",
        "duration",
        "canceled_at",
        "address",
        "total_participants",
        "max_participants",
        "rdv_insertion_id",
    )

    def get_queryset(self, request):
        return (
            super()
            .get_queryset(request)
            .annotate(num_participants=Count("participants"))
            .prefetch_related("participants")
        )

    @admin.display(description="Participant(s)")
    def participant_info(self, obj):
        if obj.is_collective:
            return f"{obj.num_participants} participant{pluralizefr(obj.num_participants)}"
        try:
            return list(obj.participants.all())[0].get_full_name()
        except IndexError:
            return self.get_empty_value_display()


@admin.register(models.WebhookEvent)
class WebhookEventAdmin(ReadonlyMixin, ItouModelAdmin):
    list_display = ("created_at", "is_processed", "is_for_appointment", "is_for_invitation")
    list_display_links = ("created_at",)
    list_filter = ("created_at", "is_processed")
    readonly_fields = (
        "pk",
        "created_at",
        "formatted_headers",
        "formatted_body",
        "is_processed",
    )

    @admin.display(boolean=True, description="RDV ?")
    def is_for_appointment(self, obj):
        return obj.for_appointment

    @admin.display(boolean=True, description="Invitation ?")
    def is_for_invitation(self, obj):
        return obj.for_invitation

    @admin.display(description="Headers")
    def formatted_headers(self, obj):
        return format_html("<pre>{}</pre>", json.dumps(obj.headers, indent=4))

    @admin.display(description="Body")
    def formatted_body(self, obj):
        return format_html("<pre>{}</pre>", json.dumps(obj.body, indent=4))
