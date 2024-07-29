from datetime import date, datetime
from functools import partial

import pytest
from dateutil.relativedelta import relativedelta
from django.conf import settings
from django.contrib.auth import get_user
from django.test import override_settings
from django.urls import reverse
from django.utils import timezone
from freezegun import freeze_time
from pytest_django.asserts import assertContains, assertNotContains
from unittest_parametrize import ParametrizedTestCase, param, parametrize

from itou.companies.enums import CompanyKind
from itou.employee_record.enums import Status
from itou.institutions.enums import InstitutionKind
from itou.job_applications.enums import JobApplicationState
from itou.prescribers.enums import PrescriberOrganizationKind
from itou.prescribers.models import PrescriberOrganization
from itou.siae_evaluations import enums as evaluation_enums
from itou.siae_evaluations.constants import CAMPAIGN_VIEWABLE_DURATION
from itou.siae_evaluations.models import Sanctions
from itou.users.enums import Title
from itou.utils import constants as global_constants
from itou.utils.models import InclusiveDateRange
from itou.utils.templatetags.format_filters import format_approval_number, format_siret
from tests.approvals.factories import ApprovalFactory, ProlongationRequestFactory
from tests.companies.factories import (
    CompanyAfterGracePeriodFactory,
    CompanyFactory,
    CompanyMembershipFactory,
    CompanyPendingGracePeriodFactory,
)
from tests.employee_record.factories import EmployeeRecordFactory
from tests.files.factories import FileFactory
from tests.geiq.factories import ImplementationAssessmentCampaignFactory, ImplementationAssessmentFactory
from tests.institutions.factories import InstitutionFactory, InstitutionMembershipFactory, LaborInspectorFactory
from tests.job_applications.factories import JobApplicationFactory
from tests.prescribers import factories as prescribers_factories
from tests.siae_evaluations.factories import (
    EvaluatedAdministrativeCriteriaFactory,
    EvaluatedJobApplicationFactory,
    EvaluatedSiaeFactory,
    EvaluationCampaignFactory,
)
from tests.users.factories import (
    EmployerFactory,
    JobSeekerFactory,
    PrescriberFactory,
)
from tests.utils.test import TestCase, parse_response_to_soup


DISABLED_NIR = 'disabled aria-describedby="id_nir_helptext" id="id_nir"'


