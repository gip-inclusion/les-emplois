from django.contrib import admin

import itou.gps.models as models

from ..utils.admin import ItouModelAdmin


class MemberInline(admin.TabularInline):
    model = models.FollowUpGroup.members.through

    fields = ["is_referent", "is_active", "member", "creator"]

    readonly_fields = ["creator"]


@admin.register(models.FollowUpGroup)
class FollowUpGroupAdmin(ItouModelAdmin):
    list_display = ("pk", "created_at", "updated_at", "beneficiary", "display_members")

    fields = ["beneficiary"]

    inlines = (MemberInline,)

    @admin.display(description="Membres du groupe de suivi")
    def display_members(self, obj):
        return ", ".join([m.get_full_name() for m in obj.members.all()])
