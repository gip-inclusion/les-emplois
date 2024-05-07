import datetime

import html5lib
import pytest
from dateutil.relativedelta import relativedelta
from django.contrib import messages
from django.contrib.messages.test import MessagesTestMixin
from django.core import mail
from django.urls import reverse
from django.utils import dateformat, timezone
from freezegun import freeze_time

from itou.eligibility.models import AdministrativeCriteria, EligibilityDiagnosis
from itou.siae_evaluations import enums as evaluation_enums
from itou.siae_evaluations.constants import CAMPAIGN_VIEWABLE_DURATION
from itou.siae_evaluations.models import (
    EvaluatedAdministrativeCriteria,
    EvaluatedJobApplication,
    EvaluationCampaign,
    Sanctions,
)
from itou.utils.templatetags.format_filters import format_approval_number, format_phone
from itou.utils.types import InclusiveDateRange
from itou.www.siae_evaluations_views.forms import LaborExplanationForm, SetChosenPercentForm
from tests.companies.factories import CompanyFactory, CompanyMembershipFactory
from tests.files.factories import FileFactory
from tests.institutions.factories import InstitutionMembershipFactory
from tests.job_applications.factories import JobApplicationFactory
from tests.siae_evaluations.factories import (
    EvaluatedAdministrativeCriteriaFactory,
    EvaluatedJobApplicationFactory,
    EvaluatedSiaeFactory,
    EvaluationCampaignFactory,
)
from tests.users.factories import JobSeekerFactory
from tests.utils.test import BASE_NUM_QUERIES, TestCase, parse_response_to_soup


# fixme vincentporte : convert this method into factory
def create_evaluated_siae_consistent_datas(evaluation_campaign, extra_evaluated_siae_kwargs=None):
    membership = CompanyMembershipFactory(company__department=evaluation_campaign.institution.department)
    user = membership.user
    siae = membership.company

    job_seeker = JobSeekerFactory()

    administrative_criteria = AdministrativeCriteria.objects.get(pk=1)
    eligibility_diagnosis = EligibilityDiagnosis.create_diagnosis(
        job_seeker, author=user, author_organization=siae, administrative_criteria=[administrative_criteria]
    )

    job_application = JobApplicationFactory(
        with_approval=True,
        to_company=siae,
        sender_company=siae,
        eligibility_diagnosis=eligibility_diagnosis,
        hiring_start_at=timezone.now() - relativedelta(months=2),
    )

    evaluated_siae = EvaluatedSiaeFactory(
        evaluation_campaign=evaluation_campaign, siae=siae, **(extra_evaluated_siae_kwargs or {})
    )
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
        super().setUp()
        membership = InstitutionMembershipFactory(institution__name="DDETS Ille et Vilaine")
        self.user = membership.user
        self.institution = membership.institution
        self.url = reverse("siae_evaluations_views:samples_selection")

    def test_access(self):
        response = self.client.get(self.url)
        assert response.status_code == 302

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

        assert response.context["institution"] == self.institution
        assert response.context["evaluation_campaign"] == evaluation_campaign
        assert response.context["back_url"] == back_url

    def test_form(self):
        evaluation_campaign = EvaluationCampaignFactory(institution=self.institution)

        form_data = {"chosen_percent": evaluation_enums.EvaluationChosenPercent.DEFAULT}
        form = SetChosenPercentForm(instance=evaluation_campaign, data=form_data)
        assert form.is_valid()

        form_data = {"chosen_percent": evaluation_enums.EvaluationChosenPercent.MIN}
        form = SetChosenPercentForm(instance=evaluation_campaign, data=form_data)
        assert form.is_valid()

        form_data = {"chosen_percent": evaluation_enums.EvaluationChosenPercent.MIN - 1}
        form = SetChosenPercentForm(instance=evaluation_campaign, data=form_data)
        assert not form.is_valid()
        assert form.errors["chosen_percent"] == ["Assurez-vous que cette valeur est supérieure ou égale à 20."]

        form_data = {"chosen_percent": evaluation_enums.EvaluationChosenPercent.MAX}
        form = SetChosenPercentForm(instance=evaluation_campaign, data=form_data)
        assert form.is_valid()

        form_data = {"chosen_percent": evaluation_enums.EvaluationChosenPercent.MAX + 1}
        form = SetChosenPercentForm(instance=evaluation_campaign, data=form_data)
        assert not form.is_valid()
        assert form.errors["chosen_percent"] == ["Assurez-vous que cette valeur est inférieure ou égale à 40."]

    def test_post_form(self):
        evaluation_campaign = EvaluationCampaignFactory(institution=self.institution)

        self.client.force_login(self.user)
        response = self.client.get(self.url)

        post_data = {"chosen_percent": evaluation_enums.EvaluationChosenPercent.MIN}
        response = self.client.post(self.url, data=post_data)
        assert response.status_code == 302

        updated_evaluation_campaign = EvaluationCampaign.objects.get(pk=evaluation_campaign.pk)
        assert updated_evaluation_campaign.percent_set_at is not None
        assert updated_evaluation_campaign.chosen_percent == post_data["chosen_percent"]


