from dateutil.relativedelta import relativedelta
from django.contrib import messages
from django.contrib.messages.storage.base import Message
from django.core import mail
from django.test import TestCase
from django.urls import reverse
from django.utils import dateformat, timezone
from freezegun import freeze_time

from itou.eligibility.models import AdministrativeCriteria, EligibilityDiagnosis
from itou.institutions.factories import InstitutionMembershipFactory
from itou.job_applications.factories import JobApplicationFactory
from itou.siae_evaluations import enums as evaluation_enums
from itou.siae_evaluations.constants import CAMPAIGN_VIEWABLE_DURATION
from itou.siae_evaluations.factories import (
    EvaluatedAdministrativeCriteriaFactory,
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

    job_application = JobApplicationFactory(
        with_approval=True,
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
        membership = InstitutionMembershipFactory(institution__name="DDETS Ille et Vilaine")
        self.user = membership.user
        self.institution = membership.institution
        self.url = reverse("siae_evaluations_views:samples_selection")

    def test_access(self):

        response = self.client.get(self.url)
        self.assertEqual(response.status_code, 302)

        # institution without active campaign
        self.client.force_login(self.user)
        response = self.client.get(self.url)
        assert response.status_code == 404

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
        assert response.status_code == 404

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

    def test_post_form_opt_out(self):
        EvaluationCampaignFactory(institution=self.institution, name="Campagne 2022")

        self.client.force_login(self.user)
        response = self.client.post(self.url, data={"opt_out": "on"})

        assert list(messages.get_messages(response.wsgi_request)) == [
            Message(
                messages.SUCCESS,
                "DDETS Ille et Vilaine ne participera pas à la campagne de contrôle a posteriori Campagne 2022.",
            )
        ]
        self.assertRedirects(response, reverse("dashboard:index"))
        assert not EvaluationCampaign.objects.exists()


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
        self.assertContains(response, "Liste des Siae à contrôler", html=True, count=1)

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
        self.assertContains(response, "Liste des Siae contrôlées", html=True, count=1)

    def test_recently_closed_campaign(self):
        evaluated_siae = EvaluatedSiaeFactory(
            complete=True,
            job_app__criteria__review_state=evaluation_enums.EvaluatedJobApplicationsState.ACCEPTED,
            evaluation_campaign__institution=self.institution,
        )
        self.client.force_login(self.user)
        response = self.client.get(
            reverse(
                "siae_evaluations_views:institution_evaluated_siae_list",
                kwargs={"evaluation_campaign_pk": evaluated_siae.evaluation_campaign_id},
            )
        )
        assert response.status_code == 200
        url = reverse(
            "siae_evaluations_views:institution_evaluated_siae_detail",
            kwargs={"evaluated_siae_pk": evaluated_siae.pk},
        )
        self.assertContains(
            response,
            f"""
            <a href="{url}" class="btn btn-outline-primary btn-sm">
              Voir le résultat
            </a>
            """,
            html=True,
            count=1,
        )
        self.assertContains(response, "Liste des Siae contrôlées", html=True, count=1)

    def test_siae_refused_can_be_notified(self):
        evaluated_siae = EvaluatedSiaeFactory(
            complete=True,
            job_app__criteria__review_state=evaluation_enums.EvaluatedJobApplicationsState.REFUSED_2,
            evaluation_campaign__institution=self.institution,
        )
        self.client.force_login(self.user)
        response = self.client.get(
            reverse(
                "siae_evaluations_views:institution_evaluated_siae_list",
                kwargs={"evaluation_campaign_pk": evaluated_siae.evaluation_campaign_id},
            )
        )
        self.assertContains(response, "Liste des Siae contrôlées", html=True, count=1)
        self.assertContains(
            response,
            """
            <p class="badge badge-pill badge-accent-03 text-primary float-right">
                <i class="ri-arrow-right-circle-line mr-1"></i> Notification à faire
            </p>
            """,
            html=True,
            count=1,
        )
        notify_url = reverse(
            "siae_evaluations_views:institution_evaluated_siae_notify",
            kwargs={"evaluated_siae_pk": evaluated_siae.pk},
        )
        self.assertContains(
            response,
            f"""
            <a class="btn btn-primary btn-sm ml-1" href="{notify_url}">
                <i class="ri-notification-4-line"></i> Notifier le résultat
            </a>
            """,
            html=True,
            count=1,
        )
        url = reverse(
            "siae_evaluations_views:institution_evaluated_siae_detail",
            kwargs={"evaluated_siae_pk": evaluated_siae.pk},
        )
        self.assertContains(
            response,
            f'<a href="{url}" class="btn btn-outline-primary btn-sm">Voir le résultat</a>',
            html=True,
            count=1,
        )

    def test_siae_incomplete_refused_can_be_notified(self):
        evaluated_siae = EvaluatedSiaeFactory(
            evaluation_campaign__institution=self.institution,
            evaluation_campaign__evaluations_asked_at=timezone.now() - relativedelta(weeks=10),
            evaluation_campaign__ended_at=timezone.now(),
        )
        self.client.force_login(self.user)
        response = self.client.get(
            reverse(
                "siae_evaluations_views:institution_evaluated_siae_list",
                kwargs={"evaluation_campaign_pk": evaluated_siae.evaluation_campaign_id},
            )
        )
        self.assertContains(response, "Liste des Siae contrôlées", html=True, count=1)
        self.assertContains(
            response,
            """
            <p class="badge badge-pill badge-accent-03 text-primary float-right">
                <i class="ri-arrow-right-circle-line mr-1"></i> Notification à faire
            </p>
            """,
            html=True,
            count=1,
        )
        notify_url = reverse(
            "siae_evaluations_views:institution_evaluated_siae_notify",
            kwargs={"evaluated_siae_pk": evaluated_siae.pk},
        )
        self.assertContains(
            response,
            f"""
            <a class="btn btn-primary btn-sm ml-1" href="{notify_url}">
                <i class="ri-notification-4-line"></i> Notifier le résultat
            </a>
            """,
            html=True,
            count=1,
        )
        url = reverse(
            "siae_evaluations_views:institution_evaluated_siae_detail",
            kwargs={"evaluated_siae_pk": evaluated_siae.pk},
        )
        self.assertContains(
            response,
            f'<a href="{url}" class="btn btn-outline-primary btn-sm">Voir le résultat</a>',
            html=True,
            count=1,
        )

    def test_siae_incomplete_refused_can_be_notified_after_review(self):
        evaluated_siae = EvaluatedSiaeFactory(
            evaluation_campaign__institution=self.institution,
            evaluation_campaign__evaluations_asked_at=timezone.now() - relativedelta(weeks=10),
            evaluation_campaign__ended_at=timezone.now(),
            reviewed_at=timezone.now() - relativedelta(weeks=4),
        )
        self.client.force_login(self.user)
        response = self.client.get(
            reverse(
                "siae_evaluations_views:institution_evaluated_siae_list",
                kwargs={"evaluation_campaign_pk": evaluated_siae.evaluation_campaign_id},
            )
        )
        self.assertContains(response, "Liste des Siae contrôlées", html=True, count=1)
        self.assertContains(
            response,
            """
            <p class="badge badge-pill badge-accent-03 text-primary float-right">
                <i class="ri-arrow-right-circle-line mr-1"></i> Notification à faire
            </p>
            """,
            html=True,
            count=1,
        )
        notify_url = reverse(
            "siae_evaluations_views:institution_evaluated_siae_notify",
            kwargs={"evaluated_siae_pk": evaluated_siae.pk},
        )
        self.assertContains(
            response,
            f"""
            <a class="btn btn-primary btn-sm ml-1" href="{notify_url}">
                <i class="ri-notification-4-line"></i> Notifier le résultat
            </a>
            """,
            html=True,
            count=1,
        )
        url = reverse(
            "siae_evaluations_views:institution_evaluated_siae_detail",
            kwargs={"evaluated_siae_pk": evaluated_siae.pk},
        )
        self.assertContains(
            response,
            f'<a href="{url}" class="btn btn-outline-primary btn-sm">Voir le résultat</a>',
            html=True,
            count=1,
        )

    def test_notified_siae(self):
        evaluated_siae = EvaluatedSiaeFactory(
            complete=True,
            job_app__criteria__review_state=evaluation_enums.EvaluatedJobApplicationsState.REFUSED_2,
            evaluation_campaign__institution=self.institution,
            notified_at=timezone.now(),
            notification_reason=evaluation_enums.EvaluatedSiaeNotificationReason.INVALID_PROOF,
            notification_text="A envoyé une photo de son chat.",
        )
        self.client.force_login(self.user)
        response = self.client.get(
            reverse(
                "siae_evaluations_views:institution_evaluated_siae_list",
                kwargs={"evaluation_campaign_pk": evaluated_siae.evaluation_campaign_id},
            )
        )
        self.assertContains(response, "Liste des Siae contrôlées", html=True, count=1)
        self.assertContains(
            response,
            """
            <p class="badge badge-pill badge-danger float-right">
                <i class="ri-close-circle-line mr-1"></i> Résultat négatif
            </p>
            """,
            html=True,
            count=1,
        )
        sanction_url = reverse(
            "siae_evaluations_views:institution_evaluated_siae_sanction",
            kwargs={"evaluated_siae_pk": evaluated_siae.pk},
        )
        url = reverse(
            "siae_evaluations_views:institution_evaluated_siae_detail",
            kwargs={"evaluated_siae_pk": evaluated_siae.pk},
        )
        self.assertContains(
            response,
            f"""
            <a class="btn btn-outline-primary btn-sm mr-1" href="{sanction_url}">
                Voir la notification de sanction
            </a>
            <a class="btn btn-outline-primary btn-sm" href="{url}">
                Voir le résultat
            </a>
            """,
            html=True,
            count=1,
        )

    def test_closed_campaign(self):
        evaluated_siae = EvaluatedSiaeFactory(
            complete=True,
            job_app__criteria__review_state=evaluation_enums.EvaluatedJobApplicationsState.ACCEPTED,
            evaluation_campaign__institution=self.institution,
            evaluation_campaign__ended_at=timezone.now() - CAMPAIGN_VIEWABLE_DURATION,
        )
        self.client.force_login(self.user)
        response = self.client.get(
            reverse(
                "siae_evaluations_views:institution_evaluated_siae_list",
                kwargs={"evaluation_campaign_pk": evaluated_siae.evaluation_campaign.pk},
            )
        )
        assert response.status_code == 404

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
        resultat_positif = "Résultat positif"
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
        review_time = timezone.now()
        evaluated_siae.reviewed_at = review_time
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

        evaluated_siae.final_reviewed_at = review_time
        evaluated_siae.save(update_fields=["final_reviewed_at"])
        response = self.client.get(url)
        self.assertEqual(response.status_code, 200)
        self.assertContains(response, resultat_positif)

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
            + 1  # fetch evaluation campaign
            + 3  # fetch evaluated_siae and its prefetch_related eval_job_app & eval_admin_crit
            + 1  # one again institution membership
            + 1  # social account
            + 3  # savepoint, update session, release savepoint
        ):
            response = self.client.get(url)
        self.assertEqual(response.status_code, 200)


class InstitutionEvaluatedSiaeDetailViewTest(TestCase):
    control_text = "Lorsque vous aurez contrôlé"
    submit_text = "Valider"
    forced_positive_text = (
        "Les petits jardins a soumis des justificatifs, mais leur contrôle n’a pas été validé avant la fin de la "
        'campagne “Contrôle Test”, le résultat du contrôle est <b class="text-success">positif</b>.'
    )
    forced_negative_text = (
        "Les petits jardins n’a pas soumis de justificatifs avant la fin de la campagne “Contrôle Test”, le résultat "
        'du contrôle est <b class="text-danger">négatif</b>.'
    )

    def setUp(self):
        membership = InstitutionMembershipFactory(institution__name="DDETS 14")
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
        self.assertNotContains(response, self.submit_text)

    def test_recently_closed_campaign(self):
        evaluated_siae = EvaluatedSiaeFactory(
            complete=True,
            job_app__criteria__review_state=evaluation_enums.EvaluatedJobApplicationsState.ACCEPTED,
            evaluation_campaign__institution=self.institution,
        )
        job_app = evaluated_siae.evaluated_job_applications.get()
        self.client.force_login(self.user)
        response = self.client.get(
            reverse(
                "siae_evaluations_views:institution_evaluated_siae_detail",
                kwargs={"evaluated_siae_pk": evaluated_siae.pk},
            )
        )
        assert response.status_code == 200
        url = reverse(
            "siae_evaluations_views:institution_evaluated_job_application",
            kwargs={"evaluated_job_application_pk": job_app.pk},
        )
        self.assertContains(
            response,
            '<p class="badge badge-pill badge-success float-right">Validé</p>',
            count=1,
        )
        self.assertContains(
            response,
            f"""
            <a href="{url}" class="btn btn-outline-primary btn-sm float-right">
                Revoir ses justificatifs
            </a>
            """,
            html=True,
            count=1,
        )
        self.assertNotContains(response, self.control_text)
        self.assertNotContains(response, self.submit_text)

    def test_campaign_closed_before_final_evaluation_refused_review_not_submitted(self):
        evaluation_campaign = EvaluationCampaignFactory(
            institution=self.institution,
            evaluations_asked_at=timezone.now() - relativedelta(weeks=6),
            ended_at=timezone.now(),
            name="Contrôle Test",
        )
        evaluated_siae = EvaluatedSiaeFactory(evaluation_campaign=evaluation_campaign, siae__name="les petits jardins")
        evaluated_job_app = EvaluatedJobApplicationFactory(evaluated_siae=evaluated_siae)
        EvaluatedAdministrativeCriteriaFactory(
            evaluated_job_application=evaluated_job_app,
            uploaded_at=timezone.now() - relativedelta(days=2),
            submitted_at=timezone.now() - relativedelta(days=1),
            review_state=evaluation_enums.EvaluatedAdministrativeCriteriaState.REFUSED,
        )

        self.client.force_login(self.user)
        response = self.client.get(
            reverse(
                "siae_evaluations_views:institution_evaluated_siae_detail",
                kwargs={"evaluated_siae_pk": evaluated_siae.pk},
            )
        )
        self.assertContains(
            response,
            '<p class="badge badge-pill badge-danger float-right">Problème constaté</p>',
            html=True,
            count=1,
        )
        self.assertNotContains(response, self.control_text)
        self.assertNotContains(response, self.submit_text)
        # Was not reviewed by the institution, assume valid (following rules in
        # most administrations).
        self.assertContains(response, self.forced_positive_text, html=True, count=1)
        self.assertNotContains(response, self.forced_negative_text)

    def test_campaign_closed_before_final_evaluation_adversarial_stage_review_not_submitted(self):
        evaluation_campaign = EvaluationCampaignFactory(
            institution=self.institution,
            evaluations_asked_at=timezone.now() - relativedelta(weeks=6),
            ended_at=timezone.now(),
            name="Contrôle Test",
        )
        evaluated_siae = EvaluatedSiaeFactory(
            evaluation_campaign=evaluation_campaign,
            siae__name="les petits jardins",
            # Starting the adversarial phase for a campaign sets reviewed_at.
            reviewed_at=timezone.now() - relativedelta(days=4),
        )
        evaluated_job_app = EvaluatedJobApplicationFactory(evaluated_siae=evaluated_siae)
        EvaluatedAdministrativeCriteriaFactory(
            evaluated_job_application=evaluated_job_app,
            uploaded_at=timezone.now() - relativedelta(days=2),
            submitted_at=timezone.now() - relativedelta(days=1),
            review_state=evaluation_enums.EvaluatedAdministrativeCriteriaState.REFUSED,
        )

        self.client.force_login(self.user)
        response = self.client.get(
            reverse(
                "siae_evaluations_views:institution_evaluated_siae_detail",
                kwargs={"evaluated_siae_pk": evaluated_siae.pk},
            )
        )
        self.assertContains(
            response,
            '<p class="badge badge-pill badge-danger float-right">Problème constaté</p>',
            html=True,
            count=1,
        )
        self.assertNotContains(response, self.control_text)
        self.assertNotContains(response, self.submit_text)
        # Was not reviewed by the institution, assume valid (following rules in
        # most administrations).
        self.assertContains(response, self.forced_positive_text, html=True, count=1)
        self.assertNotContains(response, self.forced_negative_text)

    def test_campaign_closed_before_final_evaluation_no_docs(self):
        evaluation_campaign = EvaluationCampaignFactory(
            institution=self.institution,
            evaluations_asked_at=timezone.now() - relativedelta(weeks=6),
            ended_at=timezone.now(),
            name="Contrôle Test",
        )
        evaluated_siae = EvaluatedSiaeFactory(evaluation_campaign=evaluation_campaign, siae__name="les petits jardins")
        EvaluatedJobApplicationFactory(evaluated_siae=evaluated_siae)

        self.client.force_login(self.user)
        response = self.client.get(
            reverse(
                "siae_evaluations_views:institution_evaluated_siae_detail",
                kwargs={"evaluated_siae_pk": evaluated_siae.pk},
            )
        )
        self.assertContains(
            response,
            '<p class="badge badge-pill badge-emploi float-right">En attente</p>',
            html=True,
            count=1,
        )
        self.assertNotContains(response, self.control_text)
        self.assertNotContains(response, self.submit_text)
        self.assertNotContains(response, self.forced_positive_text)
        self.assertContains(response, self.forced_negative_text, html=True, count=1)

    def test_closed_campaign(self):
        evaluated_siae = EvaluatedSiaeFactory(
            complete=True,
            job_app__criteria__review_state=evaluation_enums.EvaluatedJobApplicationsState.ACCEPTED,
            evaluation_campaign__institution=self.institution,
            evaluation_campaign__ended_at=timezone.now() - CAMPAIGN_VIEWABLE_DURATION,
        )
        self.client.force_login(self.user)
        response = self.client.get(
            reverse(
                "siae_evaluations_views:institution_evaluated_siae_detail",
                kwargs={"evaluated_siae_pk": evaluated_siae.pk},
            )
        )
        assert response.status_code == 404

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
        validation_button_disabled = f"""
            <button class="btn btn-outline-primary disabled btn-sm float-right">
                {self.submit_text}
            </button>"""
        validation_button = f"""
            <button class="btn btn-primary btn-sm float-right">
                {self.submit_text}
            </button>"""
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
        self.assertContains(response, self.control_text)

        # EvaluatedAdministrativeCriteria uploaded
        evaluated_administrative_criteria = evaluated_job_application.evaluated_administrative_criteria.first()
        evaluated_administrative_criteria.proof_url = "https://server.com/rocky-balboa.pdf"
        evaluated_administrative_criteria.save(update_fields=["proof_url"])
        response = self.client.get(url)
        self.assertEqual(response.status_code, 200)
        self.assertContains(response, back_url)
        self.assertContains(response, "Justificatifs téléversés")
        self.assertContains(response, validation_button_disabled, html=True, count=1)
        self.assertContains(response, self.control_text)

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
        self.assertContains(response, validation_button_disabled, html=True, count=1)
        self.assertNotContains(response, message)
        self.assertContains(response, self.control_text)

        # EvaluatedAdministrativeCriteria Accepted
        evaluated_administrative_criteria.review_state = evaluation_enums.EvaluatedAdministrativeCriteriaState.ACCEPTED
        evaluated_administrative_criteria.save(update_fields=["review_state"])
        self.assertContains(response, self.control_text)

        response = self.client.get(url)
        self.assertEqual(response.status_code, 200)
        self.assertContains(response, evaluated_job_application_url)
        self.assertContains(response, back_url)
        self.assertContains(response, validation_button, html=True, count=2)
        self.assertNotContains(response, message)
        self.assertContains(response, self.control_text)

        # EvaluatedAdministrativeCriteria Accepted & Reviewed
        evaluated_siae.reviewed_at = timezone.now()
        evaluated_siae.final_reviewed_at = timezone.now()
        evaluated_siae.save(update_fields=["reviewed_at", "final_reviewed_at"])
        self.assertContains(response, self.control_text)

        response = self.client.get(url)
        self.assertEqual(response.status_code, 200)
        self.assertContains(response, evaluated_job_application_url)
        self.assertContains(response, back_url)
        self.assertNotContains(response, self.submit_text)
        self.assertContains(response, message)
        self.assertNotContains(response, self.control_text)

        # EvaluatedAdministrativeCriteria Refused
        evaluated_administrative_criteria.review_state = evaluation_enums.EvaluatedAdministrativeCriteriaState.REFUSED
        evaluated_administrative_criteria.save(update_fields=["review_state"])
        evaluated_siae.reviewed_at = None
        evaluated_siae.final_reviewed_at = None
        evaluated_siae.save(update_fields=["reviewed_at", "final_reviewed_at"])

        response = self.client.get(url)
        self.assertEqual(response.status_code, 200)
        self.assertContains(response, evaluated_job_application_url)
        self.assertContains(response, back_url)
        self.assertContains(response, validation_button, html=True, count=2)
        self.assertNotContains(response, message)
        self.assertContains(response, self.control_text)

        # EvaluatedAdministrativeCriteria Refused & Reviewed
        evaluated_siae.reviewed_at = timezone.now()
        evaluated_siae.save(update_fields=["reviewed_at"])

        response = self.client.get(url)
        self.assertEqual(response.status_code, 200)
        self.assertContains(response, evaluated_job_application_url)
        self.assertContains(response, back_url)
        self.assertContains(response, validation_button_disabled, html=True, count=1)
        self.assertContains(response, message)
        self.assertContains(response, self.control_text)

        # Adversarial phase

        adversarial_phase_start = evaluated_siae.reviewed_at

        # EvaluatedAdministrativeCriteriaState.UPLOADED (again)
        evaluated_administrative_criteria.proof_url = "https://server.com/rocky-balboa.pdf"
        evaluated_administrative_criteria.uploaded_at = timezone.now()
        evaluated_administrative_criteria.review_state = evaluation_enums.EvaluatedAdministrativeCriteriaState.PENDING
        evaluated_administrative_criteria.submitted_at = None
        evaluated_administrative_criteria.save(
            update_fields=["proof_url", "review_state", "submitted_at", "uploaded_at"]
        )
        response = self.client.get(url)
        self.assertEqual(response.status_code, 200)
        self.assertContains(response, validation_button_disabled, html=True, count=1)
        self.assertContains(response, back_url)
        self.assertContains(response, "Justificatifs téléversés")
        self.assertContains(response, self.control_text)

        # EvaluatedAdministrativeCriteriaState.SUBMITTED (again)
        evaluated_administrative_criteria.submitted_at = timezone.now()
        evaluated_administrative_criteria.save(update_fields=["submitted_at"])
        response = self.client.get(url)
        self.assertEqual(response.status_code, 200)
        self.assertContains(response, evaluated_job_application_url)
        self.assertContains(response, back_url)
        self.assertNotContains(response, "Documents téléversés")
        self.assertNotContains(response, "En attente")
        self.assertNotContains(response, "Problème constaté")
        self.assertContains(response, "Nouveaux justificatifs à traiter")
        self.assertContains(response, validation_button_disabled, html=True, count=1)
        self.assertNotContains(response, message)
        self.assertContains(response, self.control_text)

        # EvaluatedAdministrativeCriteriaState.ACCEPTED (again)
        evaluated_administrative_criteria.review_state = evaluation_enums.EvaluatedAdministrativeCriteriaState.ACCEPTED
        evaluated_administrative_criteria.save(update_fields=["review_state"])

        response = self.client.get(url)
        self.assertEqual(response.status_code, 200)
        self.assertContains(response, evaluated_job_application_url)
        self.assertContains(response, back_url)
        self.assertContains(response, validation_button, html=True, count=2)
        self.assertNotContains(response, message)
        self.assertContains(response, self.control_text)

        # EvaluatedAdministrativeCriteria Accepted & Reviewed (again)
        now = timezone.now()
        evaluated_siae.reviewed_at = now
        evaluated_siae.final_reviewed_at = now
        evaluated_siae.save(update_fields=["reviewed_at", "final_reviewed_at"])

        response = self.client.get(url)
        self.assertEqual(response.status_code, 200)
        self.assertContains(response, evaluated_job_application_url)
        self.assertContains(response, back_url)
        self.assertNotContains(response, self.submit_text)
        self.assertContains(response, message)
        self.assertNotContains(response, self.control_text)

        # EvaluatedAdministrativeCriteria Refused (again)
        evaluated_siae.reviewed_at = adversarial_phase_start
        evaluated_siae.final_reviewed_at = None
        evaluated_siae.save(update_fields=["final_reviewed_at", "reviewed_at"])
        evaluated_administrative_criteria.review_state = (
            evaluation_enums.EvaluatedAdministrativeCriteriaState.REFUSED_2
        )
        evaluated_administrative_criteria.save(update_fields=["review_state"])

        response = self.client.get(url)
        self.assertEqual(response.status_code, 200)
        self.assertContains(response, evaluated_job_application_url)
        self.assertContains(response, back_url)
        self.assertContains(response, validation_button, html=True, count=2)
        self.assertNotContains(response, message)
        self.assertContains(response, self.control_text)

        # EvaluatedAdministrativeCriteria Refused & Reviewed (again)
        evaluated_siae.final_reviewed_at = timezone.now()
        evaluated_siae.save(update_fields=["final_reviewed_at"])

        response = self.client.get(url)
        self.assertEqual(response.status_code, 200)
        self.assertContains(response, evaluated_job_application_url)
        self.assertContains(response, back_url)
        self.assertNotContains(response, self.submit_text)
        self.assertNotContains(response, message)
        self.assertNotContains(response, self.control_text)
        self.assertContains(
            response, '<p class="badge badge-pill badge-danger float-right">Problème constaté</p>', count=1
        )

    def test_notification_pending_show_view_evaluated_admin_criteria(self):
        self.client.force_login(self.user)
        evaluated_siae = EvaluatedSiaeFactory(
            complete=True,
            job_app__criteria__review_state=evaluation_enums.EvaluatedJobApplicationsState.REFUSED_2,
            evaluation_campaign__institution=self.institution,
        )
        evaluated_job_application = evaluated_siae.evaluated_job_applications.first()
        evaluated_job_application_url = reverse(
            "siae_evaluations_views:institution_evaluated_job_application",
            kwargs={"evaluated_job_application_pk": evaluated_job_application.pk},
        )
        response = self.client.get(
            reverse(
                "siae_evaluations_views:institution_evaluated_siae_detail",
                kwargs={"evaluated_siae_pk": evaluated_siae.pk},
            )
        )
        self.assertContains(
            response,
            f"""
            <a href="{evaluated_job_application_url}" class="btn btn-outline-primary btn-sm float-right">
                Revoir ses justificatifs
            </a>
            """,
            html=True,
            count=1,
        )

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

    def test_job_application_adversarial_stage(self):
        reviewed_at = timezone.now()
        evaluated_job_application = EvaluatedJobApplicationFactory(
            evaluated_siae__reviewed_at=reviewed_at,
            evaluated_siae__evaluation_campaign__institution=self.institution,
            evaluated_siae__evaluation_campaign__evaluations_asked_at=timezone.now() - relativedelta(days=7),
        )
        EvaluatedAdministrativeCriteriaFactory(
            evaluated_job_application=evaluated_job_application,
            uploaded_at=reviewed_at - relativedelta(days=1, hours=1),
            submitted_at=reviewed_at - relativedelta(days=1),
            review_state=evaluation_enums.EvaluatedAdministrativeCriteriaState.REFUSED,
        )
        self.client.force_login(self.user)
        response = self.client.get(
            reverse(
                "siae_evaluations_views:institution_evaluated_siae_detail",
                kwargs={"evaluated_siae_pk": evaluated_job_application.evaluated_siae_id},
            )
        )
        self.assertContains(response, "Phase contradictoire - En attente", html=True)
        self.assertNotContains(response, self.forced_negative_text)

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


class InstitutionEvaluatedSiaeNotifyViewTest(TestCase):
    def test_access_other_institution(self):
        membership = InstitutionMembershipFactory(institution__name="DDETS 14")
        user = membership.user
        evaluated_siae = EvaluatedSiaeFactory.create(
            # Evaluation of another institution.
            complete=True,
            job_app__criteria__review_state=evaluation_enums.EvaluatedJobApplicationsState.REFUSED_2,
        )
        self.client.force_login(user)
        response = self.client.get(
            reverse(
                "siae_evaluations_views:institution_evaluated_siae_notify",
                kwargs={"evaluated_siae_pk": evaluated_siae.pk},
            )
        )
        assert response.status_code == 404

    def test_access_incomplete_on_active_campaign(self):
        membership = InstitutionMembershipFactory(institution__name="DDETS 14")
        user = membership.user
        evaluated_siae = EvaluatedSiaeFactory.create()
        self.client.force_login(user)
        response = self.client.get(
            reverse(
                "siae_evaluations_views:institution_evaluated_siae_notify",
                kwargs={"evaluated_siae_pk": evaluated_siae.pk},
            )
        )
        assert response.status_code == 404

    def test_access_notified_institution(self):
        membership = InstitutionMembershipFactory(institution__name="DDETS 14")
        user = membership.user
        institution = membership.institution
        evaluated_siae = EvaluatedSiaeFactory.create(
            evaluation_campaign__institution=institution,
            complete=True,
            job_app__criteria__review_state=evaluation_enums.EvaluatedJobApplicationsState.REFUSED_2,
            notified_at=timezone.now(),
            notification_reason=evaluation_enums.EvaluatedSiaeNotificationReason.INVALID_PROOF,
            notification_text="A envoyé une photo de son chat.",
        )
        self.client.force_login(user)
        response = self.client.get(
            reverse(
                "siae_evaluations_views:institution_evaluated_siae_notify",
                kwargs={"evaluated_siae_pk": evaluated_siae.pk},
            )
        )
        assert response.status_code == 404

    def test_access_final_refused_control_active_campaign(self):
        membership = InstitutionMembershipFactory(institution__name="DDETS 14")
        user = membership.user
        institution = membership.institution
        evaluated_siae = EvaluatedSiaeFactory.create(
            evaluation_campaign__institution=institution,
            complete=True,
            job_app__criteria__review_state=evaluation_enums.EvaluatedJobApplicationsState.REFUSED_2,
        )
        self.client.force_login(user)
        response = self.client.get(
            reverse(
                "siae_evaluations_views:institution_evaluated_siae_notify",
                kwargs={"evaluated_siae_pk": evaluated_siae.pk},
            )
        )
        self.assertContains(response, f"Notifier la sanction du contrôle pour {evaluated_siae.siae.name}")

    def test_access_incomplete_evaluation_closed_campaign(self):
        membership = InstitutionMembershipFactory(institution__name="DDETS 14")
        user = membership.user
        institution = membership.institution
        evaluated_siae = EvaluatedSiaeFactory.create(
            evaluation_campaign__institution=institution,
            evaluation_campaign__evaluations_asked_at=timezone.now() - relativedelta(weeks=4),
            evaluation_campaign__ended_at=timezone.now(),
        )
        self.client.force_login(user)
        response = self.client.get(
            reverse(
                "siae_evaluations_views:institution_evaluated_siae_notify",
                kwargs={"evaluated_siae_pk": evaluated_siae.pk},
            )
        )
        self.assertContains(response, f"Notifier la sanction du contrôle pour {evaluated_siae.siae.name}")

    def test_access_long_closed_campaign(self):
        membership = InstitutionMembershipFactory(institution__name="DDETS 14")
        user = membership.user
        institution = membership.institution
        evaluated_siae = EvaluatedSiaeFactory.create(
            evaluation_campaign__institution=institution,
            evaluation_campaign__ended_at=timezone.now() - CAMPAIGN_VIEWABLE_DURATION,
        )
        self.client.force_login(user)
        response = self.client.get(
            reverse(
                "siae_evaluations_views:institution_evaluated_siae_notify",
                kwargs={"evaluated_siae_pk": evaluated_siae.pk},
            )
        )
        assert response.status_code == 404

    @freeze_time("2022-10-24 11:11:00")
    def test_post(self):
        membership = InstitutionMembershipFactory(institution__name="DDETS 14")
        user = membership.user
        institution = membership.institution
        siae_membership = SiaeMembershipFactory(siae__name="Les petits jardins", user__email="siae@mailinator.com")
        evaluated_siae = EvaluatedSiaeFactory.create(
            siae=siae_membership.siae,
            evaluation_campaign__institution=institution,
            evaluation_campaign__name="Campagne 2022",
            evaluation_campaign__evaluations_asked_at=timezone.now() - relativedelta(weeks=4),
            evaluation_campaign__ended_at=timezone.now() - relativedelta(hours=1),
        )
        self.client.force_login(user)
        text = (
            "Votre chat a mangé le justificatif, vous devrez suivre une formation protection contre les risques "
            "félins."
        )
        response = self.client.post(
            reverse(
                "siae_evaluations_views:institution_evaluated_siae_notify",
                kwargs={"evaluated_siae_pk": evaluated_siae.pk},
            ),
            data={
                "notification_reason": "MISSING_PROOF",
                "notification_text": text,
            },
        )
        assert list(messages.get_messages(response.wsgi_request)) == [
            Message(messages.SUCCESS, "Les petits jardins a bien été notifiée de la sanction."),
        ]
        self.assertRedirects(
            response,
            reverse(
                "siae_evaluations_views:institution_evaluated_siae_list",
                kwargs={"evaluation_campaign_pk": evaluated_siae.evaluation_campaign_id},
            ),
        )
        evaluated_siae.refresh_from_db()
        assert evaluated_siae.notified_at == timezone.now()
        assert evaluated_siae.notification_reason == "MISSING_PROOF"
        assert evaluated_siae.notification_text == text
        [email] = mail.outbox
        assert email.to == ["siae@mailinator.com"]
        assert email.subject == f"Résultat du contrôle - EI Les petits jardins ID-{evaluated_siae.siae_id}"
        assert "Le résultat de la campagne de contrôle a posteriori “Campagne 2022” est disponible." in email.body
        assert "Voir le résultat du contrôle “Campagne 2022”" in email.body
        assert "http://127.0.0.1:8000/dashboard/\n" in email.body

    def test_post_missing_data(self):
        membership = InstitutionMembershipFactory(institution__name="DDETS 14")
        user = membership.user
        institution = membership.institution
        evaluated_siae = EvaluatedSiaeFactory.create(
            siae__name="Les petits jardins",
            evaluation_campaign__institution=institution,
            evaluation_campaign__evaluations_asked_at=timezone.now() - relativedelta(weeks=4),
            evaluation_campaign__ended_at=timezone.now() - relativedelta(hours=1),
        )
        self.client.force_login(user)
        response = self.client.post(
            reverse(
                "siae_evaluations_views:institution_evaluated_siae_notify",
                kwargs={"evaluated_siae_pk": evaluated_siae.pk},
            ),
            data={
                "notification_reason": "invalid data",
                "notification_text": "",
            },
        )
        placeholder = (
            "Merci de renseigner ici les raisons qui ont mené à un contrôle a posteriori des auto-prescriptions "
            "non conforme."
        )
        self.assertContains(
            response,
            f"""
            <div class="form-group is-invalid form-group-required">
                <label for="id_notification_text">Commentaire</label>
                <textarea name="notification_text" cols="40" rows="10"
                    placeholder="{placeholder}"
                    class="form-control is-invalid"
                    title=""
                    required
                    id="id_notification_text">
                </textarea>
                <div class="invalid-feedback">Ce champ est obligatoire.</div>
            </div>
            """,
            html=True,
            count=1,
        )
        self.assertContains(
            response,
            '<div class="form-group is-invalid form-group-required"><label>Raison principale</label>',
            count=1,
        )
        self.assertContains(
            response,
            '<div class="invalid-feedback">Sélectionnez un choix valide. invalid data n’en fait pas partie.</div>',
            count=1,
        )


class InstitutionEvaluatedJobApplicationViewTest(TestCase):
    btn_modifier_html = """
        <button class="btn btn-outline-primary btn-sm float-right" title="Modifier l'état de ce justificatif">
            Modifier
        </button>
    """
    save_text = "Enregistrer le commentaire"

    def setUp(self):
        membership = InstitutionMembershipFactory()
        self.user = membership.user
        self.institution = membership.institution

    @staticmethod
    def accept_url(criteria):
        return reverse(
            "siae_evaluations_views:institution_evaluated_administrative_criteria",
            kwargs={
                "evaluated_administrative_criteria_pk": criteria.pk,
                "action": "accept",
            },
        )

    @staticmethod
    def refuse_url(criteria):
        return reverse(
            "siae_evaluations_views:institution_evaluated_administrative_criteria",
            kwargs={
                "evaluated_administrative_criteria_pk": criteria.pk,
                "action": "refuse",
            },
        )

    @staticmethod
    def reinit_url(criteria):
        return reverse(
            "siae_evaluations_views:institution_evaluated_administrative_criteria",
            kwargs={
                "evaluated_administrative_criteria_pk": criteria.pk,
                "action": "reinit",
            },
        )

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

    def test_recently_closed_campaign(self):
        evaluated_siae = EvaluatedSiaeFactory(
            complete=True,
            job_app__criteria__review_state=evaluation_enums.EvaluatedJobApplicationsState.ACCEPTED,
            evaluation_campaign__institution=self.institution,
        )
        job_app = evaluated_siae.evaluated_job_applications.get()
        self.client.force_login(self.user)
        response = self.client.get(
            reverse(
                "siae_evaluations_views:institution_evaluated_job_application",
                kwargs={"evaluated_job_application_pk": job_app.pk},
            )
        )
        assert response.status_code == 200
        self.assertContains(
            response,
            """
            <a href="https://server.com/rocky-balboa.pdf"
               rel="noopener"
               target="_blank"
               title="Revoir ce justificatif (ouverture dans un nouvel onglet)"
            >
                Revoir ce justificatif
            </a>
            """,
            html=True,
            count=1,
        )

    def test_post_recently_closed_campaign(self):
        evaluated_siae = EvaluatedSiaeFactory(
            complete=True,
            job_app__criteria__review_state=evaluation_enums.EvaluatedJobApplicationsState.ACCEPTED,
            evaluation_campaign__institution=self.institution,
        )
        job_app = evaluated_siae.evaluated_job_applications.get()
        self.client.force_login(self.user)
        response = self.client.post(
            reverse(
                "siae_evaluations_views:institution_evaluated_job_application",
                kwargs={"evaluated_job_application_pk": job_app.pk},
            ),
            data={"labor_inspector_explanation": "Test"},
        )
        assert response.status_code == 404

    def test_access_closed_campaign(self):
        evaluated_siae = EvaluatedSiaeFactory(
            complete=True,
            job_app__criteria__review_state=evaluation_enums.EvaluatedJobApplicationsState.ACCEPTED,
            evaluation_campaign__institution=self.institution,
            evaluation_campaign__ended_at=timezone.now() - CAMPAIGN_VIEWABLE_DURATION,
        )
        job_app = evaluated_siae.evaluated_job_applications.get()
        self.client.force_login(self.user)
        response = self.client.get(
            reverse(
                "siae_evaluations_views:institution_evaluated_job_application",
                kwargs={"evaluated_job_application_pk": job_app.pk},
            )
        )
        assert response.status_code == 404

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
        self.assertContains(response, self.save_text, count=1)

    def test_get_before_new_criteria_submitted(self):
        now = timezone.now()
        evaluated_job_application = EvaluatedJobApplicationFactory(
            evaluated_siae__evaluation_campaign__evaluations_asked_at=now - relativedelta(days=10),
            evaluated_siae__evaluation_campaign__institution=self.institution,
            evaluated_siae__reviewed_at=now - relativedelta(days=3),
        )
        EvaluatedAdministrativeCriteriaFactory(
            evaluated_job_application=evaluated_job_application,
            uploaded_at=now - relativedelta(days=2),
            # Not submitted.
        )
        self.client.force_login(self.user)
        response = self.client.get(
            reverse(
                "siae_evaluations_views:institution_evaluated_job_application",
                kwargs={"evaluated_job_application_pk": evaluated_job_application.pk},
            )
        )
        self.assertNotContains(response, self.btn_modifier_html, html=True)

    def test_can_modify_during_adversarial_stage_review(self):
        now = timezone.now()
        evaluated_job_application = EvaluatedJobApplicationFactory(
            evaluated_siae__evaluation_campaign__evaluations_asked_at=now - relativedelta(days=10),
            evaluated_siae__evaluation_campaign__institution=self.institution,
            evaluated_siae__reviewed_at=now - relativedelta(days=3),
        )
        EvaluatedAdministrativeCriteriaFactory(
            evaluated_job_application=evaluated_job_application,
            uploaded_at=now - relativedelta(days=2),
            submitted_at=now - relativedelta(days=1),
            review_state=evaluation_enums.EvaluatedAdministrativeCriteriaState.ACCEPTED,
        )

        self.client.force_login(self.user)
        response = self.client.get(
            reverse(
                "siae_evaluations_views:institution_evaluated_job_application",
                kwargs={"evaluated_job_application_pk": evaluated_job_application.pk},
            )
        )
        self.assertContains(response, self.btn_modifier_html, html=True, count=1)

    def test_evaluations_from_previous_campaigns_read_only(self):
        evaluated_siae = EvaluatedSiaeFactory(
            complete=True,
            job_app__criteria__review_state=evaluation_enums.EvaluatedJobApplicationsState.ACCEPTED,
            evaluation_campaign__institution=self.institution,
        )
        past_job_application = evaluated_siae.evaluated_job_applications.get()

        self.client.force_login(self.user)
        response = self.client.get(
            reverse(
                "siae_evaluations_views:institution_evaluated_job_application",
                kwargs={"evaluated_job_application_pk": past_job_application.pk},
            )
        )
        assert response.status_code == 200
        self.assertNotContains(response, self.save_text)
        self.assertContains(
            response,
            """
            <a href="https://server.com/rocky-balboa.pdf"
               rel="noopener"
               target="_blank"
               title="Revoir ce justificatif (ouverture dans un nouvel onglet)"
            >
                Revoir ce justificatif
            </a>
            """,
            html=True,
            count=1,
        )

    def test_post_to_evaluations_from_previous_campaigns(self):
        evaluated_siae = EvaluatedSiaeFactory(
            complete=True,
            job_app__criteria__review_state=evaluation_enums.EvaluatedJobApplicationsState.ACCEPTED,
            evaluation_campaign__institution=self.institution,
        )
        past_job_application = evaluated_siae.evaluated_job_applications.get()

        self.client.force_login(self.user)
        response = self.client.post(
            reverse(
                "siae_evaluations_views:institution_evaluated_job_application",
                kwargs={"evaluated_job_application_pk": past_job_application.pk},
            ),
            data={"labor_inspector_explanation": "Invalide !"},
        )
        assert response.status_code == 404

    def test_criterion_validation(self):
        self.client.force_login(self.user)

        # fixme vincentporte : use EvaluatedAdministrativeCriteria instead
        evaluated_administrative_criteria = get_evaluated_administrative_criteria(self.institution)

        refuse_url = self.refuse_url(evaluated_administrative_criteria)
        accepte_url = self.accept_url(evaluated_administrative_criteria)
        reinit_url = self.reinit_url(evaluated_administrative_criteria)
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
        self.assertContains(
            response, '<p class="text-success"><i class="ri-checkbox-circle-line"></i> Validé</p>', html=True
        )

        # refused
        evaluated_administrative_criteria.review_state = evaluation_enums.EvaluatedAdministrativeCriteriaState.REFUSED
        evaluated_administrative_criteria.save(update_fields=["review_state"])

        response = self.client.get(url_view)
        self.assertEqual(response.status_code, 200)
        self.assertNotContains(response, refuse_url)
        self.assertNotContains(response, accepte_url)
        self.assertContains(response, reinit_url)
        self.assertContains(
            response, '<p class="text-danger"><i class="ri-indeterminate-circle-line"></i> Refusé</p>', html=True
        )

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

    def test_post_on_closed_campaign(self):
        self.client.force_login(self.user)
        evaluated_siae = EvaluatedSiaeFactory(
            complete=True,
            job_app__criteria__review_state=evaluation_enums.EvaluatedJobApplicationsState.ACCEPTED,
            evaluation_campaign__institution=self.institution,
        )
        job_app = evaluated_siae.evaluated_job_applications.get()
        response = self.client.post(
            reverse(
                "siae_evaluations_views:institution_evaluated_job_application",
                kwargs={"evaluated_job_application_pk": job_app.pk},
            ),
            data={"labor_inspector_explanation": "updated"},
        )
        assert response.status_code == 404
        job_app.refresh_from_db()
        # New explanation ignored.
        assert job_app.labor_inspector_explanation == ""

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
