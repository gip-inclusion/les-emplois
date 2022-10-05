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
from itou.siae_evaluations.models import EvaluatedAdministrativeCriteria, EvaluatedJobApplication, EvaluationCampaign
from itou.siaes.factories import SiaeMembershipFactory
from itou.users.enums import KIND_SIAE_STAFF
from itou.users.factories import JobSeekerFactory
from itou.utils.perms.user import UserInfo
from itou.utils.templatetags.format_filters import format_approval_number
from itou.www.siae_evaluations_views.forms import LaborExplanationForm, SetChosenPercentForm


# fixme vincentporte : convert this method into factory
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


# fixme vincentporte : remove this method. EvaluatedAdministrativeCriteria have been added yet.
def get_evaluated_administrative_criteria(institution):
    evaluation_campaign = EvaluationCampaignFactory(institution=institution, evaluations_asked_at=timezone.now())
    evaluated_siae = create_evaluated_siae_consistent_datas(evaluation_campaign)
    evaluated_job_application = evaluated_siae.evaluated_job_applications.first()
    return evaluated_job_application.evaluated_administrative_criteria.first()


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
        self.client.force_login(self.user)
        response = self.client.get(self.url)
        self.assertEqual(response.status_code, 200)
        self.assertContains(response, "Vous n'avez pas de contrôle en cours.")

        # institution with active campaign to select
        evaluation_campaign = EvaluationCampaignFactory(institution=self.institution)
        response = self.client.get(self.url)
        self.assertContains(response, "Sélection des salariés à contrôler")

        # institution with active campaign selected
        evaluation_campaign.percent_set_at = timezone.now()
        evaluation_campaign.save(update_fields=["percent_set_at"])
        response = self.client.get(self.url)
        self.assertContains(
            response, "Vous serez notifié lorsque l'étape de transmission des pièces justificatives commencera."
        )

        # institution with ended campaign
        evaluation_campaign.percent_set_at = timezone.now()
        evaluation_campaign.ended_at = timezone.now()
        evaluation_campaign.save(update_fields=["percent_set_at", "ended_at"])
        response = self.client.get(self.url)
        self.assertContains(response, "Vous n'avez pas de contrôle en cours.")

    def test_content(self):
        evaluation_campaign = EvaluationCampaignFactory(institution=self.institution)
        back_url = reverse("dashboard:index")

        self.client.force_login(self.user)
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

        self.client.force_login(self.user)
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
        self.client.force_login(self.user)

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
        evaluation_campaign.save(update_fields=["evaluations_asked_at"])
        response = self.client.get(
            reverse(
                "siae_evaluations_views:institution_evaluated_siae_list",
                kwargs={"evaluation_campaign_pk": evaluation_campaign.pk},
            )
        )
        self.assertEqual(response.status_code, 200)

        # institution with ended evaluation_campaign
        evaluation_campaign.ended_at = timezone.now()
        evaluation_campaign.save(update_fields=["ended_at"])
        response = self.client.get(
            reverse(
                "siae_evaluations_views:institution_evaluated_siae_list",
                kwargs={"evaluation_campaign_pk": evaluation_campaign.pk},
            )
        )
        self.assertEqual(response.status_code, 200)

    def test_content(self):
        self.client.force_login(self.user)
        evaluation_campaign = EvaluationCampaignFactory(
            institution=self.institution, evaluations_asked_at=timezone.now()
        )
        _ = create_evaluated_siae_consistent_datas(evaluation_campaign)
        response = self.client.get(
            reverse(
                "siae_evaluations_views:institution_evaluated_siae_list",
                kwargs={"evaluation_campaign_pk": evaluation_campaign.pk},
            )
        )
        self.assertEqual(response.status_code, 200)
        self.assertEqual(response.context["back_url"], reverse("dashboard:index"))
        self.assertContains(response, dateformat.format(evaluation_campaign.evaluations_asked_at, "d F Y"))

    def test_siae_infos(self):
        en_attente = "En attente"
        a_traiter = "À traiter"
        en_cours = "En cours"
        transmis = "Résultats transmis"
        phase_contradictoire = "Phase contradictoire"

        self.client.force_login(self.user)
        evaluation_campaign = EvaluationCampaignFactory(
            institution=self.institution, evaluations_asked_at=timezone.now()
        )
        evaluated_siae = create_evaluated_siae_consistent_datas(evaluation_campaign)
        url = reverse(
            "siae_evaluations_views:institution_evaluated_siae_list",
            kwargs={"evaluation_campaign_pk": evaluation_campaign.pk},
        )

        response = self.client.get(url)
        self.assertEqual(response.status_code, 200)
        self.assertContains(response, evaluated_siae)
        self.assertContains(response, en_attente)
        self.assertContains(
            response,
            reverse(
                "siae_evaluations_views:institution_evaluated_siae_detail",
                kwargs={"evaluated_siae_pk": evaluated_siae.pk},
            ),
        )

        EvaluatedAdministrativeCriteria.objects.update(
            submitted_at=timezone.now(), proof_url="https://server.com/rocky-balboa.pdf"
        )
        response = self.client.get(url)
        self.assertEqual(response.status_code, 200)
        self.assertContains(response, a_traiter)

        EvaluatedAdministrativeCriteria.objects.filter(
            evaluated_job_application__evaluated_siae=evaluated_siae
        ).update(review_state=evaluation_enums.EvaluatedAdministrativeCriteriaState.REFUSED)

        response = self.client.get(url)
        self.assertEqual(response.status_code, 200)
        self.assertContains(response, en_cours)

        EvaluatedAdministrativeCriteria.objects.filter(
            evaluated_job_application__evaluated_siae=evaluated_siae
        ).update(review_state=evaluation_enums.EvaluatedAdministrativeCriteriaState.ACCEPTED)

        response = self.client.get(url)
        self.assertEqual(response.status_code, 200)
        self.assertContains(response, en_cours)

        # REVIEWED
        evaluated_siae.reviewed_at = timezone.now()
        evaluated_siae.save(update_fields=["reviewed_at"])

        EvaluatedAdministrativeCriteria.objects.filter(
            evaluated_job_application__evaluated_siae=evaluated_siae
        ).update(review_state=evaluation_enums.EvaluatedAdministrativeCriteriaState.REFUSED)

        response = self.client.get(url)
        self.assertEqual(response.status_code, 200)
        self.assertContains(response, phase_contradictoire)

        EvaluatedAdministrativeCriteria.objects.filter(
            evaluated_job_application__evaluated_siae=evaluated_siae
        ).update(review_state=evaluation_enums.EvaluatedAdministrativeCriteriaState.ACCEPTED)

        response = self.client.get(url)
        self.assertEqual(response.status_code, 200)
        self.assertContains(response, transmis)

    def test_num_queries(self):
        self.client.force_login(self.user)
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
        self.client.force_login(self.user)

        # institution without evaluation_campaign
        response = self.client.get(
            reverse(
                "siae_evaluations_views:institution_evaluated_siae_detail",
                kwargs={"evaluated_siae_pk": 99999},
            )
        )
        self.assertEqual(response.status_code, 404)

        # institution with evaluation_campaign in "institution sets its ratio" phase
        evaluation_campaign = EvaluationCampaignFactory(institution=self.institution)
        evaluated_siae = create_evaluated_siae_consistent_datas(evaluation_campaign)
        url = reverse(
            "siae_evaluations_views:institution_evaluated_siae_detail",
            kwargs={"evaluated_siae_pk": evaluated_siae.pk},
        )

        response = self.client.get(url)
        self.assertEqual(response.status_code, 404)

        # institution with evaluation_campaign in "siae upload its proofs" phase
        evaluation_campaign.evaluations_asked_at = timezone.now()
        evaluation_campaign.save(update_fields=["evaluations_asked_at"])
        response = self.client.get(url)
        self.assertEqual(response.status_code, 200)

        # institution with ended evaluation_campaign
        evaluation_campaign.ended_at = timezone.now()
        evaluation_campaign.save(update_fields=["ended_at"])
        response = self.client.get(url)
        self.assertEqual(response.status_code, 200)

    def test_content(self):
        self.client.force_login(self.user)
        evaluation_campaign = EvaluationCampaignFactory(
            institution=self.institution, evaluations_asked_at=timezone.now()
        )
        evaluated_siae = create_evaluated_siae_consistent_datas(evaluation_campaign)
        evaluated_job_application = evaluated_siae.evaluated_job_applications.first()

        evaluated_job_application_url = reverse(
            "siae_evaluations_views:institution_evaluated_job_application",
            kwargs={"evaluated_job_application_pk": evaluated_job_application.pk},
        )
        url = reverse(
            "siae_evaluations_views:institution_evaluated_siae_detail",
            kwargs={"evaluated_siae_pk": evaluated_siae.pk},
        )
        validation_url = reverse(
            "siae_evaluations_views:institution_evaluated_siae_validation",
            kwargs={"evaluated_siae_pk": evaluated_siae.pk},
        )
        back_url = reverse(
            "siae_evaluations_views:institution_evaluated_siae_list",
            kwargs={"evaluation_campaign_pk": evaluation_campaign.pk},
        )
        message = '<div class="alert alert-communaute alert-dismissible fade show" role="status">'

        # EvaluatedAdministrativeCriteria not yet submitted
        response = self.client.get(url)
        self.assertEqual(response.status_code, 200)
        self.assertContains(response, evaluated_siae)
        formatted_number = format_approval_number(evaluated_job_application.job_application.approval.number)
        self.assertContains(response, formatted_number, html=True, count=1)
        self.assertContains(response, evaluated_job_application.job_application.job_seeker.last_name)
        self.assertEqual(
            response.context["back_url"],
            reverse(
                "siae_evaluations_views:institution_evaluated_siae_list",
                kwargs={"evaluation_campaign_pk": evaluation_campaign.pk},
            ),
        )
        self.assertNotContains(response, evaluated_job_application_url)
        self.assertContains(response, back_url)
        self.assertContains(response, validation_url)
        self.assertNotContains(response, message)

        # EvaluatedAdministrativeCriteria uploaded
        evaluated_administrative_criteria = evaluated_job_application.evaluated_administrative_criteria.first()
        evaluated_administrative_criteria.proof_url = "https://server.com/rocky-balboa.pdf"
        evaluated_administrative_criteria.save(update_fields=["proof_url"])
        response = self.client.get(url)
        self.assertEqual(response.status_code, 200)
        self.assertContains(response, back_url)
        self.assertContains(response, "Justificatifs téléversés")

        # EvaluatedAdministrativeCriteria submitted
        evaluated_administrative_criteria.submitted_at = timezone.now()
        evaluated_administrative_criteria.save(update_fields=["submitted_at"])
        response = self.client.get(url)
        self.assertEqual(response.status_code, 200)
        self.assertContains(response, evaluated_job_application_url)
        self.assertContains(response, back_url)
        self.assertNotContains(response, "Documents téléversés")
        self.assertNotContains(response, "En attente")
        self.assertNotContains(response, "Nouveaux justificatifs à traiter")
        self.assertContains(response, validation_url)
        self.assertNotContains(response, message)

        # EvaluatedAdministrativeCriteria Accepted
        evaluated_administrative_criteria.review_state = evaluation_enums.EvaluatedAdministrativeCriteriaState.ACCEPTED
        evaluated_administrative_criteria.save(update_fields=["review_state"])

        response = self.client.get(url)
        self.assertEqual(response.status_code, 200)
        self.assertContains(response, evaluated_job_application_url)
        self.assertContains(response, back_url)
        self.assertContains(response, validation_url)
        self.assertNotContains(response, message)

        # EvaluatedAdministrativeCriteria Accepted & Reviewed
        evaluated_siae.reviewed_at = timezone.now()
        evaluated_siae.save(update_fields=["reviewed_at"])

        response = self.client.get(url)
        self.assertEqual(response.status_code, 200)
        self.assertContains(response, evaluated_job_application_url)
        self.assertContains(response, back_url)
        self.assertContains(response, validation_url)
        self.assertContains(response, message)

        # EvaluatedAdministrativeCriteria Refused
        evaluated_administrative_criteria.review_state = evaluation_enums.EvaluatedAdministrativeCriteriaState.REFUSED
        evaluated_administrative_criteria.save(update_fields=["review_state"])
        evaluated_siae.reviewed_at = None
        evaluated_siae.save(update_fields=["reviewed_at"])

        response = self.client.get(url)
        self.assertEqual(response.status_code, 200)
        self.assertContains(response, evaluated_job_application_url)
        self.assertContains(response, back_url)
        self.assertContains(response, validation_url)
        self.assertNotContains(response, message)

        # EvaluatedAdministrativeCriteria Refused & Reviewed
        evaluated_siae.reviewed_at = timezone.now()
        evaluated_siae.save(update_fields=["reviewed_at"])

        response = self.client.get(url)
        self.assertEqual(response.status_code, 200)
        self.assertContains(response, evaluated_job_application_url)
        self.assertContains(response, back_url)
        self.assertContains(response, validation_url)
        self.assertContains(response, message)

    def test_job_seeker_infos_for_institution_state(self):
        en_attente = "En attente"
        a_traiter = "À traiter"
        refuse = "Problème constaté"
        valide = "Validé"

        evaluation_campaign = EvaluationCampaignFactory(
            institution=self.institution, evaluations_asked_at=timezone.now()
        )
        evaluated_siae = create_evaluated_siae_consistent_datas(evaluation_campaign)

        url = reverse(
            "siae_evaluations_views:institution_evaluated_siae_detail",
            kwargs={"evaluated_siae_pk": evaluated_siae.pk},
        )

        self.client.force_login(self.user)

        # not yet submitted by Siae
        response = self.client.get(url)
        self.assertEqual(response.status_code, 200)
        self.assertContains(response, en_attente)

        # submitted by Siae
        EvaluatedAdministrativeCriteria.objects.filter(
            evaluated_job_application__evaluated_siae=evaluated_siae
        ).update(submitted_at=timezone.now(), proof_url="https://server.com/rocky-balboa.pdf")

        response = self.client.get(url)
        self.assertEqual(response.status_code, 200)
        self.assertContains(response, a_traiter)

        # refused
        EvaluatedAdministrativeCriteria.objects.filter(
            evaluated_job_application__evaluated_siae=evaluated_siae
        ).update(review_state=evaluation_enums.EvaluatedAdministrativeCriteriaState.REFUSED)

        response = self.client.get(url)
        self.assertEqual(response.status_code, 200)
        self.assertContains(response, refuse)

        # accepted
        EvaluatedAdministrativeCriteria.objects.filter(
            evaluated_job_application__evaluated_siae=evaluated_siae
        ).update(review_state=evaluation_enums.EvaluatedAdministrativeCriteriaState.ACCEPTED)

        response = self.client.get(url)
        self.assertEqual(response.status_code, 200)
        self.assertContains(response, valide)

    def test_second_review_does_not_update_reviewed_at(self):
        campaign = EvaluationCampaignFactory(
            institution=self.institution,
            evaluations_asked_at=timezone.now() - relativedelta(weeks=3),
        )
        evaluated_siae = create_evaluated_siae_consistent_datas(campaign)
        EvaluatedAdministrativeCriteria.objects.filter(
            evaluated_job_application__evaluated_siae=evaluated_siae
        ).update(review_state=evaluation_enums.EvaluatedAdministrativeCriteriaState.REFUSED)
        now = timezone.now()
        evaluated_siae.reviewed_at = now
        evaluated_siae.save(update_fields=["reviewed_at"])

        self.client.force_login(self.user)
        response = self.client.post(
            reverse(
                "siae_evaluations_views:institution_evaluated_siae_validation",
                kwargs={"evaluated_siae_pk": evaluated_siae.pk},
            )
        )

        self.assertRedirects(
            response,
            reverse(
                "siae_evaluations_views:institution_evaluated_siae_detail",
                kwargs={"evaluated_siae_pk": evaluated_siae.pk},
            ),
        )
        evaluated_siae.refresh_from_db()
        self.assertEqual(evaluated_siae.reviewed_at, now)

    def test_num_queries_in_view(self):
        self.client.force_login(self.user)
        evaluation_campaign = EvaluationCampaignFactory(
            institution=self.institution, evaluations_asked_at=timezone.now()
        )
        evaluated_siae = create_evaluated_siae_consistent_datas(evaluation_campaign)
        EvaluatedJobApplicationFactory.create_batch(10, evaluated_siae=evaluated_siae)

        url = reverse(
            "siae_evaluations_views:institution_evaluated_siae_detail",
            kwargs={"evaluated_siae_pk": evaluated_siae.pk},
        )

        with self.assertNumQueries(
            1  # django session
            + 1  # fetch user
            + 3  # fetch institution membership & institution x 2 !should be fixed!
            + 6  # fetch evaluated_siae and its prefetch_related
            + 1  # one again institution membership
            + 1  # social account
            + 3  # savepoint, update session, release savepoint
        ):
            response = self.client.get(url)
        self.assertEqual(response.status_code, 200)


