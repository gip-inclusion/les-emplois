from django.test import TestCase

from itou.www.siae_evaluations_views.forms import SubmitEvaluatedAdministrativeCriteriaProofForm


class SubmitEvaluatedAdministrativeCriteriaProofFormFormTests(TestCase):
    def test_url_wo_correct_endpoint(self):
        form = SubmitEvaluatedAdministrativeCriteriaProofForm(data={"proof_url": "https://bad.com/rocky-balboa.pdf"})

        self.assertEqual(
            form.errors["proof_url"], ["Le document sélectionné ne provient pas d'une source de confiance."]
        )
