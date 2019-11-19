import json

import factory

from itou.eligibility import models
from itou.users.factories import JobSeekerFactory, PrescriberFactory
from itou.eligibility.forms import EligibilityForm


class EligibilityDiagnosisFactory(factory.django.DjangoModelFactory):
    """Generate an EligibilityDiagnosis() object for unit tests."""

    class Meta:
        model = models.EligibilityDiagnosis

    job_seeker = factory.SubFactory(JobSeekerFactory)
    author = factory.SubFactory(PrescriberFactory)
    author_kind = models.EligibilityDiagnosis.AUTHOR_KIND_PRESCRIBER
