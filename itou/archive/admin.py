from django.contrib import admin

from itou.archive import models
from itou.utils.admin import ItouModelAdmin, ReadonlyMixin


@admin.register(models.AnonymizedProfessional)
class AnonymizedProfessionalAdmin(ReadonlyMixin, ItouModelAdmin):
    pass


@admin.register(models.AnonymizedJobSeeker)
class AnonymizedJobSeekerAdmin(ReadonlyMixin, ItouModelAdmin):
    pass


@admin.register(models.AnonymizedApplication)
class AnonymizedApplicationAdmin(ReadonlyMixin, ItouModelAdmin):
    pass


@admin.register(models.AnonymizedApproval)
class AnonymizedApprovalAdmin(ReadonlyMixin, ItouModelAdmin):
    pass


@admin.register(models.AnonymizedSIAEEligibilityDiagnosis)
class AnonymizedSIAEEligibilityDiagnosisAdmin(ReadonlyMixin, ItouModelAdmin):
    pass


@admin.register(models.AnonymizedGEIQEligibilityDiagnosis)
class AnonymizedGEIQEligibilityDiagnosisAdmin(ReadonlyMixin, ItouModelAdmin):
    pass