class InstitutionEvaluatedJobApplicationViewTest(TestCase):
    def setUp(self):
        membership = InstitutionMembershipFactory()
        self.user = membership.user
        self.institution = membership.institution

    def test_access(self):
        self.client.force_login(self.user)

        # institution without evaluation_campaign
        response = self.client.get(
            reverse(
                "siae_evaluations_views:institution_evaluated_job_application",
                kwargs={"evaluated_job_application_pk": 1},
            )
        )
        self.assertEqual(response.status_code, 404)

        # institution with evaluation_campaign in "institution sets its ratio" phase
        evaluation_campaign = EvaluationCampaignFactory(institution=self.institution)
        evaluated_siae = create_evaluated_siae_consistent_datas(evaluation_campaign)
        evaluated_job_application = evaluated_siae.evaluated_job_applications.first()
        response = self.client.get(
            reverse(
                "siae_evaluations_views:institution_evaluated_job_application",
                kwargs={"evaluated_job_application_pk": evaluated_job_application.pk},
            )
        )
        self.assertEqual(response.status_code, 404)

        # institution with evaluation_campaign in "siae upload its proofs" phase
        evaluation_campaign.evaluations_asked_at = timezone.now()
        evaluation_campaign.save(update_fields=["evaluations_asked_at"])
        response = self.client.get(
            reverse(
                "siae_evaluations_views:institution_evaluated_job_application",
                kwargs={"evaluated_job_application_pk": evaluated_job_application.pk},
            )
        )
        self.assertEqual(response.status_code, 200)

        # institution with ended evaluation_campaign
        evaluation_campaign.ended_at = timezone.now()
        evaluation_campaign.save(update_fields=["ended_at"])
        response = self.client.get(
            reverse(
                "siae_evaluations_views:institution_evaluated_job_application",
                kwargs={"evaluated_job_application_pk": evaluated_job_application.pk},
            )
        )
        self.assertEqual(response.status_code, 200)

    def test_content(self):
        self.client.force_login(self.user)
        evaluation_campaign = EvaluationCampaignFactory(
            institution=self.institution, evaluations_asked_at=timezone.now()
        )
        evaluated_siae = create_evaluated_siae_consistent_datas(evaluation_campaign)
        evaluated_job_application = evaluated_siae.evaluated_job_applications.first()
        response = self.client.get(
            reverse(
                "siae_evaluations_views:institution_evaluated_job_application",
                kwargs={"evaluated_job_application_pk": evaluated_job_application.pk},
            )
        )
        self.assertEqual(response.status_code, 200)
        self.assertEqual(response.context["evaluated_job_application"], evaluated_job_application)
        self.assertEqual(response.context["evaluated_siae"], evaluated_siae)
        self.assertIsInstance(response.context["form"], LaborExplanationForm)
        self.assertEqual(
            response.context["back_url"],
            reverse(
                "siae_evaluations_views:institution_evaluated_siae_detail",
                kwargs={"evaluated_siae_pk": evaluated_siae.pk},
            )
            + f"#{evaluated_job_application.pk}",
        )

    def test_criterion_validation(self):
        self.client.force_login(self.user)

        # fixme vincentporte : use EvaluatedAdministrativeCriteria instead
        evaluated_administrative_criteria = get_evaluated_administrative_criteria(self.institution)

        refuse_url = reverse(
            "siae_evaluations_views:institution_evaluated_administrative_criteria",
            kwargs={
                "evaluated_administrative_criteria_pk": evaluated_administrative_criteria.pk,
                "action": "refuse",
            },
        )
        accepte_url = reverse(
            "siae_evaluations_views:institution_evaluated_administrative_criteria",
            kwargs={
                "evaluated_administrative_criteria_pk": evaluated_administrative_criteria.pk,
                "action": "accept",
            },
        )
        reinit_url = reverse(
            "siae_evaluations_views:institution_evaluated_administrative_criteria",
            kwargs={
                "evaluated_administrative_criteria_pk": evaluated_administrative_criteria.pk,
                "action": "reinit",
            },
        )
        url_view = reverse(
            "siae_evaluations_views:institution_evaluated_job_application",
            kwargs={"evaluated_job_application_pk": evaluated_administrative_criteria.evaluated_job_application.pk},
        )

        # unverified evaluated_administrative_criteria
        evaluated_administrative_criteria.submitted_at = timezone.now()
        evaluated_administrative_criteria.proof_url = "https://server.com/rocky-balboa.pdf"
        evaluated_administrative_criteria.save(update_fields=["submitted_at", "proof_url"])
        response = self.client.get(url_view)
        self.assertEqual(response.status_code, 200)
        self.assertContains(response, refuse_url)
        self.assertContains(response, accepte_url)
        self.assertNotContains(response, reinit_url)

        # accepted
        evaluated_administrative_criteria.review_state = evaluation_enums.EvaluatedAdministrativeCriteriaState.ACCEPTED
        evaluated_administrative_criteria.save(update_fields=["review_state"])

        response = self.client.get(url_view)
        self.assertEqual(response.status_code, 200)
        self.assertNotContains(response, refuse_url)
        self.assertNotContains(response, accepte_url)
        self.assertContains(response, reinit_url)
        self.assertContains(response, '<p class="text-success"><i class="ri-checkbox-circle-line"></i> Validé</p>')

        # refused
        evaluated_administrative_criteria.review_state = evaluation_enums.EvaluatedAdministrativeCriteriaState.REFUSED
        evaluated_administrative_criteria.save(update_fields=["review_state"])

        response = self.client.get(url_view)
        self.assertEqual(response.status_code, 200)
        self.assertNotContains(response, refuse_url)
        self.assertNotContains(response, accepte_url)
        self.assertContains(response, reinit_url)
        self.assertContains(response, '<p class="text-danger"><i class="ri-indeterminate-circle-line"></i> Refusé</p>')

        # reinited
        evaluated_administrative_criteria.review_state = evaluation_enums.EvaluatedAdministrativeCriteriaState.PENDING
        evaluated_administrative_criteria.save(update_fields=["review_state"])

        response = self.client.get(url_view)
        self.assertEqual(response.status_code, 200)
        self.assertContains(response, refuse_url)
        self.assertContains(response, accepte_url)
        self.assertNotContains(response, reinit_url)

        # reviewed
        evaluated_administrative_criteria.evaluated_job_application.evaluated_siae.reviewed_at = timezone.now()
        evaluated_administrative_criteria.evaluated_job_application.evaluated_siae.save(update_fields=["reviewed_at"])
        evaluated_administrative_criteria.review_state = evaluation_enums.EvaluatedAdministrativeCriteriaState.ACCEPTED
        evaluated_administrative_criteria.save(update_fields=["review_state"])

        response = self.client.get(url_view)
        self.assertEqual(response.status_code, 200)
        self.assertNotContains(response, refuse_url)
        self.assertNotContains(response, accepte_url)
        self.assertNotContains(response, reinit_url)

    def test_form(self):
        evaluation_campaign = EvaluationCampaignFactory(
            institution=self.institution, evaluations_asked_at=timezone.now()
        )
        evaluated_siae = create_evaluated_siae_consistent_datas(evaluation_campaign)
        evaluated_job_application = evaluated_siae.evaluated_job_applications.first()

        # form is valid
        form_data = {"labor_inspector_explanation": "test"}
        form = LaborExplanationForm(instance=evaluated_job_application, data=form_data)
        self.assertTrue(form.is_valid())

        form_data = {"labor_inspector_explanation": None}
        form = LaborExplanationForm(instance=evaluated_job_application, data=form_data)
        self.assertTrue(form.is_valid())

        # note vincentporte
        # to be added : readonly conditionnal field

    def test_post_form(self):
        self.client.force_login(self.user)
        evaluation_campaign = EvaluationCampaignFactory(
            institution=self.institution, evaluations_asked_at=timezone.now()
        )
        evaluated_siae = create_evaluated_siae_consistent_datas(evaluation_campaign)
        evaluated_job_application = evaluated_siae.evaluated_job_applications.first()

        url = reverse(
            "siae_evaluations_views:institution_evaluated_job_application",
            kwargs={"evaluated_job_application_pk": evaluated_job_application.pk},
        )

        response = self.client.get(url)
        self.assertEqual(response.status_code, 200)

        post_data = {"labor_inspector_explanation": "test"}
        response = self.client.post(url, data=post_data)
        self.assertEqual(response.status_code, 302)
        self.assertEqual(
            response.url,
            reverse(
                "siae_evaluations_views:institution_evaluated_siae_detail",
                kwargs={"evaluated_siae_pk": evaluated_siae.pk},
            )
            + f"#{evaluated_job_application.pk}",
        )

        updated_evaluated_job_application = EvaluatedJobApplication.objects.get(pk=evaluated_job_application.pk)
        self.assertEqual(
            updated_evaluated_job_application.labor_inspector_explanation, post_data["labor_inspector_explanation"]
        )

    def test_num_queries_in_view(self):
        self.client.force_login(self.user)
        # fixme vincentporte : use EvaluatedAdministrativeCriteria instead
        evaluated_administrative_criteria = get_evaluated_administrative_criteria(self.institution)
        EvaluatedAdministrativeCriteria.objects.create(
            evaluated_job_application=evaluated_administrative_criteria.evaluated_job_application,
            administrative_criteria=AdministrativeCriteria.objects.get(pk=2),
        )
        EvaluatedAdministrativeCriteria.objects.create(
            evaluated_job_application=evaluated_administrative_criteria.evaluated_job_application,
            administrative_criteria=AdministrativeCriteria.objects.get(pk=3),
        )

        url = reverse(
            "siae_evaluations_views:institution_evaluated_job_application",
            kwargs={"evaluated_job_application_pk": evaluated_administrative_criteria.evaluated_job_application.pk},
        )
        with self.assertNumQueries(
            1  # django session
            + 1  # fetch user
            + 3  # fetch institution membership & institution x 2 !should be fixed!
            + 6  # fetch evaluated_siae and its prefetch_related
            + 1  # fetch evaluation_campaign
            + 1  # one again institution membership
            + 1  # social account
            + 3  # savepoint, update session, release savepoint
            + 5  # issue with evaluated_job_application.evaluated_siae.state
        ):
            response = self.client.get(url)
        self.assertEqual(response.status_code, 200)

    def test_job_application_state_labels(self):
        self.client.force_login(self.user)
        # fixme vincentporte : use EvaluatedAdministrativeCriteria instead
        evaluated_administrative_criteria = get_evaluated_administrative_criteria(self.institution)
        evaluated_administrative_criteria.proof_url = "https://www.test.com"
        evaluated_administrative_criteria.submitted_at = timezone.now()
        evaluated_administrative_criteria.save(update_fields=["submitted_at", "proof_url"])

        url_view = reverse(
            "siae_evaluations_views:institution_evaluated_job_application",
            kwargs={"evaluated_job_application_pk": evaluated_administrative_criteria.evaluated_job_application.pk},
        )

        # Unset
        response = self.client.get(url_view)
        self.assertEqual(response.status_code, 200)
        self.assertContains(response, "badge-pilotage")
        self.assertContains(response, "À traiter")

        # Refused
        evaluated_administrative_criteria.review_state = evaluation_enums.EvaluatedAdministrativeCriteriaState.REFUSED
        evaluated_administrative_criteria.save(update_fields=["review_state"])
        response = self.client.get(url_view)
        self.assertEqual(response.status_code, 200)
        self.assertContains(response, "badge-danger")
        self.assertContains(response, "Problème constaté")

        # Accepted
        evaluated_administrative_criteria.review_state = evaluation_enums.EvaluatedAdministrativeCriteriaState.ACCEPTED
        evaluated_administrative_criteria.save(update_fields=["review_state"])
        response = self.client.get(url_view)
        self.assertEqual(response.status_code, 200)
        self.assertContains(response, "badge-success")
        self.assertContains(response, "Validé")


