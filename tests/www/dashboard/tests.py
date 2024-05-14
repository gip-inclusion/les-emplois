import math
from datetime import date, datetime, timezone as datetime_tz
from functools import partial
from unittest import mock
from urllib.parse import urlencode

import pytest
import respx
from allauth.account.models import EmailAddress, EmailConfirmationHMAC
from dateutil.relativedelta import relativedelta
from django.conf import settings
from django.contrib.contenttypes.models import ContentType
from django.contrib.gis.geos import Point
from django.core import mail
from django.db.models import Count
from django.test import override_settings
from django.urls import reverse, reverse_lazy
from django.utils import timezone
from django.utils.html import escape
from freezegun import freeze_time
from pytest_django.asserts import assertContains, assertNotContains, assertRedirects
from rest_framework.authtoken.models import Token
from unittest_parametrize import ParametrizedTestCase, param, parametrize

from itou.cities.models import City
from itou.communications import registry as notifications_registry
from itou.communications.models import DisabledNotification, NotificationSettings
from itou.companies.enums import CompanyKind
from itou.companies.models import Company
from itou.employee_record.enums import Status
from itou.institutions.enums import InstitutionKind
from itou.prescribers.enums import PrescriberOrganizationKind
from itou.prescribers.models import PrescriberOrganization
from itou.siae_evaluations import enums as evaluation_enums
from itou.siae_evaluations.constants import CAMPAIGN_VIEWABLE_DURATION
from itou.siae_evaluations.models import Sanctions
from itou.users.enums import IdentityProvider, LackOfNIRReason, LackOfPoleEmploiId, Title, UserKind
from itou.users.models import User
from itou.utils import constants as global_constants
from itou.utils.mocks.address_format import mock_get_geocoding_data_by_ban_api_resolved
from itou.utils.models import InclusiveDateRange
from itou.utils.templatetags.format_filters import format_approval_number, format_siret
from itou.www.dashboard.forms import EditUserEmailForm
from tests.approvals.factories import ApprovalFactory, ProlongationRequestFactory
from tests.companies.factories import (
    CompanyAfterGracePeriodFactory,
    CompanyFactory,
    CompanyMembershipFactory,
    CompanyPendingGracePeriodFactory,
)
from tests.employee_record.factories import EmployeeRecordFactory
from tests.institutions.factories import InstitutionFactory, InstitutionMembershipFactory, LaborInspectorFactory
from tests.job_applications.factories import JobApplicationFactory, JobApplicationSentByPrescriberFactory
from tests.openid_connect.inclusion_connect.test import (
    InclusionConnectBaseTestCase,
    override_inclusion_connect_settings,
)
from tests.openid_connect.inclusion_connect.tests import OIDC_USERINFO, mock_oauth_dance
from tests.prescribers import factories as prescribers_factories
from tests.siae_evaluations.factories import (
    EvaluatedAdministrativeCriteriaFactory,
    EvaluatedJobApplicationFactory,
    EvaluatedSiaeFactory,
    EvaluationCampaignFactory,
)
from tests.users.factories import (
    DEFAULT_PASSWORD,
    EmployerFactory,
    ItouStaffFactory,
    JobSeekerFactory,
    JobSeekerWithAddressFactory,
    PrescriberFactory,
)
from tests.utils.test import BASE_NUM_QUERIES, TestCase, parse_response_to_soup


DISABLED_NIR = 'disabled aria-describedby="id_nir_helptext" id="id_nir"'


@pytest.mark.usefixtures("unittest_compatibility")
class DashboardViewTest(ParametrizedTestCase, TestCase):
    NO_PRESCRIBER_ORG_MSG = "Votre compte utilisateur n’est rattaché à aucune organisation."
    NO_PRESCRIBER_ORG_FOR_PE_MSG = (
        "Votre compte utilisateur n’est rattaché à aucune agence France Travail, "
        "par conséquent vous ne pouvez pas bénéficier du statut de prescripteur habilité."
    )
    DANGER_CLASS = "bg-danger"
    PROLONG_SUSPEND = "Prolonger/suspendre un agrément émis par Pôle emploi"
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
        assert response.status_code == 200
        last_url = response.redirect_chain[-1][0]
        assert last_url == reverse("account_logout")

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
        self.assertContains(response, "Gérer les fiches salarié")
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

    def test_dashboard_agreements_and_job_postings(self):
        for kind in [
            CompanyKind.AI,
            CompanyKind.EI,
            CompanyKind.EITI,
            CompanyKind.ACI,
            CompanyKind.ETTI,
        ]:
            with self.subTest(f"should display when company_kind={kind}"):
                company = CompanyFactory(kind=kind, with_membership=True)
                user = company.members.first()
                self.client.force_login(user)

                response = self.client.get(reverse("dashboard:index"))
                self.assertContains(response, self.PROLONG_SUSPEND)

        for kind in [CompanyKind.EA, CompanyKind.EATT, CompanyKind.GEIQ, CompanyKind.OPCS]:
            with self.subTest(f"should not display when company_kind={kind}"):
                company = CompanyFactory(kind=kind, with_membership=True)
                user = company.members.first()
                self.client.force_login(user)

                response = self.client.get(reverse("dashboard:index"))
                self.assertNotContains(response, self.PROLONG_SUSPEND)
                if kind != CompanyKind.GEIQ:
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
        self.assertContains(response, self.PROLONG_SUSPEND)
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
        self.assertContains(
            response,
            "Suivre le traitement et les résultats des candidatures reçues par ma structure - vision mensuelle",
        )
        self.assertContains(response, reverse("stats:stats_siae_hiring"))
        self.assertContains(response, "Focus auto-prescription")
        self.assertContains(response, reverse("stats:stats_siae_auto_prescription"))
        self.assertContains(response, "Suivre le contrôle a posteriori")
        self.assertContains(response, reverse("stats:stats_siae_follow_siae_evaluation"))
        # Unofficial stats are only accessible to specific whitelisted siaes.
        self.assertNotContains(response, "Voir les données de ma structure (extranet ASP)")
        self.assertNotContains(response, reverse("stats:stats_siae_etp"))
        self.assertNotContains(response, "Voir le suivi du cofinancement de mon ACI")
        self.assertNotContains(response, reverse("stats:stats_siae_aci"))

    def test_dashboard_ddets_log_institution_stats(self):
        membershipfactory = InstitutionMembershipFactory(institution__kind=InstitutionKind.DDETS_LOG)
        self.client.force_login(membershipfactory.user)
        response = self.client.get(reverse("dashboard:index"))
        self.assertContains(response, "Suivre les prescriptions des AHI de ma région")
        self.assertContains(response, reverse("stats:stats_ddets_log_state"))

    def test_dashboard_dihal_institution_stats(self):
        membershipfactory = InstitutionMembershipFactory(institution__kind=InstitutionKind.DIHAL)
        self.client.force_login(membershipfactory.user)
        response = self.client.get(reverse("dashboard:index"))
        self.assertContains(response, "Suivre les prescriptions des AHI")
        self.assertContains(response, reverse("stats:stats_dihal_state"))

    def test_dashboard_drihl_institution_stats(self):
        membershipfactory = InstitutionMembershipFactory(institution__kind=InstitutionKind.DRIHL)
        self.client.force_login(membershipfactory.user)
        response = self.client.get(reverse("dashboard:index"))
        self.assertContains(response, "Suivre les prescriptions des AHI")
        self.assertContains(response, reverse("stats:stats_drihl_state"))

    def test_dashboard_iae_network_institution_stats(self):
        membershipfactory = InstitutionMembershipFactory(institution__kind=InstitutionKind.IAE_NETWORK)
        self.client.force_login(membershipfactory.user)
        response = self.client.get(reverse("dashboard:index"))
        self.assertContains(response, "Voir les données de candidatures des adhérents de mon réseau IAE")
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
        evaluated_siae_with_final_decision = EvaluatedSiaeFactory(
            evaluation_campaign__name="Final decision reached",
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
            complete=True,
            job_app__criteria__review_state=evaluation_enums.EvaluatedJobApplicationsState.REFUSED_2,
            siae=membership.company,
        )
        just_closed_name = "Just closed"
        evaluated_siae_campaign_closed = EvaluatedSiaeFactory(
            evaluation_campaign__name=just_closed_name,
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
            complete=True,
            siae=membership.company,
            evaluation_campaign__ended_at=timezone.now() - CAMPAIGN_VIEWABLE_DURATION,
            notified_at=timezone.now(),
            notification_reason=evaluation_enums.EvaluatedSiaeNotificationReason.INVALID_PROOF,
            notification_text="A envoyé une photo de son chat.",
        )

        self.client.force_login(membership.user)
        num_queries = BASE_NUM_QUERIES
        num_queries += 1  #  get django session
        num_queries += 1  #  get user (middleware)
        num_queries += 2  #  get company memberships (middleware)
        num_queries += 1  #  OrganizationAbstract.has_admin()
        num_queries += 1  #  select job applications states
        num_queries += 1  #  count employee records
        num_queries += 1  #  check if evaluations sanctions exists
        num_queries += 1  #  check siae conventions
        num_queries += 1  #  OrganizationAbstract.has_member()
        num_queries += 1  #  select job_appelation
        num_queries += 1  #  select siae_evaluations + evaluation campaigns
        num_queries += 1  #  prefetch evaluated job application
        num_queries += 1  #  prefetch evaluated administrative criterias
        num_queries += 1  #  select siae_evaluations for evaluated_siae_notifications
        num_queries += 3  #  update session + savepoints
        with self.assertNumQueries(num_queries):
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
        user = JobSeekerWithAddressFactory()
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
        user = JobSeekerWithAddressFactory()
        self.client.force_login(user)

        response = self.client.get(reverse("dashboard:index"))
        self.assertContains(response, "Vous n’avez pas encore de CV ?")
        self.assertContains(response, "Créez-en un grâce à notre partenaire Diagoriente.")
        self.assertContains(
            response,
            "https://diagoriente.beta.gouv.fr/services/plateforme?utm_source=emploi-inclusion-candidat",
        )

    def test_diagoriente_card_is_not_shown_for_job_seeker(self):
        user = JobSeekerFactory()
        self.client.force_login(user)

        with self.assertTemplateNotUsed("dashboard/includes/diagoriente_card.html"):
            self.client.get(reverse("dashboard:index"))

    def test_diagoriente_card_is_shown_for_employer(self):
        company = CompanyFactory(with_membership=True)
        self.client.force_login(company.members.first())

        with self.assertTemplateUsed("dashboard/includes/diagoriente_card.html"):
            self.client.get(reverse("dashboard:index"))

    def test_diagoriente_card_is_shown_for_prescriber(self):
        prescriber_organization = prescribers_factories.PrescriberOrganizationWithMembershipFactory()
        self.client.force_login(prescriber_organization.members.first())

        with self.assertTemplateUsed("dashboard/includes/diagoriente_card.html"):
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
        user = JobSeekerWithAddressFactory()
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

    @pytest.mark.ignore_unknown_variable_template_error("hiring_pending", "job_application")
    @freeze_time("2022-09-15")
    def test_dashboard_access_by_a_jobseeker(self):
        user = JobSeekerWithAddressFactory()
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
        user = JobSeekerWithAddressFactory(**empty_field)
        self.client.force_login(user)

        response = self.client.get(reverse("dashboard:index"))
        self.assertRedirects(response, reverse("dashboard:edit_user_info"))

        setattr(user, field, data)
        user.save(update_fields=(field,))

        response = self.client.get(reverse("dashboard:index"))
        assert response.status_code == 200


