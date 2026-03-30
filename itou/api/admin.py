from django.contrib import admin
from rest_framework.authtoken.admin import TokenAdmin

from itou.api.models import CompanyToken, DepartmentToken, ServiceToken
from itou.utils.admin import ItouModelAdmin


# Patching TokenAdmin for all sub-APIs
# Avoids listing all users when updating auth token via admin
# See: https://www.django-rest-framework.org/api-guide/authentication/#tokenauthentication
TokenAdmin.raw_id_fields = ("user",)


@admin.register(CompanyToken)
class CompanyTokenAdmin(ItouModelAdmin):
    list_display = ["label", "created_at"]
    ordering = ["-created_at"]
    readonly_fields = ["key", "created_at"]
    autocomplete_fields = ["companies"]

    def get_fieldsets(self, request, obj=None):
        if obj is None:
            return (
                (
                    None,
                    {
                        "classes": ("wide",),
                        "fields": (
                            "label",
                            "companies",
                        ),
                    },
                ),
            )
        else:
            return super().get_fieldsets(request, obj=obj)


@admin.register(DepartmentToken)
class DepartmentTokenAdmin(ItouModelAdmin):
    list_display = ["label", "department", "created_at"]
    ordering = ["-created_at"]
    readonly_fields = ["key", "created_at"]
    list_filter = ["department"]

    def get_readonly_fields(self, request, obj=None):
        if obj:
            return ["department"] + self.readonly_fields
        return self.readonly_fields

    def get_fieldsets(self, request, obj=None):
        if obj is None:
            return (
                (
                    None,
                    {
                        "classes": ("wide",),
                        "fields": (
                            "label",
                            "department",
                        ),
                    },
                ),
            )
        else:
            return super().get_fieldsets(request, obj=obj)


@admin.register(ServiceToken)
class ServiceTokenAdmin(ItouModelAdmin):
    list_display = ["service", "created_at"]
    ordering = ["-created_at"]
    readonly_fields = ["key", "created_at"]

    def get_fieldsets(self, request, obj=None):
        if obj is None:
            return (
                (
                    None,
                    {
                        "classes": ("wide",),
                        "fields": (
                            "service",
                            "purpose",
                        ),
                    },
                ),
            )
        else:
            return super().get_fieldsets(request, obj=obj)
