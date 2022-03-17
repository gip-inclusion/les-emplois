import factory
from dateutil.relativedelta import relativedelta
from django.utils import timezone

from itou.institutions.factories import InstitutionFactory
from itou.siae_evaluations import models


class EvaluationCampaignFactory(factory.django.DjangoModelFactory):
    class Meta:
        model = models.EvaluationCampaign

    name = factory.fuzzy.FuzzyText(length=10)
    institution = factory.SubFactory(InstitutionFactory, department="14")
    evaluated_period_start_at = (timezone.now() - relativedelta(months=3)).date()
    evaluated_period_end_at = timezone.now().date()
