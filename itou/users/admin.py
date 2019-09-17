from django.contrib import admin
from django.contrib.auth.admin import UserAdmin
from django.utils.translation import ugettext as _

from itou.users import models


class KindFilter(admin.SimpleListFilter):
    title = _("Type")
    parameter_name = "kind"

    def lookups(self, request, model_admin):
        return (
            ("is_job_seeker", _("Demandeur d'emploi")),
            ("is_prescriber", _("Prescripteur")),
            ("is_siae_staff", _("SIAE")),
        )

    def queryset(self, request, queryset):
        value = self.value()
        if value == "is_job_seeker":
            queryset = queryset.filter(is_job_seeker=True)
        elif value == "is_prescriber":
            queryset = queryset.filter(is_prescriber=True)
        elif value == "is_siae_staff":
            queryset = queryset.filter(is_siae_staff=True)
        return queryset


@admin.register(models.User)
class ItouUserAdmin(UserAdmin):

    list_filter = UserAdmin.list_filter + (KindFilter,)

    fieldsets = UserAdmin.fieldsets + (
        (
            _("Informations"),
            {
                "fields": (
                    "birthdate",
                    "phone",
                    "is_job_seeker",
                    "is_prescriber",
                    "is_siae_staff",
                )
            },
        ),
    )
