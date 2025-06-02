from dateutil.relativedelta import relativedelta
from django.utils import timezone

from itou.eligibility.enums import (
    AdministrativeCriteriaLevel,
)
from itou.eligibility.models import AdministrativeCriteria, EligibilityDiagnosis
from itou.www.siae_evaluations_views.forms import AdministrativeCriteriaEvaluationForm, LaborExplanationForm
from tests.companies.factories import CompanyFactory
from tests.job_applications.factories import JobApplicationFactory
from tests.siae_evaluations.factories import EvaluatedJobApplicationFactory
from tests.users.factories import JobSeekerFactory


class TestLaborExplanationForm:
    def test_campaign_is_ended(self):
        evaluated_job_application = EvaluatedJobApplicationFactory(
            evaluated_siae__evaluation_campaign__ended_at=timezone.now()
        )
        form = LaborExplanationForm(instance=evaluated_job_application)

        assert form.fields["labor_inspector_explanation"].disabled


class TestAdministrativeCriteriaEvaluationForm:
    def test_job_application(self):
        company = CompanyFactory(with_membership=True)
        user = company.members.first()

        job_seeker = JobSeekerFactory()

        eligibility_diagnosis = EligibilityDiagnosis.create_diagnosis(
            job_seeker,
            author=user,
            author_organization=company,
            administrative_criteria=[
                AdministrativeCriteria.objects.filter(level=AdministrativeCriteriaLevel.LEVEL_1).first()
            ]
            + [AdministrativeCriteria.objects.filter(level=AdministrativeCriteriaLevel.LEVEL_2).first()],
        )

        job_application = JobApplicationFactory(
            with_approval=True,
            to_company=company,
            sender_company=company,
            eligibility_diagnosis=eligibility_diagnosis,
            hiring_start_at=timezone.localdate() - relativedelta(months=2),
        )

        form = AdministrativeCriteriaEvaluationForm(
            company,
            job_application.eligibility_diagnosis.selected_administrative_criteria.select_related(
                "administrative_criteria"
            ),
        )

        assert 2 == len(form.fields)
        assert (
            AdministrativeCriteria.objects.filter(level=AdministrativeCriteriaLevel.LEVEL_1).first().key
            in form.fields.keys()
        )
        assert (
            AdministrativeCriteria.objects.filter(level=AdministrativeCriteriaLevel.LEVEL_2).first().key
            in form.fields.keys()
        )