@pytest.mark.usefixtures("unittest_compatibility")
class InstitutionEvaluatedSiaeListViewTest(TestCase):
    def setUp(self):
        super().setUp()
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
        assert response.status_code == 404

        # institution with evaluation_campaign in "institution sets its ratio" phase
        evaluation_campaign = EvaluationCampaignFactory(institution=self.institution)
        evaluated_siae = EvaluatedSiaeFactory(
            evaluation_campaign=evaluation_campaign,
            pk=1000,
            for_snapshot=True,
        )
        evaluated_job_app = EvaluatedJobApplicationFactory(evaluated_siae=evaluated_siae)
        EvaluatedAdministrativeCriteriaFactory.create(evaluated_job_application=evaluated_job_app)
        response = self.client.get(
            reverse(
                "siae_evaluations_views:institution_evaluated_siae_list",
                kwargs={"evaluation_campaign_pk": evaluation_campaign.pk},
            )
        )
        assert response.status_code == 404

        # institution with evaluation_campaign in "siae upload its proofs" phase
        evaluation_campaign.evaluations_asked_at = timezone.now()
        evaluation_campaign.save(update_fields=["evaluations_asked_at"])
        response = self.client.get(
            reverse(
                "siae_evaluations_views:institution_evaluated_siae_list",
                kwargs={"evaluation_campaign_pk": evaluation_campaign.pk},
            )
        )
        self.assertContains(response, "Liste des Siae à contrôler", html=True, count=1)
        state_div = parse_response_to_soup(response, selector=f"#state_of_evaluated_siae-{evaluated_siae.pk}")
        assert str(state_div) == self.snapshot(name="waiting state")

        # institution with ended evaluation_campaign
        evaluation_campaign.ended_at = timezone.now()
        evaluation_campaign.save(update_fields=["ended_at"])
        response = self.client.get(
            reverse(
                "siae_evaluations_views:institution_evaluated_siae_list",
                kwargs={"evaluation_campaign_pk": evaluation_campaign.pk},
            )
        )
        self.assertContains(response, "Liste des Siae contrôlées", html=True, count=1)
        state_div = parse_response_to_soup(response, selector=f"#state_of_evaluated_siae-{evaluated_siae.pk}")
        assert str(state_div) == self.snapshot(name="notification pending state")

    def test_recently_closed_campaign(self):
        evaluated_siae = EvaluatedSiaeFactory(
            pk=1000,
            complete=True,
            for_snapshot=True,
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
        url = reverse(
            "siae_evaluations_views:evaluated_siae_detail",
            kwargs={"evaluated_siae_pk": evaluated_siae.pk},
        )
        self.assertContains(
            response,
            f"""
            <a href="{url}" class="btn btn-outline-primary btn-block w-100 w-md-auto">
              Voir le résultat
            </a>
            """,
            html=True,
            count=1,
        )
        self.assertContains(response, "Liste des Siae contrôlées", html=True, count=1)
        state_div = parse_response_to_soup(response, selector=f"#state_of_evaluated_siae-{evaluated_siae.pk}")
        assert str(state_div) == self.snapshot(name="final accepted state")

    def test_siae_refused_can_be_notified(self):
        evaluated_siae = EvaluatedSiaeFactory(
            pk=1000,
            complete=True,
            for_snapshot=True,
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
        state_div = parse_response_to_soup(response, selector=f"#state_of_evaluated_siae-{evaluated_siae.pk}")
        assert str(state_div) == self.snapshot(name="notification pending state")
        notify_url = reverse(
            "siae_evaluations_views:institution_evaluated_siae_notify_step1",
            kwargs={"evaluated_siae_pk": evaluated_siae.pk},
        )
        self.assertContains(
            response,
            f"""
            <a class="btn btn-primary btn-block w-100 w-md-auto" href="{notify_url}">
                Notifier la sanction
            </a>
            """,
            html=True,
            count=1,
        )
        url = reverse(
            "siae_evaluations_views:evaluated_siae_detail",
            kwargs={"evaluated_siae_pk": evaluated_siae.pk},
        )
        self.assertContains(
            response,
            f"""
            <a href="{url}" class="btn btn-outline-primary btn-block w-100 w-md-auto">
              Voir le résultat
            </a>
            """,
            html=True,
            count=1,
        )

    def test_siae_incomplete_refused_can_be_notified(self):
        evaluated_siae = EvaluatedSiaeFactory(
            pk=1000,
            for_snapshot=True,
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
        state_div = parse_response_to_soup(response, selector=f"#state_of_evaluated_siae-{evaluated_siae.pk}")
        assert str(state_div) == self.snapshot(name="notification pending state")
        notify_url = reverse(
            "siae_evaluations_views:institution_evaluated_siae_notify_step1",
            kwargs={"evaluated_siae_pk": evaluated_siae.pk},
        )
        self.assertContains(
            response,
            f"""
            <a class="btn btn-primary btn-block w-100 w-md-auto" href="{notify_url}">
                Notifier la sanction
            </a>
            """,
            html=True,
            count=1,
        )
        url = reverse(
            "siae_evaluations_views:evaluated_siae_detail",
            kwargs={"evaluated_siae_pk": evaluated_siae.pk},
        )
        self.assertContains(
            response,
            f'<a href="{url}" class="btn btn-outline-primary btn-block w-100 w-md-auto">Voir le résultat</a>',
            html=True,
            count=1,
        )

    def test_siae_incomplete_refused_can_be_notified_after_review(self):
        evaluated_siae = EvaluatedSiaeFactory(
            evaluation_campaign__institution=self.institution,
            evaluation_campaign__evaluations_asked_at=timezone.now() - relativedelta(weeks=10),
            evaluation_campaign__ended_at=timezone.now(),
            pk=1000,
            for_snapshot=True,
            reviewed_at=timezone.now() - relativedelta(weeks=4),
        )
        evaluated_job_app = EvaluatedJobApplicationFactory(evaluated_siae=evaluated_siae)
        EvaluatedAdministrativeCriteriaFactory.create(evaluated_job_application=evaluated_job_app)
        self.client.force_login(self.user)
        response = self.client.get(
            reverse(
                "siae_evaluations_views:institution_evaluated_siae_list",
                kwargs={"evaluation_campaign_pk": evaluated_siae.evaluation_campaign_id},
            )
        )
        self.assertContains(response, "Liste des Siae contrôlées", html=True, count=1)
        state_div = parse_response_to_soup(response, selector=f"#state_of_evaluated_siae-{evaluated_siae.pk}")
        assert str(state_div) == self.snapshot(name="notification pending state")
        notify_url = reverse(
            "siae_evaluations_views:institution_evaluated_siae_notify_step1",
            kwargs={"evaluated_siae_pk": evaluated_siae.pk},
        )
        self.assertContains(
            response,
            f"""
            <a class="btn btn-primary btn-block w-100 w-md-auto" href="{notify_url}">
                Notifier la sanction
            </a>
            """,
            html=True,
            count=1,
        )
        url = reverse(
            "siae_evaluations_views:evaluated_siae_detail",
            kwargs={"evaluated_siae_pk": evaluated_siae.pk},
        )
        self.assertContains(
            response,
            f"""
            <a href="{url}" class="btn btn-outline-primary btn-block w-100 w-md-auto">
              Voir le résultat
            </a>
            """,
            html=True,
            count=1,
        )

    def test_notified_siae(self):
        evaluated_siae = EvaluatedSiaeFactory(
            pk=1000,
            complete=True,
            for_snapshot=True,
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
        state_div = parse_response_to_soup(response, selector=f"#state_of_evaluated_siae-{evaluated_siae.pk}")
        assert str(state_div) == self.snapshot(name="final refused state")
        sanction_url = reverse(
            "siae_evaluations_views:institution_evaluated_siae_sanction",
            kwargs={"evaluated_siae_pk": evaluated_siae.pk},
        )
        url = reverse(
            "siae_evaluations_views:evaluated_siae_detail",
            kwargs={"evaluated_siae_pk": evaluated_siae.pk},
        )
        self.assertContains(
            response,
            f"""
            <a class="btn btn-outline-primary btn-block w-100 w-md-auto" href="{sanction_url}">
                Voir la notification de sanction
            </a>
            <a href="{url}" class="btn btn-outline-primary btn-block w-100 w-md-auto">
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
        assert response.context["back_url"] == reverse("dashboard:index")
        self.assertContains(response, dateformat.format(evaluation_campaign.evaluations_asked_at, "d F Y"))

    def test_siae_infos(self):
        self.client.force_login(self.user)
        evaluation_campaign = EvaluationCampaignFactory(
            institution=self.institution, evaluations_asked_at=timezone.now()
        )
        evaluated_siae = EvaluatedSiaeFactory(
            evaluation_campaign=evaluation_campaign,
            pk=1000,
            for_snapshot=True,
        )
        evaluated_job_app = EvaluatedJobApplicationFactory(evaluated_siae=evaluated_siae)
        EvaluatedAdministrativeCriteriaFactory.create(evaluated_job_application=evaluated_job_app)
        url = reverse(
            "siae_evaluations_views:institution_evaluated_siae_list",
            kwargs={"evaluation_campaign_pk": evaluation_campaign.pk},
        )

        response = self.client.get(url)
        self.assertContains(response, evaluated_siae)
        state_div = parse_response_to_soup(response, selector=f"#state_of_evaluated_siae-{evaluated_siae.pk}")
        assert str(state_div) == self.snapshot(name="waiting state")
        self.assertContains(
            response,
            reverse(
                "siae_evaluations_views:evaluated_siae_detail",
                kwargs={"evaluated_siae_pk": evaluated_siae.pk},
            ),
        )

        EvaluatedAdministrativeCriteria.objects.update(
            submitted_at=timezone.now(),
            proof=FileFactory(),
        )
        response = self.client.get(url)
        state_div = parse_response_to_soup(response, selector=f"#state_of_evaluated_siae-{evaluated_siae.pk}")
        assert str(state_div) == self.snapshot(name="to process state")

        EvaluatedAdministrativeCriteria.objects.filter(
            evaluated_job_application__evaluated_siae=evaluated_siae
        ).update(review_state=evaluation_enums.EvaluatedAdministrativeCriteriaState.ACCEPTED)

        response = self.client.get(url)
        state_div = parse_response_to_soup(response, selector=f"#state_of_evaluated_siae-{evaluated_siae.pk}")
        assert str(state_div) == self.snapshot(name="in progress state")

        EvaluatedAdministrativeCriteria.objects.filter(
            evaluated_job_application__evaluated_siae=evaluated_siae
        ).update(review_state=evaluation_enums.EvaluatedAdministrativeCriteriaState.REFUSED)

        response = self.client.get(url)
        state_div = parse_response_to_soup(response, selector=f"#state_of_evaluated_siae-{evaluated_siae.pk}")
        assert str(state_div) == self.snapshot(name="in progress state")

        # REVIEWED
        review_time = timezone.now()
        evaluated_siae.reviewed_at = review_time
        evaluated_siae.save(update_fields=["reviewed_at"])

        response = self.client.get(url)
        state_div = parse_response_to_soup(response, selector=f"#state_of_evaluated_siae-{evaluated_siae.pk}")
        assert str(state_div) == self.snapshot(name="adversarial stage state")

        # Upload new proof
        EvaluatedAdministrativeCriteria.objects.filter(
            evaluated_job_application__evaluated_siae=evaluated_siae,
        ).update(
            review_state=evaluation_enums.EvaluatedAdministrativeCriteriaState.PENDING,
            proof=FileFactory(),
            submitted_at=None,
        )

        response = self.client.get(url)
        state_div = parse_response_to_soup(response, selector=f"#state_of_evaluated_siae-{evaluated_siae.pk}")
        assert str(state_div) == self.snapshot(name="adversarial waiting state")

        # Submit new proof
        EvaluatedAdministrativeCriteria.objects.update(submitted_at=timezone.now())

        response = self.client.get(url)
        state_div = parse_response_to_soup(response, selector=f"#state_of_evaluated_siae-{evaluated_siae.pk}")
        assert str(state_div) == self.snapshot(name="adversarial to process state")

        # DDETS sets to refused
        EvaluatedAdministrativeCriteria.objects.filter(
            evaluated_job_application__evaluated_siae=evaluated_siae
        ).update(review_state=evaluation_enums.EvaluatedAdministrativeCriteriaState.REFUSED)

        response = self.client.get(url)
        state_div = parse_response_to_soup(response, selector=f"#state_of_evaluated_siae-{evaluated_siae.pk}")
        assert str(state_div) == self.snapshot(name="adversarial in progress state")

        # DDETS sets to accepted
        EvaluatedAdministrativeCriteria.objects.filter(
            evaluated_job_application__evaluated_siae=evaluated_siae
        ).update(review_state=evaluation_enums.EvaluatedAdministrativeCriteriaState.ACCEPTED)

        response = self.client.get(url)
        state_div = parse_response_to_soup(response, selector=f"#state_of_evaluated_siae-{evaluated_siae.pk}")
        assert str(state_div) == self.snapshot(name="adversarial in progress state")

        # DDETS validates its final review
        evaluated_siae.final_reviewed_at = review_time
        evaluated_siae.save(update_fields=["final_reviewed_at"])
        response = self.client.get(url)
        state_div = parse_response_to_soup(response, selector=f"#state_of_evaluated_siae-{evaluated_siae.pk}")
        assert str(state_div) == self.snapshot(name="final accepted state")

    def test_siae_infos_with_submission_freezed_at(self):
        self.client.force_login(self.user)
        evaluation_campaign = EvaluationCampaignFactory(
            institution=self.institution, evaluations_asked_at=timezone.now()
        )
        evaluated_siae = EvaluatedSiaeFactory(
            evaluation_campaign=evaluation_campaign,
            pk=1000,
            for_snapshot=True,
        )
        evaluated_job_app = EvaluatedJobApplicationFactory(evaluated_siae=evaluated_siae)
        EvaluatedAdministrativeCriteriaFactory(evaluated_job_application=evaluated_job_app, proof=None)
        url = reverse(
            "siae_evaluations_views:institution_evaluated_siae_list",
            kwargs={"evaluation_campaign_pk": evaluation_campaign.pk},
        )
        submission_time = timezone.now()  # Will be used for SUBMITTED state
        evaluation_campaign.freeze(timezone.now())

        assert evaluated_siae.state == evaluation_enums.EvaluatedSiaeState.PENDING
        response = self.client.get(url)
        self.assertContains(response, evaluated_siae)
        state_div = parse_response_to_soup(response, selector=f"#state_of_evaluated_siae-{evaluated_siae.pk}")
        assert str(state_div) == self.snapshot(name="identified issue state")

        # Simulate the SUBMITTABLE state
        del evaluated_siae.state_from_applications
        EvaluatedAdministrativeCriteria.objects.update(proof=FileFactory())
        assert evaluated_siae.state == evaluation_enums.EvaluatedSiaeState.SUBMITTABLE
        response = self.client.get(url)
        self.assertContains(response, evaluated_siae)
        state_div = parse_response_to_soup(response, selector=f"#state_of_evaluated_siae-{evaluated_siae.pk}")
        assert str(state_div) == self.snapshot(name="identified issue state")

        # Simulate the SUBMITTED state
        del evaluated_siae.state_from_applications
        EvaluatedAdministrativeCriteria.objects.update(submitted_at=submission_time)
        assert evaluated_siae.state == evaluation_enums.EvaluatedSiaeState.SUBMITTED
        response = self.client.get(url)
        self.assertContains(response, evaluated_siae)
        state_div = parse_response_to_soup(response, selector=f"#state_of_evaluated_siae-{evaluated_siae.pk}")
        assert str(state_div) == self.snapshot(name="to process state")

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
            BASE_NUM_QUERIES
            + 1  # django session
            + 2  # fetch user & its memberships (middleware)
            + 1  # fetch evaluation campaign
            + 3  # fetch evaluated_siae and its prefetch_related eval_job_app & eval_admin_crit
            + 3  # savepoint, update session, release savepoint
        ):
            response = self.client.get(url)
        assert response.status_code == 200


class InstitutionEvaluatedSiaeDetailViewTest(TestCase):
    control_text = "Lorsque vous aurez contrôlé"
    submit_text = "Valider"
    forced_positive_text = (
        "Les petits jardins a soumis des justificatifs, mais leur contrôle n’a pas été validé avant la fin de la "
        "campagne « Contrôle Test », <b>le résultat du contrôle est positif</b>."
    )
    forced_positive_text_transition_to_adversarial_stage = (
        "Les petits jardins a soumis des justificatifs, mais leur contrôle n’a pas été validé avant la fin de la "
        "phase amiable, <b>le résultat du contrôle est positif</b>."
    )
    forced_negative_text = (
        "Les petits jardins n’a pas soumis de justificatifs avant la fin de la campagne « Contrôle Test », "
        "<b>le résultat du contrôle est négatif</b>."
    )

    def setUp(self):
        super().setUp()
        membership = InstitutionMembershipFactory(institution__name="DDETS 14")
        self.user = membership.user
        self.institution = membership.institution

    def test_access(self):
        self.client.force_login(self.user)

        # institution without evaluation_campaign
        response = self.client.get(
            reverse(
                "siae_evaluations_views:evaluated_siae_detail",
                kwargs={"evaluated_siae_pk": 99999},
            )
        )
        assert response.status_code == 404

        # institution with evaluation_campaign in "institution sets its ratio" phase
        evaluation_campaign = EvaluationCampaignFactory(institution=self.institution)
        evaluated_siae = create_evaluated_siae_consistent_datas(evaluation_campaign)
        url = reverse(
            "siae_evaluations_views:evaluated_siae_detail",
            kwargs={"evaluated_siae_pk": evaluated_siae.pk},
        )

        response = self.client.get(url)
        assert response.status_code == 404

        # institution with evaluation_campaign in "siae upload its proofs" phase
        evaluation_campaign.evaluations_asked_at = timezone.now()
        evaluation_campaign.save(update_fields=["evaluations_asked_at"])
        response = self.client.get(url)
        assert response.status_code == 200

        # institution with ended evaluation_campaign
        evaluation_campaign.ended_at = timezone.now()
        evaluation_campaign.save(update_fields=["ended_at"])
        response = self.client.get(url)
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
                "siae_evaluations_views:evaluated_siae_detail",
                kwargs={"evaluated_siae_pk": evaluated_siae.pk},
            )
        )
        url = reverse(
            "siae_evaluations_views:evaluated_job_application",
            kwargs={"evaluated_job_application_pk": job_app.pk},
        )
        self.assertContains(
            response,
            '<span class="badge badge-sm rounded-pill text-nowrap bg-success text-white">Validé</span>',
            count=1,
        )
        self.assertContains(
            response,
            f"""
            <a href="{url}" class="btn btn-outline-primary btn-block w-100 w-md-auto">
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
            name="Contrôle Test",
        )
        evaluated_siae = EvaluatedSiaeFactory(
            evaluation_campaign=evaluation_campaign,
            siae__name="les petits jardins",
            reviewed_at=timezone.now() - relativedelta(days=5),
        )
        evaluated_job_app = EvaluatedJobApplicationFactory(evaluated_siae=evaluated_siae)
        EvaluatedAdministrativeCriteriaFactory(
            evaluated_job_application=evaluated_job_app,
            uploaded_at=timezone.now() - relativedelta(days=2),
            submitted_at=timezone.now() - relativedelta(days=1),
            review_state=evaluation_enums.EvaluatedAdministrativeCriteriaState.REFUSED_2,
        )
        evaluation_campaign.close()

        self.client.force_login(self.user)
        response = self.client.get(
            reverse(
                "siae_evaluations_views:evaluated_siae_detail",
                kwargs={"evaluated_siae_pk": evaluated_siae.pk},
            )
        )
        self.assertContains(
            response,
            '<span class="badge badge-sm rounded-pill text-nowrap bg-danger text-white">Problème constaté</span>',
            html=True,
            count=1,
        )
        self.assertNotContains(response, self.control_text)
        self.assertNotContains(response, self.submit_text)
        # The institution reviewed but forgot to validate
        # auto-validation kicked in and the final result is refused
        self.assertNotContains(response, self.forced_positive_text, html=True)
        self.assertNotContains(response, self.forced_positive_text_transition_to_adversarial_stage, html=True)
        self.assertNotContains(response, self.forced_negative_text, html=True)

    def test_transition_to_adversarial_phase_before_institution_review_submitted(self):
        evaluation_campaign = EvaluationCampaignFactory(
            institution=self.institution,
            evaluations_asked_at=timezone.now() - relativedelta(weeks=6),
            name="Contrôle Test",
        )
        evaluated_siae = EvaluatedSiaeFactory(evaluation_campaign=evaluation_campaign, siae__name="les petits jardins")
        evaluated_job_app = EvaluatedJobApplicationFactory(evaluated_siae=evaluated_siae)
        EvaluatedAdministrativeCriteriaFactory(
            evaluated_job_application=evaluated_job_app,
            uploaded_at=timezone.now() - relativedelta(days=2),
            submitted_at=timezone.now() - relativedelta(days=1),
        )
        evaluation_campaign.transition_to_adversarial_phase()

        self.client.force_login(self.user)
        response = self.client.get(
            reverse(
                "siae_evaluations_views:evaluated_siae_detail",
                kwargs={"evaluated_siae_pk": evaluated_siae.pk},
            )
        )
        self.assertContains(
            response,
            """
            <span class="badge badge-sm rounded-pill text-nowrap bg-emploi-light text-primary">
            Justificatifs non contrôlés
            </span>
            """,
            html=True,
            count=1,
        )
        self.assertNotContains(response, self.control_text)
        self.assertNotContains(response, self.submit_text)
        # Was not reviewed by the institution, assume valid (following rules in
        # most administrations).
        self.assertNotContains(response, self.forced_positive_text, html=True)
        self.assertContains(response, self.forced_positive_text_transition_to_adversarial_stage, html=True, count=1)
        self.assertNotContains(response, self.forced_negative_text, html=True)

    def test_refused_does_not_show_accepted_by_default(self):
        evaluation_campaign = EvaluationCampaignFactory(
            institution=self.institution,
            evaluations_asked_at=timezone.now() - relativedelta(weeks=6),
            name="Contrôle Test",
        )
        now = timezone.now()
        evaluated_siae = EvaluatedSiaeFactory(
            evaluation_campaign=evaluation_campaign,
            siae__name="les petits jardins",
            reviewed_at=now - relativedelta(days=10),
            final_reviewed_at=now - relativedelta(days=5),
        )
        evaluated_job_app = EvaluatedJobApplicationFactory(evaluated_siae=evaluated_siae)
        EvaluatedAdministrativeCriteriaFactory(
            evaluated_job_application=evaluated_job_app,
            uploaded_at=now - relativedelta(days=7),
            submitted_at=now - relativedelta(days=6),
            review_state=evaluation_enums.EvaluatedAdministrativeCriteriaState.REFUSED_2,
        )

        self.client.force_login(self.user)
        response = self.client.get(
            reverse(
                "siae_evaluations_views:evaluated_siae_detail",
                kwargs={"evaluated_siae_pk": evaluated_siae.pk},
            )
        )
        self.assertContains(
            response,
            '<span class="badge badge-sm rounded-pill text-nowrap bg-danger text-white">Problème constaté</span>',
            html=True,
            count=1,
        )
        self.assertNotContains(response, self.control_text)
        self.assertNotContains(response, self.submit_text)
        self.assertNotContains(response, self.forced_positive_text, html=True)
        self.assertNotContains(response, self.forced_positive_text_transition_to_adversarial_stage, html=True)
        self.assertNotContains(response, self.forced_negative_text, html=True)

    def test_campaign_closed_before_final_evaluation_adversarial_stage_review_not_submitted(self):
        evaluation_campaign = EvaluationCampaignFactory(
            institution=self.institution,
            evaluations_asked_at=timezone.now() - relativedelta(weeks=6),
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
        )
        evaluation_campaign.close()

        self.client.force_login(self.user)
        response = self.client.get(
            reverse(
                "siae_evaluations_views:evaluated_siae_detail",
                kwargs={"evaluated_siae_pk": evaluated_siae.pk},
            )
        )
        self.assertContains(
            response,
            """
            <span class="badge badge-sm rounded-pill text-nowrap bg-emploi-light text-primary">
            Justificatifs non contrôlés
            </span>
            """,
            html=True,
            count=1,
        )
        self.assertNotContains(response, self.control_text)
        self.assertNotContains(response, self.submit_text)
        # Was not reviewed by the institution, assume valid (following rules in
        # most administrations).
        self.assertContains(response, self.forced_positive_text, html=True, count=1)
        self.assertNotContains(response, self.forced_positive_text_transition_to_adversarial_stage, html=True)
        self.assertNotContains(response, self.forced_negative_text, html=True)

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
                "siae_evaluations_views:evaluated_siae_detail",
                kwargs={"evaluated_siae_pk": evaluated_siae.pk},
            )
        )
        self.assertContains(
            response,
            '<span class="badge badge-sm rounded-pill text-nowrap bg-danger text-white">Non téléversés</span>',
            html=True,
            count=1,
        )
        self.assertNotContains(response, self.control_text)
        self.assertNotContains(response, self.submit_text)
        self.assertNotContains(response, self.forced_positive_text, html=True)
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
                "siae_evaluations_views:evaluated_siae_detail",
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
            "siae_evaluations_views:evaluated_job_application",
            kwargs={"evaluated_job_application_pk": evaluated_job_application.pk},
        )
        url = reverse(
            "siae_evaluations_views:evaluated_siae_detail",
            kwargs={"evaluated_siae_pk": evaluated_siae.pk},
        )
        validation_url = reverse(
            "siae_evaluations_views:institution_evaluated_siae_validation",
            kwargs={"evaluated_siae_pk": evaluated_siae.pk},
        )
        validation_button_disabled = f"""
            <button class="btn btn-primary disabled">
                {self.submit_text}
            </button>"""
        validation_button = f"""
            <button class="btn btn-primary">
                {self.submit_text}
            </button>"""
        back_url = reverse(
            "siae_evaluations_views:institution_evaluated_siae_list",
            kwargs={"evaluation_campaign_pk": evaluation_campaign.pk},
        )

        # EvaluatedAdministrativeCriteria not yet submitted
        pending_status = "En attente"
        response = self.client.get(url)
        self.assertContains(response, evaluated_siae)
        formatted_number = format_approval_number(evaluated_job_application.job_application.approval.number)
        self.assertContains(response, formatted_number, html=True, count=1)
        self.assertContains(response, evaluated_job_application.job_application.job_seeker.get_full_name())
        self.assertContains(response, format_phone(evaluated_siae.siae.phone))

        assert response.context["back_url"] == reverse(
            "siae_evaluations_views:institution_evaluated_siae_list",
            kwargs={"evaluation_campaign_pk": evaluation_campaign.pk},
        )
        self.assertNotContains(response, evaluated_job_application_url)
        self.assertContains(response, back_url)
        self.assertContains(response, validation_url)
        self.assertContains(response, self.control_text)
        self.assertContains(
            response,
            f"""
            <span class="badge badge-sm rounded-pill text-nowrap bg-info text-white">
             {pending_status}
            </span>
            """,
            html=True,
            count=1,
        )
        # Check without phone now
        evaluated_siae.siae.phone = ""
        evaluated_siae.siae.save(update_fields=("phone",))
        response = self.client.get(url)
        self.assertContains(
            response, """<p>Numéro de téléphone à utiliser au besoin :<span>Non renseigné</span>""", html=True
        )

        # EvaluatedAdministrativeCriteria uploaded
        uploaded_status = "Justificatifs téléversés"
        evaluated_administrative_criteria = evaluated_job_application.evaluated_administrative_criteria.first()
        evaluated_administrative_criteria.proof = FileFactory()
        evaluated_administrative_criteria.save(update_fields=["proof"])
        response = self.client.get(url)
        self.assertContains(response, back_url)
        self.assertContains(response, uploaded_status)
        self.assertContains(response, validation_button_disabled, html=True, count=1)
        self.assertContains(response, self.control_text)

        # EvaluatedAdministrativeCriteria submitted
        submitted_status = "À traiter"
        adversarial_submitted_status = "Nouveaux justificatifs à traiter"
        evaluated_administrative_criteria.submitted_at = timezone.now()
        evaluated_administrative_criteria.save(update_fields=["submitted_at"])
        response = self.client.get(url)
        self.assertContains(response, evaluated_job_application_url)
        self.assertContains(response, back_url)
        self.assertNotContains(response, uploaded_status)
        self.assertNotContains(response, pending_status)
        self.assertNotContains(response, adversarial_submitted_status)
        self.assertContains(response, validation_button_disabled, html=True, count=1)
        self.assertContains(response, self.control_text)
        self.assertContains(
            response,
            f"""
            <span class="badge badge-sm rounded-pill text-nowrap bg-accent-03 text-primary">
             {submitted_status}
            </span>
            """,
            html=True,
            count=1,
        )

        # EvaluatedAdministrativeCriteria Accepted
        evaluated_administrative_criteria.review_state = evaluation_enums.EvaluatedAdministrativeCriteriaState.ACCEPTED
        evaluated_administrative_criteria.save(update_fields=["review_state"])
        self.assertContains(response, self.control_text)

        response = self.client.get(url)
        self.assertContains(response, evaluated_job_application_url)
        self.assertContains(response, back_url)
        self.assertContains(response, validation_button, html=True, count=2)
        self.assertContains(response, self.control_text)
        self.assertContains(
            response,
            """
            <span class="badge badge-sm rounded-pill text-nowrap bg-success text-white">
             Validé
            </span>
            """,
            html=True,
            count=1,
        )

        # EvaluatedAdministrativeCriteria Accepted & Reviewed
        evaluated_siae.reviewed_at = timezone.now()
        evaluated_siae.final_reviewed_at = timezone.now()
        evaluated_siae.save(update_fields=["reviewed_at", "final_reviewed_at"])

        response = self.client.get(url)
        self.assertContains(response, evaluated_job_application_url)
        self.assertContains(response, back_url)
        self.assertNotContains(response, self.submit_text)
        self.assertNotContains(response, self.control_text)
        self.assertContains(
            response,
            """
            <span class="badge badge-sm rounded-pill text-nowrap bg-success text-white">
             Validé
            </span>
            """,
            html=True,
            count=1,
        )

        # EvaluatedAdministrativeCriteria Refused
        refused_status = "Problème constaté"
        evaluated_administrative_criteria.review_state = evaluation_enums.EvaluatedAdministrativeCriteriaState.REFUSED
        evaluated_administrative_criteria.save(update_fields=["review_state"])
        evaluated_siae.reviewed_at = None
        evaluated_siae.final_reviewed_at = None
        evaluated_siae.save(update_fields=["reviewed_at", "final_reviewed_at"])

        response = self.client.get(url)
        self.assertContains(response, evaluated_job_application_url)
        self.assertContains(response, back_url)
        self.assertContains(response, validation_button, html=True, count=2)
        self.assertContains(response, self.control_text)
        self.assertContains(
            response,
            f"""
            <span class="badge badge-sm rounded-pill text-nowrap bg-danger text-white">
             {refused_status}
            </span>
            """,
            html=True,
            count=1,
        )

        # EvaluatedAdministrativeCriteria Refused & Reviewed
        evaluated_siae.reviewed_at = timezone.now()
        evaluated_siae.save(update_fields=["reviewed_at"])

        response = self.client.get(url)
        self.assertContains(response, evaluated_job_application_url)
        self.assertContains(response, back_url)
        self.assertContains(response, validation_button_disabled, html=True, count=1)
        self.assertContains(response, self.control_text)
        self.assertContains(
            response,
            """
            <span class="badge badge-sm rounded-pill text-nowrap bg-info text-white">
             Phase contradictoire - En attente
            </span>
            """,
            html=True,
            count=1,
        )

        # Adversarial phase

        adversarial_phase_start = evaluated_siae.reviewed_at

        # EvaluatedAdministrativeCriteriaState.UPLOADED (again)
        evaluated_administrative_criteria.proof = FileFactory()
        evaluated_administrative_criteria.uploaded_at = timezone.now()
        evaluated_administrative_criteria.review_state = evaluation_enums.EvaluatedAdministrativeCriteriaState.PENDING
        evaluated_administrative_criteria.submitted_at = None
        evaluated_administrative_criteria.save(update_fields=["proof", "review_state", "submitted_at", "uploaded_at"])
        response = self.client.get(url)
        self.assertContains(response, validation_button_disabled, html=True, count=1)
        self.assertContains(response, back_url)
        self.assertContains(response, evaluated_job_application_url)
        self.assertContains(response, uploaded_status)
        self.assertContains(response, self.control_text)

        # EvaluatedAdministrativeCriteriaState.SUBMITTED (again)
        evaluated_administrative_criteria.submitted_at = timezone.now()
        evaluated_administrative_criteria.save(update_fields=["submitted_at"])
        response = self.client.get(url)
        self.assertContains(response, evaluated_job_application_url)
        self.assertContains(response, back_url)
        self.assertNotContains(response, uploaded_status)
        self.assertNotContains(response, pending_status)
        self.assertNotContains(response, refused_status)
        self.assertContains(response, adversarial_submitted_status)
        self.assertContains(response, validation_button_disabled, html=True, count=1)
        self.assertContains(response, self.control_text)

        # EvaluatedAdministrativeCriteriaState.ACCEPTED (again)
        evaluated_administrative_criteria.review_state = evaluation_enums.EvaluatedAdministrativeCriteriaState.ACCEPTED
        evaluated_administrative_criteria.save(update_fields=["review_state"])

        response = self.client.get(url)
        self.assertContains(response, evaluated_job_application_url)
        self.assertContains(response, back_url)
        self.assertContains(response, validation_button, html=True, count=2)
        self.assertContains(response, self.control_text)
        self.assertContains(
            response,
            """
            <span class="badge badge-sm rounded-pill text-nowrap bg-success text-white">
             Validé
            </span>
            """,
            html=True,
            count=1,
        )

        # EvaluatedAdministrativeCriteria Accepted & Reviewed (again)
        now = timezone.now()
        evaluated_siae.reviewed_at = now
        evaluated_siae.final_reviewed_at = now
        evaluated_siae.save(update_fields=["reviewed_at", "final_reviewed_at"])

        response = self.client.get(url)
        self.assertContains(response, evaluated_job_application_url)
        self.assertContains(response, back_url)
        self.assertNotContains(response, self.submit_text)
        self.assertNotContains(response, self.control_text)
        self.assertContains(
            response,
            """
            <span class="badge badge-sm rounded-pill text-nowrap bg-success text-white">
             Validé
            </span>
            """,
            html=True,
            count=1,
        )

        # EvaluatedAdministrativeCriteria Refused (again)
        evaluated_siae.reviewed_at = adversarial_phase_start
        evaluated_siae.final_reviewed_at = None
        evaluated_siae.save(update_fields=["final_reviewed_at", "reviewed_at"])
        evaluated_administrative_criteria.review_state = (
            evaluation_enums.EvaluatedAdministrativeCriteriaState.REFUSED_2
        )
        evaluated_administrative_criteria.save(update_fields=["review_state"])

        response = self.client.get(url)
        self.assertContains(response, evaluated_job_application_url)
        self.assertContains(response, back_url)
        self.assertContains(response, validation_button, html=True, count=2)
        self.assertContains(response, self.control_text)
        self.assertContains(
            response,
            f"""
            <span class="badge badge-sm rounded-pill text-nowrap bg-danger text-white">
             {refused_status}
            </span>
            """,
            html=True,
            count=1,
        )

        # EvaluatedAdministrativeCriteria Refused & Reviewed (again)
        evaluated_siae.final_reviewed_at = timezone.now()
        evaluated_siae.save(update_fields=["final_reviewed_at"])

        response = self.client.get(url)
        self.assertContains(response, evaluated_job_application_url)
        self.assertContains(response, back_url)
        self.assertNotContains(response, self.submit_text)
        self.assertNotContains(response, self.control_text)
        self.assertContains(
            response,
            f"""
            <span class="badge badge-sm rounded-pill text-nowrap bg-danger text-white">
             {refused_status}
            </span>
            """,
            html=True,
            count=1,
        )

    def test_content_with_submission_freezed_at(self):
        self.client.force_login(self.user)
        evaluation_campaign = EvaluationCampaignFactory(
            institution=self.institution, evaluations_asked_at=timezone.now()
        )
        evaluated_siae = create_evaluated_siae_consistent_datas(evaluation_campaign)
        evaluated_job_application = evaluated_siae.evaluated_job_applications.first()
        evaluation_campaign.freeze(timezone.now())

        evaluated_job_application_url = reverse(
            "siae_evaluations_views:evaluated_job_application",
            kwargs={"evaluated_job_application_pk": evaluated_job_application.pk},
        )
        url = reverse(
            "siae_evaluations_views:evaluated_siae_detail",
            kwargs={"evaluated_siae_pk": evaluated_siae.pk},
        )
        validation_url = reverse(
            "siae_evaluations_views:institution_evaluated_siae_validation",
            kwargs={"evaluated_siae_pk": evaluated_siae.pk},
        )
        validation_button_disabled = f"""
            <button class="btn btn-primary disabled">
                {self.submit_text}
            </button>"""
        back_url = reverse(
            "siae_evaluations_views:institution_evaluated_siae_list",
            kwargs={"evaluation_campaign_pk": evaluation_campaign.pk},
        )

        # EvaluatedAdministrativeCriteria not yet submitted
        not_transmitted_status = "Justificatifs non transmis"
        response = self.client.get(url)
        self.assertContains(response, evaluated_siae)
        formatted_number = format_approval_number(evaluated_job_application.job_application.approval.number)
        self.assertContains(response, formatted_number, html=True, count=1)
        self.assertContains(response, evaluated_job_application.job_application.job_seeker.get_full_name())
        assert response.context["back_url"] == reverse(
            "siae_evaluations_views:institution_evaluated_siae_list",
            kwargs={"evaluation_campaign_pk": evaluation_campaign.pk},
        )
        self.assertNotContains(response, evaluated_job_application_url)
        self.assertContains(response, back_url)
        self.assertContains(response, validation_url)
        self.assertContains(response, self.control_text)
        self.assertContains(
            response,
            f"""
            <span class="badge badge-sm rounded-pill text-nowrap bg-danger text-white">
             {not_transmitted_status}
            </span>
            """,
            html=True,
            count=1,
        )

        # EvaluatedAdministrativeCriteria uploaded
        evaluated_administrative_criteria = evaluated_job_application.evaluated_administrative_criteria.first()
        evaluated_administrative_criteria.proof = FileFactory()
        evaluated_administrative_criteria.save(update_fields=["proof"])
        response = self.client.get(url)
        self.assertContains(response, back_url)
        self.assertContains(
            response,
            f"""
            <span class="badge badge-sm rounded-pill text-nowrap bg-danger text-white">
             {not_transmitted_status}
            </span>
            """,
            html=True,
            count=1,
        )
        self.assertContains(response, validation_button_disabled, html=True, count=1)
        self.assertContains(response, self.control_text)

        # EvaluatedAdministrativeCriteria submitted
        submitted_status = "À traiter"
        adversarial_submitted_status = "Nouveaux justificatifs à traiter"
        evaluated_administrative_criteria.submitted_at = timezone.now()
        evaluated_administrative_criteria.save(update_fields=["submitted_at"])
        response = self.client.get(url)
        self.assertContains(response, evaluated_job_application_url)
        self.assertContains(response, back_url)
        self.assertNotContains(response, not_transmitted_status)
        self.assertNotContains(response, adversarial_submitted_status)
        self.assertContains(response, validation_button_disabled, html=True, count=1)
        self.assertContains(response, self.control_text)
        self.assertContains(
            response,
            f"""
            <span class="badge badge-sm rounded-pill text-nowrap bg-accent-03 text-primary">
             {submitted_status}
            </span>
            """,
            html=True,
            count=1,
        )

        # Adversarial phase (but still frozen)
        evaluated_siae.reviewed_at = timezone.now()
        evaluated_siae.save(update_fields=["reviewed_at"])

        # EvaluatedAdministrativeCriteriaState.UPLOADED (again)
        evaluated_administrative_criteria.proof = FileFactory()
        evaluated_administrative_criteria.uploaded_at = timezone.now()
        evaluated_administrative_criteria.review_state = evaluation_enums.EvaluatedAdministrativeCriteriaState.PENDING
        evaluated_administrative_criteria.submitted_at = None
        evaluated_administrative_criteria.save(update_fields=["proof", "review_state", "submitted_at", "uploaded_at"])
        response = self.client.get(url)
        self.assertContains(response, validation_button_disabled, html=True, count=1)
        self.assertContains(response, back_url)
        self.assertContains(response, evaluated_job_application_url)
        self.assertContains(response, not_transmitted_status)
        self.assertContains(response, self.control_text)

        # EvaluatedAdministrativeCriteriaState.SUBMITTED (again)
        evaluated_administrative_criteria.submitted_at = timezone.now()
        evaluated_administrative_criteria.save(update_fields=["submitted_at"])
        response = self.client.get(url)
        self.assertContains(response, evaluated_job_application_url)
        self.assertContains(response, back_url)
        self.assertNotContains(response, not_transmitted_status)
        self.assertContains(response, adversarial_submitted_status)
        self.assertContains(response, validation_button_disabled, html=True, count=1)
        self.assertContains(response, self.control_text)

    def test_job_app_status_evaluation_is_final_pending(self):
        evaluation_campaign = EvaluationCampaignFactory(
            institution=self.institution,
            evaluations_asked_at=timezone.now() - relativedelta(weeks=6),
            ended_at=timezone.now(),
        )
        evaluated_siae = EvaluatedSiaeFactory(evaluation_campaign=evaluation_campaign)
        EvaluatedJobApplicationFactory(evaluated_siae=evaluated_siae)
        self.client.force_login(self.user)
        response = self.client.get(
            reverse(
                "siae_evaluations_views:evaluated_siae_detail",
                kwargs={"evaluated_siae_pk": evaluated_siae.pk},
            )
        )
        self.assertContains(
            response,
            '<span class="badge badge-sm rounded-pill text-nowrap bg-danger text-white">Non téléversés</span>',
            count=1,
        )

    def test_job_app_status_evaluation_is_final_processing(self):
        evaluation_campaign = EvaluationCampaignFactory(
            institution=self.institution,
            evaluations_asked_at=timezone.now() - relativedelta(weeks=6),
            ended_at=timezone.now(),
        )
        evaluated_siae = EvaluatedSiaeFactory(evaluation_campaign=evaluation_campaign)
        evaluated_job_app = EvaluatedJobApplicationFactory(evaluated_siae=evaluated_siae)
        EvaluatedAdministrativeCriteriaFactory(evaluated_job_application=evaluated_job_app)
        EvaluatedAdministrativeCriteriaFactory(evaluated_job_application=evaluated_job_app, proof=None)
        self.client.force_login(self.user)
        response = self.client.get(
            reverse(
                "siae_evaluations_views:evaluated_siae_detail",
                kwargs={"evaluated_siae_pk": evaluated_siae.pk},
            )
        )
        self.assertContains(
            response,
            """
            <span class="badge badge-sm rounded-pill text-nowrap bg-warning text-white">
            Téléversement incomplet
            </span>
            """,
            html=True,
            count=1,
        )

    def test_job_app_status_evaluation_is_final_uploaded(self):
        evaluation_campaign = EvaluationCampaignFactory(
            institution=self.institution,
            evaluations_asked_at=timezone.now() - relativedelta(weeks=6),
            ended_at=timezone.now(),
        )
        evaluated_siae = EvaluatedSiaeFactory(evaluation_campaign=evaluation_campaign)
        evaluated_job_app = EvaluatedJobApplicationFactory(evaluated_siae=evaluated_siae)
        EvaluatedAdministrativeCriteriaFactory(evaluated_job_application=evaluated_job_app)
        self.client.force_login(self.user)
        response = self.client.get(
            reverse(
                "siae_evaluations_views:evaluated_siae_detail",
                kwargs={"evaluated_siae_pk": evaluated_siae.pk},
            )
        )
        self.assertContains(
            response,
            """
            <span class="badge badge-sm rounded-pill text-nowrap bg-warning text-white">
            Justificatifs téléversés
            </span>
            """,
            html=True,
            count=1,
        )

    def test_job_app_status_evaluation_is_final_submitted(self):
        evaluation_campaign = EvaluationCampaignFactory(
            institution=self.institution,
            evaluations_asked_at=timezone.now() - relativedelta(weeks=6),
            ended_at=timezone.now(),
        )
        evaluated_siae = EvaluatedSiaeFactory(evaluation_campaign=evaluation_campaign)
        evaluated_job_app = EvaluatedJobApplicationFactory(evaluated_siae=evaluated_siae)
        EvaluatedAdministrativeCriteriaFactory(
            evaluated_job_application=evaluated_job_app,
            submitted_at=timezone.now() - relativedelta(days=1),
        )
        self.client.force_login(self.user)
        response = self.client.get(
            reverse(
                "siae_evaluations_views:evaluated_siae_detail",
                kwargs={"evaluated_siae_pk": evaluated_siae.pk},
            )
        )
        self.assertContains(
            response,
            """
            <span class="badge badge-sm rounded-pill text-nowrap bg-emploi-light text-primary">
            Justificatifs non contrôlés
            </span>""",
            html=True,
            count=1,
        )

    def test_job_app_status_evaluation_is_final_accepted(self):
        evaluation_campaign = EvaluationCampaignFactory(
            institution=self.institution,
            evaluations_asked_at=timezone.now() - relativedelta(weeks=6),
            ended_at=timezone.now(),
        )
        evaluated_siae = EvaluatedSiaeFactory(
            evaluation_campaign=evaluation_campaign,
            reviewed_at=timezone.now() - relativedelta(hours=1),
            final_reviewed_at=timezone.now() - relativedelta(hours=1),
        )
        evaluated_job_app = EvaluatedJobApplicationFactory(evaluated_siae=evaluated_siae)
        EvaluatedAdministrativeCriteriaFactory(
            evaluated_job_application=evaluated_job_app,
            submitted_at=timezone.now() - relativedelta(days=1),
            review_state=evaluation_enums.EvaluatedAdministrativeCriteriaState.ACCEPTED,
        )
        self.client.force_login(self.user)
        response = self.client.get(
            reverse(
                "siae_evaluations_views:evaluated_siae_detail",
                kwargs={"evaluated_siae_pk": evaluated_siae.pk},
            )
        )
        self.assertContains(
            response,
            '<span class="badge badge-sm rounded-pill text-nowrap bg-success text-white">Validé</span>',
            count=1,
        )

    def test_job_app_status_evaluation_is_final_refused(self):
        evaluation_campaign = EvaluationCampaignFactory(
            institution=self.institution,
            evaluations_asked_at=timezone.now() - relativedelta(weeks=6),
            ended_at=timezone.now(),
        )
        evaluated_siae = EvaluatedSiaeFactory(
            evaluation_campaign=evaluation_campaign,
            reviewed_at=timezone.now() - relativedelta(hours=6),
            final_reviewed_at=timezone.now() - relativedelta(hours=1),
        )
        evaluated_job_app = EvaluatedJobApplicationFactory(evaluated_siae=evaluated_siae)
        EvaluatedAdministrativeCriteriaFactory(
            evaluated_job_application=evaluated_job_app,
            submitted_at=timezone.now() - relativedelta(days=1),
            review_state=evaluation_enums.EvaluatedAdministrativeCriteriaState.REFUSED,
        )
        self.client.force_login(self.user)
        response = self.client.get(
            reverse(
                "siae_evaluations_views:evaluated_siae_detail",
                kwargs={"evaluated_siae_pk": evaluated_siae.pk},
            )
        )
        self.assertContains(
            response,
            '<span class="badge badge-sm rounded-pill text-nowrap bg-danger text-white">Problème constaté</span>',
            count=1,
        )

    def test_job_app_status_evaluation_is_final_refused_2(self):
        evaluation_campaign = EvaluationCampaignFactory(
            institution=self.institution,
            evaluations_asked_at=timezone.now() - relativedelta(weeks=6),
            ended_at=timezone.now(),
        )
        evaluated_siae = EvaluatedSiaeFactory(
            evaluation_campaign=evaluation_campaign,
            reviewed_at=timezone.now() - relativedelta(hours=6),
            final_reviewed_at=timezone.now() - relativedelta(hours=1),
        )
        evaluated_job_app = EvaluatedJobApplicationFactory(evaluated_siae=evaluated_siae)
        EvaluatedAdministrativeCriteriaFactory(
            evaluated_job_application=evaluated_job_app,
            submitted_at=timezone.now() - relativedelta(days=1),
            review_state=evaluation_enums.EvaluatedAdministrativeCriteriaState.REFUSED_2,
        )
        self.client.force_login(self.user)
        response = self.client.get(
            reverse(
                "siae_evaluations_views:evaluated_siae_detail",
                kwargs={"evaluated_siae_pk": evaluated_siae.pk},
            )
        )
        self.assertContains(
            response,
            '<span class="badge badge-sm rounded-pill text-nowrap bg-danger text-white">Problème constaté</span>',
            count=1,
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
            "siae_evaluations_views:evaluated_job_application",
            kwargs={"evaluated_job_application_pk": evaluated_job_application.pk},
        )
        response = self.client.get(
            reverse(
                "siae_evaluations_views:evaluated_siae_detail",
                kwargs={"evaluated_siae_pk": evaluated_siae.pk},
            )
        )
        self.assertContains(
            response,
            f"""
            <a href="{evaluated_job_application_url}" class="btn btn-outline-primary btn-block w-100 w-md-auto">
                Revoir ses justificatifs
            </a>
            """,
            html=True,
            count=1,
        )

    def test_job_seeker_infos_for_institution_state(self):
        en_attente = "En attente"
        uploaded = "Justificatifs téléversés"
        a_traiter = "À traiter"
        refuse = "Problème constaté"
        valide = "Validé"

        evaluation_campaign = EvaluationCampaignFactory(
            institution=self.institution, evaluations_asked_at=timezone.now()
        )
        evaluated_siae = create_evaluated_siae_consistent_datas(evaluation_campaign)

        url = reverse(
            "siae_evaluations_views:evaluated_siae_detail",
            kwargs={"evaluated_siae_pk": evaluated_siae.pk},
        )

        self.client.force_login(self.user)

        # not yet submitted by Siae
        response = self.client.get(url)
        self.assertContains(response, en_attente)

        # submittable by SIAE
        EvaluatedAdministrativeCriteria.objects.filter(
            evaluated_job_application__evaluated_siae=evaluated_siae
        ).update(proof=FileFactory())

        response = self.client.get(url)
        self.assertContains(response, uploaded)

        # submitted by Siae
        EvaluatedAdministrativeCriteria.objects.filter(
            evaluated_job_application__evaluated_siae=evaluated_siae
        ).update(submitted_at=timezone.now())

        response = self.client.get(url)
        self.assertContains(response, a_traiter)

        # refused
        EvaluatedAdministrativeCriteria.objects.filter(
            evaluated_job_application__evaluated_siae=evaluated_siae
        ).update(review_state=evaluation_enums.EvaluatedAdministrativeCriteriaState.REFUSED)

        response = self.client.get(url)
        self.assertContains(response, refuse)

        # accepted
        EvaluatedAdministrativeCriteria.objects.filter(
            evaluated_job_application__evaluated_siae=evaluated_siae
        ).update(review_state=evaluation_enums.EvaluatedAdministrativeCriteriaState.ACCEPTED)

        response = self.client.get(url)
        self.assertContains(response, valide)

    def test_job_seeker_infos_for_institution_state_submission_freezed_at(self):
        not_transmitted = "Justificatifs non transmis"
        a_traiter = "À traiter"
        refuse = "Problème constaté"
        valide = "Validé"

        evaluation_campaign = EvaluationCampaignFactory(
            institution=self.institution, evaluations_asked_at=timezone.now()
        )
        evaluated_siae = create_evaluated_siae_consistent_datas(evaluation_campaign)
        evaluation_campaign.freeze(timezone.now())

        url = reverse(
            "siae_evaluations_views:evaluated_siae_detail",
            kwargs={"evaluated_siae_pk": evaluated_siae.pk},
        )

        self.client.force_login(self.user)

        # not yet submitted by Siae
        response = self.client.get(url)
        self.assertContains(response, not_transmitted)

        # submittable by SIAE
        EvaluatedAdministrativeCriteria.objects.filter(
            evaluated_job_application__evaluated_siae=evaluated_siae
        ).update(proof=FileFactory())

        response = self.client.get(url)
        self.assertContains(response, not_transmitted)

        # submitted by Siae
        EvaluatedAdministrativeCriteria.objects.filter(
            evaluated_job_application__evaluated_siae=evaluated_siae
        ).update(submitted_at=timezone.now())

        response = self.client.get(url)
        self.assertContains(response, a_traiter)

        # refused
        EvaluatedAdministrativeCriteria.objects.filter(
            evaluated_job_application__evaluated_siae=evaluated_siae
        ).update(review_state=evaluation_enums.EvaluatedAdministrativeCriteriaState.REFUSED)

        response = self.client.get(url)
        self.assertContains(response, refuse)

        # accepted
        EvaluatedAdministrativeCriteria.objects.filter(
            evaluated_job_application__evaluated_siae=evaluated_siae
        ).update(review_state=evaluation_enums.EvaluatedAdministrativeCriteriaState.ACCEPTED)

        response = self.client.get(url)
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
                "siae_evaluations_views:evaluated_siae_detail",
                kwargs={"evaluated_siae_pk": evaluated_job_application.evaluated_siae_id},
            )
        )
        self.assertContains(response, "Phase contradictoire - En attente", html=True)
        self.assertNotContains(response, self.forced_negative_text, html=True)

    def test_num_queries_in_view(self):
        self.client.force_login(self.user)
        evaluation_campaign = EvaluationCampaignFactory(
            institution=self.institution, evaluations_asked_at=timezone.now()
        )
        evaluated_siae = create_evaluated_siae_consistent_datas(evaluation_campaign)
        EvaluatedJobApplicationFactory.create_batch(10, evaluated_siae=evaluated_siae)

        url = reverse(
            "siae_evaluations_views:evaluated_siae_detail",
            kwargs={"evaluated_siae_pk": evaluated_siae.pk},
        )

        with self.assertNumQueries(
            BASE_NUM_QUERIES
            + 1  # django session
            + 2  # fetch user & its memberships (middleware)
            + 3  # fetch evaluated_siae, evaluated_jobapp & criteria
            + 3  # fetch jobapplication, approvals & users
            + 3  # savepoint, update session, release savepoint
        ):
            response = self.client.get(url)
        assert response.status_code == 200


