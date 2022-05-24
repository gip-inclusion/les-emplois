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
from itou.siae_evaluations.models import EvaluatedAdministrativeCriteria, EvaluationCampaign
from itou.siaes.factories import SiaeMembershipFactory
from itou.users.factories import DEFAULT_PASSWORD, JobSeekerFactory
from itou.utils.perms.user import KIND_SIAE_STAFF, UserInfo
from itou.www.siae_evaluations_views.forms import SetChosenPercentForm


def create_evaluated_siae_consistent_datas(evaluation_campaign):
    membership = SiaeMembershipFactory(siae__department=evaluation_campaign.institution.department)
    user = membership.user
    siae = membership.siae

    job_seeker = JobSeekerFactory()

    user_info = UserInfo(
        user=user, kind=KIND_SIAE_STAFF, siae=siae, prescriber_organization=None, is_authorized_prescriber=False
    )

    administrative_criteria = AdministrativeCriteria.objects.get(pk=1)
    eligibility_diagnosis = EligibilityDiagnosis.create_diagnosis(
        job_seeker, user_info, administrative_criteria=[administrative_criteria]
    )

    job_application = JobApplicationWithApprovalFactory(
        to_siae=siae,
        sender_siae=siae,
        eligibility_diagnosis=eligibility_diagnosis,
        hiring_start_at=timezone.now() - relativedelta(months=2),
    )

    evaluated_siae = EvaluatedSiaeFactory(evaluation_campaign=evaluation_campaign, siae=siae)
    evaluated_job_application = EvaluatedJobApplicationFactory(
        job_application=job_application, evaluated_siae=evaluated_siae
    )
    EvaluatedAdministrativeCriteria.objects.create(
        evaluated_job_application=evaluated_job_application, administrative_criteria=administrative_criteria
    )

    return evaluated_siae


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


class InstitutionEvaluatedSiaeListViewTest(TestCase):
    def setUp(self):
        membership = InstitutionMembershipFactory()
        self.user = membership.user
        self.institution = membership.institution

    def test_access(self):
        self.client.login(username=self.user.email, password=DEFAULT_PASSWORD)

        # institution without evaluation_campaign
        response = self.client.get(
            reverse(
                "siae_evaluations_views:institution_evaluated_siae_list",
                kwargs={"evaluation_campaign_pk": 1},
            )
        )
        self.assertEqual(response.status_code, 404)

        # institution with evaluation_campaign in "institution sets its ratio" phase
        evaluation_campaign = EvaluationCampaignFactory(institution=self.institution)
        EvaluatedSiaeFactory(evaluation_campaign=evaluation_campaign)
        response = self.client.get(
            reverse(
                "siae_evaluations_views:institution_evaluated_siae_list",
                kwargs={"evaluation_campaign_pk": evaluation_campaign.pk},
            )
        )
        self.assertEqual(response.status_code, 404)

        # institution with evaluation_campaign in "siae upload its proofs" phase
        evaluation_campaign.evaluations_asked_at = timezone.now()
        evaluation_campaign.save()
        response = self.client.get(
            reverse(
                "siae_evaluations_views:institution_evaluated_siae_list",
                kwargs={"evaluation_campaign_pk": evaluation_campaign.pk},
            )
        )
        self.assertEqual(response.status_code, 200)

        # institution with ended evaluation_campaign
        evaluation_campaign.ended_at = timezone.now()
        evaluation_campaign.save()
        response = self.client.get(
            reverse(
                "siae_evaluations_views:institution_evaluated_siae_list",
                kwargs={"evaluation_campaign_pk": evaluation_campaign.pk},
            )
        )
        self.assertEqual(response.status_code, 404)

    def test_content(self):
        self.client.login(username=self.user.email, password=DEFAULT_PASSWORD)
        evaluation_campaign = EvaluationCampaignFactory(
            institution=self.institution, evaluations_asked_at=timezone.now()
        )
        evaluated_siae = create_evaluated_siae_consistent_datas(evaluation_campaign)
        response = self.client.get(
            reverse(
                "siae_evaluations_views:institution_evaluated_siae_list",
                kwargs={"evaluation_campaign_pk": evaluation_campaign.pk},
            )
        )
        self.assertEqual(response.status_code, 200)
        self.assertContains(response, evaluated_siae)
        self.assertEqual(response.context["back_url"], reverse("dashboard:index"))
        self.assertContains(response, dateformat.format(evaluation_campaign.evaluations_asked_at, "d F Y"))
        self.assertContains(response, "En attente")

        EvaluatedAdministrativeCriteria.objects.update(
            submitted_at=timezone.now(), proof_url="https://server.com/rocky-balboa.pdf"
        )
        response = self.client.get(
            reverse(
                "siae_evaluations_views:institution_evaluated_siae_list",
                kwargs={"evaluation_campaign_pk": evaluation_campaign.pk},
            )
        )
        self.assertEqual(response.status_code, 200)
        self.assertContains(
            response,
            reverse(
                "siae_evaluations_views:institution_evaluated_siae_detail",
                kwargs={"evaluated_siae_pk": evaluated_siae.pk},
            ),
        )

    def test_num_queries(self):
        self.client.login(username=self.user.email, password=DEFAULT_PASSWORD)
        evaluation_campaign = EvaluationCampaignFactory(
            institution=self.institution, evaluations_asked_at=timezone.now()
        )
        _ = create_evaluated_siae_consistent_datas(evaluation_campaign)
        EvaluatedSiaeFactory.create_batch(10, evaluation_campaign=evaluation_campaign)
        url = reverse(
            "siae_evaluations_views:institution_evaluated_siae_list",
            kwargs={"evaluation_campaign_pk": evaluation_campaign.pk},
        )

        with self.assertNumQueries(
            1  # django session
            + 1  # fetch user
            + 3  # fetch institution membership & institution x 2 !should be fixed!
            + 3  # fetch evaluated_siae and its prefetch_related eval_job_app & eval_admin_crit
            + 1  # one again institution membership
            + 1  # social account
            + 3  # savepoint, update session, release savepoint
        ):
            response = self.client.get(url)
        self.assertEqual(response.status_code, 200)


