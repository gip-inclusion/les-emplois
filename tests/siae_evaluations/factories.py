import factory
from dateutil.relativedelta import relativedelta
from django.utils import timezone

from itou.eligibility.models import AdministrativeCriteria
from itou.siae_evaluations import models
from tests.companies.factories import SiaeFactory
from tests.files.factories import FileFactory
from tests.institutions.factories import InstitutionFactory
from tests.job_applications.factories import JobApplicationFactory


def before_ended_at(**kwargs):
    def inner(obj):
        date = getattr(obj, "ended_at", None)
        if date is None:
            date = timezone.localdate()
        return date - relativedelta(**kwargs)

    return inner


class CalendarFactory(factory.django.DjangoModelFactory):
    class Meta:
        model = models.Calendar

    adversarial_stage_start = factory.LazyFunction(lambda: timezone.localdate() + relativedelta(weeks=6))
    html = "<span>I'm valid HTML</span>"


class EvaluationCampaignFactory(factory.django.DjangoModelFactory):
    class Meta:
        model = models.EvaluationCampaign

    name = factory.fuzzy.FuzzyText(length=10)
    institution = factory.SubFactory(InstitutionFactory, department="14")
    evaluated_period_start_at = factory.LazyAttribute(before_ended_at(months=3))
    evaluated_period_end_at = factory.LazyAttribute(before_ended_at(months=1))
    calendar = factory.SubFactory(CalendarFactory)


class EvaluatedSiaeFactory(factory.django.DjangoModelFactory):
    class Meta:
        model = models.EvaluatedSiae
        skip_postgeneration_save = True

    class Params:
        complete = factory.Trait(
            evaluation_campaign=factory.SubFactory(
                EvaluationCampaignFactory,
                evaluations_asked_at=factory.LazyFunction(lambda: timezone.now() - relativedelta(weeks=12)),
                ended_at=factory.LazyFunction(lambda: timezone.now() - relativedelta(days=1)),
            ),
            job_app=factory.RelatedFactory(
                "tests.siae_evaluations.factories.EvaluatedJobApplicationFactory",
                factory_related_name="evaluated_siae",
                complete=True,
            ),
            reviewed_at=factory.LazyFunction(timezone.now),
            final_reviewed_at=factory.LazyFunction(timezone.now),
        )

    evaluation_campaign = factory.SubFactory(EvaluationCampaignFactory)
    siae = factory.SubFactory(SiaeFactory, department="14")


class EvaluatedJobApplicationFactory(factory.django.DjangoModelFactory):
    class Meta:
        model = models.EvaluatedJobApplication
        skip_postgeneration_save = True

    class Params:
        complete = factory.Trait(
            criteria=factory.RelatedFactory(
                "tests.siae_evaluations.factories.EvaluatedAdministrativeCriteriaFactory",
                factory_related_name="evaluated_job_application",
                uploaded_at=factory.LazyAttribute(
                    lambda siae: siae.factory_parent.evaluated_siae.evaluation_campaign.evaluations_asked_at
                    + relativedelta(days=10)
                ),
                submitted_at=factory.LazyAttribute(
                    lambda siae: siae.factory_parent.evaluated_siae.evaluation_campaign.evaluations_asked_at
                    + relativedelta(days=15)
                ),
            )
        )

    evaluated_siae = factory.SubFactory(EvaluatedSiaeFactory)
    job_application = factory.SubFactory(
        JobApplicationFactory,
        to_siae=factory.SelfAttribute("..evaluated_siae.siae"),
        with_approval=True,
    )


class EvaluatedAdministrativeCriteriaFactory(factory.django.DjangoModelFactory):
    class Meta:
        model = models.EvaluatedAdministrativeCriteria

    administrative_criteria = factory.Iterator(AdministrativeCriteria.objects.all())
    proof = factory.SubFactory(FileFactory)