class InstitutionEvaluatedSiaeNotifyViewAccessTestMixin:
    not_submitted = "justificatifs non soumis"

    @classmethod
    def setUpTestData(cls):
        membership = InstitutionMembershipFactory(institution__name="DDETS 14")
        cls.user = membership.user
        cls.institution = membership.institution

    def login(self, evaluated_siae):
        self.client.force_login(self.user)

    def test_anonymous_access(self):
        evaluated_siae = EvaluatedSiaeFactory(
            complete=True,
            job_app__criteria__review_state=evaluation_enums.EvaluatedJobApplicationsState.REFUSED_2,
        )
        url = reverse(self.urlname, kwargs={"evaluated_siae_pk": evaluated_siae.pk})
        response = self.client.get(url)
        self.assertRedirects(response, reverse("account_login") + f"?next={url}")

    def test_access_other_institution(self):
        evaluated_siae = EvaluatedSiaeFactory(
            # Evaluation of another institution.
            complete=True,
            job_app__criteria__review_state=evaluation_enums.EvaluatedJobApplicationsState.REFUSED_2,
        )
        self.login(evaluated_siae)
        response = self.client.get(
            reverse(
                self.urlname,
                kwargs={"evaluated_siae_pk": evaluated_siae.pk},
            )
        )
        assert response.status_code == 404

    def test_access_incomplete_on_active_campaign(self):
        evaluated_siae = EvaluatedSiaeFactory()
        self.login(evaluated_siae)
        response = self.client.get(
            reverse(
                self.urlname,
                kwargs={"evaluated_siae_pk": evaluated_siae.pk},
            )
        )
        assert response.status_code == 404

    def test_access_notified_institution(self):
        evaluated_siae = EvaluatedSiaeFactory(
            evaluation_campaign__institution=self.institution,
            complete=True,
            job_app__criteria__review_state=evaluation_enums.EvaluatedJobApplicationsState.REFUSED_2,
            notified_at=timezone.now(),
            notification_reason=evaluation_enums.EvaluatedSiaeNotificationReason.INVALID_PROOF,
            notification_text="A envoyé une photo de son chat.",
        )
        self.login(evaluated_siae)
        response = self.client.get(
            reverse(
                self.urlname,
                kwargs={"evaluated_siae_pk": evaluated_siae.pk},
            )
        )
        assert response.status_code == 404

    def test_access_long_closed_campaign(self):
        evaluated_siae = EvaluatedSiaeFactory(
            evaluation_campaign__institution=self.institution,
            evaluation_campaign__ended_at=timezone.now() - CAMPAIGN_VIEWABLE_DURATION,
        )
        self.login(evaluated_siae)
        response = self.client.get(
            reverse(
                self.urlname,
                kwargs={"evaluated_siae_pk": evaluated_siae.pk},
            )
        )
        assert response.status_code == 404

    @freeze_time("2023-01-24 11:11:00")
    def test_data_card_statistics(self):
        company = CompanyFactory()
        previous_campaign = EvaluationCampaignFactory(
            institution=self.institution,
            ended_at=timezone.now() - relativedelta(years=1),
            evaluated_period_start_at=datetime.date(2022, 1, 1),
            evaluated_period_end_at=datetime.date(2022, 12, 31),
        )
        previous_evaluated_siae = EvaluatedSiaeFactory(
            evaluation_campaign=previous_campaign,
            siae=company,
            reviewed_at=timezone.now() - relativedelta(years=1, months=3),
        )
        # SIAE didn’t answer for that evaluation campaign.
        EvaluatedJobApplicationFactory.create_batch(2, evaluated_siae=previous_evaluated_siae)

        campaign = EvaluationCampaignFactory(
            institution=self.institution, ended_at=timezone.now() - relativedelta(hours=1)
        )
        other_evaluated_siae = EvaluatedSiaeFactory(evaluation_campaign=campaign)
        EvaluatedJobApplicationFactory(evaluated_siae=other_evaluated_siae)

        evaluated_siae = EvaluatedSiaeFactory(evaluation_campaign=campaign, siae=company)
        # SIAE didn’t bother justifying this application.
        EvaluatedJobApplicationFactory(evaluated_siae=evaluated_siae)
        inprogress_evaluated_job_app = EvaluatedJobApplicationFactory(evaluated_siae=evaluated_siae)
        EvaluatedAdministrativeCriteriaFactory(
            evaluated_job_application=inprogress_evaluated_job_app, uploaded_at=timezone.now() - relativedelta(weeks=1)
        )
        EvaluatedAdministrativeCriteriaFactory(
            evaluated_job_application=inprogress_evaluated_job_app,
            uploaded_at=timezone.now() - relativedelta(weeks=1),
            submitted_at=timezone.now() - relativedelta(days=5),
        )
        refused_adversarial_evaluated_job_app = EvaluatedJobApplicationFactory(evaluated_siae=evaluated_siae)
        EvaluatedAdministrativeCriteriaFactory(
            evaluated_job_application=refused_adversarial_evaluated_job_app,
            uploaded_at=timezone.now() - relativedelta(weeks=1),
            submitted_at=timezone.now() - relativedelta(days=5),
            review_state=evaluation_enums.EvaluatedAdministrativeCriteriaState.ACCEPTED,
        )
        EvaluatedAdministrativeCriteriaFactory(
            evaluated_job_application=refused_adversarial_evaluated_job_app,
            uploaded_at=timezone.now() - relativedelta(weeks=1),
            submitted_at=timezone.now() - relativedelta(days=5),
            review_state=evaluation_enums.EvaluatedAdministrativeCriteriaState.REFUSED,
        )
        refused_evaluated_job_app = EvaluatedJobApplicationFactory(evaluated_siae=evaluated_siae)
        EvaluatedAdministrativeCriteriaFactory(
            evaluated_job_application=refused_evaluated_job_app,
            uploaded_at=timezone.now() - relativedelta(weeks=1),
            submitted_at=timezone.now() - relativedelta(days=5),
            review_state=evaluation_enums.EvaluatedAdministrativeCriteriaState.ACCEPTED,
        )
        EvaluatedAdministrativeCriteriaFactory(
            evaluated_job_application=refused_evaluated_job_app,
            uploaded_at=timezone.now() - relativedelta(weeks=1),
            submitted_at=timezone.now() - relativedelta(days=5),
            review_state=evaluation_enums.EvaluatedAdministrativeCriteriaState.REFUSED_2,
        )
        EvaluatedAdministrativeCriteriaFactory(
            evaluated_job_application=refused_evaluated_job_app,
            uploaded_at=timezone.now() - relativedelta(weeks=1),
            submitted_at=timezone.now() - relativedelta(days=5),
            review_state=evaluation_enums.EvaluatedAdministrativeCriteriaState.REFUSED_2,
        )
        accepted_evaluated_job_app = EvaluatedJobApplicationFactory(evaluated_siae=evaluated_siae)
        EvaluatedAdministrativeCriteriaFactory(
            evaluated_job_application=accepted_evaluated_job_app,
            uploaded_at=timezone.now() - relativedelta(weeks=1),
            submitted_at=timezone.now() - relativedelta(days=5),
            review_state=evaluation_enums.EvaluatedAdministrativeCriteriaState.ACCEPTED,
        )
        self.login(evaluated_siae)
        response = self.client.get(
            reverse(
                self.urlname,
                kwargs={"evaluated_siae_pk": evaluated_siae.pk},
            )
        )
        self.assertContains(response, f"Notifier la sanction du contrôle pour {evaluated_siae.siae.name}")
        self.assertContains(
            response,
            f"""
            <a target="_blank" href="/siae_evaluation/evaluated_siae_detail/{evaluated_siae.pk}/">
             Revoir les 5 auto-prescriptions
             <i class="ri-external-link-line">
             </i>
            </a>""",
            html=True,
            count=1,
        )
        # 8 criteria, 3 refused. 3/7 * 100 = 37.5 %, rounded to the closest
        # integer by floatformat.
        self.assertContains(response, "<li>38 % justificatifs refusés lors de votre contrôle</li>", count=1)
        # 1 criteria uploaded. 1/8 * 100 = 12.5 %, rounded to the closest
        # integer by floatformat.
        self.assertContains(
            response,
            f"<li>13 % {self.not_submitted} par la SIAE (dont 1 téléversé sur 1 attendu)</li>",
            html=True,
            count=1,
        )
        self.assertContains(
            response,
            """
            <h3>
             Historique des campagnes de contrôle
            </h3>
            <ul class="list-unstyled">
             <li>
              Période du 01/01/2022 au 31/12/2022 :
              <b class="text-danger">Négatif</b>
             </li>
            </ul>""",
            html=True,
            count=1,
        )
        self.assertContains(response, self.not_submitted, count=1)

    @freeze_time("2023-06-24 11:11:00")
    def test_data_card_statistics_multiple_previous_campaigns_check_sanctions(self):
        company = CompanyFactory()
        previous_campaign_1 = EvaluationCampaignFactory(
            institution=self.institution,
            ended_at=timezone.make_aware(datetime.datetime(2022, 3, 24)),
            evaluated_period_start_at=datetime.date(2022, 1, 1),
            evaluated_period_end_at=datetime.date(2022, 2, 28),
        )
        # This SIAE didn’t answer for that evaluation campaign.
        previous_evaluated_siae_1 = EvaluatedSiaeFactory(
            evaluation_campaign=previous_campaign_1,
            siae=company,
            reviewed_at=timezone.make_aware(datetime.datetime(2022, 2, 24)),
        )
        EvaluatedJobApplicationFactory.create_batch(2, evaluated_siae=previous_evaluated_siae_1)
        sanctions_1 = Sanctions.objects.create(
            evaluated_siae=previous_evaluated_siae_1, no_sanction_reason="Pas envie"
        )

        previous_campaign_2 = EvaluationCampaignFactory(
            institution=self.institution,
            ended_at=timezone.make_aware(datetime.datetime(2022, 8, 24)),
            evaluated_period_start_at=datetime.date(2022, 6, 1),
            evaluated_period_end_at=datetime.date(2022, 7, 31),
        )
        # It didn’t answer for that evaluation campaign either.
        previous_evaluated_siae_2 = EvaluatedSiaeFactory(
            evaluation_campaign=previous_campaign_2,
            siae=company,
            reviewed_at=timezone.make_aware(datetime.datetime(2022, 7, 24)),
        )
        EvaluatedJobApplicationFactory.create_batch(2, evaluated_siae=previous_evaluated_siae_2)
        Sanctions.objects.create(
            evaluated_siae=previous_evaluated_siae_2, deactivation_reason="Ça commence à bien faire"
        )

        campaign = EvaluationCampaignFactory(
            institution=self.institution, ended_at=timezone.now() - relativedelta(hours=1)
        )
        evaluated_siae = EvaluatedSiaeFactory(evaluation_campaign=campaign, siae=company)
        self.login(evaluated_siae)
        with self.assertNumQueries(
            BASE_NUM_QUERIES
            + 1  # Load session
            + 2  # Check user & its memberships
            + 1  # Load evaluated siae infos
            + 1  # Load evaluated job applications
            + 3  # Load evaluated siae infos + job application + criteria for previous campaigns
            + 3  # Update session
        ):
            response = self.client.get(
                reverse(
                    self.urlname,
                    kwargs={"evaluated_siae_pk": evaluated_siae.pk},
                )
            )
        NO_SANCTION = "<li>Ne pas sanctionner</li>"
        TEMP_SUSPENSION = "<li>Retrait temporaire de la capacité d’auto-prescription</li>"
        FINAL_SUSPENSION = "<li>Retrait définitif de la capacité d’auto-prescription</li>"
        PARTIAL_CUT = "<li>Suppression d’une partie de l’aide au poste</li>"
        TOTAL_CUT = "<li>Suppression de l’aide au poste</li>"
        DEACTIVATION = "<li>Déconventionnement de la structure</li>"

        self.assertContains(response, NO_SANCTION)
        self.assertContains(response, DEACTIVATION)
        self.assertNotContains(response, TEMP_SUSPENSION)
        self.assertNotContains(response, FINAL_SUSPENSION)
        self.assertNotContains(response, PARTIAL_CUT, html=True)
        self.assertNotContains(response, TOTAL_CUT, html=True)

        sanctions_1.no_sanction_reason = ""
        sanctions_1.suspension_dates = InclusiveDateRange(datetime.date(2022, 3, 1), datetime.date(2022, 3, 2))
        sanctions_1.subsidy_cut_dates = InclusiveDateRange(datetime.date(2022, 3, 1), datetime.date(2022, 3, 2))
        sanctions_1.subsidy_cut_percent = 50
        sanctions_1.save()

        response = self.client.get(
            reverse(
                self.urlname,
                kwargs={"evaluated_siae_pk": evaluated_siae.pk},
            )
        )
        self.assertNotContains(response, NO_SANCTION)
        self.assertContains(response, TEMP_SUSPENSION)
        self.assertNotContains(response, FINAL_SUSPENSION)
        self.assertContains(response, PARTIAL_CUT, html=True)
        self.assertNotContains(response, TOTAL_CUT, html=True)
        self.assertContains(response, DEACTIVATION)

        sanctions_1.suspension_dates = InclusiveDateRange(datetime.date(2022, 3, 1))
        sanctions_1.subsidy_cut_dates = InclusiveDateRange(datetime.date(2022, 3, 1), datetime.date(2022, 3, 2))
        sanctions_1.subsidy_cut_percent = 100
        sanctions_1.save()

        response = self.client.get(
            reverse(
                self.urlname,
                kwargs={"evaluated_siae_pk": evaluated_siae.pk},
            )
        )
        self.assertNotContains(response, NO_SANCTION)
        self.assertNotContains(response, TEMP_SUSPENSION)
        self.assertContains(response, FINAL_SUSPENSION)
        self.assertNotContains(response, PARTIAL_CUT, html=True)
        self.assertContains(response, TOTAL_CUT, html=True)
        self.assertContains(response, DEACTIVATION)


