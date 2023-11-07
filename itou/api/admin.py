from django.contrib import admin
from rest_framework.authtoken.admin import TokenAdmin

from ..utils.admin import ItouModelAdmin
from .models import CompanyApiToken


# Patching TokenAdmin for all sub-APIs
# Avoids listing all users when updating auth token via admin
# See: https://www.django-rest-framework.org/api-guide/authentication/#tokenauthentication
TokenAdmin.raw_id_fields = ("user",)


@admin.register(CompanyApiToken)
class CompanyApiTokenAdmin(ItouModelAdmin):
    list_display = ["key", "label", "created_at"]
    ordering = ["-created_at"]
    read_only_fields = ["key", "created_at"]
    autocomplete_fields = ["siaes"]
