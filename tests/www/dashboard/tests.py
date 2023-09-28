from datetime import date, datetime
from functools import partial
from urllib.parse import urlencode

import pytest
import respx
from allauth.account.models import EmailAddress, EmailConfirmationHMAC
from dateutil.relativedelta import relativedelta
from django.conf import settings
from django.core import mail
from django.test import override_settings
from django.urls import reverse
from django.utils import timezone
from django.utils.html import escape
from freezegun import freeze_time
from pytest_django.asserts import assertContains, assertNotContains, assertRedirects
from rest_framework.authtoken.models import Token

from itou.employee_record.enums import Status
from itou.institutions.enums import InstitutionKind
from itou.job_applications.notifications import (
    NewQualifiedJobAppEmployersNotification,
    NewSpontaneousJobAppEmployersNotification,
)
from itou.prescribers.enums import PrescriberOrganizationKind
from itou.prescribers.models import PrescriberOrganization
from itou.siae_evaluations import enums as evaluation_enums
from itou.siae_evaluations.constants import CAMPAIGN_VIEWABLE_DURATION
from itou.siae_evaluations.models import Sanctions
from itou.siaes.enums import SiaeKind
from itou.users.enums import IdentityProvider, LackOfNIRReason, UserKind
from itou.users.models import User
from itou.utils import constants as global_constants
from itou.utils.models import InclusiveDateRange
from itou.utils.templatetags.format_filters import format_approval_number, format_siret
from itou.www.dashboard.forms import EditUserEmailForm
from tests.approvals.factories import ApprovalFactory, ProlongationRequestFactory
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
from tests.siaes.factories import (
    SiaeAfterGracePeriodFactory,
    SiaeFactory,
    SiaeMembershipFactory,
    SiaePendingGracePeriodFactory,
    SiaeWithMembershipAndJobsFactory,
)
from tests.users.factories import DEFAULT_PASSWORD, JobSeekerFactory, PrescriberFactory, SiaeStaffFactory
from tests.utils.test import TestCase, parse_response_to_soup


pytestmark = pytest.mark.ignore_template_errors