class InstitutionEvaluatedSiaeNotifyViewStep1Test(InstitutionEvaluatedSiaeNotifyViewAccessTestMixin, TestCase):
    urlname = "siae_evaluations_views:institution_evaluated_siae_notify_step1"

    def test_access_final_refused_control_active_campaign(self):
        evaluated_siae = EvaluatedSiaeFactory(
            evaluation_campaign__institution=self.institution,
            complete=True,
            job_app__criteria__review_state=evaluation_enums.EvaluatedJobApplicationsState.REFUSED_2,
        )
        self.client.force_login(self.user)
        response = self.client.get(
            reverse(
                "siae_evaluations_views:institution_evaluated_siae_notify_step1",
                kwargs={"evaluated_siae_pk": evaluated_siae.pk},
            )
        )
        self.assertContains(response, f"Notifier la sanction du contrôle pour {evaluated_siae.siae.name}", count=1)
        self.assertContains(
            response,
            f"""
            <a target="_blank" href="/siae_evaluation/evaluated_siae_detail/{evaluated_siae.pk}/">
             Revoir l’auto-prescription
             <i class="ri-external-link-line">
             </i>
            </a>""",
            html=True,
            count=1,
        )
        self.assertContains(response, "<li>100 % justificatifs refusés lors de votre contrôle</li>", count=1)
        self.assertContains(
            response,
            """
            <h3>
             Historique des campagnes de contrôle
            </h3>
            <ul class="list-unstyled">
            </ul>""",
            html=True,
            count=1,
        )
        self.assertNotContains(response, self.not_submitted)

    def test_access_incomplete_evaluation_closed_campaign(self):
        evaluated_siae = EvaluatedSiaeFactory(
            evaluation_campaign__institution=self.institution,
            evaluation_campaign__evaluations_asked_at=timezone.now() - relativedelta(weeks=4),
            evaluation_campaign__ended_at=timezone.now(),
        )
        self.client.force_login(self.user)
        response = self.client.get(
            reverse(
                "siae_evaluations_views:institution_evaluated_siae_notify_step1",
                kwargs={"evaluated_siae_pk": evaluated_siae.pk},
            )
        )
        self.assertContains(response, f"Notifier la sanction du contrôle pour {evaluated_siae.siae.name}")

    @freeze_time("2022-10-24 11:11:00")
    def test_post(self):
        company_membership = CompanyMembershipFactory(
            company__name="Les petits jardins", user__email="siae@mailinator.com"
        )
        evaluated_siae = EvaluatedSiaeFactory(
            siae=company_membership.company,
            evaluation_campaign__institution=self.institution,
            evaluation_campaign__name="Campagne 2022",
            evaluation_campaign__evaluations_asked_at=timezone.now() - relativedelta(weeks=4),
            evaluation_campaign__ended_at=timezone.now() - relativedelta(hours=1),
        )
        self.client.force_login(self.user)
        text = (
            "Votre chat a mangé le justificatif, vous devrez suivre une formation protection contre les risques "
            "félins."
        )
        response = self.client.post(
            reverse(self.urlname, kwargs={"evaluated_siae_pk": evaluated_siae.pk}),
            data={
                "notification_reason": "MISSING_PROOF",
                "notification_text": text,
            },
        )
        self.assertRedirects(
            response,
            reverse(
                "siae_evaluations_views:institution_evaluated_siae_notify_step2",
                kwargs={"evaluated_siae_pk": evaluated_siae.pk},
            ),
        )
        evaluated_siae.refresh_from_db()
        assert evaluated_siae.notified_at is None
        assert evaluated_siae.notification_reason == "MISSING_PROOF"
        assert evaluated_siae.notification_text == text

    def test_post_missing_data(self):
        evaluated_siae = EvaluatedSiaeFactory(
            siae__name="Les petits jardins",
            evaluation_campaign__institution=self.institution,
            evaluation_campaign__evaluations_asked_at=timezone.now() - relativedelta(weeks=4),
            evaluation_campaign__ended_at=timezone.now() - relativedelta(hours=1),
        )
        self.client.force_login(self.user)
        response = self.client.post(
            reverse(self.urlname, kwargs={"evaluated_siae_pk": evaluated_siae.pk}),
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
                <label class="form-label" for="id_notification_text">Commentaire</label>
                <textarea name="notification_text" cols="40" rows="10"
                    placeholder="{placeholder}"
                    class="form-control is-invalid"
                    required aria-invalid="true"
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
            '<label class="form-label">Raison principale</label>',
            count=1,
        )
        self.assertContains(
            response,
            '<div class="invalid-feedback">Sélectionnez un choix valide. invalid data n’en fait pas partie.</div>',
            count=1,
        )