@pytest.mark.usefixtures("unittest_compatibility")
class EditUserInfoViewTest(InclusionConnectBaseTestCase):
    NIR_UPDATE_TALLY_LINK_LABEL = "Demander la correction du numéro de sécurité sociale"
    EMAIL_LABEL = "Adresse électronique"
    NIR_FIELD_ID = "id_nir"
    LACK_OF_NIR_FIELD_ID = "id_lack_of_nir"
    LACK_OF_NIR_REASON_FIELD_ID = "id_lack_of_nir_reason"
    BIRTHDATE_FIELD_NAME = "birthdate"

    def setUp(self):
        super().setUp()
        self.city = City.objects.create(
            name="Geispolsheim",
            slug="geispolsheim-67",
            department="67",
            coords=Point(7.644817, 48.515883),
            post_codes=["67118"],
            code_insee="67152",
        )

    def address_form_fields(self, fill_mode=""):
        return {
            "ban_api_resolved_address": "37 B Rue du Général De Gaulle, 67118 Geispolsheim",
            "address_line_1": "37 B Rue du Général De Gaulle",
            "address_line_2": "appartement 240",
            "insee_code": "67152",
            "post_code": "67118",
            "geocoding_score": 0.9714,
            "fill_mode": fill_mode,
        }

    def _test_address_autocomplete(self, user, post_data, ban_api_resolved_address=True):
        geocoding_data = mock_get_geocoding_data_by_ban_api_resolved(post_data["ban_api_resolved_address"])
        assert user.address_line_1 == post_data["address_line_1"]
        assert user.address_line_2 == post_data["address_line_2"]
        assert user.post_code == post_data["post_code"]
        assert user.city == self.city.name
        assert math.isclose(user.latitude, geocoding_data.get("latitude"), abs_tol=1e-5)
        assert math.isclose(user.longitude, geocoding_data.get("longitude"), abs_tol=1e-5)
        if ban_api_resolved_address:
            assert user.address_filled_at == datetime(2023, 3, 10, tzinfo=datetime_tz.utc)
            assert user.geocoding_updated_at == datetime(2023, 3, 10, tzinfo=datetime_tz.utc)

    @override_settings(TALLY_URL="https://tally.so")
    @freeze_time("2023-03-10")
    @mock.patch(
        "itou.utils.apis.geocoding.get_geocoding_data",
        side_effect=mock_get_geocoding_data_by_ban_api_resolved,
    )
    def test_edit_with_nir(self, _mock):
        user = JobSeekerFactory()
        self.client.force_login(user)
        url = reverse("dashboard:edit_user_info")
        with self.assertNumQueries(
            BASE_NUM_QUERIES
            + 1  # session
            + 1  # user
            + 1  # jobseeker_profile
            + 1  # external_data_externaldataimport (extra_data)
            + 3  # update session with savepoint & release
        ):
            response = self.client.get(url)
        # There's a specific view to edit the email so we don't show it here
        self.assertNotContains(response, self.EMAIL_LABEL)
        # Check that the NIR field is disabled
        self.assertContains(response, DISABLED_NIR)
        self.assertContains(response, self.LACK_OF_NIR_FIELD_ID)
        self.assertContains(response, self.LACK_OF_NIR_REASON_FIELD_ID)
        self.assertContains(response, self.BIRTHDATE_FIELD_NAME)
        self.assertContains(
            response,
            (
                f'<a href="https://tally.so/r/wzxQlg?jobseeker={user.pk}" target="_blank" rel="noopener">'
                f"{self.NIR_UPDATE_TALLY_LINK_LABEL}</a>"
            ),
            html=True,
        )

        post_data = {
            "email": "bob@saintclar.net",
            "title": "M",
            "first_name": "Bob",
            "last_name": "Saint Clar",
            "birthdate": "20/12/1978",
            "phone": "0610203050",
            "lack_of_pole_emploi_id_reason": LackOfPoleEmploiId.REASON_NOT_REGISTERED,
        } | self.address_form_fields(fill_mode="ban_api")
        response = self.client.post(url, data=post_data)
        assert response.status_code == 302

        user = User.objects.get(id=user.id)
        assert user.first_name == post_data["first_name"]
        assert user.last_name == post_data["last_name"]
        assert user.phone == post_data["phone"]
        assert user.birthdate.strftime("%d/%m/%Y") == post_data["birthdate"]
        self._test_address_autocomplete(user=user, post_data=post_data)

        # Ensure that the job seeker cannot edit email here.
        assert user.email != post_data["email"]

    def test_edit_title_required(self):
        user = JobSeekerFactory()
        self.client.force_login(user)
        url = reverse("dashboard:edit_user_info")
        response = self.client.get(url)
        post_data = {
            "email": user.email,
            "title": "",
            "first_name": user.first_name,
            "last_name": user.last_name,
            "birthdate": "20/12/1978",
            "phone": user.phone,
            "lack_of_pole_emploi_id_reason": user.jobseeker_profile.lack_of_pole_emploi_id_reason,
            "lack_of_nir": False,
            "nir": user.jobseeker_profile.nir,
        } | self.address_form_fields()

        response = self.client.post(url, data=post_data)
        assert response.status_code == 200
        assert response.context["form"].errors.get("title") == ["Ce champ est obligatoire."]

    def test_required_address_fields_are_present(self):
        user = JobSeekerWithAddressFactory()
        self.client.force_login(user)
        url = reverse("dashboard:edit_user_info")
        response = self.client.get(url)

        # Those fields are required for the autocomplete javascript to work
        # Explicitly test the presence of the fields to help a future developer :)
        self.assertContains(response, 'id="id_address_line_1"')
        self.assertContains(response, 'id="id_address_line_2"')
        self.assertContains(response, 'id="id_post_code"')
        self.assertContains(response, 'id="id_city"')
        self.assertContains(response, 'id="id_insee_code"')
        self.assertContains(response, 'id="id_fill_mode"')
        self.assertContains(response, 'id="id_ban_api_resolved_address"')

    @pytest.mark.usefixtures("unittest_compatibility")
    @freeze_time("2023-03-10")
    @override_settings(API_BAN_BASE_URL="http://ban-api")
    @mock.patch(
        "itou.utils.apis.geocoding.get_geocoding_data",
        side_effect=mock_get_geocoding_data_by_ban_api_resolved,
    )
    def test_update_address(self, _mock):
        user = JobSeekerWithAddressFactory()
        self.client.force_login(user)
        url = reverse("dashboard:edit_user_info")
        response = self.client.get(url)
        # Address is mandatory.
        post_data = {
            "title": "M",
            "email": "bob@saintclar.net",
            "first_name": "Bob",
            "last_name": "Saint Clar",
            "birthdate": "20/12/1978",
            "phone": "0610203050",
            "lack_of_pole_emploi_id_reason": LackOfPoleEmploiId.REASON_NOT_REGISTERED,
        }

        # Check that address field is mandatory
        response = self.client.post(url, data=post_data)
        assert response.status_code == 200
        assert not response.context["form"].is_valid()
        assert response.context["form"].errors.get("address_for_autocomplete") == ["Ce champ est obligatoire."]

        # Check that when we post a different address than the one of the user and
        # there is an error in the form (title is missing), the new address is displayed in the select
        # instead of the one attached to the user
        response = self.client.post(
            url, data=post_data | {"title": ""} | self.address_form_fields(fill_mode="ban_api")
        )
        assert response.status_code == 200
        assert not response.context["form"].is_valid()
        assert response.context["form"].errors.get("title") == ["Ce champ est obligatoire."]
        results_section = parse_response_to_soup(response, selector="#id_address_for_autocomplete")
        assert str(results_section) == self.snapshot(name="user address input on error")

        # Now try again in fallback mode (ban_api_resolved_address is missing)
        post_data = post_data | self.address_form_fields(fill_mode="fallback")
        response = self.client.post(url, data=post_data)

        assert response.status_code == 302
        user.refresh_from_db()
        self._test_address_autocomplete(user=user, post_data=post_data, ban_api_resolved_address=False)

        # Now try again providing every required field.
        post_data = post_data | self.address_form_fields(fill_mode="ban_api")
        response = self.client.post(url, data=post_data)

        assert response.status_code == 302
        user.refresh_from_db()
        self._test_address_autocomplete(user=user, post_data=post_data, ban_api_resolved_address=True)

        # Ensure the job seeker's address is displayed in the autocomplete input field.
        url = reverse("dashboard:edit_user_info")
        response = self.client.get(url)
        results_section = parse_response_to_soup(response, selector="#id_address_for_autocomplete")
        assert str(results_section) == self.snapshot(name="user address input")

    def test_update_address_unavailable_api(self):
        user = JobSeekerFactory()
        self.client.force_login(user)
        url = reverse("dashboard:edit_user_info")
        response = self.client.get(url)
        # Address is mandatory.
        post_data = {
            "title": "M",
            "email": "bob@saintclar.net",
            "first_name": "Bob",
            "last_name": "Saint Clar",
            "birthdate": "20/12/1978",
            "phone": "0610203050",
            "lack_of_pole_emploi_id_reason": LackOfPoleEmploiId.REASON_NOT_REGISTERED,
            # Address fallback fields,
            "address_for_autocomplete": "26 rue du Labrador",
            "address_line_1": "102 Quai de Jemmapes",
            "address_line_2": "Appartement 16",
            "post_code": "75010",
        }
        response = self.client.post(url, data=post_data)
        assert response.status_code == 302
        user.refresh_from_db()
        assert user.address_line_1 == post_data["address_line_1"]
        assert user.address_line_2 == post_data["address_line_2"]
        assert user.post_code == post_data["post_code"]

    @freeze_time("2023-03-10")
    @mock.patch(
        "itou.utils.apis.geocoding.get_geocoding_data",
        side_effect=mock_get_geocoding_data_by_ban_api_resolved,
    )
    def test_edit_with_lack_of_nir_reason(self, _mock):
        user = JobSeekerFactory(
            jobseeker_profile__nir="", jobseeker_profile__lack_of_nir_reason=LackOfNIRReason.TEMPORARY_NUMBER
        )
        self.client.force_login(user)
        url = reverse("dashboard:edit_user_info")
        response = self.client.get(url)
        # Check that the NIR field is disabled (it can be reenabled via lack_of_nir check box)
        self.assertContains(response, DISABLED_NIR)
        self.assertContains(response, LackOfNIRReason.TEMPORARY_NUMBER.label, html=True)
        self.assertNotContains(response, self.NIR_UPDATE_TALLY_LINK_LABEL, html=True)

        NEW_NIR = "1 970 13625838386"
        post_data = {
            "email": "bob@saintclar.net",
            "title": "M",
            "first_name": "Bob",
            "last_name": "Saint Clar",
            "birthdate": "20/12/1978",
            "phone": "0610203050",
            "lack_of_pole_emploi_id_reason": LackOfPoleEmploiId.REASON_NOT_REGISTERED,
            "lack_of_nir": False,
            "nir": NEW_NIR,
        } | self.address_form_fields(fill_mode="ban_api")

        response = self.client.post(url, data=post_data)
        assert response.status_code == 302

        user.refresh_from_db()
        user.jobseeker_profile.refresh_from_db()
        assert user.jobseeker_profile.lack_of_nir_reason == ""
        assert user.jobseeker_profile.nir == NEW_NIR.replace(" ", "")
        self._test_address_autocomplete(user=user, post_data=post_data)

    @freeze_time("2023-03-10")
    def test_edit_without_nir_information(self):
        user = JobSeekerFactory(jobseeker_profile__nir="", jobseeker_profile__lack_of_nir_reason="")
        self.client.force_login(user)
        url = reverse("dashboard:edit_user_info")
        response = self.client.get(url)
        # Check that the NIR field is enabled
        assert not response.context["form"]["nir"].field.disabled
        self.assertNotContains(response, self.NIR_UPDATE_TALLY_LINK_LABEL, html=True)

        NEW_NIR = "1 970 13625838386"
        post_data = {
            "email": "bob@saintclar.net",
            "title": "M",
            "first_name": "Bob",
            "last_name": "Saint Clar",
            "birthdate": "20/12/1978",
            "phone": "0610203050",
            "lack_of_pole_emploi_id_reason": LackOfPoleEmploiId.REASON_NOT_REGISTERED,
            "lack_of_nir": False,
            "nir": NEW_NIR,
        } | self.address_form_fields()
        response = self.client.post(url, data=post_data)
        assert response.status_code == 302

        user.jobseeker_profile.refresh_from_db()
        assert user.jobseeker_profile.lack_of_nir_reason == ""
        assert user.jobseeker_profile.nir == NEW_NIR.replace(" ", "")

    def test_edit_existing_nir(self):
        other_jobseeker = JobSeekerFactory()

        user = JobSeekerFactory(jobseeker_profile__nir="", jobseeker_profile__lack_of_nir_reason="")
        self.client.force_login(user)
        url = reverse("dashboard:edit_user_info")
        response = self.client.get(url)
        # Check that the NIR field is enabled
        assert not response.context["form"]["nir"].field.disabled
        self.assertNotContains(response, self.NIR_UPDATE_TALLY_LINK_LABEL, html=True)

        post_data = {
            "email": "bob@saintclar.net",
            "title": "M",
            "first_name": "Bob",
            "last_name": "Saint Clar",
            "birthdate": "20/12/1978",
            "phone": "0610203050",
            "lack_of_pole_emploi_id_reason": LackOfPoleEmploiId.REASON_NOT_REGISTERED,
            "address_line_1": "10, rue du Gué",
            "address_line_2": "Sous l'escalier",
            "post_code": "35400",
            "city": "Saint-Malo",
            "lack_of_nir": False,
            "nir": other_jobseeker.jobseeker_profile.nir,
        }
        response = self.client.post(url, data=post_data)
        self.assertContains(response, "Le numéro de sécurité sociale est déjà associé à un autre utilisateur")

        user.jobseeker_profile.refresh_from_db()
        assert user.jobseeker_profile.lack_of_nir_reason == ""
        assert user.jobseeker_profile.nir == ""

    @freeze_time("2023-03-10")
    @mock.patch(
        "itou.utils.apis.geocoding.get_geocoding_data",
        side_effect=mock_get_geocoding_data_by_ban_api_resolved,
    )
    def test_edit_sso(self, _mock):
        user = JobSeekerFactory(
            identity_provider=IdentityProvider.FRANCE_CONNECT,
            first_name="Not Bob",
            last_name="Not Saint Clar",
            birthdate=date(1970, 1, 1),
        )
        self.client.force_login(user)
        url = reverse("dashboard:edit_user_info")
        response = self.client.get(url)
        self.assertContains(response, self.EMAIL_LABEL)

        post_data = {
            "email": "bob@saintclar.net",
            "title": "M",
            "first_name": "Bob",
            "last_name": "Saint Clar",
            "birthdate": "20/12/1978",
            "phone": "0610203050",
            "lack_of_pole_emploi_id_reason": LackOfPoleEmploiId.REASON_NOT_REGISTERED,
        } | self.address_form_fields(fill_mode="ban_api")

        response = self.client.post(url, data=post_data)
        assert response.status_code == 302

        user = User.objects.get(id=user.id)
        assert user.phone == post_data["phone"]
        self._test_address_autocomplete(user=user, post_data=post_data)

        # Ensure that the job seeker cannot update data retreived from the SSO here.
        assert user.first_name != post_data["first_name"]
        assert user.last_name != post_data["last_name"]
        assert user.birthdate.strftime("%d/%m/%Y") != post_data["birthdate"]
        assert user.email != post_data["email"]

    def test_edit_without_title(self):
        MISSING_INFOS_WARNING_ID = "missing-infos-warning"
        user = JobSeekerWithAddressFactory(title="", phone="", address_line_1="")
        self.client.force_login(user)
        url = reverse("dashboard:edit_user_info")

        # No phone and no title and no address
        response = self.client.get(url)
        warning_text = parse_response_to_soup(response, selector=f"#{MISSING_INFOS_WARNING_ID}")
        assert str(warning_text) == self.snapshot(name="missing title warning with phone and address")

        # Phone but no title and no birthdate
        user.phone = "0123456789"
        user.address_line_1 = "123 rue de"
        user.birthdate = None
        user.save(
            update_fields=(
                "address_line_1",
                "birthdate",
                "phone",
            )
        )
        response = self.client.get(url)
        warning_text = parse_response_to_soup(response, selector=f"#{MISSING_INFOS_WARNING_ID}")
        assert str(warning_text) == self.snapshot(name="missing title warning without phone and with birthdate")

        # No phone but title
        user.phone = ""
        user.title = Title.MME
        user.save(update_fields=("phone", "title"))
        response = self.client.get(url)
        self.assertNotContains(response, MISSING_INFOS_WARNING_ID)

    def test_edit_with_invalid_pole_emploi_id(self):
        user = JobSeekerFactory()
        self.client.force_login(user)
        url = reverse("dashboard:edit_user_info")
        response = self.client.get(url)
        post_data = {
            "email": user.email,
            "title": user.title,
            "first_name": user.first_name,
            "last_name": user.last_name,
            "birthdate": "20/12/1978",
            "phone": user.phone,
            "pole_emploi_id": "trop long",
            "lack_of_pole_emploi_id_reason": "",
            "address_line_1": "10, rue du Gué",
            "address_line_2": "Sous l'escalier",
            "post_code": "35400",
            "city": "Saint-Malo",
            "lack_of_nir": False,
            "nir": user.jobseeker_profile.nir,
        }
        response = self.client.post(url, data=post_data)
        assert response.status_code == 200
        self.assertFormError(
            response.context["form"],
            "pole_emploi_id",
            "Assurez-vous que cette valeur comporte au plus 8 caractères (actuellement 9).",
        )
        self.assertFormError(
            response.context["form"],
            None,
            "Renseignez soit un identifiant France Travail (ex pôle emploi), soit la raison de son absence.",
        )

    def test_edit_as_prescriber(self):
        user = PrescriberFactory()
        self.client.force_login(user)
        url = reverse("dashboard:edit_user_info")
        response = self.client.get(url)
        self.assertNotContains(response, self.NIR_FIELD_ID)
        self.assertNotContains(response, self.LACK_OF_NIR_FIELD_ID)
        self.assertNotContains(response, self.LACK_OF_NIR_REASON_FIELD_ID)
        self.assertNotContains(response, self.BIRTHDATE_FIELD_NAME)

        post_data = {
            "first_name": "Bob",
            "last_name": "Saint Clar",
            "phone": "0610203050",
        }
        response = self.client.post(url, data=post_data)
        assert response.status_code == 302

        user = User.objects.get(id=user.id)
        assert user.phone == post_data["phone"]

    def test_edit_as_prescriber_with_ic(self):
        user = PrescriberFactory(identity_provider=IdentityProvider.INCLUSION_CONNECT)
        self.client.force_login(user)
        url = reverse("dashboard:edit_user_info")
        response = self.client.get(url)
        self.assertNotContains(response, self.NIR_FIELD_ID)
        self.assertNotContains(response, self.LACK_OF_NIR_FIELD_ID)
        self.assertNotContains(response, self.LACK_OF_NIR_REASON_FIELD_ID)
        self.assertNotContains(response, self.BIRTHDATE_FIELD_NAME)
        self.assertContains(response, f"Prénom : <strong>{user.first_name.title()}</strong>")
        self.assertContains(response, f"Nom : <strong>{user.last_name.upper()}</strong>")
        self.assertContains(response, f"Adresse e-mail : <strong>{user.email}</strong>")
        self.assertContains(response, "Modifier ces informations")

        post_data = {
            "email": "aaa",
            "first_name": "Bob",
            "last_name": "Saint Clar",
            "phone": "0610203050",
        }
        response = self.client.post(url, data=post_data)
        assert response.status_code == 302

        user = User.objects.get(id=user.id)
        assert user.first_name != "Bob"
        assert user.first_name != "Saint Clair"
        assert user.phone == post_data["phone"]


