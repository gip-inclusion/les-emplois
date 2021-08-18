from django.contrib import admin
from django.db.models import Count


class MembersInline(admin.TabularInline):
    # Remember to specify the model in child class.
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


class OrganizationAdmin(admin.ModelAdmin):
    def member_count(self, obj):
        return obj._member_count

    member_count.admin_order_field = "_member_count"

    def get_queryset(self, request):
        queryset = super().get_queryset(request)
        queryset = queryset.annotate(_member_count=Count("members", distinct=True))
        return queryset
