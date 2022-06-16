import factory
from dateutil.relativedelta import relativedelta
from django.utils import timezone

from itou.eligibility.models import AdministrativeCriteria
from itou.institutions.factories import InstitutionFactory
from itou.job_applications.factories import JobApplicationWithApprovalFactory
from itou.siae_evaluations import models
from itou.siaes.factories import SiaeFactory


class EvaluationCampaignFactory(factory.django.DjangoModelFactory):
    class Meta:
        model = models.EvaluationCampaign

    name = factory.fuzzy.FuzzyText(length=10)
    institution = factory.SubFactory(InstitutionFactory, department="14")
    evaluated_period_start_at = (timezone.now() - relativedelta(months=3)).date()
    evaluated_period_end_at = timezone.now().date()


class EvaluatedSiaeFactory(factory.django.DjangoModelFactory):
    class Meta:
        model = models.EvaluatedSiae

    evaluation_campaign = factory.SubFactory(EvaluationCampaignFactory)
    siae = factory.SubFactory(SiaeFactory, department="14")


class EvaluatedJobApplicationFactory(factory.django.DjangoModelFactory):
    class Meta:
        model = models.EvaluatedJobApplication

    evaluated_siae = factory.SubFactory(EvaluatedSiaeFactory)
    job_application = factory.SubFactory(JobApplicationWithApprovalFactory)


class EvaluatedAdministrativeCriteriaFactory(factory.django.DjangoModelFactory):
    class Meta:
        model = models.EvaluatedAdministrativeCriteria

    administrative_criteria = factory.Iterator(AdministrativeCriteria.objects.all())
    proof_url = "https://server.com/rocky-balboa.pdf"