class InstitutionEvaluatedSiaeNotifyViewStep2Test(InstitutionEvaluatedSiaeNotifyViewAccessTestMixin, TestCase):
    urlname = "siae_evaluations_views:institution_evaluated_siae_notify_step2"

    def assertChecked(self, response, checked_values):
        parser = html5lib.HTMLParser(namespaceHTMLElements=False)
        html = parser.parse(response.content)
        checkboxes = html.findall(".//input[@type='checkbox'][@name='sanctions']")
        assert len(checkboxes) == 7
        assert sorted(c.get("value") for c in checkboxes if "checked" in c.attrib) == sorted(checked_values)

    def test_get_empty_session(self):
        evaluated_siae = EvaluatedSiaeFactory(
            evaluation_campaign__institution=self.institution,
            complete=True,
            job_app__criteria__review_state=evaluation_enums.EvaluatedJobApplicationsState.REFUSED_2,
            notification_reason=evaluation_enums.EvaluatedSiaeNotificationReason.INVALID_PROOF,
            notification_text="A envoyé une photo de son chat.",
        )
        self.client.force_login(self.user)
        response = self.client.get(
            reverse(
                self.urlname,
                kwargs={"evaluated_siae_pk": evaluated_siae.pk},
            )
        )
        self.assertChecked(response, [])

    def test_get_with_session_data(self):
        evaluated_siae = EvaluatedSiaeFactory(
            evaluation_campaign__institution=self.institution,
            complete=True,
            job_app__criteria__review_state=evaluation_enums.EvaluatedJobApplicationsState.REFUSED_2,
            notification_reason=evaluation_enums.EvaluatedSiaeNotificationReason.INVALID_PROOF,
            notification_text="A envoyé une photo de son chat.",
        )
        self.client.force_login(self.user)
        key = f"siae_evaluations_views:institution_evaluated_siae_notify-{evaluated_siae.pk}"
        checked = ["SUBSIDY_CUT_PERCENT", "TRAINING"]
        session = self.client.session
        session[key] = {"sanctions": checked}
        session.save()
        response = self.client.get(
            reverse(
                self.urlname,
                kwargs={"evaluated_siae_pk": evaluated_siae.pk},
            )
        )
        self.assertChecked(response, checked)

    def test_post_fills_session(self):
        evaluated_siae = EvaluatedSiaeFactory(
            evaluation_campaign__institution=self.institution,
            complete=True,
            job_app__criteria__review_state=evaluation_enums.EvaluatedJobApplicationsState.REFUSED_2,
            notification_reason=evaluation_enums.EvaluatedSiaeNotificationReason.INVALID_PROOF,
            notification_text="A envoyé une photo de son chat.",
        )
        self.client.force_login(self.user)
        checked = ["SUBSIDY_CUT_PERCENT", "TRAINING"]
        response = self.client.post(
            reverse(
                self.urlname,
                kwargs={"evaluated_siae_pk": evaluated_siae.pk},
            ),
            data={"sanctions": checked},
        )
        self.assertRedirects(
            response,
            reverse(
                "siae_evaluations_views:institution_evaluated_siae_notify_step3",
                kwargs={"evaluated_siae_pk": evaluated_siae.pk},
            ),
        )
        key = f"siae_evaluations_views:institution_evaluated_siae_notify-{evaluated_siae.pk}"
        assert self.client.session[key] == {"sanctions": checked}

    def test_post_without_data(self):
        evaluated_siae = EvaluatedSiaeFactory(
            evaluation_campaign__institution=self.institution,
            complete=True,
            job_app__criteria__review_state=evaluation_enums.EvaluatedJobApplicationsState.REFUSED_2,
            notification_reason=evaluation_enums.EvaluatedSiaeNotificationReason.INVALID_PROOF,
            notification_text="A envoyé une photo de son chat.",
        )
        self.client.force_login(self.user)
        response = self.client.post(reverse(self.urlname, kwargs={"evaluated_siae_pk": evaluated_siae.pk}))
        self.assertContains(
            response,
            '<div class="invalid-feedback">Ce champ est obligatoire.</div>',
            html=True,
            count=1,
        )
        assert response.context["form"].errors == {"sanctions": ["Ce champ est obligatoire."]}

    def test_post_all_sanctions_errors(self):
        evaluated_siae = EvaluatedSiaeFactory(
            evaluation_campaign__institution=self.institution,
            complete=True,
            job_app__criteria__review_state=evaluation_enums.EvaluatedJobApplicationsState.REFUSED_2,
            notification_reason=evaluation_enums.EvaluatedSiaeNotificationReason.INVALID_PROOF,
            notification_text="A envoyé une photo de son chat.",
        )
        self.client.force_login(self.user)
        data_error = [
            (
                ["TEMPORARY_SUSPENSION", "PERMANENT_SUSPENSION"],
                "“Retrait temporaire de la capacité d’auto-prescription” est incompatible avec "
                "“Retrait définitif de la capacité d’auto-prescription”, "
                "choisissez l’une ou l’autre de ces sanctions.",
            ),
            (
                ["SUBSIDY_CUT_FULL", "SUBSIDY_CUT_PERCENT"],
                "“Suppression d’une partie de l’aide au poste” est incompatible avec "
                "“Suppression de toute l’aide au poste”, choisissez l’une ou l’autre de ces sanctions.",
            ),
            (
                ["NO_SANCTIONS", "SUBSIDY_CUT_FULL"],
                "“Ne pas sanctionner” est incompatible avec les autres sanctions.",
            ),
        ]
        for data, error in data_error:
            with self.subTest(data):
                response = self.client.post(
                    reverse(self.urlname, kwargs={"evaluated_siae_pk": evaluated_siae.pk}),
                    data={"sanctions": data},
                )
                self.assertContains(
                    response,
                    f'<div class="alert alert-danger" role="alert">{error}</div>',
                    html=True,
                    count=1,
                )


