from django.test import TestCase
from django.utils import timezone

from itou.siae_evaluations.factories import EvaluatedJobApplicationFactory
from itou.www.siae_evaluations_views.forms import LaborExplanationForm, SubmitEvaluatedAdministrativeCriteriaProofForm


class SubmitEvaluatedAdministrativeCriteriaProofFormFormTests(TestCase):
    def test_url_wo_correct_endpoint(self):
        form = SubmitEvaluatedAdministrativeCriteriaProofForm(data={"proof_url": "https://bad.com/rocky-balboa.pdf"})

        self.assertEqual(
            form.errors["proof_url"], ["Le document sélectionné ne provient pas d'une source de confiance."]
        )


class LaborExplanationFormTests(TestCase):
    def test_campaign_is_ended(self):
        evaluated_job_application = EvaluatedJobApplicationFactory(
            evaluated_siae__evaluation_campaign__ended_at=timezone.now()
        )
        form = LaborExplanationForm(instance=evaluated_job_application)

        self.assertTrue(form.fields["labor_inspector_explanation"].disabled)