@pytest.mark.usefixtures("unittest_compatibility")
class DashboardViewTest(ParametrizedTestCase, TestCase):
    NO_PRESCRIBER_ORG_MSG = "Votre compte utilisateur n’est rattaché à aucune organisation."
    NO_PRESCRIBER_ORG_FOR_PE_MSG = (
        "Votre compte utilisateur n’est rattaché à aucune agence France Travail, "
        "par conséquent vous ne pouvez pas bénéficier du statut de prescripteur habilité."
    )
    DANGER_CLASS = "bg-danger"
    SUSPEND_TEXT = "Suspendre un PASS IAE"
    HIRE_LINK_LABEL = "Déclarer une embauche"
    DORA_LABEL = "DORA"
    DORA_CARD_MSG = "Consultez l’offre de service de vos partenaires"

    @staticmethod
    def apply_start_url(company):
        return reverse("apply:start", kwargs={"company_pk": company.pk})

    @staticmethod
    def check_nir_for_hire_url(company):
        return reverse("apply:check_nir_for_hire", kwargs={"company_pk": company.pk})

    def test_dashboard(self):
        company = CompanyFactory(with_membership=True)
        user = company.members.first()
        self.client.force_login(user)

        url = reverse("dashboard:index")
        response = self.client.get(url)
        assert response.status_code == 200
        cities_search = parse_response_to_soup(response, selector="form[method=get]")
        assert str(cities_search) == self.snapshot

    def test_user_with_inactive_company_can_still_login_during_grace_period(self):
        company = CompanyPendingGracePeriodFactory(with_membership=True)
        user = EmployerFactory()
        company.members.add(user)
        self.client.force_login(user)

        url = reverse("dashboard:index")
        response = self.client.get(url)
        assert response.status_code == 200

    def test_user_with_inactive_company_cannot_login_after_grace_period(self):
        company = CompanyAfterGracePeriodFactory(with_membership=True)
        user = EmployerFactory()
        company.members.add(user)
        self.client.force_login(user)

        url = reverse("dashboard:index")
        response = self.client.get(url, follow=True)
        # Should be redirected to home page and logged out
        self.assertRedirects(response, reverse("search:employers_home"))
        assert response.status_code == 200
        assert not get_user(self.client).is_authenticated
        expected_message = "votre compte n&#x27;est malheureusement plus actif"
        self.assertContains(response, expected_message)

    def test_dashboard_eiti(self):
        company = CompanyFactory(kind=CompanyKind.EITI, with_membership=True)
        user = company.members.first()
        self.client.force_login(user)

        url = reverse("dashboard:index")
        response = self.client.get(url)
        self.assertContains(response, format_siret(company.siret))

    def test_dashboard_for_prescriber(self):
        prescriber_organization = prescribers_factories.PrescriberOrganizationWithMembershipFactory()
        self.client.force_login(prescriber_organization.members.first())

        response = self.client.get(reverse("dashboard:index"))
        self.assertContains(response, format_siret(prescriber_organization.siret))

    def test_dashboard_for_authorized_prescriber(self):
        prescriber_organization = prescribers_factories.PrescriberOrganizationWithMembershipFactory(authorized=True)
        self.client.force_login(prescriber_organization.members.first())

        response = self.client.get(reverse("dashboard:index"))
        self.assertContains(response, format_siret(prescriber_organization.siret))
        self.assertContains(response, "Liste de mes candidats")

    def test_dashboard_displays_asp_badge(self):
        company = CompanyFactory(kind=CompanyKind.EI, with_membership=True)
        other_company = CompanyFactory(kind=CompanyKind.ETTI, with_membership=True)
        last_company = CompanyFactory(kind=CompanyKind.ETTI, with_membership=True)

        user = company.members.first()
        user.company_set.add(other_company)
        user.company_set.add(last_company)

        self.client.force_login(user)

        url = reverse("dashboard:index")
        response = self.client.get(url)
        self.assertContains(response, "Fiches salariés ASP")
        self.assertNotContains(response, self.DANGER_CLASS)
        assert response.context["num_rejected_employee_records"] == 0

        # create rejected job applications
        job_application = JobApplicationFactory(with_approval=True, to_company=company)
        EmployeeRecordFactory(job_application=job_application, status=Status.REJECTED)
        # You can't create 2 employee records with the same job application
        # Factories were allowing it until a recent fix was applied
        job_application = JobApplicationFactory(with_approval=True, to_company=company)
        EmployeeRecordFactory(job_application=job_application, status=Status.REJECTED)

        other_job_application = JobApplicationFactory(with_approval=True, to_company=other_company)
        EmployeeRecordFactory(job_application=other_job_application, status=Status.REJECTED)

        session = self.client.session

        # select the first company's in the session
        session[global_constants.ITOU_SESSION_CURRENT_ORGANIZATION_KEY] = company.pk
        session.save()
        response = self.client.get(url)
        self.assertContains(response, self.DANGER_CLASS)
        assert response.context["num_rejected_employee_records"] == 2

        # select the second company's in the session
        session[global_constants.ITOU_SESSION_CURRENT_ORGANIZATION_KEY] = other_company.pk
        session.save()
        response = self.client.get(url)
        self.assertContains(response, self.DANGER_CLASS)
        assert response.context["num_rejected_employee_records"] == 1

        # select the third company's in the session
        session[global_constants.ITOU_SESSION_CURRENT_ORGANIZATION_KEY] = last_company.pk
        session.save()
        response = self.client.get(url)
        assert response.status_code == 200
        assert response.context["num_rejected_employee_records"] == 0

    def test_dashboard_applications_to_process(self):
        non_geiq_url = reverse("apply:list_for_siae") + "?states=new&amp;states=processing"
        geiq_url = non_geiq_url + "&amp;states=prior_to_hire"

        # Not a GEIQ
        user = CompanyFactory(kind=CompanyKind.ACI, with_membership=True).members.first()
        self.client.force_login(user)
        response = self.client.get(reverse("dashboard:index"))
        self.assertContains(response, non_geiq_url)
        self.assertNotContains(response, geiq_url)

        # GEIQ
        user = CompanyFactory(kind=CompanyKind.GEIQ, with_membership=True).members.first()
        self.client.force_login(user)
        response = self.client.get(reverse("dashboard:index"))

        self.assertContains(response, geiq_url)

    def test_dashboard_applications_count(self):
        company = CompanyFactory(with_membership=True)
        JobApplicationFactory(to_company=company)
        JobApplicationFactory(to_company=company, archived_at=timezone.now())
        JobApplicationFactory(to_company=company, state=JobApplicationState.POSTPONED)
        JobApplicationFactory(to_company=company, state=JobApplicationState.POSTPONED, archived_at=timezone.now())
        self.client.force_login(company.members.get())
        response = self.client.get(reverse("dashboard:index"))
        todo_url = reverse("apply:list_for_siae") + "?states=new&amp;states=processing"
        postponed_url = reverse("apply:list_for_siae") + "?states=postponed"
        self.assertContains(
            response,
            # Archived job application is ignored.
            f"""
            <li class="d-flex justify-content-between align-items-center mb-3">
                <a href="{todo_url}"
                   class="btn-link btn-ico"
                   data-matomo-event="true"
                   data-matomo-category="employeurs"
                   data-matomo-action="clic"
                   data-matomo-option="voir-liste-candidatures-À traiter">
                    <i class="ri-notification-4-line ri-lg font-weight-normal"></i>
                    <span>À traiter</span>
                </a>
                <span class="badge rounded-pill badge-xs bg-info-lighter text-info">1</span>
            </li>
            """,
            html=True,
            count=1,
        )
        self.assertContains(
            response,
            # Archived job application is ignored.
            f"""
            <li class="d-flex justify-content-between align-items-center mb-3">
                <a href="{postponed_url}"
                   class="btn-link btn-ico"
                   data-matomo-event="true"
                   data-matomo-category="employeurs"
                   data-matomo-action="clic"
                   data-matomo-option="voir-liste-candidatures-En attente">
                    <i class="ri-time-line ri-lg font-weight-normal"></i>
                    <span>En attente</span>
                </a>
                <span class="badge rounded-pill badge-xs bg-info-lighter text-info">1</span>
            </li>
            """,
            html=True,
            count=1,
        )

    def test_dashboard_job_postings(self):
        for kind in [
            CompanyKind.AI,
            CompanyKind.EI,
            CompanyKind.EITI,
            CompanyKind.ACI,
            CompanyKind.ETTI,
            CompanyKind.GEIQ,
        ]:
            with self.subTest(f"should display when company_kind={kind}"):
                company = CompanyFactory(kind=kind, with_membership=True)
                user = company.members.first()
                self.client.force_login(user)

                response = self.client.get(reverse("dashboard:index"))
                self.assertContains(response, self.HIRE_LINK_LABEL)

        for kind in [CompanyKind.EA, CompanyKind.EATT, CompanyKind.OPCS]:
            with self.subTest(f"should not display when company_kind={kind}"):
                company = CompanyFactory(kind=kind, with_membership=True)
                user = company.members.first()
                self.client.force_login(user)

                response = self.client.get(reverse("dashboard:index"))
                self.assertNotContains(response, self.HIRE_LINK_LABEL)

    def test_dashboard_job_applications(self):
        APPLICATION_SAVE_LABEL = "Enregistrer une candidature"
        display_kinds = [
            CompanyKind.AI,
            CompanyKind.EI,
            CompanyKind.EITI,
            CompanyKind.ACI,
            CompanyKind.ETTI,
            CompanyKind.GEIQ,
        ]
        for kind in display_kinds:
            with self.subTest(f"should display when company_kind={kind}"):
                company = CompanyFactory(kind=kind, with_membership=True)
                user = company.members.first()
                self.client.force_login(user)

                response = self.client.get(reverse("dashboard:index"))
                self.assertContains(response, APPLICATION_SAVE_LABEL)
                self.assertContains(response, self.apply_start_url(company))
                self.assertContains(response, self.HIRE_LINK_LABEL)
                self.assertContains(response, self.check_nir_for_hire_url(company))

        for kind in set(CompanyKind) - set(display_kinds):
            with self.subTest(f"should not display when company_kind={kind}"):
                company = CompanyFactory(kind=kind, with_membership=True)
                user = company.members.first()
                self.client.force_login(user)
                response = self.client.get(reverse("dashboard:index"))
                self.assertNotContains(response, APPLICATION_SAVE_LABEL)
                self.assertNotContains(response, self.apply_start_url(company))
                self.assertNotContains(response, self.HIRE_LINK_LABEL)
                self.assertNotContains(response, self.check_nir_for_hire_url(company))

    def test_dashboard_agreements_with_suspension_sanction(self):
        company = CompanyFactory(subject_to_eligibility=True, with_membership=True)
        Sanctions.objects.create(
            evaluated_siae=EvaluatedSiaeFactory(siae=company),
            suspension_dates=InclusiveDateRange(timezone.localdate() - relativedelta(days=1)),
        )

        user = company.members.first()
        self.client.force_login(user)

        response = self.client.get(reverse("dashboard:index"))
        # Check that "Déclarer une embauche" is here, but not its matching link
        self.assertContains(response, self.HIRE_LINK_LABEL)
        self.assertNotContains(response, self.apply_start_url(company))
        # Check that the button tooltip is there
        self.assertContains(
            response,
            "Vous ne pouvez pas déclarer d'embauche suite aux mesures prises dans le cadre du contrôle a posteriori",
        )

    def test_dashboard_can_create_siae_antenna(self):
        for kind in CompanyKind:
            with self.subTest(kind=kind):
                company = CompanyFactory(kind=kind, with_membership=True, membership__is_admin=True)
                user = company.members.get()

                self.client.force_login(user)
                response = self.client.get(reverse("dashboard:index"))
                assertion = self.assertContains if user.can_create_siae_antenna(company) else assertNotContains
                assertion(response, "Créer/rejoindre une autre structure")

    def test_dashboard_siae_stats(self):
        membership = CompanyMembershipFactory()
        self.client.force_login(membership.user)
        response = self.client.get(reverse("dashboard:index"))
        self.assertContains(response, "Traitement et résultats des candidatures reçues par ma ou mes structures")
        self.assertContains(response, reverse("stats:stats_siae_hiring"))
        self.assertContains(response, "Auto-prescription réalisées par ma ou mes structures")
        self.assertContains(response, reverse("stats:stats_siae_auto_prescription"))
        self.assertContains(response, "Suivi du contrôle a posteriori pour ma ou mes structures")
        self.assertContains(response, reverse("stats:stats_siae_follow_siae_evaluation"))
        # Unofficial stats are only accessible to specific whitelisted siaes.
        self.assertNotContains(response, "Suivre les effectifs annuels et mensuels en ETP de ma ou mes structures")
        self.assertNotContains(response, reverse("stats:stats_siae_etp"))
        self.assertNotContains(response, "Suivi du cofinancement des ACI de mon département")
        self.assertNotContains(response, reverse("stats:stats_siae_aci"))

    def test_dashboard_ddets_log_institution_stats(self):
        membershipfactory = InstitutionMembershipFactory(institution__kind=InstitutionKind.DDETS_LOG)
        self.client.force_login(membershipfactory.user)
        response = self.client.get(reverse("dashboard:index"))
        self.assertContains(response, "Prescriptions des acteurs AHI de ma région")
        self.assertContains(response, reverse("stats:stats_ddets_log_state"))

    def test_dashboard_dihal_institution_stats(self):
        membershipfactory = InstitutionMembershipFactory(institution__kind=InstitutionKind.DIHAL)
        self.client.force_login(membershipfactory.user)
        response = self.client.get(reverse("dashboard:index"))
        self.assertContains(response, "Prescriptions des acteurs AHI")
        self.assertContains(response, reverse("stats:stats_dihal_state"))

    def test_dashboard_drihl_institution_stats(self):
        membershipfactory = InstitutionMembershipFactory(institution__kind=InstitutionKind.DRIHL)
        self.client.force_login(membershipfactory.user)
        response = self.client.get(reverse("dashboard:index"))
        self.assertContains(response, "Prescriptions des acteurs AHI")
        self.assertContains(response, reverse("stats:stats_drihl_state"))

    def test_dashboard_iae_network_institution_stats(self):
        membershipfactory = InstitutionMembershipFactory(institution__kind=InstitutionKind.IAE_NETWORK)
        self.client.force_login(membershipfactory.user)
        response = self.client.get(reverse("dashboard:index"))
        self.assertContains(response, "Traitement et résultats des candidatures orientées par mes adhérents")
        self.assertContains(response, reverse("stats:stats_iae_network_hiring"))

    def test_dashboard_siae_evaluations_institution_access(self):
        IN_PROGRESS_LINK = "Campagne en cours"
        membershipfactory = InstitutionMembershipFactory()
        user = membershipfactory.user
        institution = membershipfactory.institution
        self.client.force_login(user)
        evaluation_campaign_label = "Contrôle a posteriori"
        sample_selection_url = reverse("siae_evaluations_views:samples_selection")

        response = self.client.get(reverse("dashboard:index"))
        self.assertNotContains(response, evaluation_campaign_label)
        self.assertNotContains(response, sample_selection_url)

        evaluation_campaign = EvaluationCampaignFactory(institution=institution)
        response = self.client.get(reverse("dashboard:index"))
        self.assertContains(response, evaluation_campaign_label)
        self.assertContains(response, IN_PROGRESS_LINK)
        self.assertContains(response, sample_selection_url)
        evaluated_siae_list_url = reverse(
            "siae_evaluations_views:institution_evaluated_siae_list",
            kwargs={"evaluation_campaign_pk": evaluation_campaign.pk},
        )
        self.assertNotContains(response, evaluated_siae_list_url)

        evaluation_campaign.evaluations_asked_at = timezone.now()
        evaluation_campaign.save(update_fields=["evaluations_asked_at"])
        response = self.client.get(reverse("dashboard:index"))
        self.assertContains(response, evaluation_campaign_label)
        self.assertNotContains(response, sample_selection_url)
        self.assertContains(response, IN_PROGRESS_LINK)
        self.assertContains(response, evaluated_siae_list_url)

        evaluation_campaign.ended_at = timezone.now()
        evaluation_campaign.save(update_fields=["ended_at"])
        response = self.client.get(reverse("dashboard:index"))
        self.assertContains(response, evaluation_campaign_label)
        self.assertNotContains(response, IN_PROGRESS_LINK)
        self.assertNotContains(response, sample_selection_url)
        self.assertContains(response, evaluated_siae_list_url)

        evaluation_campaign.ended_at = timezone.now() - CAMPAIGN_VIEWABLE_DURATION
        evaluation_campaign.save(update_fields=["ended_at"])
        response = self.client.get(reverse("dashboard:index"))
        self.assertNotContains(response, IN_PROGRESS_LINK)
        self.assertNotContains(response, evaluation_campaign_label)
        self.assertNotContains(response, sample_selection_url)
        self.assertNotContains(response, evaluated_siae_list_url)

    def test_dashboard_siae_evaluation_campaign_notifications(self):
        membership = CompanyMembershipFactory()
        # Unique institution to avoid constraints failures
        evaluating_institution = InstitutionFactory(kind=InstitutionKind.DDETS_IAE)
        evaluated_siae_with_final_decision = EvaluatedSiaeFactory(
            evaluation_campaign__name="Final decision reached",
            evaluation_campaign__institution=evaluating_institution,
            complete=True,
            job_app__criteria__review_state=evaluation_enums.EvaluatedJobApplicationsState.REFUSED_2,
            siae=membership.company,
            notified_at=timezone.now(),
            notification_reason=evaluation_enums.EvaluatedSiaeNotificationReason.INVALID_PROOF,
            notification_text="A envoyé une photo de son chat. Séparé de son chat pendant une journée.",
        )
        in_progress_name = "In progress"
        evaluated_siae = EvaluatedSiaeFactory(
            evaluation_campaign__name=in_progress_name,
            evaluation_campaign__institution=evaluating_institution,
            siae=membership.company,
            evaluation_campaign__evaluations_asked_at=timezone.now(),
        )
        # Add jb applications and criterias to check for 1+N
        evaluated_job_app_1 = EvaluatedJobApplicationFactory(evaluated_siae=evaluated_siae)
        EvaluatedAdministrativeCriteriaFactory(evaluated_job_application=evaluated_job_app_1)
        EvaluatedAdministrativeCriteriaFactory(evaluated_job_application=evaluated_job_app_1)
        evaluated_job_app_2 = EvaluatedJobApplicationFactory(evaluated_siae=evaluated_siae)
        EvaluatedAdministrativeCriteriaFactory(evaluated_job_application=evaluated_job_app_2)
        EvaluatedAdministrativeCriteriaFactory(evaluated_job_application=evaluated_job_app_2)
        not_notified_name = "Not notified"
        EvaluatedSiaeFactory(
            evaluation_campaign__name=not_notified_name,
            evaluation_campaign__institution=evaluating_institution,
            complete=True,
            job_app__criteria__review_state=evaluation_enums.EvaluatedJobApplicationsState.REFUSED_2,
            siae=membership.company,
        )
        just_closed_name = "Just closed"
        evaluated_siae_campaign_closed = EvaluatedSiaeFactory(
            evaluation_campaign__name=just_closed_name,
            evaluation_campaign__institution=evaluating_institution,
            complete=True,
            siae=membership.company,
            evaluation_campaign__ended_at=timezone.now() - relativedelta(days=4),
            notified_at=timezone.now(),
            notification_reason=evaluation_enums.EvaluatedSiaeNotificationReason.MISSING_PROOF,
            notification_text="Journée de formation.",
        )
        # Long closed.
        long_closed_name = "Long closed"
        EvaluatedSiaeFactory(
            evaluation_campaign__name=long_closed_name,
            evaluation_campaign__institution=evaluating_institution,
            complete=True,
            siae=membership.company,
            evaluation_campaign__ended_at=timezone.now() - CAMPAIGN_VIEWABLE_DURATION,
            notified_at=timezone.now(),
            notification_reason=evaluation_enums.EvaluatedSiaeNotificationReason.INVALID_PROOF,
            notification_text="A envoyé une photo de son chat.",
        )

        self.client.force_login(membership.user)
        # 1.  SELECT django_session
        # 2.  SELECT users_user
        # 3.  SELECT companies_companymembership
        # 4.  SELECT companies_company
        # END of middlewares
        # 5.  SAVEPOINT
        # 6.  SELECT companies_siaeconvention
        # 7.  SELECT job_applications_jobapplication
        # 8.  SELECT EXISTS users_user (admin membership)
        # 9.  SELECT EXISTS users_user (admin membership)
        # 10. SELECT COUNT employee_record_employeerecord
        # 11. SELECT siae_evaluations_sanction
        # 12. SELECT EXISTS users_user (admin membership)
        # 13. SELECT EXISTS jobs_appellation
        # 14. SELECT siae_evaluations_evaluatedsiae
        # 15. SELECT siae_evaluations_evaluatedjobapplication
        # 16. SELECT siae_evaluations_evaluatedadministrativecriteria
        # 17. SELECT siae_evaluations_evaluatedsiae
        # 18. RELEASE SAVEPOINT
        # 19. SAVEPOINT
        # 20. UPDATE session
        # 21. RELEASE SAVEPOINT
        with self.assertNumQueries(21):
            response = self.client.get(reverse("dashboard:index"))
        self.assertContains(
            response,
            """
            <div class="flex-grow-1">
                <span class="h4 m-0">Contrôle a posteriori</span>
            </div>
            """,
            html=True,
            count=1,
        )
        self.assertContains(
            response,
            f"""
            <a href="/siae_evaluation/evaluated_siae_sanction/{evaluated_siae_with_final_decision.pk}/"
             class="btn-link btn-ico">
                <i class="ri-file-copy-2-line ri-lg font-weight-normal"></i>
                <span>Final decision reached</span>
            </a>
            """,
            html=True,
            count=1,
        )
        self.assertContains(
            response,
            f"""
            <a href="/siae_evaluation/evaluated_siae_sanction/{evaluated_siae_campaign_closed.pk}/"
             class="btn-link btn-ico">
                <i class="ri-file-copy-2-line ri-lg font-weight-normal"></i>
                <span>{just_closed_name}</span>
            </a>
            """,
            html=True,
            count=1,
        )
        self.assertNotContains(response, long_closed_name)
        self.assertNotContains(response, not_notified_name)
        self.assertNotContains(response, in_progress_name)

    def test_dashboard_siae_evaluations_siae_access(self):
        # preset for incoming new pages
        company = CompanyFactory(with_membership=True)
        user = company.members.first()
        self.client.force_login(user)

        evaluation_campaign_label = "Contrôle a posteriori"
        response = self.client.get(reverse("dashboard:index"))
        self.assertNotContains(response, evaluation_campaign_label)

        fake_now = timezone.now()
        evaluated_siae = EvaluatedSiaeFactory(siae=company, evaluation_campaign__evaluations_asked_at=fake_now)
        response = self.client.get(reverse("dashboard:index"))
        self.assertContains(response, evaluation_campaign_label)
        TODO_BADGE = (
            '<span class="badge badge-xs rounded-pill bg-warning-lighter text-warning">'
            '<i class="ri-error-warning-line" aria-hidden="true"></i>'
            "Action à faire</span>"
        )
        self.assertContains(
            response,
            reverse(
                "siae_evaluations_views:siae_job_applications_list",
                kwargs={"evaluated_siae_pk": evaluated_siae.pk},
            ),
        )
        self.assertContains(response, TODO_BADGE, html=True)

        # Check that the badge disappears when frozen
        evaluated_siae.evaluation_campaign.freeze(timezone.now())
        response = self.client.get(reverse("dashboard:index"))
        self.assertContains(
            response,
            reverse(
                "siae_evaluations_views:siae_job_applications_list",
                kwargs={"evaluated_siae_pk": evaluated_siae.pk},
            ),
        )
        self.assertNotContains(response, TODO_BADGE, html=True)

        # Unfreeze but submit
        evaluated_siae.submission_freezed_at = None
        evaluated_siae.save(update_fields=("submission_freezed_at",))
        evaluated_job_application = EvaluatedJobApplicationFactory(evaluated_siae=evaluated_siae)
        EvaluatedAdministrativeCriteriaFactory(
            evaluated_job_application=evaluated_job_application,
            submitted_at=timezone.now(),
        )
        response = self.client.get(reverse("dashboard:index"))
        self.assertNotContains(response, TODO_BADGE, html=True)

    def test_dora_card_is_not_shown_for_job_seeker(self):
        user = JobSeekerFactory(with_address=True)
        self.client.force_login(user)

        response = self.client.get(reverse("dashboard:index"))
        self.assertNotContains(response, self.DORA_LABEL)

    def test_dora_card_is_shown_for_employer(self):
        company = CompanyFactory(with_membership=True)
        self.client.force_login(company.members.first())

        response = self.client.get(reverse("dashboard:index"))
        self.assertContains(response, self.DORA_LABEL)
        self.assertContains(response, "Consulter les services d'insertion de votre territoire")
        self.assertContains(response, "Référencer vos services")
        self.assertContains(response, "Suggérer un service partenaire")

    def test_dora_card_is_shown_for_prescriber(self):
        prescriber_organization = prescribers_factories.PrescriberOrganizationWithMembershipFactory()
        self.client.force_login(prescriber_organization.members.first())

        response = self.client.get(reverse("dashboard:index"))
        self.assertContains(response, self.DORA_LABEL)
        self.assertContains(response, "Consulter les services d'insertion de votre territoire")
        self.assertContains(response, "Référencer vos services")
        self.assertContains(response, "Suggérer un service partenaire")

    def test_diagoriente_info_is_shown_in_sidebar_for_job_seeker(self):
        user = JobSeekerFactory(with_address=True)
        self.client.force_login(user)

        response = self.client.get(reverse("dashboard:index"))
        self.assertContains(response, "Vous n’avez pas encore de CV ?")
        self.assertContains(response, "Créez-en un grâce à notre partenaire Diagoriente.")
        self.assertContains(
            response,
            "https://diagoriente.beta.gouv.fr/services/plateforme?utm_source=emploi-inclusion-candidat",
        )

    def test_gps_card_is_not_shown_for_job_seeker(self):
        user = JobSeekerFactory()
        self.client.force_login(user)

        with self.assertTemplateNotUsed("dashboard/includes/gps_card.html"):
            self.client.get(reverse("dashboard:index"))

    def test_gps_card_is_shown_for_employer(self):
        company = CompanyFactory(with_membership=True)
        self.client.force_login(company.members.first())

        with self.assertTemplateUsed("dashboard/includes/gps_card.html"):
            self.client.get(reverse("dashboard:index"))

    def test_gps_card_is_shown_for_prescriber(self):
        prescriber_organization = prescribers_factories.PrescriberOrganizationWithMembershipFactory(authorized=True)
        self.client.force_login(prescriber_organization.members.first())

        with self.assertTemplateUsed("dashboard/includes/gps_card.html"):
            self.client.get(reverse("dashboard:index"))

    def test_gps_card_is_not_shown_for_orienter(self):
        prescriber_organization = prescribers_factories.PrescriberOrganizationWithMembershipFactory()
        self.client.force_login(prescriber_organization.members.first())

        with self.assertTemplateNotUsed("dashboard/includes/gps_card.html"):
            self.client.get(reverse("dashboard:index"))

    def test_dashboard_prescriber_without_organization_message(self):
        # An orienter is a prescriber without prescriber organization
        orienter = PrescriberFactory()
        self.client.force_login(orienter)
        response = self.client.get(reverse("dashboard:index"))
        self.assertContains(response, self.NO_PRESCRIBER_ORG_MSG)
        self.assertNotContains(response, self.NO_PRESCRIBER_ORG_FOR_PE_MSG)
        self.assertContains(response, reverse("signup:prescriber_check_already_exists"))

    def test_dashboard_pole_emploi_prescriber_without_organization_message(self):
        # Pôle emploi employees can sometimes be orienters
        pe_orienter = PrescriberFactory(email="john.doe@pole-emploi.fr")
        self.client.force_login(pe_orienter)
        response = self.client.get(reverse("dashboard:index"))
        self.assertContains(response, self.NO_PRESCRIBER_ORG_FOR_PE_MSG)
        self.assertNotContains(response, self.NO_PRESCRIBER_ORG_MSG)
        self.assertContains(response, reverse("signup:prescriber_pole_emploi_safir_code"))

    def test_dashboard_delete_one_of_multiple_prescriber_orgs_while_logged_in(self):
        org_1 = prescribers_factories.PrescriberOrganizationWithMembershipFactory()
        org_2 = prescribers_factories.PrescriberOrganizationWithMembershipFactory()
        prescriber = org_1.members.first()
        org_2.members.add(prescriber)

        self.client.force_login(prescriber)
        response = self.client.get(reverse("dashboard:index"))
        assert org_1 == PrescriberOrganization.objects.get(
            pk=self.client.session.get(global_constants.ITOU_SESSION_CURRENT_ORGANIZATION_KEY)
        )
        self.assertNotContains(response, self.NO_PRESCRIBER_ORG_MSG)

        org_1.members.remove(prescriber)
        response = self.client.get(reverse("dashboard:index"))
        self.assertNotContains(response, self.NO_PRESCRIBER_ORG_MSG)

    def test_dashboard_prescriber_suspend_link(self):
        user = JobSeekerFactory(with_address=True)
        self.client.force_login(user)
        response = self.client.get(reverse("dashboard:index"))
        self.assertNotContains(response, self.SUSPEND_TEXT)

        company = CompanyFactory(with_membership=True)
        user = company.members.first()
        self.client.force_login(user)
        response = self.client.get(reverse("dashboard:index"))
        self.assertNotContains(response, self.SUSPEND_TEXT)

        membershipfactory = InstitutionMembershipFactory()
        user = membershipfactory.user
        self.client.force_login(user)
        response = self.client.get(reverse("dashboard:index"))
        self.assertNotContains(response, self.SUSPEND_TEXT)

        prescriber_org = prescribers_factories.PrescriberOrganizationWithMembershipFactory(
            kind=PrescriberOrganizationKind.CAP_EMPLOI
        )
        prescriber = prescriber_org.members.first()
        self.client.force_login(prescriber)
        response = self.client.get(reverse("dashboard:index"))
        self.assertNotContains(response, self.SUSPEND_TEXT)

        prescriber_org_pe = prescribers_factories.PrescriberOrganizationWithMembershipFactory(
            authorized=True, kind=PrescriberOrganizationKind.PE
        )
        prescriber_pe = prescriber_org_pe.members.first()
        self.client.force_login(prescriber_pe)
        response = self.client.get(reverse("dashboard:index"))
        self.assertContains(response, self.SUSPEND_TEXT)

    @freeze_time("2022-09-15")
    def test_dashboard_access_by_a_jobseeker(self):
        user = JobSeekerFactory(with_address=True)
        approval = ApprovalFactory(user=user, start_at=datetime(2022, 6, 21), end_at=datetime(2022, 12, 6))
        self.client.force_login(user)
        url = reverse("dashboard:index")
        response = self.client.get(url)
        self.assertContains(response, "Numéro de PASS IAE")
        self.assertContains(response, format_approval_number(approval))
        self.assertContains(response, "Date de début : 21/06/2022")
        self.assertContains(response, "Nombre de jours restants sur le PASS IAE : 83 jours")
        self.assertContains(response, "Date de fin prévisionnelle : 06/12/2022")

    @override_settings(TALLY_URL="http://tally.fake")
    def test_prescriber_with_authorization_pending_dashboard_must_contain_tally_link(self):
        prescriber_org = prescribers_factories.PrescriberOrganizationWithMembershipFactory(
            kind=PrescriberOrganizationKind.OTHER,
            with_pending_authorization=True,
        )

        prescriber = prescriber_org.members.first()
        self.client.force_login(prescriber)
        response = self.client.get(reverse("dashboard:index"))

        self.assertContains(
            response,
            f"http://tally.fake/r/wgDzz1?"
            f"idprescriber={prescriber_org.pk}"
            f"&iduser={prescriber.pk}"
            f"&source={settings.ITOU_ENVIRONMENT}",
        )

    @parametrize(
        "field,data",
        [
            param("title", Title.M, id="title"),
            param("first_name", "John", id="first_name"),
            param("last_name", "Doe", id="last_name"),
            param("address_line_1", "1 rue du bac", id="address_line_1"),
            param("post_code", "59140", id="post_code"),
            param("city", "Dunkerque", id="city"),
        ],
    )
    def test_job_seeker_without_required_field_redirected(self, field, data):
        empty_field = {field: ""}
        user = JobSeekerFactory(with_address=True, **empty_field)
        self.client.force_login(user)

        response = self.client.get(reverse("dashboard:index"))
        self.assertRedirects(response, reverse("dashboard:edit_user_info"))

        setattr(user, field, data)
        user.save(update_fields=(field,))

        response = self.client.get(reverse("dashboard:index"))
        assert response.status_code == 200

    @parametrize(
        "institution_kind, campaign_year, card_visible, note_visible",
        [
            (InstitutionKind.DDETS_GEIQ, 2023, True, True),
            (InstitutionKind.DDETS_IAE, 2023, False, False),
            (InstitutionKind.DDETS_GEIQ, 2024, True, False),
            (InstitutionKind.DREETS_GEIQ, 2023, True, True),
            (InstitutionKind.DREETS_IAE, 2023, False, False),
            (InstitutionKind.DREETS_GEIQ, 2024, True, False),
        ],
    )
    @freeze_time("2024-03-10")
    def test_institution_with_geiq_assessment_campaign(
        self, institution_kind, campaign_year, card_visible, note_visible
    ):
        membership = InstitutionMembershipFactory(institution__kind=institution_kind)
        user = membership.user
        self.client.force_login(user)
        ImplementationAssessmentCampaignFactory(
            year=campaign_year,
            submission_deadline=date(campaign_year + 1, 7, 1),
            review_deadline=date(campaign_year + 1, 8, 1),
        )
        response = self.client.get(reverse("dashboard:index"))
        list_link_assertion = self.assertContains if card_visible else self.assertNotContains
        list_link_assertion(response, reverse("geiq:geiq_list", kwargs={"institution_pk": membership.institution.pk}))
        note_assertion = self.assertContains if note_visible else self.assertNotContains
        note_assertion(response, "Période de contrôle bilans 2023")
        note_assertion(response, "Le contrôle devra se faire entre le 01/07/2024 et le 01/08/2024.")

    @freeze_time("2024-03-10")
    def test_geiq_implement_assessment_card(self):
        IMPLEMENTATION_ASSESSMENT = "Bilan d’exécution & salariés"
        VALIDATE_ADMONITION = "Validez votre bilan"
        campaign = ImplementationAssessmentCampaignFactory(
            year=2022,
            submission_deadline=date(2023, 7, 1),
            review_deadline=date(2023, 8, 1),
        )
        membership = CompanyMembershipFactory(company__kind=CompanyKind.GEIQ)
        user = membership.user
        self.client.force_login(user)
        response = self.client.get(reverse("dashboard:index"))
        self.assertNotContains(response, IMPLEMENTATION_ASSESSMENT)
        self.assertNotContains(response, VALIDATE_ADMONITION)
        assessment = ImplementationAssessmentFactory(campaign=campaign, company=membership.company)
        response = self.client.get(reverse("dashboard:index"))
        self.assertContains(response, IMPLEMENTATION_ASSESSMENT)
        self.assertContains(response, VALIDATE_ADMONITION)
        self.assertContains(response, reverse("geiq:assessment_info", kwargs={"assessment_pk": assessment.pk}))
        self.assertContains(
            response,
            reverse(
                "geiq:employee_list", kwargs={"assessment_pk": assessment.pk, "info_type": "personal-information"}
            ),
        )
        assessment.last_synced_at = timezone.now()
        assessment.submitted_at = timezone.now()
        assessment.activity_report_file = FileFactory()
        assessment.save()
        # submitted assessment
        response = self.client.get(reverse("dashboard:index"))
        self.assertContains(response, IMPLEMENTATION_ASSESSMENT)
        self.assertNotContains(response, VALIDATE_ADMONITION)
        self.assertContains(response, reverse("geiq:assessment_info", kwargs={"assessment_pk": assessment.pk}))
        self.assertContains(
            response,
            reverse(
                "geiq:employee_list", kwargs={"assessment_pk": assessment.pk, "info_type": "personal-information"}
            ),
        )

        # With several assessments, the last one is shown
        new_assessment = ImplementationAssessmentFactory(campaign__year=2023, company=membership.company)
        response = self.client.get(reverse("dashboard:index"))
        self.assertContains(response, IMPLEMENTATION_ASSESSMENT)
        self.assertContains(response, VALIDATE_ADMONITION)
        self.assertContains(response, reverse("geiq:assessment_info", kwargs={"assessment_pk": new_assessment.pk}))
        self.assertContains(
            response,
            reverse(
                "geiq:employee_list", kwargs={"assessment_pk": new_assessment.pk, "info_type": "personal-information"}
            ),
        )