class InstitutionEvaluatedSiaeNotifyViewStep3Test(InstitutionEvaluatedSiaeNotifyViewAccessTestMixin, TestCase):
    urlname = "siae_evaluations_views:institution_evaluated_siae_notify_step3"

    def login(self, evaluated_siae, sanctions=("TRAINING",)):
        self.client.force_login(self.user)
        key = f"siae_evaluations_views:institution_evaluated_siae_notify-{evaluated_siae.pk}"
        session = self.client.session
        session[key] = {"sanctions": sanctions}
        session.save()

    def test_get(self):
        evaluated_siae = EvaluatedSiaeFactory(
            evaluation_campaign__institution=self.institution,
            complete=True,
            job_app__criteria__review_state=evaluation_enums.EvaluatedJobApplicationsState.REFUSED_2,
            notification_reason=evaluation_enums.EvaluatedSiaeNotificationReason.INVALID_PROOF,
            notification_text="A envoyé une photo de son chat.",
        )
        self.login(evaluated_siae, sanctions=["TRAINING"])
        response = self.client.get(reverse(self.urlname, kwargs={"evaluated_siae_pk": evaluated_siae.pk}))
        assert response.status_code == 200

    @freeze_time("2022-10-24 11:11:00")
    def test_post_training(self):
        company_membership = CompanyMembershipFactory(
            company__name="Les petits jardins", user__email="siae@mailinator.com"
        )
        evaluated_siae = EvaluatedSiaeFactory(
            evaluation_campaign__name="Campagne 2022",
            evaluation_campaign__institution=self.institution,
            siae=company_membership.company,
            complete=True,
            job_app__criteria__review_state=evaluation_enums.EvaluatedJobApplicationsState.REFUSED_2,
            notification_reason=evaluation_enums.EvaluatedSiaeNotificationReason.INVALID_PROOF,
            notification_text="A envoyé une photo de son chat.",
        )
        self.login(evaluated_siae, sanctions=["TRAINING"])
        response = self.client.post(
            reverse(self.urlname, kwargs={"evaluated_siae_pk": evaluated_siae.pk}),
            {"training_session": "RDV le lundi 8 à 15h à la DDETS"},
        )
        self.assertRedirects(
            response,
            reverse(
                "siae_evaluations_views:institution_evaluated_siae_list",
                kwargs={"evaluation_campaign_pk": evaluated_siae.evaluation_campaign_id},
            ),
        )
        evaluated_siae.refresh_from_db()
        assert evaluated_siae.notified_at == timezone.now()
        assert evaluated_siae.notification_reason == "INVALID_PROOF"
        assert evaluated_siae.notification_text == "A envoyé une photo de son chat."
        [email] = mail.outbox
        assert email.to == ["siae@mailinator.com"]
        assert email.subject == "Notification de sanction"
        assert email.body == (
            "Bonjour,\n\n"
            "Suite aux manquements constatés lors du dernier contrôle a posteriori des auto-prescriptions réalisées "
            "dans votre SIAE, vous trouverez ci-dessous la mesure prise :\n\n"
            "- Participation à une session de présentation de l’auto-prescription\n\n"
            "    RDV le lundi 8 à 15h à la DDETS\n\n"
            "Cordialement,\n\n"
            "---\n"
            "[DEV] Cet email est envoyé depuis un environnement de démonstration, "
            "merci de ne pas en tenir compte [DEV]\n"
            "Les emplois de l'inclusion\n"
            "http://localhost:8000"
        )
        assert evaluated_siae.sanctions.training_session == "RDV le lundi 8 à 15h à la DDETS"
        assert evaluated_siae.sanctions.suspension_dates is None
        assert evaluated_siae.sanctions.subsidy_cut_percent is None
        assert evaluated_siae.sanctions.subsidy_cut_dates is None
        assert evaluated_siae.sanctions.deactivation_reason == ""
        assert evaluated_siae.sanctions.no_sanction_reason == ""

    @freeze_time("2022-10-24 11:11:00")
    def test_post_temporary_suspension(self):
        company_membership = CompanyMembershipFactory(
            company__name="Les petits jardins", user__email="siae@mailinator.com"
        )
        evaluated_siae = EvaluatedSiaeFactory(
            evaluation_campaign__name="Campagne 2022",
            evaluation_campaign__institution=self.institution,
            siae=company_membership.company,
            complete=True,
            job_app__criteria__review_state=evaluation_enums.EvaluatedJobApplicationsState.REFUSED_2,
            notification_reason=evaluation_enums.EvaluatedSiaeNotificationReason.INVALID_PROOF,
            notification_text="A envoyé une photo de son chat.",
        )
        self.login(evaluated_siae, sanctions=["TEMPORARY_SUSPENSION"])
        response = self.client.post(
            reverse(self.urlname, kwargs={"evaluated_siae_pk": evaluated_siae.pk}),
            {
                "temporary_suspension_from": datetime.date(2023, 1, 1),
                "temporary_suspension_to": datetime.date(2023, 2, 1),
            },
        )
        self.assertRedirects(
            response,
            reverse(
                "siae_evaluations_views:institution_evaluated_siae_list",
                kwargs={"evaluation_campaign_pk": evaluated_siae.evaluation_campaign_id},
            ),
        )
        evaluated_siae.refresh_from_db()
        assert evaluated_siae.notified_at == timezone.now()
        assert evaluated_siae.notification_reason == "INVALID_PROOF"
        assert evaluated_siae.notification_text == "A envoyé une photo de son chat."
        [email] = mail.outbox
        assert email.to == ["siae@mailinator.com"]
        assert email.subject == "Notification de sanction"
        assert email.body == (
            "Bonjour,\n\n"
            "Suite aux manquements constatés lors du dernier contrôle a posteriori des auto-prescriptions réalisées "
            "dans votre SIAE, vous trouverez ci-dessous la mesure prise :\n\n"
            "- Retrait temporaire de la capacité d’auto-prescription\n\n"
            "    La capacité d’auto-prescrire un parcours d’insertion par l’activité économique est suspendue pour "
            "une durée déterminée par l’autorité administrative.\n\n"
            "    Dans votre cas, le retrait temporaire de la capacité d’auto-prescription sera effectif à partir du "
            "1 janvier 2023 et jusqu’au 1 février 2023.\n\n"
            "Cordialement,\n\n"
            "---\n"
            "[DEV] Cet email est envoyé depuis un environnement de démonstration, "
            "merci de ne pas en tenir compte [DEV]\n"
            "Les emplois de l'inclusion\n"
            "http://localhost:8000"
        )
        assert evaluated_siae.sanctions.training_session == ""
        assert evaluated_siae.sanctions.suspension_dates == InclusiveDateRange(
            datetime.date(2023, 1, 1), datetime.date(2023, 2, 1)
        )
        assert evaluated_siae.sanctions.subsidy_cut_percent is None
        assert evaluated_siae.sanctions.subsidy_cut_dates is None
        assert evaluated_siae.sanctions.deactivation_reason == ""
        assert evaluated_siae.sanctions.no_sanction_reason == ""

    @freeze_time("2022-10-24 11:11:00")
    def test_post_temporary_suspension_incorrect_date_order(self):
        company_membership = CompanyMembershipFactory(
            company__name="Les petits jardins", user__email="siae@mailinator.com"
        )
        evaluated_siae = EvaluatedSiaeFactory(
            evaluation_campaign__name="Campagne 2022",
            evaluation_campaign__institution=self.institution,
            siae=company_membership.company,
            complete=True,
            job_app__criteria__review_state=evaluation_enums.EvaluatedJobApplicationsState.REFUSED_2,
            notification_reason=evaluation_enums.EvaluatedSiaeNotificationReason.INVALID_PROOF,
            notification_text="A envoyé une photo de son chat.",
        )
        self.login(evaluated_siae, sanctions=["TEMPORARY_SUSPENSION"])
        response = self.client.post(
            reverse(self.urlname, kwargs={"evaluated_siae_pk": evaluated_siae.pk}),
            {
                "temporary_suspension_from": datetime.date(2023, 2, 1),
                "temporary_suspension_to": datetime.date(2023, 1, 1),
            },
        )
        self.assertContains(
            response,
            """
            <div class="alert alert-danger" role="alert">
             La date de fin de suspension ne peut pas être avant la date de début de suspension.
            </div>
            """,
            html=True,
            count=1,
        )
        evaluated_siae.refresh_from_db()
        assert [] == mail.outbox
        with pytest.raises(Sanctions.DoesNotExist):
            evaluated_siae.sanctions

    @freeze_time("2022-10-24 11:11:00")
    def test_post_temporary_suspension_missing_lower_date(self):
        company_membership = CompanyMembershipFactory(
            company__name="Les petits jardins", user__email="siae@mailinator.com"
        )
        evaluated_siae = EvaluatedSiaeFactory(
            evaluation_campaign__name="Campagne 2022",
            evaluation_campaign__institution=self.institution,
            siae=company_membership.company,
            complete=True,
            job_app__criteria__review_state=evaluation_enums.EvaluatedJobApplicationsState.REFUSED_2,
            notification_reason=evaluation_enums.EvaluatedSiaeNotificationReason.INVALID_PROOF,
            notification_text="A envoyé une photo de son chat.",
        )
        self.login(evaluated_siae, sanctions=["TEMPORARY_SUSPENSION"])
        response = self.client.post(
            reverse(self.urlname, kwargs={"evaluated_siae_pk": evaluated_siae.pk}),
            {"temporary_suspension_to": datetime.date(2023, 1, 1)},
        )
        self.assertContains(
            response,
            """
            <div class="form-group is-invalid form-group-required">
             <label class="form-label" for="id_temporary_suspension_from">
              À partir du
             </label>
             <duet-date-picker aria-label="Retrait temporaire de la capacité d’auto-prescription à partir du"
                               class="is-invalid"
                               identifier="id_temporary_suspension_from"
                               min="2022-11-24"
                               name="temporary_suspension_from"
                               required aria-invalid="true"
                               ></duet-date-picker>
              <div class="invalid-feedback">
               Ce champ est obligatoire.
              </div>
            </div>
            """,
            html=True,
            count=1,
        )
        evaluated_siae.refresh_from_db()
        assert [] == mail.outbox
        with pytest.raises(Sanctions.DoesNotExist):
            evaluated_siae.sanctions

    @freeze_time("2022-10-24 11:11:00")
    def test_post_temporary_suspension_missing_upper_date(self):
        company_membership = CompanyMembershipFactory(
            company__name="Les petits jardins", user__email="siae@mailinator.com"
        )
        evaluated_siae = EvaluatedSiaeFactory(
            evaluation_campaign__name="Campagne 2022",
            evaluation_campaign__institution=self.institution,
            siae=company_membership.company,
            complete=True,
            job_app__criteria__review_state=evaluation_enums.EvaluatedJobApplicationsState.REFUSED_2,
            notification_reason=evaluation_enums.EvaluatedSiaeNotificationReason.INVALID_PROOF,
            notification_text="A envoyé une photo de son chat.",
        )
        self.login(evaluated_siae, sanctions=["TEMPORARY_SUSPENSION"])
        response = self.client.post(
            reverse(self.urlname, kwargs={"evaluated_siae_pk": evaluated_siae.pk}),
            {"temporary_suspension_from": datetime.date(2023, 1, 1)},
        )
        self.assertContains(
            response,
            """
            <div class="form-group is-invalid form-group-required">
             <label class="form-label" for="id_temporary_suspension_to">
              Jusqu’au
             </label>
             <duet-date-picker aria-label="Retrait temporaire de la capacité d’auto-prescription jusqu’au"
                               class="is-invalid"
                               identifier="id_temporary_suspension_to"
                               min="2022-11-24"
                               name="temporary_suspension_to"
                               required aria-invalid="true"
                               ></duet-date-picker>
              <div class="invalid-feedback">
               Ce champ est obligatoire.
              </div>
            </div>
            """,
            html=True,
            count=1,
        )
        evaluated_siae.refresh_from_db()
        assert [] == mail.outbox
        with pytest.raises(Sanctions.DoesNotExist):
            evaluated_siae.sanctions

    @freeze_time("2022-10-24 11:11:00")
    def test_post_temporary_suspension_bad_input(self):
        company_membership = CompanyMembershipFactory(
            company__name="Les petits jardins", user__email="siae@mailinator.com"
        )
        evaluated_siae = EvaluatedSiaeFactory(
            evaluation_campaign__name="Campagne 2022",
            evaluation_campaign__institution=self.institution,
            siae=company_membership.company,
            complete=True,
            job_app__criteria__review_state=evaluation_enums.EvaluatedJobApplicationsState.REFUSED_2,
            notification_reason=evaluation_enums.EvaluatedSiaeNotificationReason.INVALID_PROOF,
            notification_text="A envoyé une photo de son chat.",
        )
        self.login(evaluated_siae, sanctions=["TEMPORARY_SUSPENSION"])
        response = self.client.post(
            reverse(self.urlname, kwargs={"evaluated_siae_pk": evaluated_siae.pk}),
            {
                # Field is ignored.
                "permanent_suspension": datetime.date(2023, 1, 1),
                "temporary_suspension_from": "invalid",
                "temporary_suspension_to": "invalid",
            },
        )
        from tests.utils.test import pprint_html

        pprint_html(response, name="form")
        self.assertContains(
            response,
            """
            <div class="form-group is-invalid form-group-required">
             <label class="form-label" for="id_temporary_suspension_from">
              À partir du
             </label>
             <duet-date-picker aria-label="Retrait temporaire de la capacité d’auto-prescription à partir du"
                               class="is-invalid"
                               identifier="id_temporary_suspension_from"
                               min="2022-11-24"
                               name="temporary_suspension_from"
                               required aria-invalid="true"
                               value="invalid"></duet-date-picker>
              <div class="invalid-feedback">
               Saisissez une date valide.
              </div>
            </div>
                """,
            html=True,
            count=1,
        )
        self.assertContains(
            response,
            """
            <div class="form-group is-invalid form-group-required">
             <label class="form-label" for="id_temporary_suspension_to">
              Jusqu’au
             </label>
             <duet-date-picker aria-label="Retrait temporaire de la capacité d’auto-prescription jusqu’au"
                               class="is-invalid"
                               identifier="id_temporary_suspension_to"
                               min="2022-11-24"
                               name="temporary_suspension_to"
                               required aria-invalid="true"
                               value="invalid"></duet-date-picker>
              <div class="invalid-feedback">
               Saisissez une date valide.
              </div>
            </div>
            """,
            html=True,
            count=1,
        )
        evaluated_siae.refresh_from_db()
        assert [] == mail.outbox
        with pytest.raises(Sanctions.DoesNotExist):
            evaluated_siae.sanctions

    @freeze_time("2022-10-24 11:11:00")
    def test_post_temporary_suspension_starts_in_less_than_a_month(self):
        company_membership = CompanyMembershipFactory(
            company__name="Les petits jardins", user__email="siae@mailinator.com"
        )
        evaluated_siae = EvaluatedSiaeFactory(
            evaluation_campaign__name="Campagne 2022",
            evaluation_campaign__institution=self.institution,
            siae=company_membership.company,
            complete=True,
            job_app__criteria__review_state=evaluation_enums.EvaluatedJobApplicationsState.REFUSED_2,
            notification_reason=evaluation_enums.EvaluatedSiaeNotificationReason.INVALID_PROOF,
            notification_text="A envoyé une photo de son chat.",
        )
        self.login(evaluated_siae, sanctions=["TEMPORARY_SUSPENSION"])
        response = self.client.post(
            reverse(self.urlname, kwargs={"evaluated_siae_pk": evaluated_siae.pk}),
            {
                "temporary_suspension_from": datetime.date(2022, 11, 20),
                "temporary_suspension_to": datetime.date(2022, 11, 20),
            },
        )
        self.assertContains(
            response,
            """
            <div class="form-group is-invalid form-group-required">
             <label class="form-label" for="id_temporary_suspension_from">
              À partir du
             </label>
             <duet-date-picker aria-label="Retrait temporaire de la capacité d’auto-prescription à partir du"
                               class="is-invalid"
                               identifier="id_temporary_suspension_from"
                               min="2022-11-24"
                               name="temporary_suspension_from"
                               required aria-invalid="true"
                               value="2022-11-20"></duet-date-picker>
              <div class="invalid-feedback">
               Assurez-vous que cette valeur est supérieure ou égale à 24/11/2022.
              </div>
            </div>
            """,
            html=True,
            count=1,
        )
        self.assertContains(
            response,
            """
            <div class="form-group is-invalid form-group-required">
             <label class="form-label" for="id_temporary_suspension_to">
              Jusqu’au
             </label>
             <duet-date-picker aria-label="Retrait temporaire de la capacité d’auto-prescription jusqu’au"
                               class="is-invalid"
                               identifier="id_temporary_suspension_to"
                               min="2022-11-24"
                               name="temporary_suspension_to"
                               required aria-invalid="true"
                               value="2022-11-20"></duet-date-picker>
              <div class="invalid-feedback">
               Assurez-vous que cette valeur est supérieure ou égale à 24/11/2022.
              </div>
            </div>
            """,
            html=True,
            count=1,
        )
        evaluated_siae.refresh_from_db()
        assert [] == mail.outbox
        with pytest.raises(Sanctions.DoesNotExist):
            evaluated_siae.sanctions

    @freeze_time("2022-10-24 11:11:00")
    def test_post_permanent_suspension(self):
        company_membership = CompanyMembershipFactory(
            company__name="Les petits jardins", user__email="siae@mailinator.com"
        )
        evaluated_siae = EvaluatedSiaeFactory(
            evaluation_campaign__name="Campagne 2022",
            evaluation_campaign__institution=self.institution,
            siae=company_membership.company,
            complete=True,
            job_app__criteria__review_state=evaluation_enums.EvaluatedJobApplicationsState.REFUSED_2,
            notification_reason=evaluation_enums.EvaluatedSiaeNotificationReason.INVALID_PROOF,
            notification_text="A envoyé une photo de son chat.",
        )
        self.login(evaluated_siae, sanctions=["PERMANENT_SUSPENSION"])
        response = self.client.post(
            reverse(self.urlname, kwargs={"evaluated_siae_pk": evaluated_siae.pk}),
            {"permanent_suspension": datetime.date(2023, 1, 1)},
        )
        self.assertRedirects(
            response,
            reverse(
                "siae_evaluations_views:institution_evaluated_siae_list",
                kwargs={"evaluation_campaign_pk": evaluated_siae.evaluation_campaign_id},
            ),
        )
        evaluated_siae.refresh_from_db()
        assert evaluated_siae.notified_at == timezone.now()
        assert evaluated_siae.notification_reason == "INVALID_PROOF"
        assert evaluated_siae.notification_text == "A envoyé une photo de son chat."
        [email] = mail.outbox
        assert email.to == ["siae@mailinator.com"]
        assert email.subject == "Notification de sanction"
        assert email.body == (
            "Bonjour,\n\n"
            "Suite aux manquements constatés lors du dernier contrôle a posteriori des auto-prescriptions réalisées "
            "dans votre SIAE, vous trouverez ci-dessous la mesure prise :\n\n"
            "- Retrait définitif de la capacité d’auto-prescription\n\n"
            "    La capacité à prescrire un parcours est rompue, elle peut être rétablie par le préfet, à la demande "
            "de la structure, sous réserve de la participation de ses dirigeants ou salariés à des actions de "
            "formation définies par l’autorité administrative.\n\n"
            "    Dans votre cas, le retrait définitif de la capacité d’auto-prescription sera effectif à partir du "
            "1 janvier 2023.\n\n"
            "Cordialement,\n\n"
            "---\n"
            "[DEV] Cet email est envoyé depuis un environnement de démonstration, "
            "merci de ne pas en tenir compte [DEV]\n"
            "Les emplois de l'inclusion\n"
            "http://localhost:8000"
        )
        assert evaluated_siae.sanctions.training_session == ""
        assert evaluated_siae.sanctions.suspension_dates == InclusiveDateRange(datetime.date(2023, 1, 1))
        assert evaluated_siae.sanctions.subsidy_cut_percent is None
        assert evaluated_siae.sanctions.subsidy_cut_dates is None
        assert evaluated_siae.sanctions.deactivation_reason == ""
        assert evaluated_siae.sanctions.no_sanction_reason == ""

    @freeze_time("2022-10-24 11:11:00")
    def test_post_permanent_suspension_bad_input(self):
        company_membership = CompanyMembershipFactory(
            company__name="Les petits jardins", user__email="siae@mailinator.com"
        )
        evaluated_siae = EvaluatedSiaeFactory(
            evaluation_campaign__name="Campagne 2022",
            evaluation_campaign__institution=self.institution,
            siae=company_membership.company,
            complete=True,
            job_app__criteria__review_state=evaluation_enums.EvaluatedJobApplicationsState.REFUSED_2,
            notification_reason=evaluation_enums.EvaluatedSiaeNotificationReason.INVALID_PROOF,
            notification_text="A envoyé une photo de son chat.",
        )
        self.login(evaluated_siae, sanctions=["PERMANENT_SUSPENSION"])
        response = self.client.post(
            reverse(self.urlname, kwargs={"evaluated_siae_pk": evaluated_siae.pk}),
            {
                "permanent_suspension": "invalid",
                # Field is ignored.
                "temporary_suspension_from": datetime.date(2023, 1, 1),
            },
        )
        self.assertContains(
            response,
            """
            <div class="form-group is-invalid form-group-required">
             <label class="form-label" for="id_permanent_suspension">
              À partir du
             </label>
             <duet-date-picker aria-label="Retrait définitif de la capacité d’auto-prescription à partir du"
                               class="is-invalid"
                               identifier="id_permanent_suspension"
                               min="2022-11-24"
                               name="permanent_suspension"
                               required aria-invalid="true"
                               value="invalid"></duet-date-picker>
              <div class="invalid-feedback">
               Saisissez une date valide.
              </div>
            </div>
            """,
            html=True,
            count=1,
        )
        evaluated_siae.refresh_from_db()
        assert [] == mail.outbox
        with pytest.raises(Sanctions.DoesNotExist):
            evaluated_siae.sanctions

    @freeze_time("2022-10-24 11:11:00")
    def test_post_subsidy_cut_percent(self):
        company_membership = CompanyMembershipFactory(
            company__name="Les petits jardins", user__email="siae@mailinator.com"
        )
        evaluated_siae = EvaluatedSiaeFactory(
            evaluation_campaign__name="Campagne 2022",
            evaluation_campaign__institution=self.institution,
            siae=company_membership.company,
            complete=True,
            job_app__criteria__review_state=evaluation_enums.EvaluatedJobApplicationsState.REFUSED_2,
            notification_reason=evaluation_enums.EvaluatedSiaeNotificationReason.INVALID_PROOF,
            notification_text="A envoyé une photo de son chat.",
        )
        self.login(evaluated_siae, sanctions=["SUBSIDY_CUT_PERCENT"])
        response = self.client.post(
            reverse(self.urlname, kwargs={"evaluated_siae_pk": evaluated_siae.pk}),
            {
                "subsidy_cut_percent": 20,
                "subsidy_cut_from": datetime.date(2023, 1, 1),
                "subsidy_cut_to": datetime.date(2023, 6, 1),
            },
        )
        self.assertRedirects(
            response,
            reverse(
                "siae_evaluations_views:institution_evaluated_siae_list",
                kwargs={"evaluation_campaign_pk": evaluated_siae.evaluation_campaign_id},
            ),
        )
        evaluated_siae.refresh_from_db()
        assert evaluated_siae.notified_at == timezone.now()
        assert evaluated_siae.notification_reason == "INVALID_PROOF"
        assert evaluated_siae.notification_text == "A envoyé une photo de son chat."
        [email] = mail.outbox
        assert email.to == ["siae@mailinator.com"]
        assert email.subject == "Notification de sanction"
        assert email.body == (
            "Bonjour,\n\n"
            "Suite aux manquements constatés lors du dernier contrôle a posteriori des auto-prescriptions réalisées "
            "dans votre SIAE, vous trouverez ci-dessous la mesure prise :\n\n"
            "- Suppression d’une partie de l’aide au poste\n\n"
            "    La suppression de l’aide attribuée aux salariés s’apprécie par l’autorité administrative, par "
            "imputation de l’année N+1. Cette notification s’accompagne d’une demande conforme auprès de l’ASP de la "
            "part du préfet. Lorsque le département a participé aux aides financières concernées en application de "
            "l’article L. 5132-2, le préfet informe le président du conseil départemental de sa décision en vue de "
            "la récupération, le cas échéant, des montants correspondants.\n\n"
            "    Dans votre cas, la suppression de 20 % de l’aide au poste sera effective à partir du 1 janvier 2023 "
            "et jusqu’au 1 juin 2023.\n\n"
            "Cordialement,\n\n"
            "---\n"
            "[DEV] Cet email est envoyé depuis un environnement de démonstration, "
            "merci de ne pas en tenir compte [DEV]\n"
            "Les emplois de l'inclusion\n"
            "http://localhost:8000"
        )
        assert evaluated_siae.sanctions.training_session == ""
        assert evaluated_siae.sanctions.suspension_dates is None
        assert evaluated_siae.sanctions.subsidy_cut_percent == 20
        assert evaluated_siae.sanctions.subsidy_cut_dates == InclusiveDateRange(
            datetime.date(2023, 1, 1), datetime.date(2023, 6, 1)
        )
        assert evaluated_siae.sanctions.deactivation_reason == ""
        assert evaluated_siae.sanctions.no_sanction_reason == ""

    @freeze_time("2022-10-24 11:11:00")
    def test_post_subsidy_percent_invalid_date_and_percent(self):
        company_membership = CompanyMembershipFactory(
            company__name="Les petits jardins", user__email="siae@mailinator.com"
        )
        evaluated_siae = EvaluatedSiaeFactory(
            evaluation_campaign__name="Campagne 2022",
            evaluation_campaign__institution=self.institution,
            siae=company_membership.company,
            complete=True,
            job_app__criteria__review_state=evaluation_enums.EvaluatedJobApplicationsState.REFUSED_2,
            notification_reason=evaluation_enums.EvaluatedSiaeNotificationReason.INVALID_PROOF,
            notification_text="A envoyé une photo de son chat.",
        )
        self.login(evaluated_siae, sanctions=["SUBSIDY_CUT_PERCENT"])
        response = self.client.post(
            reverse(self.urlname, kwargs={"evaluated_siae_pk": evaluated_siae.pk}),
            {
                "subsidy_cut_percent": "110",
                "subsidy_cut_from": "invalid",
                "subsidy_cut_to": "invalid",
            },
        )
        self.assertContains(
            response,
            """
            <div class="form-group is-invalid form-group-required">
             <label class="form-label" for="id_subsidy_cut_percent">
              Pourcentage d’aide retiré à la SIAE
             </label>
             <input aria-label="Suppression d’une partie de l’aide au poste à partir du"
                    class="form-control is-invalid"
                    id="id_subsidy_cut_percent"
                    max="100"
                    min="1"
                    name="subsidy_cut_percent"
                    placeholder="Pourcentage d’aide retiré à la SIAE"
                    required aria-invalid="true"
                    step="1"
                    type="number"
                    value="110" />
             <div class="invalid-feedback">
              Assurez-vous que cette valeur est inférieure ou égale à 100.
             </div>
            </div>
            <div class="form-group is-invalid form-group-required">
             <label class="form-label" for="id_subsidy_cut_from">
              À partir du
             </label>
             <duet-date-picker aria-label="Suppression d’une partie de l’aide au poste à partir du"
                               class="is-invalid"
                               identifier="id_subsidy_cut_from"
                               name="subsidy_cut_from"
                               required aria-invalid="true"
                               value="invalid"></duet-date-picker>
              <div class="invalid-feedback">
               Saisissez une date valide.
              </div>
            </div>
            <div class="form-group is-invalid form-group-required">
             <label class="form-label" for="id_subsidy_cut_to">
              Jusqu’au
             </label>
             <duet-date-picker aria-label="Suppression d’une partie de l’aide au poste jusqu’au"
                               class="is-invalid"
                               identifier="id_subsidy_cut_to"
                               name="subsidy_cut_to"
                               required aria-invalid="true"
                               value="invalid"></duet-date-picker>
              <div class="invalid-feedback">
               Saisissez une date valide.
              </div>
            </div>
            """,
            html=True,
            count=1,
        )
        evaluated_siae.refresh_from_db()
        assert [] == mail.outbox
        with pytest.raises(Sanctions.DoesNotExist):
            evaluated_siae.sanctions

    @freeze_time("2022-10-24 11:11:00")
    def test_post_subsidy_cut_full(self):
        company_membership = CompanyMembershipFactory(
            company__name="Les petits jardins", user__email="siae@mailinator.com"
        )
        evaluated_siae = EvaluatedSiaeFactory(
            evaluation_campaign__name="Campagne 2022",
            evaluation_campaign__institution=self.institution,
            siae=company_membership.company,
            complete=True,
            job_app__criteria__review_state=evaluation_enums.EvaluatedJobApplicationsState.REFUSED_2,
            notification_reason=evaluation_enums.EvaluatedSiaeNotificationReason.INVALID_PROOF,
            notification_text="A envoyé une photo de son chat.",
        )
        self.login(evaluated_siae, sanctions=["SUBSIDY_CUT_FULL"])
        response = self.client.post(
            reverse(self.urlname, kwargs={"evaluated_siae_pk": evaluated_siae.pk}),
            {
                "subsidy_cut_percent": 20,  # Ignored.
                "subsidy_cut_from": datetime.date(2023, 1, 1),
                "subsidy_cut_to": datetime.date(2023, 6, 1),
            },
        )
        self.assertRedirects(
            response,
            reverse(
                "siae_evaluations_views:institution_evaluated_siae_list",
                kwargs={"evaluation_campaign_pk": evaluated_siae.evaluation_campaign_id},
            ),
        )
        evaluated_siae.refresh_from_db()
        assert evaluated_siae.notified_at == timezone.now()
        assert evaluated_siae.notification_reason == "INVALID_PROOF"
        assert evaluated_siae.notification_text == "A envoyé une photo de son chat."
        [email] = mail.outbox
        assert email.to == ["siae@mailinator.com"]
        assert email.subject == "Notification de sanction"
        assert email.body == (
            "Bonjour,\n\n"
            "Suite aux manquements constatés lors du dernier contrôle a posteriori des auto-prescriptions réalisées "
            "dans votre SIAE, vous trouverez ci-dessous la mesure prise :\n\n"
            "- Suppression de l’aide au poste\n\n"
            "    La suppression de l’aide attribuée aux salariés s’apprécie par l’autorité administrative, par "
            "imputation de l’année N+1. Cette notification s’accompagne d’une demande conforme auprès de l’ASP de la "
            "part du préfet. Lorsque le département a participé aux aides financières concernées en application de "
            "l’article L. 5132-2, le préfet informe le président du conseil départemental de sa décision en vue de "
            "la récupération, le cas échéant, des montants correspondants.\n\n"
            "    Dans votre cas, la suppression de l’aide au poste sera effective à partir du 1 janvier 2023 "
            "et jusqu’au 1 juin 2023.\n\n"
            "Cordialement,\n\n"
            "---\n"
            "[DEV] Cet email est envoyé depuis un environnement de démonstration, "
            "merci de ne pas en tenir compte [DEV]\n"
            "Les emplois de l'inclusion\n"
            "http://localhost:8000"
        )
        assert evaluated_siae.sanctions.training_session == ""
        assert evaluated_siae.sanctions.suspension_dates is None
        assert evaluated_siae.sanctions.subsidy_cut_percent == 100
        assert evaluated_siae.sanctions.subsidy_cut_dates == InclusiveDateRange(
            datetime.date(2023, 1, 1), datetime.date(2023, 6, 1)
        )
        assert evaluated_siae.sanctions.deactivation_reason == ""
        assert evaluated_siae.sanctions.no_sanction_reason == ""

    @freeze_time("2022-10-24 11:11:00")
    def test_post_deactivation(self):
        company_membership = CompanyMembershipFactory(
            company__name="Les petits jardins", user__email="siae@mailinator.com"
        )
        evaluated_siae = EvaluatedSiaeFactory(
            evaluation_campaign__name="Campagne 2022",
            evaluation_campaign__institution=self.institution,
            siae=company_membership.company,
            complete=True,
            job_app__criteria__review_state=evaluation_enums.EvaluatedJobApplicationsState.REFUSED_2,
            notification_reason=evaluation_enums.EvaluatedSiaeNotificationReason.INVALID_PROOF,
            notification_text="A envoyé une photo de son chat.",
        )
        self.login(evaluated_siae, sanctions=["DEACTIVATION"])
        response = self.client.post(
            reverse(self.urlname, kwargs={"evaluated_siae_pk": evaluated_siae.pk}),
            {"deactivation_reason": "Chat trop vorace."},
        )
        self.assertRedirects(
            response,
            reverse(
                "siae_evaluations_views:institution_evaluated_siae_list",
                kwargs={"evaluation_campaign_pk": evaluated_siae.evaluation_campaign_id},
            ),
        )
        evaluated_siae.refresh_from_db()
        assert evaluated_siae.notified_at == timezone.now()
        assert evaluated_siae.notification_reason == "INVALID_PROOF"
        assert evaluated_siae.notification_text == "A envoyé une photo de son chat."
        [email] = mail.outbox
        assert email.to == ["siae@mailinator.com"]
        assert email.subject == "Notification de sanction"
        assert email.body == (
            "Bonjour,\n\n"
            "Suite aux manquements constatés lors du dernier contrôle a posteriori des auto-prescriptions réalisées "
            "dans votre SIAE, vous trouverez ci-dessous la mesure prise :\n\n"
            "- Déconventionnement de la structure\n\n"
            "    La suppression du conventionnement s’apprécie par l’autorité administrative. Cette notification "
            "s’accompagne d’une demande conforme auprès de l’ASP de la part du préfet. Lorsque le département a "
            "participé aux aides financières concernées en application de l’article L. 5132-2, le préfet informe le "
            "président du conseil départemental de sa décision.\n\n"
            "    Chat trop vorace.\n\n"
            "Cordialement,\n\n"
            "---\n"
            "[DEV] Cet email est envoyé depuis un environnement de démonstration, "
            "merci de ne pas en tenir compte [DEV]\n"
            "Les emplois de l'inclusion\n"
            "http://localhost:8000"
        )
        assert evaluated_siae.sanctions.training_session == ""
        assert evaluated_siae.sanctions.suspension_dates is None
        assert evaluated_siae.sanctions.subsidy_cut_percent is None
        assert evaluated_siae.sanctions.subsidy_cut_dates is None
        assert evaluated_siae.sanctions.deactivation_reason == "Chat trop vorace."
        assert evaluated_siae.sanctions.no_sanction_reason == ""

    @freeze_time("2022-10-24 11:11:00")
    def test_post_no_sanction(self):
        company_membership = CompanyMembershipFactory(
            company__name="Les petits jardins", user__email="siae@mailinator.com"
        )
        evaluated_siae = EvaluatedSiaeFactory(
            evaluation_campaign__name="Campagne 2022",
            evaluation_campaign__institution=self.institution,
            siae=company_membership.company,
            complete=True,
            job_app__criteria__review_state=evaluation_enums.EvaluatedJobApplicationsState.REFUSED_2,
            notification_reason=evaluation_enums.EvaluatedSiaeNotificationReason.INVALID_PROOF,
            notification_text="A envoyé une photo de son chat.",
        )
        self.login(evaluated_siae, sanctions=["NO_SANCTIONS"])
        response = self.client.post(
            reverse(self.urlname, kwargs={"evaluated_siae_pk": evaluated_siae.pk}),
            {"no_sanction_reason": "Chat trop mignon."},
        )
        self.assertRedirects(
            response,
            reverse(
                "siae_evaluations_views:institution_evaluated_siae_list",
                kwargs={"evaluation_campaign_pk": evaluated_siae.evaluation_campaign_id},
            ),
        )
        evaluated_siae.refresh_from_db()
        assert evaluated_siae.notified_at == timezone.now()
        assert evaluated_siae.notification_reason == "INVALID_PROOF"
        assert evaluated_siae.notification_text == "A envoyé une photo de son chat."
        [email] = mail.outbox
        assert email.to == ["siae@mailinator.com"]
        assert email.subject == "Notification de sanction"
        assert email.body == (
            "Bonjour,\n\n"
            "Suite aux manquements constatés lors du dernier contrôle a posteriori des auto-prescriptions réalisées "
            "dans votre SIAE, nous avons décidé de ne pas appliquer de sanction. Vous trouverez ci-dessous le détail "
            "de cette décision :\n\n"
            "Chat trop mignon.\n\n"
            "Cordialement,\n\n"
            "---\n"
            "[DEV] Cet email est envoyé depuis un environnement de démonstration, "
            "merci de ne pas en tenir compte [DEV]\n"
            "Les emplois de l'inclusion\n"
            "http://localhost:8000"
        )
        assert evaluated_siae.sanctions.training_session == ""
        assert evaluated_siae.sanctions.suspension_dates is None
        assert evaluated_siae.sanctions.subsidy_cut_percent is None
        assert evaluated_siae.sanctions.subsidy_cut_dates is None
        assert evaluated_siae.sanctions.deactivation_reason == ""
        assert evaluated_siae.sanctions.no_sanction_reason == "Chat trop mignon."

    @freeze_time("2022-10-24 11:11:00")
    def test_post_combined_sanctions(self):
        company_membership = CompanyMembershipFactory(
            company__name="Les petits jardins", user__email="siae@mailinator.com"
        )
        evaluated_siae = EvaluatedSiaeFactory(
            evaluation_campaign__name="Campagne 2022",
            evaluation_campaign__institution=self.institution,
            siae=company_membership.company,
            complete=True,
            job_app__criteria__review_state=evaluation_enums.EvaluatedJobApplicationsState.REFUSED_2,
            notification_reason=evaluation_enums.EvaluatedSiaeNotificationReason.INVALID_PROOF,
            notification_text="A envoyé une photo de son chat.",
        )
        self.login(evaluated_siae, sanctions=["PERMANENT_SUSPENSION", "SUBSIDY_CUT_PERCENT", "DEACTIVATION"])
        response = self.client.post(
            reverse(self.urlname, kwargs={"evaluated_siae_pk": evaluated_siae.pk}),
            {
                "permanent_suspension": datetime.date(2023, 1, 1),
                "subsidy_cut_percent": 20,
                "subsidy_cut_from": datetime.date(2023, 1, 1),
                "subsidy_cut_to": datetime.date(2023, 6, 1),
                "deactivation_reason": "Chat trop vorace.",
            },
        )
        self.assertRedirects(
            response,
            reverse(
                "siae_evaluations_views:institution_evaluated_siae_list",
                kwargs={"evaluation_campaign_pk": evaluated_siae.evaluation_campaign_id},
            ),
        )
        evaluated_siae.refresh_from_db()
        assert evaluated_siae.notified_at == timezone.now()
        assert evaluated_siae.notification_reason == "INVALID_PROOF"
        assert evaluated_siae.notification_text == "A envoyé une photo de son chat."
        [email] = mail.outbox
        assert email.to == ["siae@mailinator.com"]
        assert email.subject == "Notification de sanctions"
        assert email.body == (
            "Bonjour,\n\n"
            "Suite aux manquements constatés lors du dernier contrôle a posteriori des auto-prescriptions réalisées "
            "dans votre SIAE, vous trouverez ci-dessous les mesures prises :\n\n"
            "- Retrait définitif de la capacité d’auto-prescription\n\n"
            "    La capacité à prescrire un parcours est rompue, elle peut être rétablie par le préfet, à la demande "
            "de la structure, sous réserve de la participation de ses dirigeants ou salariés à des actions de "
            "formation définies par l’autorité administrative.\n\n"
            "    Dans votre cas, le retrait définitif de la capacité d’auto-prescription sera effectif à partir du "
            "1 janvier 2023.\n\n"
            "- Suppression d’une partie de l’aide au poste\n\n"
            "    La suppression de l’aide attribuée aux salariés s’apprécie par l’autorité administrative, par "
            "imputation de l’année N+1. Cette notification s’accompagne d’une demande conforme auprès de l’ASP de la "
            "part du préfet. Lorsque le département a participé aux aides financières concernées en application de "
            "l’article L. 5132-2, le préfet informe le président du conseil départemental de sa décision en vue de "
            "la récupération, le cas échéant, des montants correspondants.\n\n"
            "    Dans votre cas, la suppression de 20 % de l’aide au poste sera effective à partir du 1 janvier 2023 "
            "et jusqu’au 1 juin 2023.\n\n"
            "- Déconventionnement de la structure\n\n"
            "    La suppression du conventionnement s’apprécie par l’autorité administrative. Cette notification "
            "s’accompagne d’une demande conforme auprès de l’ASP de la part du préfet. Lorsque le département a "
            "participé aux aides financières concernées en application de l’article L. 5132-2, le préfet informe le "
            "président du conseil départemental de sa décision.\n\n"
            "    Chat trop vorace.\n\n"
            "Cordialement,\n\n"
            "---\n"
            "[DEV] Cet email est envoyé depuis un environnement de démonstration, "
            "merci de ne pas en tenir compte [DEV]\n"
            "Les emplois de l'inclusion\n"
            "http://localhost:8000"
        )
        assert evaluated_siae.sanctions.training_session == ""
        assert evaluated_siae.sanctions.suspension_dates == InclusiveDateRange(datetime.date(2023, 1, 1))
        assert evaluated_siae.sanctions.subsidy_cut_percent == 20
        assert evaluated_siae.sanctions.subsidy_cut_dates == InclusiveDateRange(
            datetime.date(2023, 1, 1), datetime.date(2023, 6, 1)
        )
        assert evaluated_siae.sanctions.deactivation_reason == "Chat trop vorace."
        assert evaluated_siae.sanctions.no_sanction_reason == ""


