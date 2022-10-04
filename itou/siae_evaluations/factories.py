import factory
from dateutil.relativedelta import relativedelta
from django.utils import timezone

from itou.eligibility.models import AdministrativeCriteria
from itou.institutions.factories import InstitutionFactory
from itou.job_applications.factories import JobApplicationWithApprovalFactory
from itou.siae_evaluations import enums as evaluation_enums, models
from itou.siaes.factories import SiaeFactory


def before_ended_at(**kwargs):
    def inner(obj):
        date = getattr(obj, "ended_at", None)
        if date is None:
            date = timezone.localdate()
        return date - relativedelta(**kwargs)

    return inner


class EvaluationCampaignFactory(factory.django.DjangoModelFactory):
    class Meta:
        model = models.EvaluationCampaign

    name = factory.fuzzy.FuzzyText(length=10)
    institution = factory.SubFactory(InstitutionFactory, department="14")
    evaluated_period_start_at = factory.LazyAttribute(before_ended_at(months=3))
    evaluated_period_end_at = factory.LazyAttribute(before_ended_at(months=1))


class EvaluatedSiaeFactory(factory.django.DjangoModelFactory):
    class Meta:
        model = models.EvaluatedSiae

    class Params:
        accepted = factory.Trait(
            evaluation_campaign=factory.SubFactory(
                EvaluationCampaignFactory,
                evaluations_asked_at=factory.LazyFunction(lambda: timezone.now() - relativedelta(weeks=12)),
                ended_at=factory.LazyFunction(lambda: timezone.now() - relativedelta(days=1)),
            ),
            job_app=factory.RelatedFactory(
                "itou.siae_evaluations.factories.EvaluatedJobApplicationFactory",
                factory_related_name="evaluated_siae",
                accepted=True,
            ),
            reviewed_at=factory.LazyFunction(timezone.now),
            final_reviewed_at=factory.LazyFunction(timezone.now),
        )

    evaluation_campaign = factory.SubFactory(EvaluationCampaignFactory)
    siae = factory.SubFactory(SiaeFactory, department="14")


class EvaluatedJobApplicationFactory(factory.django.DjangoModelFactory):
    class Meta:
        model = models.EvaluatedJobApplication

    class Params:
        accepted = factory.Trait(
            criteria=factory.RelatedFactory(
                "itou.siae_evaluations.factories.EvaluatedAdministrativeCriteriaFactory",
                factory_related_name="evaluated_job_application",
                uploaded_at=factory.LazyAttribute(
                    lambda siae: siae.factory_parent.evaluated_siae.evaluation_campaign.ended_at
                    - relativedelta(days=10)
                ),
                submitted_at=factory.LazyAttribute(
                    lambda siae: siae.factory_parent.evaluated_siae.evaluation_campaign.ended_at
                    - relativedelta(days=5)
                ),
                review_state=evaluation_enums.EvaluatedAdministrativeCriteriaState.ACCEPTED,
            )
        )

    evaluated_siae = factory.SubFactory(EvaluatedSiaeFactory)
    job_application = factory.SubFactory(JobApplicationWithApprovalFactory)


class EvaluatedAdministrativeCriteriaFactory(factory.django.DjangoModelFactory):
    class Meta:
        model = models.EvaluatedAdministrativeCriteria

    administrative_criteria = factory.Iterator(AdministrativeCriteria.objects.all())
    proof_url = "https://server.com/rocky-balboa.pdf"