class EditJobSeekerInfo(TestCase):
    NIR_UPDATE_TALLY_LINK_LABEL = "Demander la correction du numéro de sécurité sociale"
    EMAIL_LABEL = "Adresse électronique"

    def setUp(self):
        super().setUp()
        self.city = City.objects.create(
            name="Geispolsheim",
            slug="geispolsheim-67",
            department="67",
            coords=Point(7.644817, 48.515883),
            post_codes=["67118"],
            code_insee="67152",
        )

    @property
    def address_form_fields(self):
        return {
            "ban_api_resolved_address": "37 B Rue du Général De Gaulle, 67118 Geispolsheim",
            "address_line_1": "37 B Rue du Général De Gaulle",
            "insee_code": "67152",
            "post_code": "67118",
            "fill_mode": "ban_api",
        }

    def _test_address_autocomplete(self, user, post_data):
        geocoding_data = mock_get_geocoding_data_by_ban_api_resolved(post_data["ban_api_resolved_address"])
        assert user.address_line_1 == post_data["address_line_1"]
        if post_data.get("addres_line_2"):
            assert user.address_line_2 == post_data["address_line_2"]
        assert user.post_code == post_data["post_code"]
        assert user.city == self.city.name
        assert math.isclose(user.latitude, geocoding_data.get("latitude"), abs_tol=1e-5)
        assert math.isclose(user.longitude, geocoding_data.get("longitude"), abs_tol=1e-5)

    @override_settings(TALLY_URL="https://tally.so")
    @mock.patch(
        "itou.utils.apis.geocoding.get_geocoding_data",
        side_effect=mock_get_geocoding_data_by_ban_api_resolved,
    )
    def test_edit_by_company_with_nir(self, _mock):
        job_application = JobApplicationSentByPrescriberFactory()
        user = job_application.to_company.members.first()

        # Ensure that the job seeker is not autonomous (i.e. he did not register by himself).
        job_application.job_seeker.created_by = user
        job_application.job_seeker.save()
        previous_last_checked_at = job_application.job_seeker.last_checked_at

        self.client.force_login(user)

        back_url = reverse("apply:details_for_company", kwargs={"job_application_id": job_application.id})
        url = reverse("dashboard:edit_job_seeker_info", kwargs={"job_seeker_pk": job_application.job_seeker_id})
        url = f"{url}?back_url={back_url}&from_application={job_application.pk}"

        with self.assertNumQueries(
            BASE_NUM_QUERIES
            + 1  # session
            + 3  # user, memberships, company (ItouCurrentOrganizationMiddleware)
            + 1  # job seeker infos (get_object_or_404)
            + 1  # account_emailaddress (can_edit_email/has_verified_email)
            + 3  # update session with savepoint & release
        ):
            response = self.client.get(url)
        self.assertContains(
            response,
            (
                f'<a href="https://tally.so/r/wzxQlg?jobapplication={job_application.pk}" target="_blank" '
                f'rel="noopener">{self.NIR_UPDATE_TALLY_LINK_LABEL}</a>'
            ),
            html=True,
        )

        post_data = {
            "email": "bob@saintclar.net",
            "title": "M",
            "first_name": "Bob",
            "last_name": "Saint Clar",
            "birthdate": "20/12/1978",
            "lack_of_pole_emploi_id_reason": LackOfPoleEmploiId.REASON_NOT_REGISTERED,
        } | self.address_form_fields

        response = self.client.post(url, data=post_data)

        assert response.status_code == 302
        assert response.url == back_url

        job_seeker = User.objects.get(id=job_application.job_seeker.id)
        assert job_seeker.first_name == post_data["first_name"]
        assert job_seeker.last_name == post_data["last_name"]
        assert job_seeker.birthdate.strftime("%d/%m/%Y") == post_data["birthdate"]
        self._test_address_autocomplete(user=job_seeker, post_data=post_data)

        # Optional fields
        post_data |= {
            "phone": "0610203050",
            "address_line_2": "Sous l'escalier",
        }
        response = self.client.post(url, data=post_data)
        job_seeker.refresh_from_db()

        assert job_seeker.phone == post_data["phone"]
        assert job_seeker.address_line_2 == post_data["address_line_2"]

        # last_checked_at should have been updated
        assert job_seeker.last_checked_at > previous_last_checked_at

    @mock.patch(
        "itou.utils.apis.geocoding.get_geocoding_data",
        side_effect=mock_get_geocoding_data_by_ban_api_resolved,
    )
    def test_edit_by_company_with_lack_of_nir_reason(self, _mock):
        job_application = JobApplicationSentByPrescriberFactory(
            job_seeker__jobseeker_profile__nir="",
            job_seeker__jobseeker_profile__lack_of_nir_reason=LackOfNIRReason.TEMPORARY_NUMBER,
        )
        user = job_application.to_company.members.first()

        # Ensure that the job seeker is not autonomous (i.e. he did not register by himself).
        job_application.job_seeker.created_by = user
        job_application.job_seeker.save()
        previous_last_checked_at = job_application.job_seeker.last_checked_at

        self.client.force_login(user)

        back_url = reverse("apply:details_for_company", kwargs={"job_application_id": job_application.id})
        url = reverse("dashboard:edit_job_seeker_info", kwargs={"job_seeker_pk": job_application.job_seeker_id})
        url = f"{url}?back_url={back_url}"

        response = self.client.get(url)
        self.assertContains(response, LackOfNIRReason.TEMPORARY_NUMBER.label, html=True)
        self.assertContains(response, DISABLED_NIR)
        self.assertNotContains(response, self.NIR_UPDATE_TALLY_LINK_LABEL, html=True)

        NEW_NIR = "1 970 13625838386"
        post_data = {
            "email": "bob@saintclar.net",
            "title": "M",
            "first_name": "Bob",
            "last_name": "Saint Clar",
            "birthdate": "20/12/1978",
            "lack_of_pole_emploi_id_reason": LackOfPoleEmploiId.REASON_NOT_REGISTERED,
            "lack_of_nir": False,
            "nir": NEW_NIR,
        } | self.address_form_fields

        response = self.client.post(url, data=post_data)

        assert response.status_code == 302
        assert response.url == back_url

        job_seeker = User.objects.get(id=job_application.job_seeker.id)
        assert job_seeker.jobseeker_profile.lack_of_nir_reason == ""
        assert job_seeker.jobseeker_profile.nir == NEW_NIR.replace(" ", "")

        # last_checked_at should have been updated
        assert job_seeker.last_checked_at > previous_last_checked_at

    @mock.patch(
        "itou.utils.apis.geocoding.get_geocoding_data",
        side_effect=mock_get_geocoding_data_by_ban_api_resolved,
    )
    def test_edit_by_company_without_nir_information(self, _mock):
        job_application = JobApplicationSentByPrescriberFactory(
            job_seeker__jobseeker_profile__nir="", job_seeker__jobseeker_profile__lack_of_nir_reason=""
        )
        user = job_application.to_company.members.first()

        # Ensure that the job seeker is not autonomous (i.e. he did not register by himself).
        job_application.job_seeker.created_by = user
        job_application.job_seeker.save()
        previous_last_checked_at = job_application.job_seeker.last_checked_at

        self.client.force_login(user)

        back_url = reverse("apply:details_for_company", kwargs={"job_application_id": job_application.id})
        url = reverse("dashboard:edit_job_seeker_info", kwargs={"job_seeker_pk": job_application.job_seeker_id})
        url = f"{url}?back_url={back_url}"

        response = self.client.get(url)
        # Check that the NIR field is enabled
        assert not response.context["form"]["nir"].field.disabled
        self.assertNotContains(response, self.NIR_UPDATE_TALLY_LINK_LABEL, html=True)

        post_data = {
            "email": "bob@saintclar.net",
            "title": "M",
            "first_name": "Bob",
            "last_name": "Saint Clar",
            "birthdate": "20/12/1978",
            "lack_of_pole_emploi_id_reason": LackOfPoleEmploiId.REASON_NOT_REGISTERED,
            "lack_of_nir": False,
        } | self.address_form_fields

        response = self.client.post(url, data=post_data)
        self.assertContains(response, "Le numéro de sécurité sociale n'est pas valide", html=True)

        post_data["lack_of_nir"] = True
        response = self.client.post(url, data=post_data)
        self.assertContains(response, "Le numéro de sécurité sociale n'est pas valide", html=True)
        self.assertContains(response, "Veuillez sélectionner un motif pour continuer", html=True)

        post_data.update(
            {
                "lack_of_nir": True,
                "lack_of_nir_reason": LackOfNIRReason.TEMPORARY_NUMBER.value,
            }
        )
        response = self.client.post(url, data=post_data)
        self.assertRedirects(response, expected_url=back_url)
        job_seeker = User.objects.get(id=job_application.job_seeker.id)
        assert job_seeker.jobseeker_profile.lack_of_nir_reason == LackOfNIRReason.TEMPORARY_NUMBER
        assert job_seeker.jobseeker_profile.nir == ""

        post_data.update(
            {
                "lack_of_nir": False,
                "nir": "1234",
            }
        )
        response = self.client.post(url, data=post_data)
        self.assertContains(response, "Le numéro de sécurité sociale n'est pas valide", html=True)
        self.assertFormError(
            response.context["form"],
            "nir",
            "Le numéro de sécurité sociale est trop court (15 caractères autorisés).",
        )

        NEW_NIR = "1 970 13625838386"
        post_data["nir"] = NEW_NIR
        response = self.client.post(url, data=post_data)
        self.assertRedirects(response, expected_url=back_url)

        job_seeker.refresh_from_db()
        assert job_seeker.jobseeker_profile.lack_of_nir_reason == ""
        assert job_seeker.jobseeker_profile.nir == NEW_NIR.replace(" ", "")

        # last_checked_at should have been updated
        assert job_seeker.last_checked_at > previous_last_checked_at

    def test_edit_by_prescriber(self):
        job_application = JobApplicationFactory(sent_by_authorized_prescriber_organisation=True)
        user = job_application.sender

        # Ensure that the job seeker is not autonomous (i.e. he did not register by himself).
        job_application.job_seeker.created_by = user
        job_application.job_seeker.save()

        self.client.force_login(user)
        url = reverse("dashboard:edit_job_seeker_info", kwargs={"job_seeker_pk": job_application.job_seeker_id})
        with self.assertNumQueries(
            BASE_NUM_QUERIES
            + 1  # session
            + 2  # user, memberships (ItouCurrentOrganizationMiddleware)
            + 1  # job seeker infos (get_object_or_404)
            + 1  # prescribers_prescribermembership (can_edit_personal_information/is_prescriber_with_authorized_org)
            + 1  # account_emailaddress (can_edit_email/has_verified_email)
            + 3  # update session with savepoint & release
        ):
            response = self.client.get(url)
        assert response.status_code == 200

    def test_edit_by_prescriber_of_organization(self):
        job_application = JobApplicationFactory(sent_by_authorized_prescriber_organisation=True)
        prescriber = job_application.sender

        # Ensure that the job seeker is not autonomous (i.e. he did not register by himself).
        job_application.job_seeker.created_by = prescriber
        job_application.job_seeker.save()

        # Log as other member of the same organization
        other_prescriber = PrescriberFactory()
        prescribers_factories.PrescriberMembershipFactory(
            user=other_prescriber, organization=job_application.sender_prescriber_organization
        )
        self.client.force_login(other_prescriber)
        url = reverse("dashboard:edit_job_seeker_info", kwargs={"job_seeker_pk": job_application.job_seeker_id})
        response = self.client.get(url)
        assert response.status_code == 200

    def test_edit_autonomous_not_allowed(self):
        job_application = JobApplicationSentByPrescriberFactory()
        # The job seeker manages his own personal information (autonomous)
        user = job_application.sender
        self.client.force_login(user)

        url = reverse("dashboard:edit_job_seeker_info", kwargs={"job_seeker_pk": job_application.job_seeker_id})

        response = self.client.get(url)
        assert response.status_code == 403

    def test_edit_not_allowed(self):
        # Ensure that the job seeker is not autonomous (i.e. he did not register by himself).
        job_application = JobApplicationSentByPrescriberFactory(job_seeker__created_by=PrescriberFactory())

        # Lambda prescriber not member of the sender organization
        prescriber = PrescriberFactory()
        self.client.force_login(prescriber)
        url = reverse("dashboard:edit_job_seeker_info", kwargs={"job_seeker_pk": job_application.job_seeker_id})

        response = self.client.get(url)
        assert response.status_code == 403

    def test_name_is_required(self):
        company = CompanyFactory(with_membership=True)
        user = company.members.first()
        job_application = JobApplicationSentByPrescriberFactory(to_company=company, job_seeker__created_by=user)
        post_data = {
            "title": "M",
            "email": "bidou@yopmail.com",
            "birthdate": "20/12/1978",
            "lack_of_pole_emploi_id_reason": LackOfPoleEmploiId.REASON_NOT_REGISTERED,
        } | self.address_form_fields

        self.client.force_login(user)
        response = self.client.post(
            reverse("dashboard:edit_job_seeker_info", kwargs={"job_seeker_pk": job_application.job_seeker_id}),
            data=post_data,
        )
        self.assertContains(
            response,
            """
            <div class="form-group is-invalid form-group-required">
            <label class="form-label" for="id_first_name">Prénom</label>
            <input type="text" name="first_name" maxlength="150" class="form-control is-invalid"
                   placeholder="Prénom" required aria-invalid="true" id="id_first_name">
            <div class="invalid-feedback">Ce champ est obligatoire.</div>
            </div>
            """,
            html=True,
            count=1,
        )
        self.assertContains(
            response,
            """
            <div class="form-group is-invalid form-group-required">
            <label class="form-label" for="id_last_name">Nom</label>
            <input type="text" name="last_name" maxlength="150" class="form-control is-invalid"
                   placeholder="Nom" required aria-invalid="true" id="id_last_name">
            <div class="invalid-feedback">Ce champ est obligatoire.</div>
            </div>
            """,
            html=True,
            count=1,
        )

    @mock.patch(
        "itou.utils.apis.geocoding.get_geocoding_data",
        side_effect=mock_get_geocoding_data_by_ban_api_resolved,
    )
    def test_edit_email_when_unconfirmed(self, _mock):
        """
        The SIAE can edit the email of a jobseeker it works with, provided he did not confirm its email.
        """
        new_email = "bidou@yopmail.com"
        company = CompanyFactory(with_membership=True)
        user = company.members.first()
        job_application = JobApplicationSentByPrescriberFactory(to_company=company, job_seeker__created_by=user)

        self.client.force_login(user)

        back_url = reverse("apply:details_for_company", kwargs={"job_application_id": job_application.id})
        url = reverse("dashboard:edit_job_seeker_info", kwargs={"job_seeker_pk": job_application.job_seeker_id})
        url = f"{url}?back_url={back_url}"

        response = self.client.get(url)
        self.assertContains(response, self.EMAIL_LABEL)

        post_data = {
            "title": "M",
            "first_name": "Manuel",
            "last_name": "Calavera",
            "email": new_email,
            "birthdate": "20/12/1978",
            "lack_of_pole_emploi_id_reason": LackOfPoleEmploiId.REASON_NOT_REGISTERED,
        } | self.address_form_fields

        response = self.client.post(url, data=post_data)

        assert response.status_code == 302
        assert response.url == back_url

        job_seeker = User.objects.get(id=job_application.job_seeker.id)
        assert job_seeker.email == new_email

        # Optional fields
        post_data |= {
            "phone": "0610203050",
            "address_line_2": "Sous l'escalier",
        }
        response = self.client.post(url, data=post_data)
        job_seeker.refresh_from_db()

        assert job_seeker.phone == post_data["phone"]
        self._test_address_autocomplete(user=job_seeker, post_data=post_data)

    @mock.patch(
        "itou.utils.apis.geocoding.get_geocoding_data",
        side_effect=mock_get_geocoding_data_by_ban_api_resolved,
    )
    def test_edit_email_when_confirmed(self, _mock):
        new_email = "bidou@yopmail.com"
        job_application = JobApplicationSentByPrescriberFactory()
        user = job_application.to_company.members.first()

        # Ensure that the job seeker is not autonomous (i.e. he did not register by himself).
        job_application.job_seeker.created_by = user
        job_application.job_seeker.save()

        # Confirm job seeker email
        job_seeker = User.objects.get(id=job_application.job_seeker.id)
        EmailAddress.objects.create(user=job_seeker, email=job_seeker.email, verified=True)

        # Now the SIAE wants to edit the jobseeker email. The field is not available, and it cannot be bypassed
        self.client.force_login(user)

        back_url = reverse("apply:details_for_company", kwargs={"job_application_id": job_application.id})
        url = reverse("dashboard:edit_job_seeker_info", kwargs={"job_seeker_pk": job_application.job_seeker_id})
        url = f"{url}?back_url={back_url}"

        response = self.client.get(url)
        self.assertNotContains(response, self.EMAIL_LABEL)

        post_data = {
            "title": "M",
            "first_name": "Manuel",
            "last_name": "Calavera",
            "email": new_email,
            "birthdate": "20/12/1978",
            "lack_of_pole_emploi_id_reason": LackOfPoleEmploiId.REASON_NOT_REGISTERED,
        } | self.address_form_fields

        response = self.client.post(url, data=post_data)

        assert response.status_code == 302
        assert response.url == back_url

        job_seeker = User.objects.get(id=job_application.job_seeker.id)
        # The email is not changed, but other fields are taken into account
        assert job_seeker.email != new_email
        assert job_seeker.birthdate.strftime("%d/%m/%Y") == post_data["birthdate"]
        assert job_seeker.address_line_1 == post_data["address_line_1"]
        assert job_seeker.post_code == post_data["post_code"]
        assert job_seeker.city == self.city.name

        # Optional fields
        post_data |= {
            "phone": "0610203050",
            "address_line_2": "Sous l'escalier",
        }
        response = self.client.post(url, data=post_data)
        job_seeker.refresh_from_db()

        assert job_seeker.phone == post_data["phone"]
        self._test_address_autocomplete(user=job_seeker, post_data=post_data)

    def test_edit_no_address_does_not_crash(self):
        job_application = JobApplicationFactory(sent_by_authorized_prescriber_organisation=True)
        user = job_application.sender

        # Ensure that the job seeker is not autonomous (i.e. he did not register by himself).
        job_application.job_seeker.created_by = user
        job_application.job_seeker.save()

        self.client.force_login(user)
        url = reverse("dashboard:edit_job_seeker_info", kwargs={"job_seeker_pk": job_application.job_seeker_id})
        post_data = {
            "title": "M",
            "email": user.email,
            "birthdate": "20/12/1978",
            "lack_of_pole_emploi_id_reason": LackOfPoleEmploiId.REASON_NOT_REGISTERED,
            "address_line_1": "",
            "post_code": "35400",
            "city": "Saint-Malo",
        }
        response = self.client.post(url, data=post_data)
        self.assertContains(response, "Ce champ est obligatoire.")
        assert response.context["form"].errors["address_for_autocomplete"] == ["Ce champ est obligatoire."]