class InstitutionEvaluatedJobApplicationViewTest(TestCase):
    btn_modifier_html = """
    <button class="btn btn-sm btn-primary" aria-label="Modifier l'état de ce justificatif">Modifier</button>
    """
    save_text = "Enregistrer le commentaire"

    def setUp(self):
        super().setUp()
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
                "siae_evaluations_views:evaluated_job_application",
                kwargs={"evaluated_job_application_pk": 1},
            )
        )
        assert response.status_code == 404

        # institution with evaluation_campaign in "institution sets its ratio" phase
        evaluation_campaign = EvaluationCampaignFactory(institution=self.institution)
        evaluated_siae = create_evaluated_siae_consistent_datas(evaluation_campaign)
        evaluated_job_application = evaluated_siae.evaluated_job_applications.first()
        response = self.client.get(
            reverse(
                "siae_evaluations_views:evaluated_job_application",
                kwargs={"evaluated_job_application_pk": evaluated_job_application.pk},
            )
        )
        assert response.status_code == 404

        # institution with evaluation_campaign in "siae upload its proofs" phase
        evaluation_campaign.evaluations_asked_at = timezone.now()
        evaluation_campaign.save(update_fields=["evaluations_asked_at"])
        response = self.client.get(
            reverse(
                "siae_evaluations_views:evaluated_job_application",
                kwargs={"evaluated_job_application_pk": evaluated_job_application.pk},
            )
        )
        assert response.status_code == 200

    def test_recently_closed_campaign(self):
        evaluated_siae = EvaluatedSiaeFactory(
            complete=True,
            job_app__criteria__review_state=evaluation_enums.EvaluatedJobApplicationsState.ACCEPTED,
            evaluation_campaign__institution=self.institution,
        )
        job_app = evaluated_siae.evaluated_job_applications.get()
        crit = job_app.evaluated_administrative_criteria.get()
        self.client.force_login(self.user)
        response = self.client.get(
            reverse(
                "siae_evaluations_views:evaluated_job_application",
                kwargs={"evaluated_job_application_pk": job_app.pk},
            )
        )
        proof_url = reverse(
            "siae_evaluations_views:view_proof",
            kwargs={"evaluated_administrative_criteria_id": crit.pk},
        )
        self.assertContains(
            response,
            f"""
            <a href="{proof_url}"
               rel="noopener"
               target="_blank"
               class="btn btn-sm btn-link"
               aria-label="Revoir ce justificatif (ouverture dans un nouvel onglet)"
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
                "siae_evaluations_views:evaluated_job_application",
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
                "siae_evaluations_views:evaluated_job_application",
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
                "siae_evaluations_views:evaluated_job_application",
                kwargs={"evaluated_job_application_pk": evaluated_job_application.pk},
            )
        )
        assert response.context["evaluated_job_application"] == evaluated_job_application
        assert response.context["evaluated_siae"] == evaluated_siae
        assert isinstance(response.context["form"], LaborExplanationForm)
        assert (
            response.context["back_url"]
            == reverse(
                "siae_evaluations_views:evaluated_siae_detail",
                kwargs={"evaluated_siae_pk": evaluated_siae.pk},
            )
            + f"#{evaluated_job_application.pk}"
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
                "siae_evaluations_views:evaluated_job_application",
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
                "siae_evaluations_views:evaluated_job_application",
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
        crit = past_job_application.evaluated_administrative_criteria.get()

        self.client.force_login(self.user)
        response = self.client.get(
            reverse(
                "siae_evaluations_views:evaluated_job_application",
                kwargs={"evaluated_job_application_pk": past_job_application.pk},
            )
        )
        self.assertNotContains(response, self.save_text)
        proof_url = reverse(
            "siae_evaluations_views:view_proof",
            kwargs={"evaluated_administrative_criteria_id": crit.pk},
        )
        self.assertContains(
            response,
            f"""
            <a href="{proof_url}"
               rel="noopener"
               target="_blank"
               class="btn btn-sm btn-link"
               aria-label="Revoir ce justificatif (ouverture dans un nouvel onglet)"
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
                "siae_evaluations_views:evaluated_job_application",
                kwargs={"evaluated_job_application_pk": past_job_application.pk},
            ),
            data={"labor_inspector_explanation": "Invalide !"},
        )
        assert response.status_code == 404

    @pytest.mark.ignore_unknown_variable_template_error("reviewed_at")
    def test_criterion_validation(self):
        self.client.force_login(self.user)

        # fixme vincentporte : use EvaluatedAdministrativeCriteria instead
        evaluated_administrative_criteria = get_evaluated_administrative_criteria(self.institution)

        refuse_url = self.refuse_url(evaluated_administrative_criteria)
        accepte_url = self.accept_url(evaluated_administrative_criteria)
        reinit_url = self.reinit_url(evaluated_administrative_criteria)
        url_view = reverse(
            "siae_evaluations_views:evaluated_job_application",
            kwargs={"evaluated_job_application_pk": evaluated_administrative_criteria.evaluated_job_application.pk},
        )

        # unverified evaluated_administrative_criteria
        evaluated_administrative_criteria.submitted_at = timezone.now()
        evaluated_administrative_criteria.proof = FileFactory()
        evaluated_administrative_criteria.save(update_fields=["submitted_at", "proof"])
        response = self.client.get(url_view)
        self.assertContains(response, refuse_url)
        self.assertContains(response, accepte_url)
        self.assertNotContains(response, reinit_url)

        # accepted
        evaluated_administrative_criteria.review_state = evaluation_enums.EvaluatedAdministrativeCriteriaState.ACCEPTED
        evaluated_administrative_criteria.save(update_fields=["review_state"])

        response = self.client.get(url_view)
        self.assertNotContains(response, refuse_url)
        self.assertNotContains(response, accepte_url)
        self.assertContains(response, reinit_url)
        self.assertContains(
            response, '<strong class="text-success"><i class="ri-check-line"></i> Validé</strong>', html=True
        )

        # refused
        evaluated_administrative_criteria.review_state = evaluation_enums.EvaluatedAdministrativeCriteriaState.REFUSED
        evaluated_administrative_criteria.save(update_fields=["review_state"])

        response = self.client.get(url_view)
        self.assertNotContains(response, refuse_url)
        self.assertNotContains(response, accepte_url)
        self.assertContains(response, reinit_url)
        self.assertContains(
            response, '<strong class="text-danger"><i class="ri-close-line"></i> Refusé</strong>', html=True
        )

        # reinited
        evaluated_administrative_criteria.review_state = evaluation_enums.EvaluatedAdministrativeCriteriaState.PENDING
        evaluated_administrative_criteria.save(update_fields=["review_state"])

        response = self.client.get(url_view)
        self.assertContains(response, refuse_url)
        self.assertContains(response, accepte_url)
        self.assertNotContains(response, reinit_url)

        # reviewed
        evaluated_administrative_criteria.evaluated_job_application.evaluated_siae.reviewed_at = timezone.now()
        evaluated_administrative_criteria.evaluated_job_application.evaluated_siae.save(update_fields=["reviewed_at"])
        evaluated_administrative_criteria.review_state = evaluation_enums.EvaluatedAdministrativeCriteriaState.ACCEPTED
        evaluated_administrative_criteria.save(update_fields=["review_state"])

        response = self.client.get(url_view)
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
        assert form.is_valid()

        form_data = {"labor_inspector_explanation": None}
        form = LaborExplanationForm(instance=evaluated_job_application, data=form_data)
        assert form.is_valid()

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
            "siae_evaluations_views:evaluated_job_application",
            kwargs={"evaluated_job_application_pk": evaluated_job_application.pk},
        )

        response = self.client.get(url)
        assert response.status_code == 200

        post_data = {"labor_inspector_explanation": "test"}
        response = self.client.post(url, data=post_data)
        assert response.status_code == 302
        assert (
            response.url
            == reverse(
                "siae_evaluations_views:evaluated_siae_detail",
                kwargs={"evaluated_siae_pk": evaluated_siae.pk},
            )
            + f"#{evaluated_job_application.pk}"
        )

        updated_evaluated_job_application = EvaluatedJobApplication.objects.get(pk=evaluated_job_application.pk)
        assert (
            updated_evaluated_job_application.labor_inspector_explanation == post_data["labor_inspector_explanation"]
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
                "siae_evaluations_views:evaluated_job_application",
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
            "siae_evaluations_views:evaluated_job_application",
            kwargs={"evaluated_job_application_pk": evaluated_administrative_criteria.evaluated_job_application.pk},
        )
        with self.assertNumQueries(
            BASE_NUM_QUERIES
            + 1  # django session
            + 2  # fetch user & its memberships (middleware)
            + 3  # fetch evaluated_jobapp & criteria
            + 3  # jobapp, approvals & users
            + 2  # evaljobapp & its evalcriteria
            + 3  # savepoint, update session, release savepoint
        ):
            response = self.client.get(url)
        assert response.status_code == 200

    @pytest.mark.ignore_unknown_variable_template_error("reviewed_at")
    def test_job_application_state_labels(self):
        self.client.force_login(self.user)
        # fixme vincentporte : use EvaluatedAdministrativeCriteria instead
        evaluated_administrative_criteria = get_evaluated_administrative_criteria(self.institution)
        evaluated_administrative_criteria.proof = FileFactory()
        evaluated_administrative_criteria.submitted_at = timezone.now()
        evaluated_administrative_criteria.save(update_fields=["submitted_at", "proof"])

        url_view = reverse(
            "siae_evaluations_views:evaluated_job_application",
            kwargs={"evaluated_job_application_pk": evaluated_administrative_criteria.evaluated_job_application.pk},
        )

        # Unset
        response = self.client.get(url_view)
        self.assertContains(response, "bg-accent-03")
        self.assertContains(response, "À traiter")

        # Refused
        evaluated_administrative_criteria.review_state = evaluation_enums.EvaluatedAdministrativeCriteriaState.REFUSED
        evaluated_administrative_criteria.save(update_fields=["review_state"])
        response = self.client.get(url_view)
        self.assertContains(response, "bg-danger")
        self.assertContains(response, "Problème constaté")

        # Accepted
        evaluated_administrative_criteria.review_state = evaluation_enums.EvaluatedAdministrativeCriteriaState.ACCEPTED
        evaluated_administrative_criteria.save(update_fields=["review_state"])
        response = self.client.get(url_view)
        self.assertContains(response, "bg-success")
        self.assertContains(response, "Validé")