class InstitutionEvaluatedAdministrativeCriteriaViewTest(TestCase):
    def setUp(self):
        membership = InstitutionMembershipFactory()
        self.user = membership.user
        self.institution = membership.institution

    def test_access(self):
        self.client.force_login(self.user)

        # institution without evaluation_campaign
        response = self.client.post(
            reverse(
                "siae_evaluations_views:institution_evaluated_administrative_criteria",
                kwargs={"evaluated_administrative_criteria_pk": 1, "action": "dummy"},
            )
        )
        self.assertEqual(response.status_code, 404)

        # institution with evaluation_campaign in "institution sets its ratio" phase
        evaluation_campaign = EvaluationCampaignFactory(institution=self.institution)
        evaluated_siae = create_evaluated_siae_consistent_datas(evaluation_campaign)
        evaluated_job_application = evaluated_siae.evaluated_job_applications.first()
        evaluated_administrative_criteria = evaluated_job_application.evaluated_administrative_criteria.first()
        response = self.client.post(
            reverse(
                "siae_evaluations_views:institution_evaluated_administrative_criteria",
                kwargs={
                    "evaluated_administrative_criteria_pk": evaluated_administrative_criteria.pk,
                    "action": "dummy",
                },
            )
        )
        self.assertEqual(response.status_code, 404)

        # institution with evaluation_campaign in "siae upload its proofs" phase
        evaluation_campaign.evaluations_asked_at = timezone.now()
        evaluation_campaign.save(update_fields=["evaluations_asked_at"])
        response = self.client.post(
            reverse(
                "siae_evaluations_views:institution_evaluated_administrative_criteria",
                kwargs={
                    "evaluated_administrative_criteria_pk": evaluated_administrative_criteria.pk,
                    "action": "dummy",
                },
            )
        )
        self.assertEqual(response.status_code, 302)

        # institution with ended evaluation_campaign
        evaluation_campaign.ended_at = timezone.now()
        evaluation_campaign.save(update_fields=["ended_at"])
        response = self.client.post(
            reverse(
                "siae_evaluations_views:institution_evaluated_administrative_criteria",
                kwargs={
                    "evaluated_administrative_criteria_pk": evaluated_administrative_criteria.pk,
                    "action": "dummy",
                },
            )
        )
        self.assertEqual(response.status_code, 404)

    def test_actions_and_redirection(self):
        self.client.force_login(self.user)
        # fixme vincentporte : use EvaluatedAdministrativeCriteria instead
        evaluated_administrative_criteria = get_evaluated_administrative_criteria(self.institution)
        redirect_url = reverse(
            "siae_evaluations_views:institution_evaluated_job_application",
            kwargs={"evaluated_job_application_pk": evaluated_administrative_criteria.evaluated_job_application.pk},
        )

        # action = dummy
        response = self.client.post(
            reverse(
                "siae_evaluations_views:institution_evaluated_administrative_criteria",
                kwargs={
                    "evaluated_administrative_criteria_pk": evaluated_administrative_criteria.pk,
                    "action": "dummy",
                },
            )
        )
        self.assertEqual(response.status_code, 302)
        self.assertEqual(response.url, redirect_url)
        eval_admin_crit = EvaluatedAdministrativeCriteria.objects.get(pk=evaluated_administrative_criteria.pk)
        self.assertEqual(evaluation_enums.EvaluatedAdministrativeCriteriaState.REFUSED, eval_admin_crit.review_state)

        # action reinit
        response = self.client.post(
            reverse(
                "siae_evaluations_views:institution_evaluated_administrative_criteria",
                kwargs={
                    "evaluated_administrative_criteria_pk": evaluated_administrative_criteria.pk,
                    "action": "reinit",
                },
            )
        )
        self.assertEqual(response.status_code, 302)
        self.assertEqual(response.url, redirect_url)
        eval_admin_crit.refresh_from_db()
        self.assertEqual(evaluation_enums.EvaluatedAdministrativeCriteriaState.PENDING, eval_admin_crit.review_state)

        # action = accept
        response = self.client.post(
            reverse(
                "siae_evaluations_views:institution_evaluated_administrative_criteria",
                kwargs={
                    "evaluated_administrative_criteria_pk": evaluated_administrative_criteria.pk,
                    "action": "accept",
                },
            )
        )
        self.assertEqual(response.status_code, 302)
        self.assertEqual(response.url, redirect_url)
        eval_admin_crit.refresh_from_db()
        self.assertEqual(evaluation_enums.EvaluatedAdministrativeCriteriaState.ACCEPTED, eval_admin_crit.review_state)

        # action = refuse
        response = self.client.post(
            reverse(
                "siae_evaluations_views:institution_evaluated_administrative_criteria",
                kwargs={
                    "evaluated_administrative_criteria_pk": evaluated_administrative_criteria.pk,
                    "action": "refuse",
                },
            )
        )
        self.assertEqual(response.status_code, 302)
        self.assertEqual(response.url, redirect_url)
        eval_admin_crit.refresh_from_db()
        self.assertEqual(evaluation_enums.EvaluatedAdministrativeCriteriaState.REFUSED, eval_admin_crit.review_state)

        # action = refuse after review
        evsiae = evaluated_administrative_criteria.evaluated_job_application.evaluated_siae
        evsiae.reviewed_at = timezone.now()
        evsiae.save(update_fields=["reviewed_at"])

        response = self.client.post(
            reverse(
                "siae_evaluations_views:institution_evaluated_administrative_criteria",
                kwargs={
                    "evaluated_administrative_criteria_pk": evaluated_administrative_criteria.pk,
                    "action": "refuse",
                },
            )
        )
        self.assertEqual(response.status_code, 302)
        self.assertEqual(response.url, redirect_url)
        eval_admin_crit.refresh_from_db()
        self.assertEqual(evaluation_enums.EvaluatedAdministrativeCriteriaState.REFUSED_2, eval_admin_crit.review_state)