class ChangeEmailViewTest(TestCase):
    def test_update_email(self):
        user = JobSeekerFactory()
        old_email = user.email
        new_email = "jean@gabin.fr"

        self.client.force_login(user)
        url = reverse("dashboard:edit_user_email")
        response = self.client.get(url)

        email_address = EmailAddress(email=old_email, verified=True, primary=True)
        email_address.user = user
        email_address.save()

        post_data = {"email": new_email, "email_confirmation": new_email}
        response = self.client.post(url, data=post_data)
        assert response.status_code == 302

        # User is logged out
        user.refresh_from_db()
        assert response.request.get("user") is None
        assert user.email == new_email
        assert user.emailaddress_set.count() == 0

        # User cannot log in with his old address
        post_data = {"login": old_email, "password": DEFAULT_PASSWORD}
        url = reverse("login:job_seeker")
        response = self.client.post(url, data=post_data)
        assert response.status_code == 200
        assert not response.context_data["form"].is_valid()

        # User cannot log in until confirmation
        post_data = {"login": new_email, "password": DEFAULT_PASSWORD}
        url = reverse("login:job_seeker")
        response = self.client.post(url, data=post_data)
        assert response.status_code == 302
        assert response.url == reverse("account_email_verification_sent")

        # User receives an email to confirm his new address.
        email = mail.outbox[0]
        assert "Confirmez votre adresse e-mail" in email.subject
        assert "Afin de finaliser votre inscription, cliquez sur le lien suivant" in email.body
        assert email.to[0] == new_email

        # Confirm email + auto login.
        confirmation_token = EmailConfirmationHMAC(user.emailaddress_set.first()).key
        confirm_email_url = reverse("account_confirm_email", kwargs={"key": confirmation_token})
        response = self.client.post(confirm_email_url)
        assert response.status_code == 302
        assert response.url == reverse("account_login")

        post_data = {"login": user.email, "password": DEFAULT_PASSWORD}
        url = reverse("account_login")
        response = self.client.post(url, data=post_data)
        assert response.context.get("user").is_authenticated

        user.refresh_from_db()
        assert user.email == new_email
        assert user.emailaddress_set.count() == 1
        new_address = user.emailaddress_set.first()
        assert new_address.email == new_email
        assert new_address.verified

    def test_update_email_forbidden(self):
        url = reverse("dashboard:edit_user_email")

        job_seeker = JobSeekerFactory(identity_provider=IdentityProvider.FRANCE_CONNECT)
        self.client.force_login(job_seeker)
        response = self.client.get(url)
        assert response.status_code == 403

        prescriber = PrescriberFactory(identity_provider=IdentityProvider.INCLUSION_CONNECT)
        self.client.force_login(prescriber)
        response = self.client.get(url)
        assert response.status_code == 403


