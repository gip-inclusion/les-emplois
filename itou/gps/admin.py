from django.contrib import admin
from django.utils import timezone

import itou.gps.models as models

from ..utils.admin import ItouModelAdmin


class MemberInline(admin.TabularInline):
    model = models.FollowUpGroup.members.through
    extra = 0
    can_delete = False
    readonly_fields = [
        "is_active",
        "ended_at",
        "is_referent",
        "member",
        "updated_at",
        "created_in_bulk",
        "created_at",
        "creator",
    ]

    show_change_link = True

    def has_change_permission(self, request, obj=None):
        return False

    def has_add_permission(self, request, obj=None):
        return False


@admin.register(models.FollowUpGroupMembership)
class FollowUpGroupMembershipAdmin(ItouModelAdmin):
    list_display = ("created_at", "updated_at", "member", "follow_up_group", "is_referent")
    list_filter = (
        "is_referent",
        "created_in_bulk",
    )
    raw_id_fields = ("follow_up_group", "member")
    readonly_fields = ("creator", "created_at", "updated_at", "ended_at", "created_in_bulk")
    ordering = ["-created_at"]

    def get_readonly_fields(self, request, obj=None):
        if obj:
            return ("follow_up_group", "member") + self.readonly_fields
        return self.readonly_fields

    def lookup_allowed(self, lookup, value, request):
        if lookup in ["follow_up_group__beneficiary"]:
            return True
        return super().lookup_allowed(lookup, value)

    def save_model(self, request, obj, form, change):
        if not change:
            obj.creator = request.user

        else:
            if not form.cleaned_data["is_active"] and form.initial["is_active"]:
                obj.ended_at = timezone.now()

        super().save_model(request, obj, form, change)


@admin.register(models.FollowUpGroup)
class FollowUpGroupAdmin(ItouModelAdmin):
    list_display = ("created_at", "updated_at", "beneficiary", "beneficiary_department", "display_members")
    readonly_fields = [
        "created_in_bulk",
    ]
    list_filter = ("created_in_bulk", "beneficiary__department")
    search_fields = ("beneficiary__first_name", "beneficiary__last_name", "beneficiary__email")

    raw_id_fields = [
        "beneficiary",
    ]

    inlines = (MemberInline,)

    def lookup_allowed(self, lookup, value, request):
        if lookup in ["memberships__member"]:
            return True
        return super().lookup_allowed(lookup, value)

    @admin.display(description="Département")
    def beneficiary_department(self, obj):
        return obj.beneficiary.department

    @admin.display(description="Membres du groupe de suivi")
    def display_members(self, obj):
        return ", ".join([m.get_full_name() for m in obj.members.all()])