class DashboardViewTest(TestCase):
    NO_PRESCRIBER_ORG_MSG = "Votre compte utilisateur n’est rattaché à aucune organisation."
    NO_PRESCRIBER_ORG_FOR_PE_MSG = (
        "Votre compte utilisateur n’est rattaché à aucune agence Pôle emploi, "
        "par conséquent vous ne pouvez pas bénéficier du statut de prescripteur habilité."
    )

    def test_dashboard(self):
        siae = SiaeFactory(with_membership=True)
        user = siae.members.first()
        self.client.force_login(user)

        url = reverse("dashboard:index")
        response = self.client.get(url)
        assert response.status_code == 200

    def test_user_with_inactive_siae_can_still_login_during_grace_period(self):
        siae = SiaePendingGracePeriodFactory()
        user = SiaeStaffFactory()
        siae.members.add(user)
        self.client.force_login(user)

        url = reverse("dashboard:index")
        response = self.client.get(url)
        assert response.status_code == 200

    def test_user_with_inactive_siae_cannot_login_after_grace_period(self):
        siae = SiaeAfterGracePeriodFactory()
        user = SiaeStaffFactory()
        siae.members.add(user)
        self.client.force_login(user)

        url = reverse("dashboard:index")
        response = self.client.get(url, follow=True)
        assert response.status_code == 200
        last_url = response.redirect_chain[-1][0]
        assert last_url == reverse("account_logout")

        expected_message = "votre compte n&#x27;est malheureusement plus actif"
        self.assertContains(response, expected_message)

    def test_dashboard_eiti(self):
        siae = SiaeFactory(kind=SiaeKind.EITI, with_membership=True)
        user = siae.members.first()
        self.client.force_login(user)

        url = reverse("dashboard:index")
        response = self.client.get(url)
        self.assertContains(response, format_siret(siae.siret))

    def test_dashboard_for_prescriber(self):
        prescriber_organization = prescribers_factories.PrescriberOrganizationWithMembershipFactory()
        self.client.force_login(prescriber_organization.members.first())

        response = self.client.get(reverse("dashboard:index"))
        self.assertContains(response, format_siret(prescriber_organization.siret))

    def test_dashboard_displays_asp_badge(self):
        siae = SiaeFactory(kind=SiaeKind.EI, with_membership=True)
        other_siae = SiaeFactory(kind=SiaeKind.ETTI, with_membership=True)
        last_siae = SiaeFactory(kind=SiaeKind.ETTI, with_membership=True)

        user = siae.members.first()
        user.siae_set.add(other_siae)
        user.siae_set.add(last_siae)

        self.client.force_login(user)

        url = reverse("dashboard:index")
        response = self.client.get(url)
        self.assertContains(response, "Gérer les fiches salarié")
        self.assertNotContains(response, "badge-danger")
        assert response.context["num_rejected_employee_records"] == 0

        # create rejected job applications
        job_application = JobApplicationFactory(with_approval=True, to_siae=siae)
        EmployeeRecordFactory(job_application=job_application, status=Status.REJECTED)
        # You can't create 2 employee records with the same job application
        # Factories were allowing it until a recent fix was applied
        job_application = JobApplicationFactory(with_approval=True, to_siae=siae)
        EmployeeRecordFactory(job_application=job_application, status=Status.REJECTED)

        other_job_application = JobApplicationFactory(with_approval=True, to_siae=other_siae)
        EmployeeRecordFactory(job_application=other_job_application, status=Status.REJECTED)

        session = self.client.session

        # select the first SIAE's in the session
        session[global_constants.ITOU_SESSION_CURRENT_ORGANIZATION_KEY] = siae.pk
        session.save()
        response = self.client.get(url)
        self.assertContains(response, "badge-danger")
        assert response.context["num_rejected_employee_records"] == 2

        # select the second SIAE's in the session
        session[global_constants.ITOU_SESSION_CURRENT_ORGANIZATION_KEY] = other_siae.pk
        session.save()
        response = self.client.get(url)
        self.assertContains(response, "badge-danger")
        assert response.context["num_rejected_employee_records"] == 1

        # select the third SIAE's in the session
        session[global_constants.ITOU_SESSION_CURRENT_ORGANIZATION_KEY] = last_siae.pk
        session.save()
        response = self.client.get(url)
        assert response.status_code == 200
        assert response.context["num_rejected_employee_records"] == 0

    def test_dashboard_applications_to_process(self):
        non_geiq_url = reverse("apply:list_for_siae") + "?states=new&amp;states=processing"
        geiq_url = non_geiq_url + "&amp;states=prior_to_hire"

        # Not a GEIQ
        user = SiaeFactory(kind=SiaeKind.ACI, with_membership=True).members.first()
        self.client.force_login(user)
        response = self.client.get(reverse("dashboard:index"))
        self.assertContains(response, non_geiq_url)
        self.assertNotContains(response, geiq_url)

        # GEIQ
        user = SiaeFactory(kind=SiaeKind.GEIQ, with_membership=True).members.first()
        self.client.force_login(user)
        response = self.client.get(reverse("dashboard:index"))

        self.assertContains(response, geiq_url)

    def test_dashboard_agreements_and_job_postings(self):
        for kind in [
            SiaeKind.AI,
            SiaeKind.EI,
            SiaeKind.EITI,
            SiaeKind.ACI,
            SiaeKind.ETTI,
        ]:
            with self.subTest(f"should display when siae_kind={kind}"):
                siae = SiaeFactory(kind=kind, with_membership=True)
                user = siae.members.first()
                self.client.force_login(user)

                response = self.client.get(reverse("dashboard:index"))
                self.assertContains(response, "Prolonger/suspendre un agrément émis par Pôle emploi")

        for kind in [SiaeKind.EA, SiaeKind.EATT, SiaeKind.GEIQ, SiaeKind.OPCS]:
            with self.subTest(f"should not display when siae_kind={kind}"):
                siae = SiaeFactory(kind=kind, with_membership=True)
                user = siae.members.first()
                self.client.force_login(user)

                response = self.client.get(reverse("dashboard:index"))
                self.assertNotContains(response, "Prolonger/suspendre un agrément émis par Pôle emploi")
                if kind != SiaeKind.GEIQ:
                    self.assertNotContains(response, "Déclarer une embauche")

    def test_dashboard_job_applications(self):
        HIRE_LINK_LABEL = "Déclarer une embauche"
        APPLICATION_SAVE_LABEL = "Enregistrer une candidature"
        display_kinds = [
            SiaeKind.AI,
            SiaeKind.EI,
            SiaeKind.EITI,
            SiaeKind.ACI,
            SiaeKind.ETTI,
            SiaeKind.GEIQ,
        ]
        for kind in display_kinds:
            with self.subTest(f"should display when siae_kind={kind}"):
                siae = SiaeFactory(kind=kind, with_membership=True)
                user = siae.members.first()
                self.client.force_login(user)

                response = self.client.get(reverse("dashboard:index"))
                self.assertContains(response, APPLICATION_SAVE_LABEL)
                self.assertContains(response, reverse("apply:start", kwargs={"siae_pk": siae.pk}))
                self.assertContains(response, HIRE_LINK_LABEL)
                self.assertContains(response, reverse("apply:check_nir_for_hire", kwargs={"siae_pk": siae.pk}))

        for kind in set(SiaeKind) - set(display_kinds):
            with self.subTest(f"should not display when siae_kind={kind}"):
                siae = SiaeFactory(kind=kind, with_membership=True)
                user = siae.members.first()
                self.client.force_login(user)
                response = self.client.get(reverse("dashboard:index"))
                self.assertNotContains(response, APPLICATION_SAVE_LABEL)
                self.assertNotContains(response, reverse("apply:start", kwargs={"siae_pk": siae.pk}))
                self.assertNotContains(response, HIRE_LINK_LABEL)
                self.assertNotContains(response, reverse("apply:check_nir_for_hire", kwargs={"siae_pk": siae.pk}))

    def test_dashboard_agreements_with_suspension_sanction(self):
        siae = SiaeFactory(subject_to_eligibility=True, with_membership=True)
        Sanctions.objects.create(
            evaluated_siae=EvaluatedSiaeFactory(siae=siae),
            suspension_dates=InclusiveDateRange(timezone.localdate() - relativedelta(days=1)),
        )

        user = siae.members.first()
        self.client.force_login(user)

        response = self.client.get(reverse("dashboard:index"))
        self.assertContains(response, "Prolonger/suspendre un agrément émis par Pôle emploi")
        # Check that "Déclarer une embauche" is here, but not its matching link
        self.assertContains(response, "Déclarer une embauche")
        self.assertNotContains(response, reverse("apply:start", kwargs={"siae_pk": siae.pk}))
        # Check that the button tooltip is there
        self.assertContains(
            response,
            "Vous ne pouvez pas déclarer d'embauche suite aux mesures prises dans le cadre du contrôle a posteriori",
        )

    def test_dashboard_can_create_siae_antenna(self):
        for kind in SiaeKind:
            with self.subTest(kind=kind):
                siae = SiaeFactory(kind=kind, with_membership=True, membership__is_admin=True)
                user = siae.members.get()

                self.client.force_login(user)
                response = self.client.get(reverse("dashboard:index"))

                if user.can_create_siae_antenna(siae):
                    self.assertContains(response, "Créer/rejoindre une autre structure")
                else:
                    self.assertNotContains(response, "Créer/rejoindre une autre structure")

    def test_dashboard_siae_stats(self):
        membershipfactory = SiaeMembershipFactory()
        self.client.force_login(membershipfactory.user)
        response = self.client.get(reverse("dashboard:index"))
        self.assertContains(response, "Voir les données de candidatures de mes structures")
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

        response = self.client.get(reverse("dashboard:index"))
        self.assertNotContains(response, "Contrôle a posteriori")
        self.assertNotContains(response, reverse("siae_evaluations_views:samples_selection"))

        evaluation_campaign = EvaluationCampaignFactory(institution=institution)
        response = self.client.get(reverse("dashboard:index"))
        self.assertContains(response, "Contrôle a posteriori")
        self.assertContains(response, IN_PROGRESS_LINK)
        self.assertContains(response, reverse("siae_evaluations_views:samples_selection"))
        self.assertNotContains(
            response,
            reverse(
                "siae_evaluations_views:institution_evaluated_siae_list",
                kwargs={"evaluation_campaign_pk": evaluation_campaign.pk},
            ),
        )

        evaluation_campaign.evaluations_asked_at = timezone.now()
        evaluation_campaign.save(update_fields=["evaluations_asked_at"])
        response = self.client.get(reverse("dashboard:index"))
        self.assertContains(response, "Contrôle a posteriori")
        self.assertNotContains(response, reverse("siae_evaluations_views:samples_selection"))
        self.assertContains(response, IN_PROGRESS_LINK)
        self.assertContains(
            response,
            reverse(
                "siae_evaluations_views:institution_evaluated_siae_list",
                kwargs={"evaluation_campaign_pk": evaluation_campaign.pk},
            ),
        )

        evaluation_campaign.ended_at = timezone.now()
        evaluation_campaign.save(update_fields=["ended_at"])
        response = self.client.get(reverse("dashboard:index"))
        self.assertContains(response, "Contrôle a posteriori")
        self.assertNotContains(response, IN_PROGRESS_LINK)
        self.assertNotContains(response, reverse("siae_evaluations_views:samples_selection"))
        self.assertContains(
            response,
            reverse(
                "siae_evaluations_views:institution_evaluated_siae_list",
                kwargs={"evaluation_campaign_pk": evaluation_campaign.pk},
            ),
        )

        evaluation_campaign.ended_at = timezone.now() - CAMPAIGN_VIEWABLE_DURATION
        evaluation_campaign.save(update_fields=["ended_at"])
        response = self.client.get(reverse("dashboard:index"))
        self.assertNotContains(response, IN_PROGRESS_LINK)
        self.assertNotContains(response, "Contrôle a posteriori")
        self.assertNotContains(response, reverse("siae_evaluations_views:samples_selection"))
        self.assertNotContains(
            response,
            reverse(
                "siae_evaluations_views:institution_evaluated_siae_list",
                kwargs={"evaluation_campaign_pk": evaluation_campaign.pk},
            ),
        )

    def test_dashboard_siae_evaluation_campaign_notifications(self):
        membership = SiaeMembershipFactory()
        evaluated_siae_with_final_decision = EvaluatedSiaeFactory(
            evaluation_campaign__name="Final decision reached",
            complete=True,
            job_app__criteria__review_state=evaluation_enums.EvaluatedJobApplicationsState.REFUSED_2,
            siae=membership.siae,
            notified_at=timezone.now(),
            notification_reason=evaluation_enums.EvaluatedSiaeNotificationReason.INVALID_PROOF,
            notification_text="A envoyé une photo de son chat. Séparé de son chat pendant une journée.",
        )
        EvaluatedSiaeFactory(
            evaluation_campaign__name="In progress",
            siae=membership.siae,
            evaluation_campaign__evaluations_asked_at=timezone.now(),
        )
        EvaluatedSiaeFactory(
            evaluation_campaign__name="Not notified",
            complete=True,
            job_app__criteria__review_state=evaluation_enums.EvaluatedJobApplicationsState.REFUSED_2,
            siae=membership.siae,
        )
        evaluated_siae_campaign_closed = EvaluatedSiaeFactory(
            evaluation_campaign__name="Just closed",
            complete=True,
            siae=membership.siae,
            evaluation_campaign__ended_at=timezone.now() - relativedelta(days=4),
            notified_at=timezone.now(),
            notification_reason=evaluation_enums.EvaluatedSiaeNotificationReason.MISSING_PROOF,
            notification_text="Journée de formation.",
        )
        # Long closed.
        EvaluatedSiaeFactory(
            evaluation_campaign__name="Long closed",
            complete=True,
            siae=membership.siae,
            evaluation_campaign__ended_at=timezone.now() - CAMPAIGN_VIEWABLE_DURATION,
            notified_at=timezone.now(),
            notification_reason=evaluation_enums.EvaluatedSiaeNotificationReason.INVALID_PROOF,
            notification_text="A envoyé une photo de son chat.",
        )

        self.client.force_login(membership.user)
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
                <span>Just closed</span>
            </a>
            """,
            html=True,
            count=1,
        )
        self.assertNotContains(response, "Long closed")
        self.assertNotContains(response, "Not notified")
        self.assertNotContains(response, "In progress")

    def test_dashboard_siae_evaluations_siae_access(self):
        # preset for incoming new pages
        siae = SiaeFactory(with_membership=True)
        user = siae.members.first()
        self.client.force_login(user)

        response = self.client.get(reverse("dashboard:index"))
        self.assertNotContains(response, "Contrôle a posteriori")

        fake_now = timezone.now()
        evaluated_siae = EvaluatedSiaeFactory(siae=siae, evaluation_campaign__evaluations_asked_at=fake_now)
        response = self.client.get(reverse("dashboard:index"))
        self.assertContains(response, "Contrôle a posteriori")
        TODO_BADGE = (
            '<span class="badge badge-xs badge-pill badge-warning-lighter text-warning">'
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
        user = JobSeekerFactory()
        self.client.force_login(user)

        response = self.client.get(reverse("dashboard:index"))
        self.assertNotContains(response, "DORA")

    def test_dora_card_is_shown_for_siae(self):
        siae = SiaeFactory(with_membership=True)
        self.client.force_login(siae.members.first())

        response = self.client.get(reverse("dashboard:index"))
        self.assertContains(response, "DORA")
        self.assertContains(response, "Consulter les services d'insertion de votre territoire")
        self.assertContains(response, "Référencer vos services")
        self.assertContains(response, "Suggérer un service partenaire")

    def test_dora_card_is_shown_for_prescriber(self):
        prescriber_organization = prescribers_factories.PrescriberOrganizationWithMembershipFactory()
        self.client.force_login(prescriber_organization.members.first())

        response = self.client.get(reverse("dashboard:index"))
        self.assertContains(response, "DORA")
        self.assertContains(response, "Consulter les services d'insertion de votre territoire")
        self.assertContains(response, "Référencer vos services")
        self.assertContains(response, "Suggérer un service partenaire")

    def test_dora_banner_is_not_shown_for_job_seeker(self):
        user = JobSeekerFactory()
        self.client.force_login(user)

        response = self.client.get(reverse("dashboard:index"))
        self.assertNotContains(response, "Consultez l’offre de service de vos partenaires")
        self.assertNotContains(response, "Donnez de la visibilité à votre offre d’insertion")

    def test_dora_banner_is_shown_for_siae(self):
        for department in ["91", "26", "74", "30"]:
            with self.subTest(department=department):
                siae = SiaeFactory(
                    with_membership=True,
                    department=department,
                    membership__user__identity_provider=IdentityProvider.INCLUSION_CONNECT,
                )
                self.client.force_login(siae.members.first())

                response = self.client.get(reverse("dashboard:index"))
                self.assertContains(response, "Donnez de la visibilité à votre offre d’insertion")

    def test_dora_banner_is_shown_for_prescriber(self):
        for department in ["91", "26", "74", "30"]:
            with self.subTest(department=department):
                prescriber_organization = prescribers_factories.PrescriberOrganizationWithMembershipFactory(
                    department=department,
                    membership__user__identity_provider=IdentityProvider.INCLUSION_CONNECT,
                )
                self.client.force_login(prescriber_organization.members.first())

                response = self.client.get(reverse("dashboard:index"))
                self.assertContains(response, "Consultez l’offre de service de vos partenaires")

    def test_dora_banner_is_not_shown_for_other_department(self):
        siae = SiaeFactory(with_membership=True, department="01")
        self.client.force_login(siae.members.first())

        response = self.client.get(reverse("dashboard:index"))
        self.assertNotContains(response, "Donnez de la visibilité à votre offre d’insertion")

        prescriber_organization = prescribers_factories.PrescriberOrganizationWithMembershipFactory(
            department="01",
        )
        self.client.force_login(prescriber_organization.members.first())

        response = self.client.get(reverse("dashboard:index"))
        self.assertNotContains(response, "Consultez l’offre de service de vos partenaires")

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
        self.assertNotContains(response, "Votre compte utilisateur n’est rattaché à aucune organisation.")

        org_1.members.remove(prescriber)
        response = self.client.get(reverse("dashboard:index"))
        self.assertNotContains(response, "Votre compte utilisateur n’est rattaché à aucune organisation.")

    def test_dashboard_prescriber_suspend_link(self):
        user = JobSeekerFactory()
        self.client.force_login(user)
        response = self.client.get(reverse("dashboard:index"))
        self.assertNotContains(response, "Suspendre un PASS IAE")

        siae = SiaeFactory(with_membership=True)
        user = siae.members.first()
        self.client.force_login(user)
        response = self.client.get(reverse("dashboard:index"))
        self.assertNotContains(response, "Suspendre un PASS IAE")

        membershipfactory = InstitutionMembershipFactory()
        user = membershipfactory.user
        self.client.force_login(user)
        response = self.client.get(reverse("dashboard:index"))
        self.assertNotContains(response, "Suspendre un PASS IAE")

        prescriber_org = prescribers_factories.PrescriberOrganizationWithMembershipFactory(
            kind=PrescriberOrganizationKind.CAP_EMPLOI
        )
        prescriber = prescriber_org.members.first()
        self.client.force_login(prescriber)
        response = self.client.get(reverse("dashboard:index"))
        self.assertNotContains(response, "Suspendre un PASS IAE")

        prescriber_org_pe = prescribers_factories.PrescriberOrganizationWithMembershipFactory(
            authorized=True, kind=PrescriberOrganizationKind.PE
        )
        prescriber_pe = prescriber_org_pe.members.first()
        self.client.force_login(prescriber_pe)
        response = self.client.get(reverse("dashboard:index"))
        self.assertContains(response, "Suspendre un PASS IAE")

    @freeze_time("2022-09-15")
    def test_dashboard_access_by_a_jobseeker(self):
        approval = ApprovalFactory(start_at=datetime(2022, 6, 21), end_at=datetime(2022, 12, 6))
        self.client.force_login(approval.user)
        url = reverse("dashboard:index")
        response = self.client.get(url)
        self.assertContains(response, "Numéro de PASS IAE")
        self.assertContains(response, format_approval_number(approval))
        self.assertContains(response, "Date de début : 21/06/2022")
        self.assertContains(response, "Nombre de jours restants sur le PASS IAE : 82 jours")
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


class EditUserInfoViewTest(InclusionConnectBaseTestCase):
    def setUp(self):
        super().setUp()
        self.NIR_UPDATE_TALLY_LINK_LABEL = "Demander la correction du numéro de sécurité sociale"

    @override_settings(TALLY_URL="https://tally.so")
    def test_edit_with_nir(self):
        user = JobSeekerFactory()
        self.client.force_login(user)
        url = reverse("dashboard:edit_user_info")
        response = self.client.get(url)
        # There's a specific view to edit the email so we don't show it here
        self.assertNotContains(response, "Adresse électronique")
        # Check that the NIR field is disabled
        self.assertContains(response, 'disabled id="id_nir"')
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
            "first_name": "Bob",
            "last_name": "Saint Clar",
            "birthdate": "20/12/1978",
            "phone": "0610203050",
            "lack_of_pole_emploi_id_reason": user.REASON_NOT_REGISTERED,
            "address_line_1": "10, rue du Gué",
            "address_line_2": "Sous l'escalier",
            "post_code": "35400",
            "city": "Saint-Malo",
        }
        response = self.client.post(url, data=post_data)
        assert response.status_code == 302

        user = User.objects.get(id=user.id)
        assert user.first_name == post_data["first_name"]
        assert user.last_name == post_data["last_name"]
        assert user.phone == post_data["phone"]
        assert user.birthdate.strftime("%d/%m/%Y") == post_data["birthdate"]
        assert user.address_line_1 == post_data["address_line_1"]
        assert user.address_line_2 == post_data["address_line_2"]
        assert user.post_code == post_data["post_code"]
        assert user.city == post_data["city"]

        # Ensure that the job seeker cannot edit email here.
        assert user.email != post_data["email"]

    def test_edit_with_lack_of_nir_reason(self):
        user = JobSeekerFactory(nir="", lack_of_nir_reason=LackOfNIRReason.TEMPORARY_NUMBER)
        self.client.force_login(user)
        url = reverse("dashboard:edit_user_info")
        response = self.client.get(url)
        # Check that the NIR field is disabled (it can be reenabled via lack_of_nir check box)
        self.assertContains(response, 'disabled id="id_nir"')
        self.assertContains(response, LackOfNIRReason.TEMPORARY_NUMBER.label, html=True)
        self.assertNotContains(response, self.NIR_UPDATE_TALLY_LINK_LABEL, html=True)

        NEW_NIR = "1 970 13625838386"
        post_data = {
            "email": "bob@saintclar.net",
            "first_name": "Bob",
            "last_name": "Saint Clar",
            "birthdate": "20/12/1978",
            "phone": "0610203050",
            "lack_of_pole_emploi_id_reason": user.REASON_NOT_REGISTERED,
            "address_line_1": "10, rue du Gué",
            "address_line_2": "Sous l'escalier",
            "post_code": "35400",
            "city": "Saint-Malo",
            "lack_of_nir": False,
            "nir": NEW_NIR,
        }
        response = self.client.post(url, data=post_data)
        assert response.status_code == 302

        user.refresh_from_db()
        assert user.lack_of_nir_reason == ""
        assert user.nir == NEW_NIR.replace(" ", "")

    def test_edit_without_nir_information(self):
        user = JobSeekerFactory(nir="", lack_of_nir_reason="")
        self.client.force_login(user)
        url = reverse("dashboard:edit_user_info")
        response = self.client.get(url)
        # Check that the NIR field is enabled
        assert not response.context["form"]["nir"].field.disabled
        self.assertNotContains(response, self.NIR_UPDATE_TALLY_LINK_LABEL, html=True)

        NEW_NIR = "1 970 13625838386"
        post_data = {
            "email": "bob@saintclar.net",
            "first_name": "Bob",
            "last_name": "Saint Clar",
            "birthdate": "20/12/1978",
            "phone": "0610203050",
            "lack_of_pole_emploi_id_reason": user.REASON_NOT_REGISTERED,
            "address_line_1": "10, rue du Gué",
            "address_line_2": "Sous l'escalier",
            "post_code": "35400",
            "city": "Saint-Malo",
            "lack_of_nir": False,
            "nir": NEW_NIR,
        }
        response = self.client.post(url, data=post_data)
        assert response.status_code == 302

        user.refresh_from_db()
        assert user.lack_of_nir_reason == ""
        assert user.nir == NEW_NIR.replace(" ", "")

    def test_edit_sso(self):
        user = JobSeekerFactory(
            identity_provider=IdentityProvider.FRANCE_CONNECT,
            first_name="Not Bob",
            last_name="Not Saint Clar",
            birthdate=date(1970, 1, 1),
        )
        self.client.force_login(user)
        url = reverse("dashboard:edit_user_info")
        response = self.client.get(url)
        self.assertContains(response, "Adresse électronique")

        post_data = {
            "email": "bob@saintclar.net",
            "first_name": "Bob",
            "last_name": "Saint Clar",
            "birthdate": "20/12/1978",
            "phone": "0610203050",
            "lack_of_pole_emploi_id_reason": user.REASON_NOT_REGISTERED,
            "address_line_1": "10, rue du Gué",
            "address_line_2": "Sous l'escalier",
            "post_code": "35400",
            "city": "Saint-Malo",
        }
        response = self.client.post(url, data=post_data)
        assert response.status_code == 302

        user = User.objects.get(id=user.id)
        assert user.phone == post_data["phone"]
        assert user.address_line_1 == post_data["address_line_1"]
        assert user.address_line_2 == post_data["address_line_2"]
        assert user.post_code == post_data["post_code"]
        assert user.city == post_data["city"]

        # Ensure that the job seeker cannot update data retreived from the SSO here.
        assert user.first_name != post_data["first_name"]
        assert user.last_name != post_data["last_name"]
        assert user.birthdate.strftime("%d/%m/%Y") != post_data["birthdate"]
        assert user.email != post_data["email"]

    def test_edit_as_prescriber(self):
        user = PrescriberFactory()
        self.client.force_login(user)
        url = reverse("dashboard:edit_user_info")
        response = self.client.get(url)
        self.assertNotContains(response, "id_nir")
        self.assertNotContains(response, "id_lack_of_nir")
        self.assertNotContains(response, "id_lack_of_nir_reason")
        self.assertNotContains(response, "birthdate")

        post_data = {
            "first_name": "Bob",
            "last_name": "Saint Clar",
            "phone": "0610203050",
            "address_line_1": "10, rue du Gué",
            "address_line_2": "Sous l'escalier",
            "post_code": "35400",
            "city": "Saint-Malo",
        }
        response = self.client.post(url, data=post_data)
        assert response.status_code == 302

        user = User.objects.get(id=user.id)
        assert user.phone == post_data["phone"]
        assert user.address_line_1 == post_data["address_line_1"]
        assert user.address_line_2 == post_data["address_line_2"]
        assert user.post_code == post_data["post_code"]
        assert user.city == post_data["city"]

    def test_edit_as_prescriber_with_ic(self):
        user = PrescriberFactory(identity_provider=IdentityProvider.INCLUSION_CONNECT)
        self.client.force_login(user)
        url = reverse("dashboard:edit_user_info")
        response = self.client.get(url)
        self.assertNotContains(response, "id_nir")
        self.assertNotContains(response, "id_lack_of_nir")
        self.assertNotContains(response, "id_lack_of_nir_reason")
        self.assertNotContains(response, "birthdate")
        self.assertContains(response, f"Prénom : <strong>{user.first_name.title()}</strong>")
        self.assertContains(response, f"Nom : <strong>{user.last_name.upper()}</strong>")
        self.assertContains(response, f"Adresse e-mail : <strong>{user.email}</strong>")
        self.assertContains(response, "Modifier ces informations")

        post_data = {
            "email": "aaa",
            "first_name": "Bob",
            "last_name": "Saint Clar",
            "phone": "0610203050",
            "address_line_1": "10, rue du Gué",
            "address_line_2": "Sous l'escalier",
            "post_code": "35400",
            "city": "Saint-Malo",
        }
        response = self.client.post(url, data=post_data)
        assert response.status_code == 302

        user = User.objects.get(id=user.id)
        assert user.first_name != "Bob"
        assert user.first_name != "Saint Clair"
        assert user.phone == post_data["phone"]
        assert user.address_line_1 == post_data["address_line_1"]
        assert user.address_line_2 == post_data["address_line_2"]
        assert user.post_code == post_data["post_code"]
        assert user.city == post_data["city"]


class EditJobSeekerInfo(TestCase):
    def setUp(self):
        super().setUp()
        self.NIR_UPDATE_TALLY_LINK_LABEL = "Demander la correction du numéro de sécurité sociale"

    @override_settings(TALLY_URL="https://tally.so")
    def test_edit_by_siae_with_nir(self):
        job_application = JobApplicationSentByPrescriberFactory()
        user = job_application.to_siae.members.first()

        # Ensure that the job seeker is not autonomous (i.e. he did not register by himself).
        job_application.job_seeker.created_by = user
        job_application.job_seeker.save()
        previous_last_checked_at = job_application.job_seeker.last_checked_at

        self.client.force_login(user)

        back_url = reverse("apply:details_for_siae", kwargs={"job_application_id": job_application.id})
        url = reverse("dashboard:edit_job_seeker_info", kwargs={"job_seeker_pk": job_application.job_seeker_id})
        url = f"{url}?back_url={back_url}&from_application={job_application.pk}"

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
            "first_name": "Bob",
            "last_name": "Saint Clar",
            "birthdate": "20/12/1978",
            "lack_of_pole_emploi_id_reason": user.REASON_NOT_REGISTERED,
            "address_line_1": "10, rue du Gué",
            "post_code": "35400",
            "city": "Saint-Malo",
        }
        response = self.client.post(url, data=post_data)

        assert response.status_code == 302
        assert response.url == back_url

        job_seeker = User.objects.get(id=job_application.job_seeker.id)
        assert job_seeker.first_name == post_data["first_name"]
        assert job_seeker.last_name == post_data["last_name"]
        assert job_seeker.birthdate.strftime("%d/%m/%Y") == post_data["birthdate"]
        assert job_seeker.address_line_1 == post_data["address_line_1"]
        assert job_seeker.post_code == post_data["post_code"]
        assert job_seeker.city == post_data["city"]

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

    def test_edit_by_siae_with_lack_of_nir_reason(self):
        job_application = JobApplicationSentByPrescriberFactory(
            job_seeker__nir="", job_seeker__lack_of_nir_reason=LackOfNIRReason.TEMPORARY_NUMBER
        )
        user = job_application.to_siae.members.first()

        # Ensure that the job seeker is not autonomous (i.e. he did not register by himself).
        job_application.job_seeker.created_by = user
        job_application.job_seeker.save()
        previous_last_checked_at = job_application.job_seeker.last_checked_at

        self.client.force_login(user)

        back_url = reverse("apply:details_for_siae", kwargs={"job_application_id": job_application.id})
        url = reverse("dashboard:edit_job_seeker_info", kwargs={"job_seeker_pk": job_application.job_seeker_id})
        url = f"{url}?back_url={back_url}"

        response = self.client.get(url)
        self.assertContains(response, LackOfNIRReason.TEMPORARY_NUMBER.label, html=True)
        self.assertContains(response, 'disabled id="id_nir"')
        self.assertNotContains(response, self.NIR_UPDATE_TALLY_LINK_LABEL, html=True)

        NEW_NIR = "1 970 13625838386"
        post_data = {
            "email": "bob@saintclar.net",
            "first_name": "Bob",
            "last_name": "Saint Clar",
            "birthdate": "20/12/1978",
            "lack_of_pole_emploi_id_reason": user.REASON_NOT_REGISTERED,
            "address_line_1": "10, rue du Gué",
            "post_code": "35400",
            "city": "Saint-Malo",
            "lack_of_nir": False,
            "nir": NEW_NIR,
        }
        response = self.client.post(url, data=post_data)

        assert response.status_code == 302
        assert response.url == back_url

        job_seeker = User.objects.get(id=job_application.job_seeker.id)
        assert job_seeker.lack_of_nir_reason == ""
        assert job_seeker.nir == NEW_NIR.replace(" ", "")

        # last_checked_at should have been updated
        assert job_seeker.last_checked_at > previous_last_checked_at

    def test_edit_by_siae_without_nir_information(self):
        job_application = JobApplicationSentByPrescriberFactory(job_seeker__nir="", job_seeker__lack_of_nir_reason="")
        user = job_application.to_siae.members.first()

        # Ensure that the job seeker is not autonomous (i.e. he did not register by himself).
        job_application.job_seeker.created_by = user
        job_application.job_seeker.save()
        previous_last_checked_at = job_application.job_seeker.last_checked_at

        self.client.force_login(user)

        back_url = reverse("apply:details_for_siae", kwargs={"job_application_id": job_application.id})
        url = reverse("dashboard:edit_job_seeker_info", kwargs={"job_seeker_pk": job_application.job_seeker_id})
        url = f"{url}?back_url={back_url}"

        response = self.client.get(url)
        # Check that the NIR field is enabled
        assert not response.context["form"]["nir"].field.disabled
        self.assertNotContains(response, self.NIR_UPDATE_TALLY_LINK_LABEL, html=True)

        post_data = {
            "email": "bob@saintclar.net",
            "first_name": "Bob",
            "last_name": "Saint Clar",
            "birthdate": "20/12/1978",
            "lack_of_pole_emploi_id_reason": user.REASON_NOT_REGISTERED,
            "address_line_1": "10, rue du Gué",
            "post_code": "35400",
            "city": "Saint-Malo",
            "lack_of_nir": False,
        }
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
        assert job_seeker.lack_of_nir_reason == LackOfNIRReason.TEMPORARY_NUMBER
        assert job_seeker.nir == ""

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
        assert job_seeker.lack_of_nir_reason == ""
        assert job_seeker.nir == NEW_NIR.replace(" ", "")

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
        response = self.client.get(url)
        assert response.status_code == 200

    def test_edit_by_prescriber_with_job_application_URL(self):
        job_application = JobApplicationFactory(sent_by_authorized_prescriber_organisation=True)
        user = job_application.sender

        # Ensure that the job seeker is not autonomous (i.e. he did not register by himself).
        job_application.job_seeker.created_by = user
        job_application.job_seeker.save()

        self.client.force_login(user)
        url = reverse("dashboard:edit_job_seeker_info", kwargs={"job_application_id": job_application.pk})
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

    def test_edit_email_when_unconfirmed(self):
        """
        The SIAE can edit the email of a jobseeker it works with, provided he did not confirm its email.
        """
        new_email = "bidou@yopmail.com"
        siae = SiaeFactory(with_membership=True)
        user = siae.members.first()
        job_application = JobApplicationSentByPrescriberFactory(to_siae=siae, job_seeker__created_by=user)

        self.client.force_login(user)

        back_url = reverse("apply:details_for_siae", kwargs={"job_application_id": job_application.id})
        url = reverse("dashboard:edit_job_seeker_info", kwargs={"job_seeker_pk": job_application.job_seeker_id})
        url = f"{url}?back_url={back_url}"

        response = self.client.get(url)
        self.assertContains(response, "Adresse électronique")

        post_data = {
            "email": new_email,
            "birthdate": "20/12/1978",
            "lack_of_pole_emploi_id_reason": user.REASON_NOT_REGISTERED,
            "address_line_1": "10, rue du Gué",
            "post_code": "35400",
            "city": "Saint-Malo",
        }
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
        assert job_seeker.address_line_2 == post_data["address_line_2"]

    def test_edit_email_when_confirmed(self):
        new_email = "bidou@yopmail.com"
        job_application = JobApplicationSentByPrescriberFactory()
        user = job_application.to_siae.members.first()

        # Ensure that the job seeker is not autonomous (i.e. he did not register by himself).
        job_application.job_seeker.created_by = user
        job_application.job_seeker.save()

        # Confirm job seeker email
        job_seeker = User.objects.get(id=job_application.job_seeker.id)
        EmailAddress.objects.create(user=job_seeker, email=job_seeker.email, verified=True)

        # Now the SIAE wants to edit the jobseeker email. The field is not available, and it cannot be bypassed
        self.client.force_login(user)

        back_url = reverse("apply:details_for_siae", kwargs={"job_application_id": job_application.id})
        url = reverse("dashboard:edit_job_seeker_info", kwargs={"job_seeker_pk": job_application.job_seeker_id})
        url = f"{url}?back_url={back_url}"

        response = self.client.get(url)
        self.assertNotContains(response, "Adresse électronique")

        post_data = {
            "email": new_email,
            "birthdate": "20/12/1978",
            "lack_of_pole_emploi_id_reason": user.REASON_NOT_REGISTERED,
            "address_line_1": "10, rue du Gué",
            "post_code": "35400",
            "city": "Saint-Malo",
        }
        response = self.client.post(url, data=post_data)

        assert response.status_code == 302
        assert response.url == back_url

        job_seeker = User.objects.get(id=job_application.job_seeker.id)
        # The email is not changed, but other fields are taken into account
        assert job_seeker.email != new_email
        assert job_seeker.birthdate.strftime("%d/%m/%Y") == post_data["birthdate"]
        assert job_seeker.address_line_1 == post_data["address_line_1"]
        assert job_seeker.post_code == post_data["post_code"]
        assert job_seeker.city == post_data["city"]

        # Optional fields
        post_data |= {
            "phone": "0610203050",
            "address_line_2": "Sous l'escalier",
        }
        response = self.client.post(url, data=post_data)
        job_seeker.refresh_from_db()

        assert job_seeker.phone == post_data["phone"]
        assert job_seeker.address_line_2 == post_data["address_line_2"]

    def test_edit_no_address_does_not_crash(self):
        job_application = JobApplicationFactory(sent_by_authorized_prescriber_organisation=True)
        user = job_application.sender

        # Ensure that the job seeker is not autonomous (i.e. he did not register by himself).
        job_application.job_seeker.created_by = user
        job_application.job_seeker.save()

        self.client.force_login(user)
        url = reverse("dashboard:edit_job_seeker_info", kwargs={"job_seeker_pk": job_application.job_seeker_id})
        post_data = {
            "email": user.email,
            "birthdate": "20/12/1978",
            "lack_of_pole_emploi_id_reason": user.REASON_NOT_REGISTERED,
            "address_line_1": "",
            "post_code": "35400",
            "city": "Saint-Malo",
        }
        response = self.client.post(url, data=post_data)
        self.assertContains(response, "Ce champ est obligatoire.")
        assert response.context["form"].errors["address_line_1"] == ["Ce champ est obligatoire."]


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


class SwitchSiaeTest(TestCase):
    def test_switch_siae(self):
        siae = SiaeFactory(with_membership=True)
        user = siae.members.first()
        self.client.force_login(user)

        related_siae = SiaeFactory()
        related_siae.members.add(user)

        url = reverse("dashboard:index")
        response = self.client.get(url)
        assert response.status_code == 200
        assert response.context["request"].current_organization == siae

        url = reverse("siaes_views:card", kwargs={"siae_id": siae.pk})
        response = self.client.get(url)
        assert response.status_code == 200
        assert response.context["request"].current_organization == siae
        assert response.context["siae"] == siae

        url = reverse("dashboard:switch_organization")
        response = self.client.post(url, data={"organization_id": related_siae.pk})
        assert response.status_code == 302

        url = reverse("dashboard:index")
        response = self.client.get(url)
        assert response.status_code == 200
        assert response.context["request"].current_organization == related_siae

        url = reverse("siaes_views:card", kwargs={"siae_id": related_siae.pk})
        response = self.client.get(url)
        assert response.status_code == 200
        assert response.context["request"].current_organization == related_siae
        assert response.context["siae"] == related_siae

        url = reverse("siaes_views:job_description_list")
        response = self.client.get(url)
        assert response.status_code == 200
        assert response.context["request"].current_organization == related_siae

        url = reverse("apply:list_for_siae")
        response = self.client.get(url)
        assert response.status_code == 200
        assert response.context["request"].current_organization == related_siae

    def test_can_still_switch_to_inactive_siae_during_grace_period(self):
        siae = SiaeFactory(with_membership=True)
        user = siae.members.first()
        self.client.force_login(user)

        related_siae = SiaePendingGracePeriodFactory()
        related_siae.members.add(user)

        url = reverse("dashboard:index")
        response = self.client.get(url)
        assert response.status_code == 200
        assert response.context["request"].current_organization == siae

        url = reverse("dashboard:switch_organization")
        response = self.client.post(url, data={"organization_id": related_siae.pk})
        assert response.status_code == 302

        # User has indeed switched.
        url = reverse("dashboard:index")
        response = self.client.get(url)
        assert response.status_code == 200
        assert response.context["request"].current_organization == related_siae

    def test_cannot_switch_to_inactive_siae_after_grace_period(self):
        siae = SiaeFactory(with_membership=True)
        user = siae.members.first()
        self.client.force_login(user)

        related_siae = SiaeAfterGracePeriodFactory()
        related_siae.members.add(user)

        url = reverse("dashboard:index")
        response = self.client.get(url)
        assert response.status_code == 200
        assert response.context["request"].current_organization == siae

        # Switching to that siae is not even possible in practice because
        # it does not even show up in the menu.
        url = reverse("dashboard:switch_organization")
        response = self.client.post(url, data={"organization_id": related_siae.pk})
        assert response.status_code == 404

        # User is still working on the main active siae.
        url = reverse("dashboard:index")
        response = self.client.get(url)
        assert response.status_code == 200
        assert response.context["request"].current_organization == siae


class EditUserPreferencesTest(TestCase):
    def test_employer_opt_in_siae_no_job_description(self):
        siae = SiaeFactory(with_membership=True)
        user = siae.members.first()
        recipient = user.siaemembership_set.get(siae=siae)
        form_name = "new_job_app_notification_form"

        self.client.force_login(user)

        # Recipient's notifications are empty for the moment.
        assert not recipient.notifications

        url = reverse("dashboard:edit_user_notifications")
        response = self.client.get(url)
        assert response.status_code == 200

        # Recipients are subscribed to spontaneous notifications by default,
        # the form should reflect that.
        assert response.context[form_name].fields["spontaneous"].initial

        data = {"spontaneous": True}
        response = self.client.post(url, data=data)

        assert response.status_code == 302

        recipient.refresh_from_db()
        assert recipient.notifications
        assert NewSpontaneousJobAppEmployersNotification.is_subscribed(recipient=recipient)

    def test_employer_opt_in_siae_with_job_descriptions(self):
        siae = SiaeWithMembershipAndJobsFactory()
        user = siae.members.first()
        job_descriptions_pks = list(siae.job_description_through.values_list("pk", flat=True))
        recipient = user.siaemembership_set.get(siae=siae)
        form_name = "new_job_app_notification_form"
        self.client.force_login(user)

        # Recipient's notifications are empty for the moment.
        assert not recipient.notifications

        url = reverse("dashboard:edit_user_notifications")
        response = self.client.get(url)
        assert response.status_code == 200

        # Recipients are subscribed to spontaneous notifications by default,
        # the form should reflect that.
        assert response.context[form_name].fields["qualified"].initial == job_descriptions_pks

        data = {"qualified": job_descriptions_pks}
        response = self.client.post(url, data=data)
        assert response.status_code == 302

        recipient.refresh_from_db()
        assert recipient.notifications

        for pk in job_descriptions_pks:
            assert NewQualifiedJobAppEmployersNotification.is_subscribed(recipient=recipient, subscribed_pk=pk)

    def test_employer_opt_out_siae_no_job_descriptions(self):
        siae = SiaeFactory(with_membership=True)
        user = siae.members.first()
        recipient = user.siaemembership_set.get(siae=siae)
        form_name = "new_job_app_notification_form"
        self.client.force_login(user)

        # Recipient's notifications are empty for the moment.
        assert not recipient.notifications

        url = reverse("dashboard:edit_user_notifications")
        response = self.client.get(url)
        assert response.status_code == 200

        # Recipients are subscribed to spontaneous notifications by default,
        # the form should reflect that.
        assert response.context[form_name].fields["spontaneous"].initial

        data = {"spontaneous": False}
        response = self.client.post(url, data=data)

        assert response.status_code == 302

        recipient.refresh_from_db()
        assert recipient.notifications
        assert not NewSpontaneousJobAppEmployersNotification.is_subscribed(recipient=recipient)

    def test_employer_opt_out_siae_with_job_descriptions(self):
        siae = SiaeWithMembershipAndJobsFactory()
        user = siae.members.first()
        job_descriptions_pks = list(siae.job_description_through.values_list("pk", flat=True))
        recipient = user.siaemembership_set.get(siae=siae)
        form_name = "new_job_app_notification_form"
        self.client.force_login(user)

        # Recipient's notifications are empty for the moment.
        assert not recipient.notifications

        url = reverse("dashboard:edit_user_notifications")
        response = self.client.get(url)
        assert response.status_code == 200

        # Recipients are subscribed to qualified notifications by default,
        # the form should reflect that.
        assert response.context[form_name].fields["qualified"].initial == job_descriptions_pks

        # The recipient opted out from every notification.
        data = {"spontaneous": False}
        response = self.client.post(url, data=data)
        assert response.status_code == 302

        recipient.refresh_from_db()
        assert recipient.notifications

        for _i, pk in enumerate(job_descriptions_pks):
            assert not NewQualifiedJobAppEmployersNotification.is_subscribed(recipient=recipient, subscribed_pk=pk)


class EditUserPreferencesExceptionsTest(TestCase):
    def test_not_allowed_user(self):
        # Only employers can currently access the Preferences page.

        prescriber = PrescriberFactory()
        self.client.force_login(prescriber)
        url = reverse("dashboard:edit_user_notifications")
        response = self.client.get(url)
        assert response.status_code == 403

        job_seeker = JobSeekerFactory()
        self.client.force_login(job_seeker)
        url = reverse("dashboard:edit_user_notifications")
        response = self.client.get(url)
        assert response.status_code == 403


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


def test_api_token_view_for_siae_admin(client):
    siae_staff = SiaeMembershipFactory().user
    client.force_login(siae_staff)

    assert not Token.objects.exists()

    url = reverse("dashboard:index")
    response = client.get(url)

    url = reverse("dashboard:api_token")
    assertContains(response, TOKEN_MENU_STR)
    assertContains(response, url)

    response = client.get(url)
    assertContains(response, "Vous n'avez pas encore de token d'API")
    assertContains(response, "Créer un token d'API")

    response = client.post(url)
    token = Token.objects.filter(user=siae_staff).get()
    assertContains(response, token.key)
    assertContains(response, "Copier le token")

    # Check multi-posts
    response = client.post(url)
    assert Token.objects.filter(user=siae_staff).count() == 1


def test_api_token_view_for_non_siae_admin(client):
    siae_staff = SiaeMembershipFactory(is_admin=False).user
    client.force_login(siae_staff)

    assert not Token.objects.exists()

    url = reverse("dashboard:index")
    response = client.get(url)

    url = reverse("dashboard:api_token")
    assertNotContains(response, TOKEN_MENU_STR)
    assertNotContains(response, url)

    response = client.get(url)
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
def test_siae_staff_using_django_has_to_activate_ic_account(client):
    user = SiaeStaffFactory(with_siae=True, identity_provider=IdentityProvider.DJANGO, email=OIDC_USERINFO["email"])
    client.force_login(user)
    url = reverse("dashboard:index")
    response = client.get(url, follow=True)
    activate_ic_account_url = reverse("dashboard:activate_ic_account")
    assertRedirects(response, activate_ic_account_url)
    params = {
        "user_kind": UserKind.SIAE_STAFF,
        "previous_url": activate_ic_account_url,
        "user_email": user.email,
    }
    url = escape(f"{reverse('inclusion_connect:activate_account')}?{urlencode(params)}")
    assertContains(response, url + '"')
    response = mock_oauth_dance(
        client,
        UserKind.SIAE_STAFF,
        previous_url=activate_ic_account_url,
    )
    user.refresh_from_db()
    assert user.identity_provider == IdentityProvider.INCLUSION_CONNECT


@pytest.mark.parametrize(
    "factory,expected",
    [
        pytest.param(JobSeekerFactory, assertNotContains, id="JobSeeker"),
        pytest.param(partial(SiaeStaffFactory, with_siae=True), assertNotContains, id="SiaeStaff"),
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