class EditUserEmailFormTest(TestCase):
    def test_invalid_form(self):
        old_email = "bernard@blier.fr"

        # Email and confirmation email do not match
        email = "jean@gabin.fr"
        email_confirmation = "oscar@gabin.fr"
        data = {"email": email, "email_confirmation": email_confirmation}
        form = EditUserEmailForm(data=data, user_email=old_email)
        assert not form.is_valid()

        # Email already taken by another user. Bad luck!
        user = JobSeekerFactory()
        data = {"email": user.email, "email_confirmation": user.email}
        form = EditUserEmailForm(data=data, user_email=old_email)
        assert not form.is_valid()

        # New address is the same as the old one.
        data = {"email": old_email, "email_confirmation": old_email}
        form = EditUserEmailForm(data=data, user_email=old_email)
        assert not form.is_valid()

    def test_valid_form(self):
        old_email = "bernard@blier.fr"
        new_email = "jean@gabin.fr"
        data = {"email": new_email, "email_confirmation": new_email}
        form = EditUserEmailForm(data=data, user_email=old_email)
        assert form.is_valid()


class SwitchCompanyTest(TestCase):
    @pytest.mark.ignore_unknown_variable_template_error("matomo_event_attrs")
    def test_switch_company(self):
        company = CompanyFactory(with_membership=True)
        user = company.members.first()
        self.client.force_login(user)

        related_company = CompanyFactory(with_membership=True)
        related_company.members.add(user)

        url = reverse("dashboard:index")
        response = self.client.get(url)
        assert response.status_code == 200
        assert response.context["request"].current_organization == company

        url = reverse("companies_views:card", kwargs={"siae_id": company.pk})
        response = self.client.get(url)
        assert response.status_code == 200
        assert response.context["request"].current_organization == company
        assert response.context["siae"] == company

        url = reverse("dashboard:switch_organization")
        response = self.client.post(url, data={"organization_id": related_company.pk})
        assert response.status_code == 302

        url = reverse("dashboard:index")
        response = self.client.get(url)
        assert response.status_code == 200
        assert response.context["request"].current_organization == related_company

        url = reverse("companies_views:card", kwargs={"siae_id": related_company.pk})
        response = self.client.get(url)
        assert response.status_code == 200
        assert response.context["request"].current_organization == related_company
        assert response.context["siae"] == related_company

        url = reverse("companies_views:job_description_list")
        response = self.client.get(url)
        assert response.status_code == 200
        assert response.context["request"].current_organization == related_company

        url = reverse("apply:list_for_siae")
        response = self.client.get(url)
        assert response.status_code == 200
        assert response.context["request"].current_organization == related_company

    def test_can_still_switch_to_inactive_company_during_grace_period(self):
        company = CompanyFactory(with_membership=True)
        user = company.members.first()
        self.client.force_login(user)

        related_company = CompanyPendingGracePeriodFactory(with_membership=True)
        related_company.members.add(user)

        url = reverse("dashboard:index")
        response = self.client.get(url)
        assert response.status_code == 200
        assert response.context["request"].current_organization == company

        url = reverse("dashboard:switch_organization")
        response = self.client.post(url, data={"organization_id": related_company.pk})
        assert response.status_code == 302

        # User has indeed switched.
        url = reverse("dashboard:index")
        response = self.client.get(url)
        assert response.status_code == 200
        assert response.context["request"].current_organization == related_company

    def test_cannot_switch_to_inactive_company_after_grace_period(self):
        company = CompanyFactory(with_membership=True)
        user = company.members.first()
        self.client.force_login(user)

        related_company = CompanyAfterGracePeriodFactory()
        related_company.members.add(user)

        url = reverse("dashboard:index")
        response = self.client.get(url)
        assert response.status_code == 200
        assert response.context["request"].current_organization == company

        # Switching to that company is not even possible in practice because
        # it does not even show up in the menu.
        url = reverse("dashboard:switch_organization")
        response = self.client.post(url, data={"organization_id": related_company.pk})
        assert response.status_code == 404

        # User is still working on the main active company.
        url = reverse("dashboard:index")
        response = self.client.get(url)
        assert response.status_code == 200
        assert response.context["request"].current_organization == company


