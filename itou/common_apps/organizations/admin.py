from django.contrib import admin, messages
from django.db.models import Count

from itou.utils.admin import ItouModelAdmin, ItouTabularInline


class MembersInline(ItouTabularInline):
    # Remember to specify the model in child class. Example:
    # model = models.Siae.members.through
    extra = 1
    raw_id_fields = ("user",)
    readonly_fields = ("is_active", "created_at", "updated_at", "updated_by", "joined_at")


class HasMembersFilter(admin.SimpleListFilter):
    title = "A des membres"
    parameter_name = "has_members"

    def lookups(self, request, model_admin):
        return (("yes", "Oui"), ("no", "Non"))

    def queryset(self, request, queryset):
        value = self.value()
        if value == "yes":
            return queryset.filter(_member_count__gt=0)
        if value == "no":
            return queryset.exclude(_member_count__gt=0)
        return queryset


class OrganizationAdmin(ItouModelAdmin):
    @admin.display(ordering="_member_count")
    def member_count(self, obj):
        return obj._member_count

    def get_queryset(self, request):
        return super().get_queryset(request).annotate(_member_count=Count("members", distinct=True))

    def save_related(self, request, form, formsets, change):
        had_admin = change and form.instance.active_admin_members.exists()
        super().save_related(request, form, formsets, change)
        if had_admin:
            active_memberships = form.instance.memberships.all()
            if active_memberships and not any(membership.is_admin for membership in active_memberships):
                messages.warning(
                    request,
                    (
                        "Vous venez de supprimer le dernier administrateur de la structure. "
                        "Les membres restants risquent de solliciter le support."
                    ),
                )
