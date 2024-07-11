from django.contrib import admin

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
    raw_id_fields = ["follow_up_group"]
    readonly_fields = ["member", "creator", "created_at", "updated_at", "ended_at", "created_in_bulk"]
    ordering = ["-created_at"]


@admin.register(models.FollowUpGroup)
class FollowUpGroupAdmin(ItouModelAdmin):
    list_display = ("created_at", "updated_at", "beneficiary", "display_members")
    readonly_fields = [
        "created_in_bulk",
    ]
    list_filter = ("created_in_bulk",)

    raw_id_fields = [
        "beneficiary",
    ]

    inlines = (MemberInline,)

    @admin.display(description="Membres du groupe de suivi")
    def display_members(self, obj):
        return ", ".join([m.get_full_name() for m in obj.members.all()])