class InstitutionEvaluatedSiaeDetailViewTest(TestCase):
    def setUp(self):
        membership = InstitutionMembershipFactory()
        self.user = membership.user
        self.institution = membership.institution

    def test_access(self):
        self.client.login(username=self.user.email, password=DEFAULT_PASSWORD)

        # institution without evaluation_campaign
        response = self.client.get(
            reverse(
                "siae_evaluations_views:institution_evaluated_siae_detail",
                kwargs={"evaluated_siae_pk": 1},
            )
        )
        self.assertEqual(response.status_code, 404)

        # institution with evaluation_campaign in "institution sets its ratio" phase
        evaluation_campaign = EvaluationCampaignFactory(institution=self.institution)
        evaluated_siae = create_evaluated_siae_consistent_datas(evaluation_campaign)
        response = self.client.get(
            reverse(
                "siae_evaluations_views:institution_evaluated_siae_detail",
                kwargs={"evaluated_siae_pk": evaluated_siae.pk},
            )
        )
        self.assertEqual(response.status_code, 404)

        # institution with evaluation_campaign in "siae upload its proofs" phase
        evaluation_campaign.evaluations_asked_at = timezone.now()
        evaluation_campaign.save()
        response = self.client.get(
            reverse(
                "siae_evaluations_views:institution_evaluated_siae_detail",
                kwargs={"evaluated_siae_pk": evaluated_siae.pk},
            )
        )
        self.assertEqual(response.status_code, 200)

        # institution with ended evaluation_campaign
        evaluation_campaign.ended_at = timezone.now()
        evaluation_campaign.save()
        response = self.client.get(
            reverse(
                "siae_evaluations_views:institution_evaluated_siae_detail",
                kwargs={"evaluated_siae_pk": evaluated_siae.pk},
            )
        )
        self.assertEqual(response.status_code, 200)

    def test_content(self):
        self.client.login(username=self.user.email, password=DEFAULT_PASSWORD)
        evaluation_campaign = EvaluationCampaignFactory(
            institution=self.institution, evaluations_asked_at=timezone.now()
        )
        evaluated_siae = create_evaluated_siae_consistent_datas(evaluation_campaign)
        evaluated_job_application = evaluated_siae.evaluated_job_applications.first()
        response = self.client.get(
            reverse(
                "siae_evaluations_views:institution_evaluated_siae_detail",
                kwargs={"evaluated_siae_pk": evaluated_siae.pk},
            )
        )
        self.assertEqual(response.status_code, 200)
        self.assertContains(response, evaluated_siae)
        self.assertContains(response, evaluated_job_application.job_application.approval.number_with_spaces)
        self.assertContains(response, evaluated_job_application.job_application.job_seeker.last_name)
        self.assertEqual(
            response.context["back_url"],
            reverse(
                "siae_evaluations_views:institution_evaluated_siae_list",
                kwargs={"evaluation_campaign_pk": evaluation_campaign.pk},
            ),
        )
