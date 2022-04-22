from dateutil.relativedelta import relativedelta
from django.test import TestCase
from django.urls import reverse
from django.utils import dateformat, timezone

from itou.eligibility.models import AdministrativeCriteria, EligibilityDiagnosis
from itou.institutions.factories import InstitutionMembershipFactory
from itou.job_applications.factories import JobApplicationWithApprovalFactory
from itou.siae_evaluations import enums as evaluation_enums
from itou.siae_evaluations.factories import (
    EvaluatedJobApplicationFactory,
    EvaluatedSiaeFactory,
    EvaluationCampaignFactory,
)
from itou.siae_evaluations.models import EvaluatedEligibilityDiagnosis, EvaluationCampaign
from itou.siaes.factories import SiaeMembershipFactory
from itou.users.factories import DEFAULT_PASSWORD, JobSeekerFactory
from itou.utils.perms.user import KIND_SIAE_STAFF, UserInfo
from itou.www.siae_evaluations_views.forms import SetChosenPercentForm


def create_evaluated_siae_with_consistent_datas(siae, user, level_1=True, level_2=False):
    job_seeker = JobSeekerFactory()

    user_info = UserInfo(
        user=user, kind=KIND_SIAE_STAFF, siae=siae, prescriber_organization=None, is_authorized_prescriber=False
    )

    eligibility_diagnosis = EligibilityDiagnosis.create_diagnosis(
        job_seeker,
        user_info,
        administrative_criteria=list(
            AdministrativeCriteria.objects.filter(
                level__in=[AdministrativeCriteria.Level.LEVEL_1 if level_1 else None]
                + [AdministrativeCriteria.Level.LEVEL_2 if level_2 else None]
            )
        ),
    )

    job_application = JobApplicationWithApprovalFactory(
        to_siae=siae,
        sender_siae=siae,
        eligibility_diagnosis=eligibility_diagnosis,
        hiring_start_at=timezone.now() - relativedelta(months=2),
    )

    evaluated_siae = EvaluatedSiaeFactory(evaluation_campaign__evaluations_asked_at=timezone.now(), siae=siae)
    evaluated_job_application = EvaluatedJobApplicationFactory(
        job_application=job_application, evaluated_siae=evaluated_siae
    )

    return evaluated_job_application


def create_evaluated_eligibility_diagnosis_from_evaluated_job_application(evaluated_job_application, level):
    administrative_criteria = (
        evaluated_job_application.job_application.eligibility_diagnosis.selectedadministrativecriteria_set.all()
    )
    return EvaluatedEligibilityDiagnosis.objects.bulk_create(
        [
            EvaluatedEligibilityDiagnosis(
                evaluated_job_application=evaluated_job_application,
                administrative_criteria=sel_adm.administrative_criteria,
            )
            for sel_adm in administrative_criteria
            if sel_adm.administrative_criteria.level == level
        ]
    )


