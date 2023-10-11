from django.utils import timezone

from itou.www.siae_evaluations_views.forms import LaborExplanationForm
from tests.siae_evaluations.factories import EvaluatedJobApplicationFactory
from tests.utils.test import TestCase


class LaborExplanationFormTests(TestCase):
    def test_campaign_is_ended(self):
        evaluated_job_application = EvaluatedJobApplicationFactory(
            evaluated_siae__evaluation_campaign__ended_at=timezone.now()
        )
        form = LaborExplanationForm(instance=evaluated_job_application)

        assert form.fields["labor_inspector_explanation"].disabled
