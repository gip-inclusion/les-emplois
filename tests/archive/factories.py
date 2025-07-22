import factory
from django.utils import timezone

from itou.archive import models


class AnonymizedApplicationFactory(factory.django.DjangoModelFactory):
    class Meta:
        model = models.AnonymizedApplication

    applied_at = timezone.localdate()


class AnonymizedApprovalFactory(factory.django.DjangoModelFactory):
    class Meta:
        model = models.AnonymizedApproval

    start_at = timezone.localdate()


class AnonymizedCancelledApprovalFactory(factory.django.DjangoModelFactory):
    class Meta:
        model = models.AnonymizedCancelledApproval


class AnonymizedSIAEEligibilityDiagnosisFactory(factory.django.DjangoModelFactory):
    class Meta:
        model = models.AnonymizedSIAEEligibilityDiagnosis

    created_at = timezone.localdate()


class AnonymizedGEIQEligibilityDiagnosisFactory(factory.django.DjangoModelFactory):
    class Meta:
        model = models.AnonymizedGEIQEligibilityDiagnosis

    created_at = timezone.localdate()


class AnonymizedJobSeekerFactory(factory.django.DjangoModelFactory):
    class Meta:
        model = models.AnonymizedJobSeeker

    date_joined = timezone.localdate()


class AnonymizedProfessionalFactory(factory.django.DjangoModelFactory):
    class Meta:
        model = models.AnonymizedProfessional

    date_joined = timezone.localdate()