class InstitutionEvaluatedAdministrativeCriteriaViewTest(TestCase):
    def setUp(self):
        super().setUp()
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
        assert response.status_code == 404

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
        assert response.status_code == 404

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
        assert response.status_code == 302

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
        assert response.status_code == 404

    def test_actions_and_redirection(self):
        self.client.force_login(self.user)
        # fixme vincentporte : use EvaluatedAdministrativeCriteria instead
        evaluated_administrative_criteria = get_evaluated_administrative_criteria(self.institution)
        redirect_url = reverse(
            "siae_evaluations_views:evaluated_job_application",
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
        assert response.status_code == 302
        assert response.url == redirect_url
        eval_admin_crit = EvaluatedAdministrativeCriteria.objects.get(pk=evaluated_administrative_criteria.pk)
        assert evaluation_enums.EvaluatedAdministrativeCriteriaState.REFUSED == eval_admin_crit.review_state

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
        assert response.status_code == 302
        assert response.url == redirect_url
        eval_admin_crit.refresh_from_db()
        assert evaluation_enums.EvaluatedAdministrativeCriteriaState.PENDING == eval_admin_crit.review_state

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
        assert response.status_code == 302
        assert response.url == redirect_url
        eval_admin_crit.refresh_from_db()
        assert evaluation_enums.EvaluatedAdministrativeCriteriaState.ACCEPTED == eval_admin_crit.review_state

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
        assert response.status_code == 302
        assert response.url == redirect_url
        eval_admin_crit.refresh_from_db()
        assert evaluation_enums.EvaluatedAdministrativeCriteriaState.REFUSED == eval_admin_crit.review_state

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
        assert response.status_code == 302
        assert response.url == redirect_url
        eval_admin_crit.refresh_from_db()
        assert evaluation_enums.EvaluatedAdministrativeCriteriaState.REFUSED_2 == eval_admin_crit.review_state


class InstitutionEvaluatedSiaeValidationViewTest(MessagesTestMixin, TestCase):
    @classmethod
    def setUpTestData(cls):
        membership = InstitutionMembershipFactory()
        cls.institution = membership.institution
        cls.user = membership.user
        cls.evaluation_campaign = EvaluationCampaignFactory(institution=membership.institution)
        cls.evaluated_siae = create_evaluated_siae_consistent_datas(cls.evaluation_campaign)

    def test_access(self):
        self.client.force_login(self.user)

        # institution without evaluation_campaign
        response = self.client.post(
            reverse(
                "siae_evaluations_views:institution_evaluated_siae_validation",
                kwargs={"evaluated_siae_pk": 1},
            )
        )
        assert response.status_code == 404

        # institution with evaluation_campaign in "institution sets its ratio" phase
        url = reverse(
            "siae_evaluations_views:institution_evaluated_siae_validation",
            kwargs={"evaluated_siae_pk": self.evaluated_siae.pk},
        )

        response = self.client.post(url)
        assert response.status_code == 404

        # institution with evaluation_campaign in "siae upload its proofs" phase
        self.evaluation_campaign.evaluations_asked_at = timezone.now()
        self.evaluation_campaign.save(update_fields=["evaluations_asked_at"])
        response = self.client.post(url)
        assert response.status_code == 302

        # institution with ended evaluation_campaign
        self.evaluation_campaign.ended_at = timezone.now()
        self.evaluation_campaign.save(update_fields=["ended_at"])
        response = self.client.post(url)
        assert response.status_code == 404

    def test_actions_and_redirection(self):
        self.client.force_login(self.user)

        self.evaluation_campaign.evaluations_asked_at = timezone.now()
        self.evaluation_campaign.save(update_fields=["evaluations_asked_at"])
        EvaluatedAdministrativeCriteria.objects.filter(
            evaluated_job_application__evaluated_siae=self.evaluated_siae
        ).update(submitted_at=timezone.now(), proof=FileFactory())

        url = reverse(
            "siae_evaluations_views:institution_evaluated_siae_validation",
            kwargs={"evaluated_siae_pk": self.evaluated_siae.pk},
        )
        redirect_url = reverse(
            "siae_evaluations_views:evaluated_siae_detail",
            kwargs={"evaluated_siae_pk": self.evaluated_siae.pk},
        )

        # before validation
        response = self.client.post(url)
        assert response.status_code == 302
        assert response.url == redirect_url
        self.evaluated_siae.refresh_from_db()
        assert self.evaluated_siae.reviewed_at is None
        self.assertMessages(response, [])

        # accepted
        EvaluatedAdministrativeCriteria.objects.filter(
            evaluated_job_application__evaluated_siae=self.evaluated_siae
        ).update(review_state=evaluation_enums.EvaluatedAdministrativeCriteriaState.ACCEPTED)
        response = self.client.post(url)
        self.evaluated_siae.refresh_from_db()
        assert self.evaluated_siae.reviewed_at is not None
        self.assertMessages(
            response,
            [
                messages.Message(
                    messages.SUCCESS,
                    "<b>Résultats enregistrés !</b><br>"
                    "Merci d'avoir pris le temps de contrôler les pièces justificatives.",
                )
            ],
        )
        self.assertRedirects(response, redirect_url)

        # refused
        self.evaluated_siae.reviewed_at = None
        self.evaluated_siae.final_reviewed_at = None
        self.evaluated_siae.save(update_fields=["reviewed_at", "final_reviewed_at"])
        EvaluatedAdministrativeCriteria.objects.filter(
            evaluated_job_application__evaluated_siae=self.evaluated_siae
        ).update(review_state=evaluation_enums.EvaluatedAdministrativeCriteriaState.REFUSED)

        response = self.client.post(url)
        self.evaluated_siae.refresh_from_db()
        assert self.evaluated_siae.reviewed_at is not None
        self.assertMessages(
            response,
            [
                messages.Message(
                    messages.SUCCESS,
                    "<b>Résultats enregistrés !</b><br>"
                    "Merci d'avoir pris le temps de contrôler les pièces justificatives.",
                )
            ],
        )
        self.assertRedirects(response, redirect_url)

        # cannot validate twice
        timestamp = self.evaluated_siae.reviewed_at
        response = self.client.post(url)
        assert response.status_code == 302
        self.evaluated_siae.refresh_from_db()
        assert timestamp == self.evaluated_siae.reviewed_at
        self.assertMessages(response, [])

    def test_accepted(self):
        evaluated_siae = EvaluatedSiaeFactory.create(
            evaluation_campaign__institution=self.institution,
            evaluation_campaign__evaluations_asked_at=timezone.now() - relativedelta(weeks=1),
            siae__name="Les petits jardins",
        )
        evaluated_job_application = EvaluatedJobApplicationFactory(evaluated_siae=evaluated_siae)
        EvaluatedAdministrativeCriteriaFactory(
            evaluated_job_application=evaluated_job_application,
            uploaded_at=timezone.now() - relativedelta(hours=2),
            submitted_at=timezone.now() - relativedelta(hours=1),
            review_state=evaluation_enums.EvaluatedAdministrativeCriteriaState.ACCEPTED,
        )
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
                "siae_evaluations_views:evaluated_siae_detail",
                kwargs={"evaluated_siae_pk": evaluated_siae.pk},
            ),
        )
        assert mail.outbox == []

    def test_accepted_after_adversarial(self):
        evaluated_siae = EvaluatedSiaeFactory.create(
            evaluation_campaign__institution=self.institution,
            evaluation_campaign__evaluations_asked_at=timezone.now() - relativedelta(weeks=1),
            siae__name="Les petits jardins",
            reviewed_at=timezone.now() - relativedelta(days=1),
        )
        evaluated_job_application = EvaluatedJobApplicationFactory(evaluated_siae=evaluated_siae)
        EvaluatedAdministrativeCriteriaFactory(
            evaluated_job_application=evaluated_job_application,
            uploaded_at=timezone.now() - relativedelta(hours=2),
            submitted_at=timezone.now() - relativedelta(hours=1),
            review_state=evaluation_enums.EvaluatedAdministrativeCriteriaState.ACCEPTED,
        )
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
                "siae_evaluations_views:evaluated_siae_detail",
                kwargs={"evaluated_siae_pk": evaluated_siae.pk},
            ),
        )
        assert mail.outbox == []

    def test_refused(self):
        evaluated_siae = EvaluatedSiaeFactory.create(
            evaluation_campaign__institution=self.institution,
            evaluation_campaign__evaluations_asked_at=timezone.now() - relativedelta(weeks=1),
            siae__name="Les petits jardins",
        )
        evaluated_job_application = EvaluatedJobApplicationFactory(evaluated_siae=evaluated_siae)
        EvaluatedAdministrativeCriteriaFactory(
            evaluated_job_application=evaluated_job_application,
            uploaded_at=timezone.now() - relativedelta(hours=2),
            submitted_at=timezone.now() - relativedelta(hours=1),
            review_state=evaluation_enums.EvaluatedAdministrativeCriteriaState.REFUSED,
        )
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
                "siae_evaluations_views:evaluated_siae_detail",
                kwargs={"evaluated_siae_pk": evaluated_siae.pk},
            ),
        )
        assert mail.outbox == []

    def test_refused_after_adversarial(self):
        evaluated_siae = EvaluatedSiaeFactory.create(
            evaluation_campaign__institution=self.institution,
            evaluation_campaign__evaluations_asked_at=timezone.now() - relativedelta(weeks=1),
            siae__name="Les petits jardins",
            reviewed_at=timezone.now() - relativedelta(days=1),
        )
        evaluated_job_application = EvaluatedJobApplicationFactory(evaluated_siae=evaluated_siae)
        EvaluatedAdministrativeCriteriaFactory(
            evaluated_job_application=evaluated_job_application,
            uploaded_at=timezone.now() - relativedelta(hours=2),
            submitted_at=timezone.now() - relativedelta(hours=1),
            review_state=evaluation_enums.EvaluatedAdministrativeCriteriaState.REFUSED_2,
        )
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
                "siae_evaluations_views:evaluated_siae_detail",
                kwargs={"evaluated_siae_pk": evaluated_siae.pk},
            ),
        )
        assert mail.outbox == []


class InstitutionCalendarViewTest(TestCase):
    def setUp(self):
        super().setUp()
        membership = InstitutionMembershipFactory(institution__name="DDETS Ille et Vilaine")
        self.user = membership.user
        self.institution = membership.institution

    def test_active_campaign_calendar(self):
        calendar_html = """
            <table class="table">
                <thead class="thead-light">
                    <tr>
                        <th></th>
                        <th scope="col">Dates</th>
                        <th scope="col">Acteurs</th>
                        <th scope="col">Actions attendues</th>
                    </tr>
                </thead>
                <tbody>
                    <tr>
                        <th scope="row">Phase 1</th>
                        <td>Du 15 mai 2023 au 11 juin 2023</td>

                        <td>DDETS</td>
                        <td>Sélection du taux de SIAE</td>
                    </tr>
                </tbody>
            </table>
        """
        evaluation_campaign = EvaluationCampaignFactory(institution=self.institution, calendar__html=calendar_html)
        calendar_url = reverse("siae_evaluations_views:campaign_calendar", args=[evaluation_campaign.pk])

        self.client.force_login(self.user)
        response = self.client.get(reverse("dashboard:index"))
        assert response.status_code == 200
        self.assertContains(response, calendar_url)

        response = self.client.get(calendar_url)
        assert response.status_code == 200
        self.assertContains(response, calendar_html)

        # Old campaigns don't have a calendar.
        evaluation_campaign.calendar.delete()
        response = self.client.get(reverse("dashboard:index"))
        assert response.status_code == 200
        self.assertNotContains(response, calendar_url)
