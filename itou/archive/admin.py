from django.contrib import admin

from itou.archive import models
from itou.utils.admin import ItouModelAdmin


@admin.register(models.ArchivedJobSeeker)
class ArchiveJobSeekerAdmin(ItouModelAdmin):
    class Media:
        css = {"all": ("css/itou-admin.css",)}

    fields = (
        "date_joined",
        "first_login",
        "last_login",
        "archived_at",
        "user_signup_kind",
        "department",
        "title",
        "identity_provider",
        "had_pole_emploi_id",
        "had_nir",
        "lack_of_nir_reason",
        "nir_sex",
        "nir_year",
        "birth_year",
    )

    readonly_fields = fields
