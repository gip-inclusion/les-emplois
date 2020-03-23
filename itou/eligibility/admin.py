from django.contrib import admin

from itou.eligibility import models


class AdministrativeCriteriaLevel1Inline(admin.StackedInline):
    model = models.AdministrativeCriteriaLevel1
    extra = 0
    show_change_link = True
    can_delete = False

    def has_change_permission(self, request, obj=None):
        return False

    def has_add_permission(self, request, obj=None):
        return False


class AdministrativeCriteriaLevel2Inline(admin.StackedInline):
    model = models.AdministrativeCriteriaLevel2
    extra = 0
    show_change_link = True
    can_delete = False

    def has_change_permission(self, request, obj=None):
        return False

    def has_add_permission(self, request, obj=None):
        return False


@admin.register(models.EligibilityDiagnosis)
class EligibilityAdmin(admin.ModelAdmin):
    list_display = ("id", "job_seeker", "author", "author_kind", "created_at")
    list_display_links = ("id", "job_seeker")
    list_filter = ("author_kind",)
    raw_id_fields = ("job_seeker", "author", "author_siae", "author_prescriber_organization")
    readonly_fields = ("created_at", "updated_at")
    search_fields = ("job_seeker__email", "author__email")
    inlines = (AdministrativeCriteriaLevel1Inline, AdministrativeCriteriaLevel2Inline)