class SamplesSelectionViewTest(TestCase):
    def setUp(self):
        membership = InstitutionMembershipFactory()
        self.user = membership.user
        self.institution = membership.institution
        self.url = reverse("siae_evaluations_views:samples_selection")

    def test_access(self):

        response = self.client.get(self.url)
        self.assertEqual(response.status_code, 302)

        # institution without active campaign
        self.client.login(username=self.user.email, password=DEFAULT_PASSWORD)
        response = self.client.get(self.url)
        self.assertEqual(response.status_code, 200)
        self.assertContains(response, "Vous n'avez pas de contrôle en cours.")

        # institution with active campaign to select
        evaluation_campaign = EvaluationCampaignFactory(institution=self.institution)
        response = self.client.get(self.url)
        self.assertContains(response, "Sélection des salariés à contrôler")

        # institution with active campaign selected
        evaluation_campaign.percent_set_at = timezone.now()
        evaluation_campaign.save()
        response = self.client.get(self.url)
        self.assertContains(
            response, "Vous serez notifié lorsque l'étape de transmission des pièces justificatives commencera."
        )

        # institution with ended campaign
        evaluation_campaign.percent_set_at = timezone.now()
        evaluation_campaign.ended_at = timezone.now()
        evaluation_campaign.save()
        response = self.client.get(self.url)
        self.assertContains(response, "Vous n'avez pas de contrôle en cours.")

    def test_content(self):
        evaluation_campaign = EvaluationCampaignFactory(institution=self.institution)
        back_url = reverse("dashboard:index")

        self.client.login(username=self.user.email, password=DEFAULT_PASSWORD)
        response = self.client.get(self.url)

        self.assertEqual(response.context["institution"], self.institution)
        self.assertEqual(response.context["evaluation_campaign"], evaluation_campaign)
        self.assertEqual(response.context["back_url"], back_url)

    def test_form(self):
        evaluation_campaign = EvaluationCampaignFactory(institution=self.institution)

        form_data = {"chosen_percent": evaluation_enums.EvaluationChosenPercent.DEFAULT}
        form = SetChosenPercentForm(instance=evaluation_campaign, data=form_data)
        self.assertTrue(form.is_valid())

        form_data = {"chosen_percent": evaluation_enums.EvaluationChosenPercent.MIN}
        form = SetChosenPercentForm(instance=evaluation_campaign, data=form_data)
        self.assertTrue(form.is_valid())

        form_data = {"chosen_percent": evaluation_enums.EvaluationChosenPercent.MIN - 1}
        form = SetChosenPercentForm(instance=evaluation_campaign, data=form_data)
        self.assertFalse(form.is_valid())
        self.assertEqual(
            form.errors["chosen_percent"], ["Assurez-vous que cette valeur est supérieure ou égale à 20."]
        )

        form_data = {"chosen_percent": evaluation_enums.EvaluationChosenPercent.MAX}
        form = SetChosenPercentForm(instance=evaluation_campaign, data=form_data)
        self.assertTrue(form.is_valid())

        form_data = {"chosen_percent": evaluation_enums.EvaluationChosenPercent.MAX + 1}
        form = SetChosenPercentForm(instance=evaluation_campaign, data=form_data)
        self.assertFalse(form.is_valid())
        self.assertEqual(
            form.errors["chosen_percent"], ["Assurez-vous que cette valeur est inférieure ou égale à 40."]
        )

    def test_post_form(self):
        evaluation_campaign = EvaluationCampaignFactory(institution=self.institution)

        self.client.login(username=self.user.email, password=DEFAULT_PASSWORD)
        response = self.client.get(self.url)

        post_data = {"chosen_percent": evaluation_enums.EvaluationChosenPercent.MIN}
        response = self.client.post(self.url, data=post_data)
        self.assertEqual(response.status_code, 302)

        updated_evaluation_campaign = EvaluationCampaign.objects.get(pk=evaluation_campaign.pk)
        self.assertIsNotNone(updated_evaluation_campaign.percent_set_at)
        self.assertEqual(updated_evaluation_campaign.chosen_percent, post_data["chosen_percent"])


class SiaeJobApplicationListViewTest(TestCase):
    def setUp(self):
        membership = SiaeMembershipFactory()
        self.user = membership.user
        self.siae = membership.siae
        self.url = reverse("siae_evaluations_views:siae_job_applications_list")

    def test_access(self):
        response = self.client.get(self.url)
        self.assertEqual(response.status_code, 302)

        # siae without active campaign
        self.client.login(username=self.user.email, password=DEFAULT_PASSWORD)
        response = self.client.get(self.url)
        self.assertEqual(response.status_code, 200)
        self.assertFalse(response.context["evaluations_asked_at"])
        self.assertFalse(response.context["evaluated_job_applications"])
        self.assertContains(response, "Vous n'avez aucun contrôle en cours.")

        # siae with active campaign
        evaluated_siae = EvaluatedSiaeFactory(evaluation_campaign__evaluations_asked_at=timezone.now(), siae=self.siae)
        evaluated_job_application = EvaluatedJobApplicationFactory(evaluated_siae=evaluated_siae)

        with self.assertNumQueries(10):
            response = self.client.get(self.url)

        self.assertEqual(
            evaluated_siae.evaluation_campaign.evaluations_asked_at, response.context["evaluations_asked_at"]
        )
        self.assertEqual(response.status_code, 200)
        self.assertEqual(
            evaluated_job_application,
            response.context["evaluated_job_applications"][0],
        )
        self.assertEqual(
            reverse("dashboard:index"),
            response.context["back_url"],
        )

        self.assertContains(
            response,
            f"Contrôle initié le "
            f"{dateformat.format(evaluated_siae.evaluation_campaign.evaluations_asked_at, 'd E Y').lower()}",
        )