class InstitutionEvaluatedSiaeValidationViewTest(TestCase):
    def setUp(self):
        membership = InstitutionMembershipFactory()
        self.user = membership.user
        self.evaluation_campaign = EvaluationCampaignFactory(institution=membership.institution)
        self.evaluated_siae = create_evaluated_siae_consistent_datas(self.evaluation_campaign)

    def test_access(self):
        self.client.force_login(self.user)

        # institution without evaluation_campaign
        response = self.client.post(
            reverse(
                "siae_evaluations_views:institution_evaluated_siae_validation",
                kwargs={"evaluated_siae_pk": 1},
            )
        )
        self.assertEqual(response.status_code, 404)

        # institution with evaluation_campaign in "institution sets its ratio" phase
        url = reverse(
            "siae_evaluations_views:institution_evaluated_siae_validation",
            kwargs={"evaluated_siae_pk": self.evaluated_siae.pk},
        )

        response = self.client.post(url)
        self.assertEqual(response.status_code, 404)

        # institution with evaluation_campaign in "siae upload its proofs" phase
        self.evaluation_campaign.evaluations_asked_at = timezone.now()
        self.evaluation_campaign.save(update_fields=["evaluations_asked_at"])
        response = self.client.post(url)
        self.assertEqual(response.status_code, 302)

        # institution with ended evaluation_campaign
        self.evaluation_campaign.ended_at = timezone.now()
        self.evaluation_campaign.save(update_fields=["ended_at"])
        response = self.client.post(url)
        self.assertEqual(response.status_code, 404)

    def test_actions_and_redirection(self):
        self.client.force_login(self.user)

        self.evaluation_campaign.evaluations_asked_at = timezone.now()
        self.evaluation_campaign.save(update_fields=["evaluations_asked_at"])
        EvaluatedAdministrativeCriteria.objects.filter(
            evaluated_job_application__evaluated_siae=self.evaluated_siae
        ).update(submitted_at=timezone.now(), proof_url="https://server.com/rocky-balboa.pdf")

        url = reverse(
            "siae_evaluations_views:institution_evaluated_siae_validation",
            kwargs={"evaluated_siae_pk": self.evaluated_siae.pk},
        )
        redirect_url = reverse(
            "siae_evaluations_views:institution_evaluated_siae_detail",
            kwargs={"evaluated_siae_pk": self.evaluated_siae.pk},
        )

        # before validation
        response = self.client.post(url)
        self.assertEqual(response.status_code, 302)
        self.assertEqual(response.url, redirect_url)
        self.evaluated_siae.refresh_from_db()
        self.assertIsNone(self.evaluated_siae.reviewed_at)

        # accepted
        EvaluatedAdministrativeCriteria.objects.filter(
            evaluated_job_application__evaluated_siae=self.evaluated_siae
        ).update(review_state=evaluation_enums.EvaluatedAdministrativeCriteriaState.ACCEPTED)
        response = self.client.post(url)
        self.assertEqual(response.status_code, 302)
        self.assertEqual(response.url, redirect_url)
        self.evaluated_siae.refresh_from_db()
        self.assertIsNotNone(self.evaluated_siae.reviewed_at)

        # refused
        self.evaluated_siae.reviewed_at = None
        self.evaluated_siae.save(update_fields=["reviewed_at"])
        EvaluatedAdministrativeCriteria.objects.filter(
            evaluated_job_application__evaluated_siae=self.evaluated_siae
        ).update(review_state=evaluation_enums.EvaluatedAdministrativeCriteriaState.REFUSED)

        response = self.client.post(url)
        self.assertEqual(response.status_code, 302)
        self.assertEqual(response.url, redirect_url)
        self.evaluated_siae.refresh_from_db()
        self.assertIsNotNone(self.evaluated_siae.reviewed_at)

        # cannot validate twice
        timestamp = self.evaluated_siae.reviewed_at
        response = self.client.post(url)
        self.assertEqual(response.status_code, 302)
        self.evaluated_siae.refresh_from_db()
        self.assertEqual(timestamp, self.evaluated_siae.reviewed_at)