class EditUserNotificationsTest(TestCase):
    def test_staff_user_not_allowed(self):
        staff_user = ItouStaffFactory()
        self.client.force_login(staff_user)
        url = reverse("dashboard:edit_user_notifications")
        response = self.client.get(url)
        assert response.status_code == 404

    def test_labor_inspector_not_allowed(self):
        labor_inspector = LaborInspectorFactory(membership=True)
        self.client.force_login(labor_inspector)
        url = reverse("dashboard:edit_user_notifications")
        response = self.client.get(url)
        assert response.status_code == 404

    def test_employer_allowed(self):
        employer = EmployerFactory(with_company=True)
        self.client.force_login(employer)
        url = reverse("dashboard:edit_user_notifications")
        # prewarm ContentType cache if needed to avoid extra query
        ContentType.objects.get_for_model(Company)
        with self.assertNumQueries(
            1  # Load django session
            + 1  # Load current user
            + 1  # Load company membership
            + 1  # Load company
            + 2  # Savepoint and release
            + 1  # Load employer notification settings (form init)
            + 3  # Savepoint, update session and release
        ):
            response = self.client.get(url)
        assert response.status_code == 200

    def test_prescriber_allowed(self):
        prescriber = PrescriberFactory(membership=True)
        self.client.force_login(prescriber)
        url = reverse("dashboard:edit_user_notifications")
        # prewarm ContentType cache if needed to avoid extra query
        ContentType.objects.get_for_model(PrescriberOrganization)
        with self.assertNumQueries(
            1  # Load django session
            + 1  # Load current user
            + 1  # Load prescriber membership
            + 2  # Savepoint and release
            + 1  # Load prescriber notification settings (form init)
            + 1  # Check prescriber membership exists for this structure (form init)
            + 3  # Savepoint, update session and release
        ):
            response = self.client.get(url)
        assert response.status_code == 200

    def test_solo_adviser_allowed(self):
        solo_adviser = PrescriberFactory(membership=False)
        self.client.force_login(solo_adviser)
        url = reverse("dashboard:edit_user_notifications")
        # prewarm ContentType cache if needed to avoid extra query
        ContentType.objects.get_for_model(PrescriberOrganization)
        with self.assertNumQueries(
            1  # Load django session
            + 1  # Load current user
            + 1  # Load prescriber membership
            + 2  # Savepoint and release
            + 1  # Load prescriber notification settings (form init)
            + 1  # Check prescriber membership exists for this structure (form init)
            + 3  # Savepoint, update session and release
        ):
            response = self.client.get(url)
        assert response.status_code == 200

    def test_job_seeker_allowed(self):
        job_seeker = JobSeekerFactory()
        self.client.force_login(job_seeker)
        url = reverse("dashboard:edit_user_notifications")
        with self.assertNumQueries(
            1  # Load django session
            + 1  # Load current user
            + 2  # Savepoint and release
            + 1  # Load job seeker notification settings (form init)
            + 3  # Savepoint, update session and release
        ):
            response = self.client.get(url)
        assert response.status_code == 200

    def test_employer_create_update_notification_settings(self):
        employer = EmployerFactory(with_company=True)
        company = employer.company_set.first()
        self.client.force_login(employer)
        url = reverse("dashboard:edit_user_notifications")

        # Fetch available notifications for this user/company
        available_notifications = [
            notification
            for notification in notifications_registry
            if notification(employer, company).is_manageable_by_user()
        ]

        # prewarm ContentType cache if needed to avoid extra query
        ContentType.objects.get_for_model(Company)

        # No notification settings defined by default
        assert not NotificationSettings.objects.exists()
        assert not DisabledNotification.objects.exists()

        with self.assertNumQueries(
            1  # Load django session
            + 1  # Load current user
            + 1  # Load company membership
            + 1  # Load company
            + 2  # Savepoint and release
            + 1  # Load employer notification settings (form init)
            + 1  # Load employer notification settings (form save)
            + 3  # Savepoint, create notification settings and release (form save)
            + 1  # Load notification records (form save)
            + 3  # Savepoint, update session and release
        ):
            response = self.client.post(
                url, data={notification.__name__: "on" for notification in available_notifications}
            )
        assert response.status_code == 302
        assert response["Location"] == "/dashboard/"
        self.assertQuerySetEqual(
            NotificationSettings.objects.all(),
            [
                NotificationSettings.objects.get(
                    user=employer,
                    structure_type=ContentType.objects.get_for_model(company),
                    structure_pk=company.pk,
                    disabled_notifications__isnull=True,
                )
            ],
        )
        assert not DisabledNotification.objects.exists()

        # Update, disable all notifications
        with self.assertNumQueries(
            1  # Load django session
            + 1  # Load current user
            + 1  # Load company membership
            + 1  # Load company
            + 2  # Savepoint and release
            + 1  # Load employer notification settings (form init)
            + 1  # Load employer disabled notification (form init)
            + 1  # Load employer notification settings (form save)
            + len(available_notifications)  # Load disabled notification record (form save)
            + 1  # Load notification records (form save)
            + 1  # Load disabled notifications' notification records (form save)
            + 1  # Bulk insert disabled notifications (form save)
        ):
            # Send data to bind to the form, otherwise is_valid() returns False
            response = self.client.post(url, {"foo": "bar"})
        assert response.status_code == 302
        assert response["Location"] == "/dashboard/"
        self.assertQuerySetEqual(
            NotificationSettings.objects.all(),
            [
                NotificationSettings.objects.annotate(Count("disabled_notifications")).get(
                    user=employer,
                    structure_type=ContentType.objects.get_for_model(company),
                    structure_pk=company.pk,
                    disabled_notifications__count=len(available_notifications),
                )
            ],
        )
        assert DisabledNotification.objects.count() == len(available_notifications)

    def test_prescriber_create_update_notification_settings(self):
        prescriber = PrescriberFactory(membership=True)
        organization = prescriber.prescriberorganization_set.first()
        self.client.force_login(prescriber)
        url = reverse("dashboard:edit_user_notifications")

        # Fetch available notifications for this user/organization
        available_notifications = [
            notification
            for notification in notifications_registry
            if notification(prescriber, organization).is_manageable_by_user()
        ]

        # prewarm ContentType cache if needed to avoid extra query
        ContentType.objects.get_for_model(PrescriberOrganization)

        # No notification settings defined by default
        assert not NotificationSettings.objects.exists()
        assert not DisabledNotification.objects.exists()

        with self.assertNumQueries(
            1  # Load django session
            + 1  # Load current user
            + 1  # Load organization membership
            + 2  # Savepoint and release
            + 1  # Load prescriber notification settings (form init)
            + 1  # Load prescriber notification settings (form save)
            + 3  # Savepoint, create notification settings and release (form save)
            + 1  # Load notification records (form save)
            + 3  # Savepoint, update session and release
        ):
            response = self.client.post(
                url, data={notification.__name__: "on" for notification in available_notifications}
            )
        assert response.status_code == 302
        assert response["Location"] == "/dashboard/"
        self.assertQuerySetEqual(
            NotificationSettings.objects.all(),
            [
                NotificationSettings.objects.get(
                    user=prescriber,
                    structure_type=ContentType.objects.get_for_model(organization),
                    structure_pk=organization.pk,
                    disabled_notifications__isnull=True,
                )
            ],
        )
        assert not DisabledNotification.objects.exists()

        # Update, disable all notifications
        with self.assertNumQueries(
            1  # Load django session
            + 1  # Load current user
            + 1  # Load organization membership
            + 2  # Savepoint and release
            + 1  # Load prescriber notification settings (form init)
            + 1  # Load prescriber disabled notification (form init)
            + 1  # Load prescriber notification settings (form save)
            + len(available_notifications)  # Load disabled notification record (form save)
            + 1  # Load notification records (form save)
            + 1  # Load disabled notifications' notification records (form save)
            + 1  # Bulk insert disabled notifications (form save)
        ):
            # Send data to bind to the form, otherwise is_valid() returns False
            response = self.client.post(url, {"foo": "bar"})
        assert response.status_code == 302
        assert response["Location"] == "/dashboard/"
        self.assertQuerySetEqual(
            NotificationSettings.objects.all(),
            [
                NotificationSettings.objects.annotate(Count("disabled_notifications")).get(
                    user=prescriber,
                    structure_type=ContentType.objects.get_for_model(organization),
                    structure_pk=organization.pk,
                    disabled_notifications__count=len(available_notifications),
                )
            ],
        )
        assert DisabledNotification.objects.count() == len(available_notifications)

    def test_solo_adviser_create_update_notification_settings(self):
        solo_adviser = PrescriberFactory(membership=False)
        self.client.force_login(solo_adviser)
        url = reverse("dashboard:edit_user_notifications")

        # Fetch available notifications for this user
        available_notifications = [
            notification
            for notification in notifications_registry
            if notification(solo_adviser).is_manageable_by_user()
        ]

        # No notification settings defined by default
        assert not NotificationSettings.objects.exists()
        assert not DisabledNotification.objects.exists()

        with self.assertNumQueries(
            1  # Load django session
            + 1  # Load current user
            + 1  # Load organization membership
            + 2  # Savepoint and release
            + 1  # Load prescriber notification settings (form init)
            + 1  # Load prescriber notification settings (form save)
            + 3  # Savepoint, create notification settings and release (form save)
            + 1  # Load notification records (form save)
        ):
            response = self.client.post(
                url, data={notification.__name__: "on" for notification in available_notifications}
            )
        assert response.status_code == 302
        assert response["Location"] == "/dashboard/"
        self.assertQuerySetEqual(
            NotificationSettings.objects.all(),
            [
                NotificationSettings.objects.get(
                    user=solo_adviser,
                    structure_type=None,
                    structure_pk=None,
                    disabled_notifications__isnull=True,
                )
            ],
        )
        assert not DisabledNotification.objects.exists()

        # Update, disable all notifications
        with self.assertNumQueries(
            1  # Load django session
            + 1  # Load current user
            + 1  # Load organization membership
            + 2  # Savepoint and release
            + 1  # Load prescriber notification settings (form init)
            + 1  # Load prescriber disabled notification (form init)
            + 1  # Load prescriber notification settings (form save)
            + len(available_notifications)  # Load disabled notification record (form save)
            + 1  # Load notification records (form save)
            + 1  # Load disabled notifications' notification records (form save)
            + 1  # Bulk insert disabled notifications (form save)
        ):
            # Send data to bind to the form, otherwise is_valid() returns False
            response = self.client.post(url, {"foo": "bar"})
        assert response.status_code == 302
        assert response["Location"] == "/dashboard/"
        self.assertQuerySetEqual(
            NotificationSettings.objects.all(),
            [
                NotificationSettings.objects.annotate(Count("disabled_notifications")).get(
                    user=solo_adviser,
                    structure_type=None,
                    structure_pk=None,
                    disabled_notifications__count=len(available_notifications),
                )
            ],
        )
        assert DisabledNotification.objects.count() == len(available_notifications)

    def test_job_seeker_create_update_notification_settings(self):
        job_seeker = JobSeekerFactory()
        self.client.force_login(job_seeker)
        url = reverse("dashboard:edit_user_notifications")

        # Fetch available notifications for this user
        available_notifications = [
            notification for notification in notifications_registry if notification(job_seeker).is_manageable_by_user()
        ]

        # No notification settings defined by default
        assert not NotificationSettings.objects.exists()
        assert not DisabledNotification.objects.exists()

        with self.assertNumQueries(
            1  # Load django session
            + 1  # Load current user
            + 2  # Savepoint and release
            + 1  # Load job seeker notification settings (form init)
            + 1  # Load job seeker notification settings (form save)
            + 3  # Savepoint, create notification settings and release (form save)
            + 1  # Load notification records (form save)
        ):
            response = self.client.post(
                url, data={notification.__name__: "on" for notification in available_notifications}
            )
        assert response.status_code == 302
        assert response["Location"] == "/dashboard/"
        self.assertQuerySetEqual(
            NotificationSettings.objects.all(),
            [
                NotificationSettings.objects.get(
                    user=job_seeker,
                    structure_type=None,
                    structure_pk=None,
                    disabled_notifications__isnull=True,
                )
            ],
        )
        assert not DisabledNotification.objects.exists()

        # Update, disable all notifications
        with self.assertNumQueries(
            1  # Load django session
            + 1  # Load current user
            + 2  # Savepoint and release
            + 1  # Load job seeker notification settings (form init)
            + 1  # Load job seeker disabled notification (form init)
            + 1  # Load job seeker notification settings (form save)
            + len(available_notifications)  # Load disabled notification record (form save)
            + 1  # Load notification records (form save)
            + 1  # Load disabled notifications' notification records (form save)
            + 1  # Bulk insert disabled notifications (form save)
        ):
            # Send data to bind to the form, otherwise is_valid() returns False
            response = self.client.post(url, {"foo": "bar"})
        assert response.status_code == 302
        assert response["Location"] == "/dashboard/"
        self.assertQuerySetEqual(
            NotificationSettings.objects.all(),
            [
                NotificationSettings.objects.annotate(Count("disabled_notifications")).get(
                    user=job_seeker,
                    structure_type=None,
                    structure_pk=None,
                    disabled_notifications__count=len(available_notifications),
                )
            ],
        )
        assert DisabledNotification.objects.count() == len(available_notifications)