@pytest.mark.parametrize(
    "factory,expected",
    [
        pytest.param(partial(JobSeekerFactory, with_address=True), assertNotContains, id="JobSeeker"),
        pytest.param(partial(EmployerFactory, with_company=True), assertNotContains, id="Employer"),
        pytest.param(partial(LaborInspectorFactory, membership=True), assertNotContains, id="LaborInspector"),
        pytest.param(PrescriberFactory, assertNotContains, id="PrescriberWithoutOrganization"),
        pytest.param(
            partial(PrescriberFactory, membership__organization__authorized=False),
            assertNotContains,
            id="PrescriberWithOrganization",
        ),
        pytest.param(
            partial(PrescriberFactory, membership__organization__authorized=True),
            assertContains,
            id="AuthorizedPrescriber",
        ),
    ],
)
def test_prolongation_requests_access(client, factory, expected):
    client.force_login(factory())
    response = client.get(reverse("dashboard:index"))
    expected(response, "Gérer mes prolongations de PASS IAE")
    expected(response, reverse("approvals:prolongation_requests_list"))


def test_prolongation_requests_badge(client):
    prescriber = PrescriberFactory(membership__organization__authorized=True)
    ProlongationRequestFactory.create_batch(3, prescriber_organization=prescriber.prescriberorganization_set.first())

    client.force_login(prescriber)
    soup = parse_response_to_soup(
        client.get(reverse("dashboard:index")),
        f"""a[href^='{reverse("approvals:prolongation_requests_list")}'] + .badge""",
    )
    assert soup.text == "3"