class SwitchOrganizationTest(TestCase):
    def test_not_allowed_user(self):
        organization = prescribers_factories.PrescriberOrganizationFactory()

        for user in (
            JobSeekerFactory(),
            PrescriberFactory(),
        ):
            self.client.force_login(user)
            url = reverse("dashboard:switch_organization")
            response = self.client.post(url, data={"organization_id": organization.pk})
            assert response.status_code == 404

    def test_usual_case(self):
        url = reverse("dashboard:switch_organization")

        user = PrescriberFactory()
        orga1 = prescribers_factories.PrescriberMembershipFactory(user=user).organization
        orga2 = prescribers_factories.PrescriberMembershipFactory(user=user).organization
        self.client.force_login(user)

        response = self.client.post(url, data={"organization_id": orga1.pk})
        assert response.status_code == 302

        response = self.client.get(reverse("dashboard:index"))
        assert response.status_code == 200
        assert response.context["request"].current_organization == orga1

        response = self.client.post(url, data={"organization_id": orga2.pk})
        assert response.status_code == 302

        response = self.client.get(reverse("dashboard:index"))
        assert response.status_code == 200
        assert response.context["request"].current_organization == orga2


class SwitchInstitutionTest(TestCase):
    def test_not_allowed_user(self):
        institution = InstitutionFactory()

        for user in (
            JobSeekerFactory(),
            # Create a user with other membership
            # (otherwise the middleware intercepts labor inspector without any membership)
            InstitutionMembershipFactory().user,
        ):
            self.client.force_login(user)
            url = reverse("dashboard:switch_organization")
            response = self.client.post(url, data={"organization_id": institution.pk})
            assert response.status_code == 404

    def test_usual_case(self):
        url = reverse("dashboard:switch_organization")

        user = LaborInspectorFactory()
        institution1 = InstitutionMembershipFactory(user=user).institution
        institution2 = InstitutionMembershipFactory(user=user).institution
        self.client.force_login(user)

        response = self.client.post(url, data={"organization_id": institution1.pk})
        assert response.status_code == 302

        response = self.client.get(reverse("dashboard:index"))
        assert response.status_code == 200
        assert response.context["request"].current_organization == institution1

        response = self.client.post(url, data={"organization_id": institution2.pk})
        assert response.status_code == 302

        response = self.client.get(reverse("dashboard:index"))
        assert response.status_code == 200
        assert response.context["request"].current_organization == institution2


TOKEN_MENU_STR = "Accès aux APIs"
API_TOKEN_URL = reverse_lazy("dashboard:api_token")


@pytest.mark.ignore_unknown_variable_template_error("matomo_event_attrs")
def test_api_token_view_for_company_admin(client):
    employer = CompanyMembershipFactory().user
    client.force_login(employer)

    assert not Token.objects.exists()

    response = client.get(reverse("dashboard:index"))

    assertContains(response, TOKEN_MENU_STR)
    assertContains(response, API_TOKEN_URL)

    response = client.get(API_TOKEN_URL)
    assertContains(response, "Vous n'avez pas encore de token d'API")
    assertContains(response, "Créer un token d'API")

    response = client.post(API_TOKEN_URL)
    token = Token.objects.filter(user=employer).get()
    assertContains(response, token.key)
    assertContains(response, "Copier le token")

    # Check multi-posts
    response = client.post(API_TOKEN_URL)
    assert Token.objects.filter(user=employer).count() == 1


def test_api_token_view_for_non_company_admin(client):
    company = CompanyFactory(with_membership=True)
    employer = CompanyMembershipFactory(is_admin=False, company=company).user
    client.force_login(employer)

    assert not Token.objects.exists()

    response = client.get(reverse("dashboard:index"))

    assertNotContains(response, TOKEN_MENU_STR)
    assertNotContains(response, API_TOKEN_URL)

    response = client.get(API_TOKEN_URL)
    assert response.status_code == 403


@respx.mock
@override_inclusion_connect_settings
def test_prescriber_using_django_has_to_activate_ic_account(client):
    user = PrescriberFactory(identity_provider=IdentityProvider.DJANGO, email=OIDC_USERINFO["email"])
    client.force_login(user)
    url = reverse("dashboard:index")
    response = client.get(url, follow=True)
    activate_ic_account_url = reverse("dashboard:activate_ic_account")
    assertRedirects(response, activate_ic_account_url)
    params = {
        "user_kind": UserKind.PRESCRIBER,
        "previous_url": activate_ic_account_url,
        "user_email": user.email,
    }
    url = escape(f"{reverse('inclusion_connect:activate_account')}?{urlencode(params)}")
    assertContains(response, url + '"')
    response = mock_oauth_dance(
        client,
        UserKind.PRESCRIBER,
        previous_url=activate_ic_account_url,
    )
    user.refresh_from_db()
    assert user.identity_provider == IdentityProvider.INCLUSION_CONNECT


@respx.mock
@override_inclusion_connect_settings
def test_employer_using_django_has_to_activate_ic_account(client):
    user = EmployerFactory(with_company=True, identity_provider=IdentityProvider.DJANGO, email=OIDC_USERINFO["email"])
    client.force_login(user)
    url = reverse("dashboard:index")
    response = client.get(url, follow=True)
    activate_ic_account_url = reverse("dashboard:activate_ic_account")
    assertRedirects(response, activate_ic_account_url)
    params = {
        "user_kind": UserKind.EMPLOYER,
        "previous_url": activate_ic_account_url,
        "user_email": user.email,
    }
    url = escape(f"{reverse('inclusion_connect:activate_account')}?{urlencode(params)}")
    assertContains(response, url + '"')
    response = mock_oauth_dance(
        client,
        UserKind.EMPLOYER,
        previous_url=activate_ic_account_url,
    )
    user.refresh_from_db()
    assert user.identity_provider == IdentityProvider.INCLUSION_CONNECT


@pytest.mark.parametrize(
    "factory,expected",
    [
        pytest.param(JobSeekerWithAddressFactory, assertNotContains, id="JobSeeker"),
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
