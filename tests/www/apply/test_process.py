import datetime
import logging
import random
import uuid
from itertools import product

import factory
import pytest
from bs4 import BeautifulSoup
from dateutil.relativedelta import relativedelta
from django.contrib import messages
from django.db.models import Exists, OuterRef, Q
from django.template.defaultfilters import urlencode as urlencode_filter
from django.urls import reverse
from django.utils import timezone
from django.utils.formats import date_format
from freezegun import freeze_time
from pytest_django.asserts import (
    assertContains,
    assertFormError,
    assertMessages,
    assertNotContains,
    assertRedirects,
    assertTemplateNotUsed,
    assertTemplateUsed,
)

from itou.approvals.models import Approval, Suspension
from itou.asp.models import Commune, Country
from itou.cities.models import City
from itou.companies.enums import CompanyKind, ContractType, JobDescriptionSource
from itou.eligibility.enums import CERTIFIABLE_ADMINISTRATIVE_CRITERIA_KINDS, AdministrativeCriteriaKind, AuthorKind
from itou.eligibility.models import AdministrativeCriteria, EligibilityDiagnosis
from itou.eligibility.models.common import AbstractSelectedAdministrativeCriteria
from itou.eligibility.models.geiq import GEIQSelectedAdministrativeCriteria
from itou.employee_record.enums import Status
from itou.employee_record.models import EmployeeRecordTransition, EmployeeRecordTransitionLog
from itou.job_applications import enums as job_applications_enums
from itou.job_applications.enums import JobApplicationState, QualificationLevel, QualificationType, SenderKind
from itou.job_applications.models import JobApplication, JobApplicationWorkflow
from itou.jobs.models import Appellation
from itou.prescribers.enums import PrescriberAuthorizationStatus
from itou.siae_evaluations.models import Sanctions
from itou.users.enums import LackOfNIRReason, LackOfPoleEmploiId, Title
from itou.users.models import User
from itou.utils.mocks.address_format import mock_get_geocoding_data_by_ban_api_resolved
from itou.utils.mocks.api_particulier import RESPONSES, ResponseKind
from itou.utils.models import InclusiveDateRange
from itou.utils.templatetags.format_filters import format_nir, format_phone
from itou.utils.urls import add_url_params
from itou.utils.widgets import DuetDatePickerWidget
from itou.www.apply.forms import AcceptForm
from itou.www.apply.views.batch_views import RefuseWizardView
from itou.www.apply.views.process_views import job_application_sender_left_org
from tests.approvals.factories import ApprovalFactory, SuspensionFactory
from tests.cities.factories import create_test_cities
from tests.companies.factories import CompanyFactory, CompanyMembershipFactory, JobDescriptionFactory
from tests.eligibility.factories import (
    GEIQEligibilityDiagnosisFactory,
    IAEEligibilityDiagnosisFactory,
    IAESelectedAdministrativeCriteriaFactory,
)
from tests.employee_record.factories import EmployeeRecordFactory
from tests.job_applications.factories import (
    JobApplicationFactory,
    JobApplicationSentByJobSeekerFactory,
    JobApplicationSentByPrescriberOrganizationFactory,
    PriorActionFactory,
)
from tests.jobs.factories import create_test_romes_and_appellations
from tests.prescribers.factories import PrescriberMembershipFactory
from tests.siae_evaluations.factories import EvaluatedSiaeFactory
from tests.users import constants as users_test_constants
from tests.users.factories import EmployerFactory, JobSeekerFactory, LaborInspectorFactory, PrescriberFactory
from tests.utils.htmx.test import assertSoupEqual, update_page_with_htmx
from tests.utils.test import (
    assert_previous_step,
    assertSnapshotQueries,
    get_session_name,
    parse_response_to_soup,
)
from tests.www.eligibility_views.utils import CERTIFIED_BADGE_HTML


logger = logging.getLogger(__name__)

DISABLED_NIR = 'disabled aria-describedby="id_nir_helptext" id="id_nir"'
PRIOR_ACTION_SECTION_TITLE = "Action préalable à l'embauche"
REFUSED_JOB_APPLICATION_PRESCRIBER_SECTION_TITLE = "L’employeur a refusé la candidature avec le motif “Autre”."
REFUSED_JOB_APPLICATION_PRESCRIBER_SECTION_BODY = (
    "Si les détails apportés dans le message de réponse ne vous ont pas permis d’en savoir plus,"
    " vous pouvez contacter l’employeur."
)
SENDER_LEFT_ORG = "Les réponses seront transmises aux administrateurs de l’organisation"
SENDER_LEFT_ORG_ALERT = "L’émetteur de cette candidature ne fait plus partie de l’organisation émettrice"

IAE_CANCELLATION_CONFIRMATION = (
    "En validant, <strong>vous renoncez aux aides au poste</strong> liées à cette candidature "
    "pour tous les jours travaillés de ce salarié."
)
NON_IAE_CANCELLATION_CONFIRMATION = (
    "En validant, vous confirmez que le salarié n’avait pas encore commencé à travailler dans votre structure."
)


@pytest.mark.ignore_unknown_variable_template_error("has_form_error", "with_matomo_event")
class TestProcessViews:
    DIAGORIENTE_INVITE_TITLE = "Ce candidat n’a pas de CV ?"
    DIAGORIENTE_INVITE_PRESCRIBER_MESSAGE = "Invitez le prescripteur à en créer un via notre partenaire Diagoriente."
    DIAGORIENTE_INVITE_JOB_SEEKER_MESSAGE = "Invitez-le à en créer un via notre partenaire Diagoriente."
    DIAGORIENTE_INVITE_BUTTON_TITLE = "Inviter à créer un CV avec Diagoriente"
    DIAGORIENTE_INVITE_TOOLTIP = "Vous avez invité l'émetteur de cette candidature à créer un CV sur Diagoriente le"
    DIAGORIENTE_INVITE_EMAIL_SUBJECT = "Créer un CV avec Diagoriente"
    DIAGORIENTE_INVITE_EMAIL_PRESCRIBER_BODY_HEADER_LINE_1 = (
        "L’entreprise {company_name} vous propose d’utiliser Diagoriente pour valoriser "
        "les expériences de votre candidat : {job_seeker_name}."
    )
    DIAGORIENTE_INVITE_EMAIL_PRESCRIBER_BODY_HEADER_LINE_2 = (
        "Vous pourrez lui créer un compte en cliquant sur ce lien : "
        "https://diagoriente.beta.gouv.fr/services/plateforme?utm_source=emploi-inclusion-employeur"
    )
    DIAGORIENTE_INVITE_EMAIL_JOB_SEEKER_BODY_HEADER_LINE_1 = (
        "L’entreprise {company_name} vous propose d’utiliser Diagoriente pour valoriser vos expériences."
    )
    DIAGORIENTE_INVITE_EMAIL_JOB_SEEKER_BODY_HEADER_LINE_2 = (
        "Vous pourrez créer votre compte en cliquant sur ce lien : "
        "https://diagoriente.beta.gouv.fr/services/plateforme?utm_source=emploi-inclusion-employeur"
    )
    REFUSAL_REASON_JOB_SEEKER_MENTION = "<small>Motif de refus</small><strong>Autre</strong>"
    REFUSAL_REASON_SHARED_MENTION = "<small>Motif de refus partagé avec le candidat</small><strong>Autre</strong>"
    REFUSAL_REASON_NOT_SHARED_MENTION = (
        "<small>Motif de refus non partagé avec le candidat</small><strong>Autre</strong>"
    )

    @pytest.fixture(autouse=True)
    def setup_method(self):
        create_test_romes_and_appellations(("N1101", "N1105", "N1103", "N4105"))
        self.cities = create_test_cities(["54", "57"], num_per_department=2)

    def get_random_city(self):
        return random.choice(self.cities)

    def _get_transition_logs_content(self, response, job_application):
        soup = BeautifulSoup(response.content, "html5lib", from_encoding=response.charset or "utf-8")
        return soup.find("ul", attrs={"id": "transition_logs_" + str(job_application.id)})

    def test_details_for_company_from_approval(self, client, snapshot):
        """Display the details of a job application coming from the approval detail page."""

        job_application = JobApplicationFactory(
            sent_by_authorized_prescriber_organisation=True, resume=None, with_approval=True
        )
        company = job_application.to_company
        employer = company.members.first()
        client.force_login(employer)

        back_url = reverse("employees:detail", kwargs={"public_id": job_application.job_seeker.public_id})
        url = add_url_params(
            reverse("apply:details_for_company", kwargs={"job_application_id": job_application.pk}),
            {"back_url": back_url},
        )
        approval_url = reverse("approvals:details", kwargs={"public_id": job_application.approval.public_id})
        with assertSnapshotQueries(snapshot(name="job application detail for company")):
            response = client.get(url)
        assertContains(response, "Ce candidat a pris le contrôle de son compte utilisateur.")
        assertContains(response, format_nir(job_application.job_seeker.jobseeker_profile.nir))
        assertContains(response, job_application.job_seeker.jobseeker_profile.pole_emploi_id)
        assertContains(response, job_application.job_seeker.phone.replace(" ", ""))
        assertNotContains(response, PRIOR_ACTION_SECTION_TITLE)  # the company is not a GEIQ
        assertContains(response, f"{approval_url}?back_url={urlencode_filter(url)}")
        assert_previous_step(response, back_url)

        job_application.job_seeker.created_by = employer
        job_application.job_seeker.phone = ""
        job_application.job_seeker.save()
        job_application.job_seeker.jobseeker_profile.nir = ""
        job_application.job_seeker.jobseeker_profile.pole_emploi_id = ""
        job_application.job_seeker.jobseeker_profile.save()

        url = reverse("apply:details_for_company", kwargs={"job_application_id": job_application.pk})
        response = client.get(url)
        assertContains(response, "Modifier les informations")
        assertContains(response, '<small>Adresse</small><i class="text-disabled">Non renseignée</i>', html=True)
        assertContains(response, '<small>Téléphone</small><i class="text-disabled">Non renseigné</i>', html=True)
        assertContains(
            response, '<small>Curriculum vitae</small><i class="text-disabled">Non renseigné</i>', html=True
        )
        assertContains(
            response,
            '<small>Identifiant France Travail</small><i class="text-disabled">Non renseigné</i>',
            html=True,
        )
        assertContains(
            response, '<small>Numéro de sécurité sociale</small><i class="text-disabled">Non renseigné</i>', html=True
        )
        assert_previous_step(response, back_url)  # Back_url is restored from session

        job_application.job_seeker.jobseeker_profile.lack_of_nir_reason = LackOfNIRReason.TEMPORARY_NUMBER
        job_application.job_seeker.jobseeker_profile.save()

        url = reverse("apply:details_for_company", kwargs={"job_application_id": job_application.pk})
        response = client.get(url)
        assertContains(response, LackOfNIRReason.TEMPORARY_NUMBER.label)

        # Test resume presence:
        job_application = JobApplicationSentByJobSeekerFactory(to_company=company)
        url = reverse("apply:details_for_company", kwargs={"job_application_id": job_application.pk})
        response = client.get(url)
        assertContains(response, job_application.resume_link)
        assertNotContains(response, PRIOR_ACTION_SECTION_TITLE)

    def test_details_for_company_from_list(self, client, snapshot):
        """Display the details of a job application coming from the job applications list."""

        job_application = JobApplicationFactory(
            sent_by_authorized_prescriber_organisation=True, resume=None, with_approval=True
        )
        company = job_application.to_company
        employer = company.members.first()
        client.force_login(employer)

        back_url = f"{reverse('apply:list_for_siae')}?job_seeker_public_id={job_application.job_seeker.id}"
        url = add_url_params(
            reverse("apply:details_for_company", kwargs={"job_application_id": job_application.pk}),
            {"back_url": back_url},
        )
        with assertSnapshotQueries(snapshot(name="job application detail for company")):
            response = client.get(url)
        assertContains(response, "Ce candidat a pris le contrôle de son compte utilisateur.")
        assertContains(response, format_nir(job_application.job_seeker.jobseeker_profile.nir))
        assertContains(response, job_application.job_seeker.jobseeker_profile.pole_emploi_id)
        assertContains(response, job_application.job_seeker.phone.replace(" ", ""))
        assertNotContains(response, PRIOR_ACTION_SECTION_TITLE)  # the company is not a GEIQ
        assert_previous_step(response, back_url, back_to_list=True)

        job_application.job_seeker.created_by = employer
        job_application.job_seeker.phone = ""
        job_application.job_seeker.save()
        job_application.job_seeker.jobseeker_profile.nir = ""
        job_application.job_seeker.jobseeker_profile.pole_emploi_id = ""
        job_application.job_seeker.jobseeker_profile.save()

        url = reverse("apply:details_for_company", kwargs={"job_application_id": job_application.pk})
        response = client.get(url)
        assertContains(response, "Modifier les informations")
        assertContains(response, '<small>Adresse</small><i class="text-disabled">Non renseignée</i>', html=True)
        assertContains(response, '<small>Téléphone</small><i class="text-disabled">Non renseigné</i>', html=True)
        assertContains(
            response, '<small>Curriculum vitae</small><i class="text-disabled">Non renseigné</i>', html=True
        )
        assertContains(
            response,
            '<small>Identifiant France Travail</small><i class="text-disabled">Non renseigné</i>',
            html=True,
        )
        assertContains(
            response, '<small>Numéro de sécurité sociale</small><i class="text-disabled">Non renseigné</i>', html=True
        )
        assert_previous_step(response, back_url, back_to_list=True)  # Back_url is restored from session

        job_application.job_seeker.jobseeker_profile.lack_of_nir_reason = LackOfNIRReason.TEMPORARY_NUMBER
        job_application.job_seeker.jobseeker_profile.save()

        url = reverse("apply:details_for_company", kwargs={"job_application_id": job_application.pk})
        response = client.get(url)
        assertContains(response, LackOfNIRReason.TEMPORARY_NUMBER.label)

        # Test resume presence:
        job_application = JobApplicationSentByJobSeekerFactory(to_company=company)
        url = reverse("apply:details_for_company", kwargs={"job_application_id": job_application.pk})
        response = client.get(url)
        assertContains(response, job_application.resume_link)
        assertNotContains(response, PRIOR_ACTION_SECTION_TITLE)

    def test_details_for_company_with_expired_approval(self, client, subtests):
        # Expired but still retrieved by job_seerk.latest_common_approval
        approval = ApprovalFactory(
            start_at=timezone.localdate() - datetime.timedelta(days=3 * 365),
            end_at=timezone.localdate() - datetime.timedelta(days=365),
        )
        company = CompanyFactory(for_snapshot=True, with_membership=True)
        employer = company.members.first()
        client.force_login(employer)

        for state in job_applications_enums.JobApplicationState:
            with subtests.test(state=state.label):
                # Expired approval are only shown to employers on already accepted applications
                assertion = (
                    assertContains
                    if state is job_applications_enums.JobApplicationState.ACCEPTED
                    else assertNotContains
                )
                job_application = JobApplicationFactory(
                    job_seeker=approval.user,
                    approval=approval,
                    to_company=company,
                    sent_by_authorized_prescriber_organisation=True,
                    state=state,
                )
                url = reverse("apply:details_for_company", kwargs={"job_application_id": job_application.pk})
                response = client.get(url)
                # Check if approval is displayed
                assertion(response, "Numéro de PASS IAE")

    def test_details_for_company_certified_criteria_after_expiration(self, client):
        company = CompanyFactory(subject_to_eligibility=True, with_membership=True)
        now = timezone.now()
        today = timezone.localdate(now)
        job_seeker = JobSeekerFactory()
        certification_grace_period = datetime.timedelta(
            days=AbstractSelectedAdministrativeCriteria.CERTIFICATION_GRACE_PERIOD_DAYS
        )
        created_at = now - certification_grace_period - datetime.timedelta(days=1)
        expires_at = today - datetime.timedelta(days=1)
        certification_period = InclusiveDateRange(timezone.localdate(created_at), expires_at)
        selected_criteria = IAESelectedAdministrativeCriteriaFactory(
            eligibility_diagnosis__author_siae=company,
            eligibility_diagnosis__job_seeker=job_seeker,
            eligibility_diagnosis__created_at=created_at,
            eligibility_diagnosis__expires_at=expires_at,
            certified=True,
            certification_period=certification_period,
        )
        eligibility_diagnosis = selected_criteria.eligibility_diagnosis
        job_application = JobApplicationFactory(
            to_company=company,
            job_seeker=job_seeker,
            hiring_start_at=today,
            eligibility_diagnosis=eligibility_diagnosis,
        )
        url = reverse("apply:details_for_company", kwargs={"job_application_id": job_application.pk})

        client.force_login(company.members.get())
        response = client.get(url)
        assertNotContains(response, CERTIFIED_BADGE_HTML, html=True)

        eligibility_diagnosis.expires_at = today + datetime.timedelta(days=1)
        eligibility_diagnosis.save()
        response = client.get(url)
        assertContains(response, CERTIFIED_BADGE_HTML, html=True)

    def test_details_when_sender_left_org(self, client):
        job_application = JobApplicationFactory(sent_by_authorized_prescriber_organisation=True)
        company = job_application.to_company
        employer = company.members.first()
        sender = job_application.sender
        sender.prescribermembership_set.update(is_active=False)
        client.force_login(employer)

        url = reverse("apply:details_for_company", kwargs={"job_application_id": job_application.pk})
        response = client.get(url)
        assertNotContains(response, sender.email)
        assertContains(response, SENDER_LEFT_ORG)
        assertContains(response, SENDER_LEFT_ORG_ALERT)

    def test_details_archived(self, client):
        UNARCHIVE = "Désarchiver"
        job_application = JobApplicationFactory(
            archived_at=datetime.datetime(2024, 9, 2, 11, 11, 11, tzinfo=timezone.get_current_timezone()),
        )
        to_company = job_application.to_company
        client.force_login(to_company.members.get())
        response = client.get(
            reverse(
                "apply:details_for_company",
                kwargs={"job_application_id": job_application.pk},
            )
        )
        assertContains(response, UNARCHIVE)
        assertContains(
            response,
            """
            <p>
                Cette candidature a été archivée automatiquement le 2 septembre 2024 à 11:11.
                Elle n’est plus visible par défaut dans votre liste de candidatures.
            </p>
            """,
            html=True,
            count=1,
        )

        gilles = EmployerFactory(first_name="Gilles", last_name="Pardoux")
        to_company.members.add(gilles)
        job_application.archived_by = gilles
        job_application.save(update_fields=["archived_by", "updated_at"])
        response = client.get(
            reverse(
                "apply:details_for_company",
                kwargs={"job_application_id": job_application.pk},
            )
        )
        assertContains(response, UNARCHIVE)
        assertContains(
            response,
            """
            <p>
                Cette candidature a été archivée par Gilles PARDOUX le 2 septembre 2024 à 11:11.
                Elle n’est plus visible par défaut dans votre liste de candidatures.
            </p>
            """,
            html=True,
            count=1,
        )

        client.force_login(job_application.sender)
        response = client.get(
            reverse(
                "apply:details_for_prescriber",
                kwargs={"job_application_id": job_application.pk},
            )
        )
        assertNotContains(response, UNARCHIVE)
        assertContains(
            response,
            """
            <p>
                Cette candidature a été archivée par Gilles PARDOUX le 2 septembre 2024 à 11:11.
                Elle n’est plus visible par défaut dans votre liste de candidatures.
            </p>
            """,
            html=True,
            count=1,
        )

        client.force_login(job_application.job_seeker)
        response = client.get(
            reverse(
                "apply:details_for_jobseeker",
                kwargs={"job_application_id": job_application.pk},
            )
        )
        assertNotContains(response, UNARCHIVE)
        assertContains(
            response,
            """
            <p>Cette candidature a été archivée par l’employeur le 2 septembre 2024 à 11:11.</p>
            """,
            html=True,
            count=1,
        )

    def test_details_for_company_as_prescriber(self, client):
        """As a prescriber, I cannot access the job_applications details for companies."""

        job_application = JobApplicationFactory(sent_by_authorized_prescriber_organisation=True)
        prescriber = job_application.sender_prescriber_organization.members.first()

        client.force_login(prescriber)

        url = reverse("apply:details_for_company", kwargs={"job_application_id": job_application.pk})
        response = client.get(url)
        assert response.status_code == 403

    def test_details_for_prescriber(self, client):
        """As a prescriber, I can access the job_applications details for prescribers."""

        appelation = Appellation.objects.first()
        job_application = JobApplicationFactory(
            with_approval=True,
            resume=None,
            sent_by_authorized_prescriber_organisation=True,
            selected_jobs=[appelation],
        )
        prescriber = job_application.sender_prescriber_organization.members.first()

        client.force_login(prescriber)

        url = reverse("apply:details_for_prescriber", kwargs={"job_application_id": job_application.pk})
        response = client.get(url)
        # Job seeker nir is displayed
        assertContains(response, format_nir(job_application.job_seeker.jobseeker_profile.nir))
        # Approval is displayed
        assertContains(response, "Numéro de PASS IAE")
        # Sender phone is displayed
        assertContains(response, format_phone(job_application.sender.phone))

        assertContains(response, '<small>Adresse</small><i class="text-disabled">Non renseignée</i>', html=True)
        assertContains(
            response, '<small>Curriculum vitae</small><i class="text-disabled">Non renseigné</i>', html=True
        )
        assert_previous_step(response, reverse("apply:list_prescriptions"), back_to_list=True)

        # Has link to job description with back_url set
        job_description = job_application.selected_jobs.first()
        job_description_url = f"{job_description.get_absolute_url()}?back_url={url}"
        assertContains(response, job_description_url)

        job_application.job_seeker.jobseeker_profile.nir = ""
        job_application.job_seeker.jobseeker_profile.save()
        response = client.get(url)
        assertContains(
            response, '<small>Numéro de sécurité sociale</small><i class="text-disabled">Non renseigné</i>', html=True
        )

        job_application.job_seeker.jobseeker_profile.lack_of_nir_reason = LackOfNIRReason.NIR_ASSOCIATED_TO_OTHER
        job_application.job_seeker.jobseeker_profile.save()
        response = client.get(url)
        assertContains(response, LackOfNIRReason.NIR_ASSOCIATED_TO_OTHER.label, html=True)

        assertContains(response, f"<strong>{job_application.to_company.display_name}</strong>")
        assertContains(response, reverse("companies_views:card", kwargs={"siae_id": job_application.to_company.pk}))

    def test_details_for_prescriber_when_sender_left_org(self, client):
        job_application = JobApplicationFactory(sent_by_authorized_prescriber_organisation=True)
        prescriber = PrescriberMembershipFactory(organization=job_application.sender_prescriber_organization).user
        sender = job_application.sender
        sender.prescribermembership_set.update(is_active=False)
        client.force_login(prescriber)

        url = reverse("apply:details_for_prescriber", kwargs={"job_application_id": job_application.pk})
        response = client.get(url)
        assertNotContains(response, sender.email)
        assertContains(response, SENDER_LEFT_ORG)
        assertContains(response, SENDER_LEFT_ORG_ALERT)

    def test_details_for_prescriber_as_company_when_i_am_not_the_sender(self, client):
        job_application = JobApplicationFactory(sent_by_authorized_prescriber_organisation=True)
        employer = job_application.to_company.members.first()
        client.force_login(employer)

        url = reverse("apply:details_for_prescriber", kwargs={"job_application_id": job_application.pk})
        response = client.get(url)
        assert response.status_code == 404

    def test_details_for_prescriber_as_company_when_i_am_the_sender(self, client):
        company = CompanyFactory(with_membership=True)
        employer = company.members.first()
        job_application = JobApplicationFactory(
            sender_kind=SenderKind.EMPLOYER,
            sender=employer,
            sender_company=company,
        )
        client.force_login(employer)

        url = reverse("apply:details_for_prescriber", kwargs={"job_application_id": job_application.pk})
        response = client.get(url)
        assert response.status_code == 200

    def test_details_for_unauthorized_prescriber(self, client):
        """As an unauthorized prescriber I cannot access personal information of arbitrary job seekers"""
        prescriber = PrescriberFactory()
        job_application = JobApplicationFactory(
            job_seeker__first_name="Supersecretname",
            job_seeker__last_name="Unknown",
            job_seeker__jobseeker_profile__nir="11111111111111",
            job_seeker__post_code="59140",
            job_seeker__with_mocked_address=True,
            sender=prescriber,
            sender_kind=job_applications_enums.SenderKind.PRESCRIBER,
        )
        client.force_login(prescriber)
        url = reverse("apply:details_for_prescriber", kwargs={"job_application_id": job_application.pk})
        response = client.get(url)
        assertNotContains(response, format_nir(job_application.job_seeker.jobseeker_profile.nir))
        assertContains(response, "<small>Prénom</small><strong>S…</strong>", html=True)
        assertContains(response, "<small>Nom</small><strong>U…</strong>", html=True)
        assertContains(response, "S… U…")
        assertNotContains(response, job_application.job_seeker.email)
        assertNotContains(response, job_application.job_seeker.phone)
        assertNotContains(response, job_application.job_seeker.post_code)
        assertNotContains(response, "Supersecretname")
        assertNotContains(response, "Unknown")

    def test_details_for_job_seeker(self, client, snapshot):
        """As a job seeker, I can access the job_applications details for job seekers."""
        job_seeker = JobSeekerFactory()

        job_application = JobApplicationFactory(job_seeker=job_seeker)
        job_application.process()

        client.force_login(job_seeker)

        url = reverse("apply:details_for_jobseeker", kwargs={"job_application_id": job_application.pk})
        with assertSnapshotQueries(snapshot):
            response = client.get(url)
        assertContains(response, format_nir(job_seeker.jobseeker_profile.nir))
        assertContains(response, job_seeker.email)
        assertContains(response, job_seeker.post_code)
        assertContains(response, job_seeker.address_line_1)
        assertContains(response, job_seeker.city)
        assertContains(response, f"<small>Prénom</small><strong>{job_seeker.first_name}</strong>", html=True)
        assertContains(response, f"<small>Nom</small><strong>{job_seeker.last_name.upper()}</strong>", html=True)
        assertContains(
            response,
            f"{job_seeker.first_name} {job_seeker.last_name.upper()}",
            html=True,
        )

        # phone sender is hidden for job seeker
        assertNotContains(response, format_phone(job_application.sender.phone))

        assertNotContains(response, PRIOR_ACTION_SECTION_TITLE)

        assertContains(response, f"<strong>{job_application.to_company.display_name}</strong>")
        assertContains(response, reverse("companies_views:card", kwargs={"siae_id": job_application.to_company.pk}))

    def test_details_for_job_seeker_when_sender_left_org(self, client):
        job_application = JobApplicationFactory(sent_by_authorized_prescriber_organisation=True)
        sender = job_application.sender
        sender.prescribermembership_set.update(is_active=False)

        client.force_login(job_application.job_seeker)

        url = reverse("apply:details_for_jobseeker", kwargs={"job_application_id": job_application.pk})
        response = client.get(url)
        assertNotContains(response, sender.email)
        assertNotContains(response, SENDER_LEFT_ORG)  # A job seeker never sees the email of the sender
        assertContains(response, SENDER_LEFT_ORG_ALERT)

    def test_details_for_job_seeker_as_other_user(self, client, subtests):
        job_application = JobApplicationFactory()
        url = reverse("apply:details_for_jobseeker", kwargs={"job_application_id": job_application.pk})

        for user in [
            JobSeekerFactory(),
            EmployerFactory(with_company=True),
            PrescriberFactory(),
            LaborInspectorFactory(membership=True),
        ]:
            with subtests.test(user_kind=user.kind.label):
                client.force_login(user)
                response = client.get(url)
                assert response.status_code == 404

    def test_details_for_prescriber_with_transition_logs(self, client, snapshot):
        """As a prescriber, I can access transition logs for job_applications details for prescribers."""
        with freeze_time("2023-12-10 11:11:00", tz_offset=-1):
            job_application = JobApplicationFactory(
                for_snapshot=True,
                sent_by_authorized_prescriber_organisation=True,
            )

        user = job_application.to_company.members.first()
        # transition logs setup
        with freeze_time("2023-12-12 13:37:00", tz_offset=-1):
            job_application.process(user=user)
        with freeze_time("2023-12-12 13:38:00", tz_offset=-1):
            job_application.accept(user=user)

        prescriber = job_application.sender_prescriber_organization.members.first()
        client.force_login(prescriber)

        url = reverse("apply:details_for_prescriber", kwargs={"job_application_id": job_application.pk})
        response = client.get(url)
        html_fragment = self._get_transition_logs_content(response, job_application)

        assert str(html_fragment) == snapshot

    def test_details_for_job_seeker_with_transition_logs(self, client, snapshot):
        """As a prescriber, I can access transition logs for job_applications details for prescribers."""
        with freeze_time("2023-12-10 11:11:00", tz_offset=-1):
            job_application = JobApplicationFactory(
                for_snapshot=True,
                sent_by_authorized_prescriber_organisation=True,
            )

        user = job_application.to_company.active_members.first()
        # transition logs setup
        with freeze_time("2023-12-12 13:37:00", tz_offset=-1):
            job_application.process(user=user)
        with freeze_time("2023-12-12 13:38:00", tz_offset=-1):
            job_application.accept(user=user)

        client.force_login(job_application.job_seeker)

        url = reverse("apply:details_for_jobseeker", kwargs={"job_application_id": job_application.pk})
        response = client.get(url)
        html_fragment = self._get_transition_logs_content(response, job_application)

        assert str(html_fragment) == snapshot

    def test_details_for_company_with_transition_logs(self, client, snapshot):
        """As a prescriber, I can access transition logs for job_applications details for prescribers."""
        with freeze_time("2023-12-10 11:11:00", tz_offset=-1):
            job_application = JobApplicationFactory(
                for_snapshot=True,
                sent_by_authorized_prescriber_organisation=True,
            )

        user = job_application.to_company.active_members.first()
        # transition logs setup
        with freeze_time("2023-12-12 13:37:00", tz_offset=-1):
            job_application.process(user=user)
        with freeze_time("2023-12-12 13:38:00", tz_offset=-1):
            job_application.accept(user=user)

        client.force_login(user)

        url = reverse("apply:details_for_company", kwargs={"job_application_id": job_application.pk})
        response = client.get(url)
        html_fragment = self._get_transition_logs_content(response, job_application)

        assert str(html_fragment) == snapshot

    def test_external_transfer_log_display(self, client, snapshot):
        job_seeker = JobSeekerFactory()
        with freeze_time("2023-12-10 11:11:00", tz_offset=-1):
            job_app = JobApplicationFactory(
                for_snapshot=True,
                job_seeker=job_seeker,
                sent_by_authorized_prescriber_organisation=True,
            )

        employer = job_app.to_company.active_members.first()
        other_company = CompanyFactory()

        # transition logs setup
        with freeze_time("2023-12-12 13:37:00", tz_offset=-1):
            job_app.refuse(user=employer)
        with freeze_time("2023-12-12 13:38:00", tz_offset=-1):
            job_app.external_transfer(user=employer, target_company=other_company)

        client.force_login(employer)

        url = reverse("apply:details_for_company", kwargs={"job_application_id": job_app.pk})
        response = client.get(url)
        html_fragment = self._get_transition_logs_content(response, job_app)

        assert str(html_fragment) == snapshot

    def test_details_for_company_transition_logs_hides_hired_by_other(self, client, snapshot):
        job_seeker = JobSeekerFactory()
        with freeze_time("2023-12-10 11:11:00", tz_offset=-1):
            job_app1 = JobApplicationFactory(
                for_snapshot=True,
                job_seeker=job_seeker,
                sent_by_authorized_prescriber_organisation=True,
            )
            job_app2 = JobApplicationFactory(
                job_seeker=job_seeker,
                sent_by_authorized_prescriber_organisation=True,
            )

        user1 = job_app1.to_company.active_members.first()
        user2 = job_app2.to_company.active_members.first()
        # transition logs setup
        with freeze_time("2023-12-12 13:37:00", tz_offset=-1):
            job_app2.process(user=user2)
        with freeze_time("2023-12-12 13:38:00", tz_offset=-1):
            job_app2.accept(user=user2)

        client.force_login(user1)

        url = reverse("apply:details_for_company", kwargs={"job_application_id": job_app1.pk})
        response = client.get(url)
        html_fragment = self._get_transition_logs_content(response, job_app1)

        assert str(html_fragment) == snapshot

    def test_details_for_job_seeker_when_refused(self, client):
        job_application = JobApplicationFactory(
            sent_by_authorized_prescriber_organisation=True,
            state=job_applications_enums.JobApplicationState.REFUSED,
            answer="abc",
            answer_to_prescriber="undisclosed",
            refusal_reason="other",
        )
        client.force_login(job_application.job_seeker)
        url = reverse("apply:details_for_jobseeker", kwargs={"job_application_id": job_application.pk})
        response = client.get(url)
        assertNotContains(response, self.REFUSAL_REASON_JOB_SEEKER_MENTION, html=True)
        assertNotContains(response, self.REFUSAL_REASON_SHARED_MENTION, html=True)
        assertNotContains(response, self.REFUSAL_REASON_NOT_SHARED_MENTION, html=True)
        assertContains(response, "<small>Message envoyé au candidat</small>", html=True)
        assertContains(response, f"<p>{job_application.answer}</p>", html=True)
        assertNotContains(response, "<small>Commentaire privé de l'employeur</small>")
        assertNotContains(response, f"<p>{job_application.answer_to_prescriber}</p>", html=True)

        # Test with refusal reason shared with job seeker
        job_application.refusal_reason_shared_with_job_seeker = True
        job_application.save()
        response = client.get(url)
        assertContains(response, self.REFUSAL_REASON_JOB_SEEKER_MENTION, html=True)
        assertNotContains(response, self.REFUSAL_REASON_SHARED_MENTION, html=True)
        assertNotContains(response, self.REFUSAL_REASON_NOT_SHARED_MENTION, html=True)

    def test_details_for_prescriber_when_refused(self, client):
        job_application = JobApplicationFactory(
            sent_by_authorized_prescriber_organisation=True,
            state=job_applications_enums.JobApplicationState.REFUSED,
            answer="abc",
            answer_to_prescriber="undisclosed",
            refusal_reason="other",
        )
        prescriber = job_application.sender_prescriber_organization.members.first()
        client.force_login(prescriber)
        url = reverse("apply:details_for_prescriber", kwargs={"job_application_id": job_application.pk})
        response = client.get(url)
        assertNotContains(response, self.REFUSAL_REASON_JOB_SEEKER_MENTION, html=True)
        assertNotContains(response, self.REFUSAL_REASON_SHARED_MENTION, html=True)
        assertContains(response, self.REFUSAL_REASON_NOT_SHARED_MENTION, html=True)
        assertContains(response, "<small>Message envoyé au candidat</small>", html=True)
        assertContains(response, f"<p>{job_application.answer}</p>", html=True)
        assertContains(response, "<small>Commentaire privé de l'employeur</small>")
        assertContains(response, f"<p>{job_application.answer_to_prescriber}</p>", html=True)

        # Test with refusal reason shared with job seeker
        job_application.refusal_reason_shared_with_job_seeker = True
        job_application.save()
        response = client.get(url)
        assertNotContains(response, self.REFUSAL_REASON_JOB_SEEKER_MENTION, html=True)
        assertContains(response, self.REFUSAL_REASON_SHARED_MENTION, html=True)
        assertNotContains(response, self.REFUSAL_REASON_NOT_SHARED_MENTION, html=True)

    def test_details_for_company_when_refused(self, client):
        job_application = JobApplicationFactory(
            sent_by_authorized_prescriber_organisation=True,
            state=job_applications_enums.JobApplicationState.REFUSED,
            answer="abc",
            answer_to_prescriber="undisclosed",
            refusal_reason="other",
        )
        employer = job_application.to_company.members.first()
        client.force_login(employer)
        url = reverse("apply:details_for_company", kwargs={"job_application_id": job_application.pk})
        response = client.get(url)
        assertNotContains(response, self.REFUSAL_REASON_JOB_SEEKER_MENTION, html=True)
        assertNotContains(response, self.REFUSAL_REASON_SHARED_MENTION, html=True)
        assertContains(response, self.REFUSAL_REASON_NOT_SHARED_MENTION, html=True)
        assertContains(response, "<small>Message envoyé au candidat</small>", html=True)
        assertContains(response, f"<p>{job_application.answer}</p>", html=True)
        assertContains(response, "<small>Commentaire privé de l'employeur</small>")
        assertContains(response, f"<p>{job_application.answer_to_prescriber}</p>", html=True)

        # Test with refusal reason shared with job seeker
        job_application.refusal_reason_shared_with_job_seeker = True
        job_application.save()
        response = client.get(url)
        assertNotContains(response, self.REFUSAL_REASON_JOB_SEEKER_MENTION, html=True)
        assertContains(response, self.REFUSAL_REASON_SHARED_MENTION, html=True)
        assertNotContains(response, self.REFUSAL_REASON_NOT_SHARED_MENTION, html=True)

    def test_company_information_displayed_for_prescriber_when_refused(self, client, subtests):
        """
        As a prescriber, the company's contact details are displayed
        when the application is refused for the "other" reason
        """

        job_application = JobApplicationFactory(
            to_company__with_membership=True,
            to_company__email="refused_job_application@example.com",
            sent_by_authorized_prescriber_organisation=True,
            state=job_applications_enums.JobApplicationState.REFUSED,
            answer="abc",
            answer_to_prescriber="undisclosed",
            refusal_reason=job_applications_enums.RefusalReason.OTHER,
        )
        prescriber = job_application.sender_prescriber_organization.members.first()
        client.force_login(prescriber)
        url = reverse("apply:details_for_prescriber", kwargs={"job_application_id": job_application.pk})

        with subtests.test("Test without workflow logging"):
            response = client.get(url)
            assert response.context["display_refusal_info"]
            assert response.context["refused_by"] is None
            assert response.context["refusal_contact_email"] == "refused_job_application@example.com"
            assertContains(response, REFUSED_JOB_APPLICATION_PRESCRIBER_SECTION_TITLE)
            assertContains(response, REFUSED_JOB_APPLICATION_PRESCRIBER_SECTION_BODY)

        with subtests.test("Test with the log of the workflow to retrieve the user who refused the application"):
            company_user = job_application.to_company.members.first()
            job_application.logs.create(
                transition=JobApplicationWorkflow.TRANSITION_REFUSE,
                from_state=job_applications_enums.JobApplicationState.NEW,
                to_state=job_applications_enums.JobApplicationState.REFUSED,
                user=company_user,
            )
            url = reverse("apply:details_for_prescriber", kwargs={"job_application_id": job_application.pk})
            response = client.get(url)
            assert response.context["display_refusal_info"]
            assert response.context["refused_by"] == company_user
            assert response.context["refusal_contact_email"] == company_user.email
            assertContains(response, REFUSED_JOB_APPLICATION_PRESCRIBER_SECTION_TITLE)
            assertContains(response, REFUSED_JOB_APPLICATION_PRESCRIBER_SECTION_BODY)

        # With any other reason, the section should not be displayed
        for refusal_reason in job_applications_enums.RefusalReason.values:
            if refusal_reason == job_applications_enums.RefusalReason.OTHER:
                continue
            with subtests.test("Test all other refused reasons", refusal_reason=refusal_reason):
                job_application.refusal_reason = refusal_reason
                job_application.save()
                url = reverse("apply:details_for_prescriber", kwargs={"job_application_id": job_application.pk})
                response = client.get(url)
                assert not response.context["display_refusal_info"]
                assert response.context["refused_by"] is None
                assert response.context["refusal_contact_email"] == ""
                assertNotContains(response, REFUSED_JOB_APPLICATION_PRESCRIBER_SECTION_TITLE)
                assertNotContains(response, REFUSED_JOB_APPLICATION_PRESCRIBER_SECTION_BODY)

    def test_company_information_not_displayed_for_job_seeker_when_refused(self, client):
        """As a job seeker, I can't see the company's contact details when the application is refused"""

        job_application = JobApplicationFactory(
            to_company__with_membership=True,
            to_company__email="refused_job_application@example.com",
            sent_by_authorized_prescriber_organisation=True,
            state=job_applications_enums.JobApplicationState.REFUSED,
            answer="abc",
            answer_to_prescriber="undisclosed",
            refusal_reason=job_applications_enums.RefusalReason.OTHER,
        )
        client.force_login(job_application.job_seeker)
        url = reverse("apply:details_for_jobseeker", kwargs={"job_application_id": job_application.pk})
        response = client.get(url)
        assert not response.context["display_refusal_info"]
        assert "refused_by" not in response.context
        assert "refusal_contact_email" not in response.context
        assertNotContains(response, REFUSED_JOB_APPLICATION_PRESCRIBER_SECTION_TITLE)
        assertNotContains(response, REFUSED_JOB_APPLICATION_PRESCRIBER_SECTION_BODY)

    def test_company_information_not_displayed_for_company_when_refused(self, client):
        """As the company's employee, I don't see my own company's contact details when the application is refused"""

        job_application = JobApplicationFactory(
            to_company__with_membership=True,
            to_company__email="refused_job_application@example.com",
            sent_by_authorized_prescriber_organisation=True,
            state=job_applications_enums.JobApplicationState.REFUSED,
            answer="abc",
            answer_to_prescriber="undisclosed",
            refusal_reason=job_applications_enums.RefusalReason.OTHER,
        )
        client.force_login(job_application.to_company.members.first())
        url = reverse("apply:details_for_company", kwargs={"job_application_id": job_application.pk})
        response = client.get(url)
        assert not response.context["display_refusal_info"]
        assert "refused_by" not in response.context
        assert "refusal_contact_email" not in response.context
        assertNotContains(response, REFUSED_JOB_APPLICATION_PRESCRIBER_SECTION_TITLE)
        assertNotContains(response, REFUSED_JOB_APPLICATION_PRESCRIBER_SECTION_BODY)

    def test_process(self, client):
        """Ensure that the `process` transition is triggered."""

        job_application = JobApplicationFactory(sent_by_authorized_prescriber_organisation=True)
        employer = job_application.to_company.members.first()
        client.force_login(employer)

        url = reverse("apply:process", kwargs={"job_application_id": job_application.pk})
        response = client.post(url)
        next_url = reverse("apply:details_for_company", kwargs={"job_application_id": job_application.pk})
        assertRedirects(response, next_url)

        job_application = JobApplication.objects.get(pk=job_application.pk)
        assert job_application.state.is_processing

    def test_refuse_session_prefix(self, client):
        """Ensure that each refusal session is isolated from each other."""

        job_application = JobApplicationFactory()
        employer = job_application.to_company.members.first()
        client.force_login(employer)

        url = reverse("apply:refuse", kwargs={"job_application_id": job_application.pk})
        response = client.get(url)

        refuse_session_name = get_session_name(client.session, RefuseWizardView.expected_session_kind)
        assert client.session[refuse_session_name] == {
            "config": {
                "tunnel": "single",
                "reset_url": reverse("apply:details_for_company", kwargs={"job_application_id": job_application.pk}),
            },
            "application_ids": [job_application.pk],
        }
        refusal_reason_url = reverse(
            "apply:batch_refuse_steps", kwargs={"session_uuid": refuse_session_name, "step": "reason"}
        )
        assertRedirects(response, refusal_reason_url)

        post_data = {
            "refusal_reason": job_applications_enums.RefusalReason.HIRED_ELSEWHERE,
        }
        client.post(refusal_reason_url, data=post_data)
        expected_session = {
            "config": {
                "tunnel": "single",
                "reset_url": reverse("apply:details_for_company", kwargs={"job_application_id": job_application.pk}),
            },
            "application_ids": [job_application.pk],
            "reason": {
                "refusal_reason": job_applications_enums.RefusalReason.HIRED_ELSEWHERE,
                "refusal_reason_shared_with_job_seeker": False,
            },
        }
        assert client.session[refuse_session_name] == expected_session

        # Check that the user can start and other refusal wizard/session
        job_application_2 = JobApplicationFactory(to_company=job_application.to_company)
        url = reverse("apply:refuse", kwargs={"job_application_id": job_application_2.pk})
        response = client.get(url)

        refuse_session_name_2 = get_session_name(
            client.session, RefuseWizardView.expected_session_kind, ignore=[refuse_session_name]
        )
        refusal_reason_url_2 = reverse(
            "apply:batch_refuse_steps", kwargs={"session_uuid": refuse_session_name_2, "step": "reason"}
        )
        assertRedirects(response, refusal_reason_url_2)
        post_data = {
            "refusal_reason": job_applications_enums.RefusalReason.NON_ELIGIBLE,
        }
        client.post(refusal_reason_url_2, data=post_data)
        assert client.session[refuse_session_name_2] == {
            "config": {
                "tunnel": "single",
                "reset_url": reverse("apply:details_for_company", kwargs={"job_application_id": job_application_2.pk}),
            },
            "application_ids": [job_application_2.pk],
            "reason": {
                "refusal_reason": job_applications_enums.RefusalReason.NON_ELIGIBLE,
                "refusal_reason_shared_with_job_seeker": False,
            },
        }
        # Session for 1st application is still here & untouched
        assert refuse_session_name in client.session
        assert client.session[refuse_session_name] == expected_session

    def test_refuse_from_prescriber(self, client):
        """Ensure that the `refuse` transition is triggered through the expected workflow for a prescriber."""

        state = random.choice(JobApplicationWorkflow.CAN_BE_REFUSED_STATES)
        reason, reason_label = random.choice(job_applications_enums.RefusalReason.displayed_choices())
        job_application = JobApplicationFactory(sent_by_authorized_prescriber_organisation=True, state=state)
        employer = job_application.to_company.members.first()
        client.force_login(employer)

        response = client.get(reverse("apply:refuse", kwargs={"job_application_id": job_application.pk}), follow=True)
        refuse_session_name = get_session_name(client.session, RefuseWizardView.expected_session_kind)
        refusal_reason_url = reverse(
            "apply:batch_refuse_steps", kwargs={"session_uuid": refuse_session_name, "step": "reason"}
        )
        assertRedirects(response, refusal_reason_url)
        assertContains(response, "<strong>Étape 1</strong>/3 : Choix du motif de refus", html=True)
        assert response.context["matomo_custom_title"] == "Candidature refusée"
        assert response.context["matomo_event_name"] == "batch-refuse-application-reason-submit"

        post_data = {
            "refusal_reason": reason,
            "refusal_reason_shared_with_job_seeker": True,
        }
        response = client.post(refusal_reason_url, data=post_data, follow=True)
        job_seeker_answer_url = reverse(
            "apply:batch_refuse_steps", kwargs={"session_uuid": refuse_session_name, "step": "job-seeker-answer"}
        )
        assertRedirects(response, job_seeker_answer_url)
        assertContains(response, "<strong>Étape 2</strong>/3 : Message au candidat", html=True)
        assertContains(response, "Réponse au candidat")
        assertContains(response, f"<strong>Motif de refus :</strong> {reason_label}", html=True)
        assert response.context["matomo_custom_title"] == "Candidature refusée"
        assert response.context["matomo_event_name"] == "batch-refuse-application-job-seeker-answer-submit"

        post_data = {
            "job_seeker_answer": "Message au candidat",
        }
        response = client.post(job_seeker_answer_url, data=post_data, follow=True)
        prescriber_answer_url = reverse(
            "apply:batch_refuse_steps", kwargs={"session_uuid": refuse_session_name, "step": "prescriber-answer"}
        )
        assertRedirects(response, prescriber_answer_url)
        assertContains(response, "<strong>Étape 3</strong>/3 : Message au prescripteur", html=True)
        assertContains(response, "Réponse au prescripteur")
        assertContains(response, f"<strong>Motif de refus :</strong> {reason_label}", html=True)
        assert response.context["matomo_custom_title"] == "Candidature refusée"
        assert response.context["matomo_event_name"] == "batch-refuse-application-prescriber-answer-submit"

        post_data = {
            "prescriber_answer": "Message au prescripteur",
        }
        response = client.post(prescriber_answer_url, data=post_data, follow=True)
        assertRedirects(
            response, reverse("apply:details_for_company", kwargs={"job_application_id": job_application.pk})
        )

        job_application = JobApplication.objects.get(pk=job_application.pk)
        assert job_application.state.is_refused
        assert job_application.answer == "Message au candidat"
        assert job_application.answer_to_prescriber == "Message au prescripteur"

    def test_refuse_from_job_seeker(self, client):
        """Ensure that the `refuse` transition is triggered through the expected workflow for a job seeker."""

        state = random.choice(JobApplicationWorkflow.CAN_BE_REFUSED_STATES)
        reason, reason_label = random.choice(job_applications_enums.RefusalReason.displayed_choices())
        job_application = JobApplicationSentByJobSeekerFactory(state=state)
        employer = job_application.to_company.members.first()
        client.force_login(employer)

        refusal_reason_url = reverse("apply:refuse", kwargs={"job_application_id": job_application.pk})
        response = client.get(refusal_reason_url, follow=True)
        refuse_session_name = get_session_name(client.session, RefuseWizardView.expected_session_kind)
        refusal_reason_url = reverse(
            "apply:batch_refuse_steps", kwargs={"session_uuid": refuse_session_name, "step": "reason"}
        )
        assertRedirects(response, refusal_reason_url)
        assertContains(response, "<strong>Étape 1</strong>/2 : Choix du motif de refus", html=True)
        assert response.context["matomo_custom_title"] == "Candidature refusée"
        assert response.context["matomo_event_name"] == "batch-refuse-application-reason-submit"

        post_data = {
            "refusal_reason": reason,
            "refusal_reason_shared_with_job_seeker": False,
        }
        response = client.post(refusal_reason_url, data=post_data, follow=True)
        job_seeker_answer_url = reverse(
            "apply:batch_refuse_steps", kwargs={"session_uuid": refuse_session_name, "step": "job-seeker-answer"}
        )
        assertRedirects(response, job_seeker_answer_url)
        assertContains(response, "<strong>Étape 2</strong>/2 : Message au candidat", html=True)
        assertContains(response, "Réponse au candidat")
        assertContains(
            response,
            f"<strong>Motif de refus :</strong> {reason_label} <em>(Motif non communiqué au candidat)</em>",
            html=True,
        )
        assert response.context["matomo_custom_title"] == "Candidature refusée"
        assert response.context["matomo_event_name"] == "batch-refuse-application-job-seeker-answer-submit"

        post_data = {
            "job_seeker_answer": "Message au candidat",
        }
        response = client.post(job_seeker_answer_url, data=post_data, follow=True)
        assertRedirects(
            response, reverse("apply:details_for_company", kwargs={"job_application_id": job_application.pk})
        )

        job_application = JobApplication.objects.get(pk=job_application.pk)
        assert job_application.state.is_refused
        assert job_application.answer == "Message au candidat"

    def test_refuse_labels_for_prescriber_or_orienteur(self, client):
        """
        Ensure that the `refuse` is correctly adapted for prescribers depending their status:
        - Authorized prescriber: labeled "prescripteur"
        - Unauthorized prescriber: labeled "orienteur"
        - Prescriber with no organizations: labeled "orienteur"
        """
        job_application = JobApplicationFactory(sent_by_authorized_prescriber_organisation=True)
        employer = job_application.to_company.members.first()
        client.force_login(employer)

        response = client.get(reverse("apply:refuse", kwargs={"job_application_id": job_application.pk}))

        refuse_session_name = get_session_name(client.session, RefuseWizardView.expected_session_kind)
        refusal_reason_url = reverse(
            "apply:batch_refuse_steps", kwargs={"session_uuid": refuse_session_name, "step": "reason"}
        )
        assertRedirects(response, refusal_reason_url)
        response = client.get(refusal_reason_url)
        assertContains(
            response,
            "la transparence sur les motifs de refus est importante pour le candidat comme pour le prescripteur.",
        )
        assertContains(response, "Choisir le motif de refus envoyé au prescripteur")
        assertContains(response, "Autre (détails à fournir dans le message au prescripteur)", html=True)

        post_data = {
            "refusal_reason": job_applications_enums.RefusalReason.OTHER,
        }
        response = client.post(refusal_reason_url, data=post_data, follow=True)
        job_seeker_answer_url = reverse(
            "apply:batch_refuse_steps", kwargs={"session_uuid": refuse_session_name, "step": "job-seeker-answer"}
        )
        assertRedirects(response, job_seeker_answer_url)
        assertContains(response, "Une copie de ce message sera adressée au prescripteur.")

        post_data = {
            "job_seeker_answer": "Message au candidat",
        }
        response = client.post(job_seeker_answer_url, data=post_data, follow=True)
        prescriber_answer_url = reverse(
            "apply:batch_refuse_steps", kwargs={"session_uuid": refuse_session_name, "step": "prescriber-answer"}
        )
        assertRedirects(response, prescriber_answer_url)
        assertContains(response, "<strong>Étape 3</strong>/3 : Message au prescripteur", html=True)
        assertContains(response, "Réponse au prescripteur")
        assertContains(response, "Vous pouvez partager un message au prescripteur uniquement")
        assertContains(response, "Commentaire envoyé au prescripteur (n’est pas communiqué au candidat)")

        # Un-authorize prescriber (ie. considered as "orienteur")
        job_application.sender_prescriber_organization.authorization_status = PrescriberAuthorizationStatus.REFUSED
        job_application.sender_prescriber_organization.save(update_fields=["authorization_status", "updated_at"])

        response = client.get(refusal_reason_url)
        assertContains(
            response,
            "la transparence sur les motifs de refus est importante pour le candidat comme pour l’orienteur.",
        )
        assertContains(response, "Choisir le motif de refus envoyé à l’orienteur")
        assertContains(response, "Autre (détails à fournir dans le message à l’orienteur)", html=True)

        response = client.get(job_seeker_answer_url)
        assertContains(response, "Une copie de ce message sera adressée à l’orienteur.")

        response = client.get(prescriber_answer_url)
        assertContains(response, "<strong>Étape 3</strong>/3 : Message à l’orienteur", html=True)
        assertContains(response, "Réponse à l’orienteur")
        assertContains(response, "Vous pouvez partager un message à l’orienteur uniquement")
        assertContains(response, "Commentaire envoyé à l’orienteur (n’est pas communiqué au candidat)")

        # Remove prescriber's organization membership (ie. considered as "orienteur solo")
        job_application.sender_prescriber_organization.members.clear()
        job_application.sender_prescriber_organization = None
        job_application.save(update_fields=["sender_prescriber_organization", "updated_at"])

        response = client.get(refusal_reason_url)
        assertContains(
            response,
            "la transparence sur les motifs de refus est importante pour le candidat comme pour l’orienteur.",
        )
        assertContains(response, "Choisir le motif de refus envoyé à l’orienteur")
        assertContains(response, "Autre (détails à fournir dans le message à l’orienteur)", html=True)

        response = client.get(job_seeker_answer_url)
        assertContains(response, "Une copie de ce message sera adressée à l’orienteur.")

        response = client.get(prescriber_answer_url)
        assertContains(response, "<strong>Étape 3</strong>/3 : Message à l’orienteur", html=True)
        assertContains(response, "Réponse à l’orienteur")
        assertContains(response, "Vous pouvez partager un message à l’orienteur uniquement")
        assertContains(response, "Commentaire envoyé à l’orienteur (n’est pas communiqué au candidat)")

    def test_refuse_incompatible_state(self, client):
        job_application = JobApplicationFactory(
            job_seeker__first_name="Jean",
            job_seeker__last_name="Bond",
            sent_by_authorized_prescriber_organisation=True,
            state=job_applications_enums.JobApplicationState.ACCEPTED,
        )
        employer = job_application.to_company.members.first()
        client.force_login(employer)

        url = reverse("apply:refuse", kwargs={"job_application_id": job_application.pk})
        response = client.get(url)
        next_url = reverse("apply:details_for_company", kwargs={"job_application_id": job_application.pk})
        assertRedirects(response, next_url)
        assertMessages(
            response,
            [
                messages.Message(
                    messages.ERROR,
                    (
                        "La candidature de Jean BOND ne peut pas être refusée car elle est au statut "
                        "«\u202fCandidature acceptée\u202f»."
                    ),
                )
            ],
        )

        job_application.refresh_from_db()
        assert not job_application.state.is_refused

    def test_refuse_already_refused(self, client):
        job_application = JobApplicationFactory(
            job_seeker__first_name="Jean",
            job_seeker__last_name="Bond",
            sent_by_authorized_prescriber_organisation=True,
            state=job_applications_enums.JobApplicationState.REFUSED,
        )
        employer = job_application.to_company.members.first()
        client.force_login(employer)

        url = reverse("apply:refuse", kwargs={"job_application_id": job_application.pk})
        response = client.get(url)
        next_url = reverse("apply:details_for_company", kwargs={"job_application_id": job_application.pk})
        assertRedirects(response, next_url)
        assertMessages(
            response,
            [
                messages.Message(
                    messages.ERROR,
                    (
                        "La candidature de Jean BOND ne peut pas être refusée car elle est au statut "
                        "«\u202fCandidature déclinée\u202f»."
                    ),
                )
            ],
        )

        job_application.refresh_from_db()
        assert job_application.state.is_refused

    def test_refuse_step_bypass(self, client):
        job_application = JobApplicationFactory(
            sent_by_authorized_prescriber_organisation=True,
            state=job_applications_enums.JobApplicationState.NEW,
        )
        employer = job_application.to_company.members.first()
        client.force_login(employer)

        refusal_reason_url = reverse("apply:refuse", kwargs={"job_application_id": job_application.pk})
        response = client.get(refusal_reason_url, follow=True)
        refuse_session_name = get_session_name(client.session, RefuseWizardView.expected_session_kind)
        refusal_reason_url = reverse(
            "apply:batch_refuse_steps", kwargs={"session_uuid": refuse_session_name, "step": "reason"}
        )
        assertRedirects(response, refusal_reason_url)
        job_seeker_answer_url = reverse(
            "apply:batch_refuse_steps", kwargs={"session_uuid": refuse_session_name, "step": "job-seeker-answer"}
        )
        response = client.get(job_seeker_answer_url)
        # Trying to access step 2 without providing data for step 1 redirects to step 1
        assertRedirects(response, refusal_reason_url)

    def test_postpone_from_prescriber(self, client, snapshot, mailoutbox, subtests):
        """Ensure that the `postpone` transition is triggered."""

        states = [
            job_applications_enums.JobApplicationState.PROCESSING,
            job_applications_enums.JobApplicationState.PRIOR_TO_HIRE,
        ]

        job_seeker = JobSeekerFactory(for_snapshot=True)
        company = CompanyFactory(for_snapshot=True, with_membership=True)

        for state in states:
            mailoutbox.clear()
            with subtests.test(state=state.label):
                job_application = JobApplicationFactory(
                    job_seeker=job_seeker,
                    to_company=company,
                    sent_by_authorized_prescriber_organisation=True,
                    state=state,
                )
                employer = job_application.to_company.members.first()
                client.force_login(employer)

                url = reverse("apply:postpone", kwargs={"job_application_id": job_application.pk})
                response = client.get(url)
                assert response.status_code == 200

                post_data = {"answer": ""}
                response = client.post(url, data=post_data)
                next_url = reverse("apply:details_for_company", kwargs={"job_application_id": job_application.pk})
                assertRedirects(response, next_url)

                job_application = JobApplication.objects.get(pk=job_application.pk)
                assert job_application.state.is_postponed

                [mail_to_job_seeker, mail_to_prescriber] = mailoutbox
                assert mail_to_job_seeker.to == [job_application.job_seeker.email]
                assert mail_to_job_seeker.subject == snapshot(name="postpone_email_to_job_seeker_subject")
                assert mail_to_job_seeker.body == snapshot(name="postpone_email_to_job_seeker_body")
                assert mail_to_prescriber.to == [job_application.sender.email]
                assert mail_to_prescriber.subject == snapshot(name="postpone_email_to_proxy_subject")
                assert mail_to_prescriber.body == snapshot(name="postpone_email_to_proxy_body")

    def test_postpone_from_job_seeker(self, client, snapshot, mailoutbox, subtests):
        """Ensure that the `postpone` transition is triggered."""

        states = [
            job_applications_enums.JobApplicationState.PROCESSING,
            job_applications_enums.JobApplicationState.PRIOR_TO_HIRE,
        ]

        job_seeker = JobSeekerFactory(for_snapshot=True)
        company = CompanyFactory(for_snapshot=True, with_membership=True)

        for state in states:
            mailoutbox.clear()
            with subtests.test(state=state.label):
                job_application = JobApplicationFactory(
                    job_seeker=job_seeker,
                    to_company=company,
                    sender_kind=SenderKind.JOB_SEEKER,
                    sender=job_seeker,
                    state=state,
                )
                employer = job_application.to_company.members.first()
                client.force_login(employer)

                url = reverse("apply:postpone", kwargs={"job_application_id": job_application.pk})
                response = client.get(url)
                assert response.status_code == 200

                post_data = {"answer": "On vous rappellera."}
                response = client.post(url, data=post_data)
                next_url = reverse("apply:details_for_company", kwargs={"job_application_id": job_application.pk})
                assertRedirects(response, next_url)

                job_application = JobApplication.objects.get(pk=job_application.pk)
                assert job_application.state.is_postponed
                [mail_to_job_seeker] = mailoutbox
                assert mail_to_job_seeker.to == [job_application.job_seeker.email]
                assert mail_to_job_seeker.subject == snapshot(name="postpone_email_to_job_seeker_subject")
                assert mail_to_job_seeker.body == snapshot(name="postpone_email_to_job_seeker_body")

    def test_postpone_from_employer_orienter(self, client, snapshot, mailoutbox, subtests):
        """Ensure that the `postpone` transition is triggered."""

        states = [
            job_applications_enums.JobApplicationState.PROCESSING,
            job_applications_enums.JobApplicationState.PRIOR_TO_HIRE,
        ]

        job_seeker = JobSeekerFactory(for_snapshot=True)
        company = CompanyFactory(for_snapshot=True, with_membership=True)

        for state in states:
            mailoutbox.clear()
            with subtests.test(state=state.label):
                job_application = JobApplicationFactory(
                    job_seeker=job_seeker,
                    to_company=company,
                    sent_by_another_employer=True,
                    state=state,
                )
                employer = job_application.to_company.members.first()
                client.force_login(employer)

                url = reverse("apply:postpone", kwargs={"job_application_id": job_application.pk})
                response = client.get(url)
                assert response.status_code == 200

                post_data = {"answer": "On vous rappellera."}
                response = client.post(url, data=post_data)
                next_url = reverse("apply:details_for_company", kwargs={"job_application_id": job_application.pk})
                assertRedirects(response, next_url)

                job_application = JobApplication.objects.get(pk=job_application.pk)
                assert job_application.state.is_postponed
                [mail_to_job_seeker, mail_to_other_employer] = mailoutbox
                assert mail_to_job_seeker.to == [job_application.job_seeker.email]
                assert mail_to_job_seeker.subject == snapshot(name="postpone_email_to_job_seeker_subject")
                assert mail_to_job_seeker.body == snapshot(name="postpone_email_to_job_seeker_body")
                assert mail_to_other_employer.to == [job_application.sender.email]
                assert mail_to_other_employer.subject == snapshot(name="postpone_email_to_proxy_subject")
                assert mail_to_other_employer.body == snapshot(name="postpone_email_to_proxy_body")

    def test_eligibility(self, client):
        """Test eligibility."""
        job_application = JobApplicationSentByPrescriberOrganizationFactory(
            state=job_applications_enums.JobApplicationState.PROCESSING,
            job_seeker=JobSeekerFactory(with_address_in_qpv=True),
            eligibility_diagnosis=None,
        )

        assert job_application.state.is_processing
        employer = job_application.to_company.members.first()
        client.force_login(employer)

        has_considered_valid_diagnoses = EligibilityDiagnosis.objects.has_considered_valid(
            job_application.job_seeker, for_siae=job_application.to_company
        )
        assert not has_considered_valid_diagnoses

        criterion1 = AdministrativeCriteria.objects.level1().get(pk=1)
        criterion2 = AdministrativeCriteria.objects.level2().get(pk=5)
        criterion3 = AdministrativeCriteria.objects.level2().get(pk=15)

        url = reverse("apply:eligibility", kwargs={"job_application_id": job_application.pk})
        response = client.get(url)
        assert response.status_code == 200
        assertTemplateUsed(response, "apply/includes/known_criteria.html", count=1)

        # Ensure that some criteria are mandatory.
        post_data = {
            f"{criterion1.key}": "false",
        }
        response = client.post(url, data=post_data)
        assert response.status_code == 200
        assert response.context["form"].errors

        post_data = {
            # Administrative criteria level 1.
            f"{criterion1.key}": "true",
            # Administrative criteria level 2.
            f"{criterion2.key}": "true",
            f"{criterion3.key}": "true",
        }
        response = client.post(url, data=post_data)
        next_url = reverse("apply:accept", kwargs={"job_application_id": job_application.pk})
        assertRedirects(response, next_url)

        has_considered_valid_diagnoses = EligibilityDiagnosis.objects.has_considered_valid(
            job_application.job_seeker, for_siae=job_application.to_company
        )
        assert has_considered_valid_diagnoses

        # Check diagnosis.
        eligibility_diagnosis = job_application.get_eligibility_diagnosis()
        assert eligibility_diagnosis.author == employer
        assert eligibility_diagnosis.author_kind == AuthorKind.EMPLOYER
        assert eligibility_diagnosis.author_siae == job_application.to_company
        # Check administrative criteria.
        administrative_criteria = eligibility_diagnosis.administrative_criteria.all()
        assert 3 == administrative_criteria.count()
        assert criterion1 in administrative_criteria
        assert criterion2 in administrative_criteria
        assert criterion3 in administrative_criteria

    def test_eligibility_for_company_not_subject_to_eligibility_rules(self, client):
        """Test eligibility for a company not subject to eligibility rules."""

        job_application = JobApplicationFactory(
            sent_by_authorized_prescriber_organisation=True,
            state=job_applications_enums.JobApplicationState.PROCESSING,
            to_company__kind=CompanyKind.GEIQ,
        )
        employer = job_application.to_company.members.first()
        client.force_login(employer)

        url = reverse("apply:eligibility", kwargs={"job_application_id": job_application.pk})
        response = client.get(url)
        assert response.status_code == 404

    def test_eligibility_for_siae_with_suspension_sanction(self, client):
        """Test eligibility for an Siae that has been suspended."""

        job_application = JobApplicationSentByPrescriberOrganizationFactory(
            state=job_applications_enums.JobApplicationState.PROCESSING,
            job_seeker=JobSeekerFactory(with_address=True),
        )
        Sanctions.objects.create(
            evaluated_siae=EvaluatedSiaeFactory(siae=job_application.to_company),
            suspension_dates=InclusiveDateRange(timezone.localdate()),
        )

        employer = job_application.to_company.members.first()
        client.force_login(employer)

        url = reverse("apply:eligibility", kwargs={"job_application_id": job_application.pk})
        response = client.get(url)
        assertContains(response, "suite aux mesures prises dans le cadre du contrôle a posteriori", status_code=403)

    def test_eligibility_state_for_job_application(self, client):
        """The eligibility diagnosis page must only be accessible
        in JobApplicationWorkflow.CAN_BE_ACCEPTED_STATES states."""
        company = CompanyFactory(with_membership=True)
        employer = company.members.first()
        job_application = JobApplicationSentByJobSeekerFactory(
            to_company=company, job_seeker=JobSeekerFactory(with_address=True)
        )

        # Right states
        for state in JobApplicationWorkflow.CAN_BE_ACCEPTED_STATES:
            job_application.state = state
            if state in JobApplicationWorkflow.JOB_APPLICATION_PROCESSED_STATES:
                job_application.processed_at = timezone.now()
            job_application.save()
            client.force_login(employer)
            url = reverse("apply:eligibility", kwargs={"job_application_id": job_application.pk})
            response = client.get(url)
            assert response.status_code == 200
            client.logout()

        # Wrong state
        job_application.state = job_applications_enums.JobApplicationState.ACCEPTED
        job_application.processed_at = timezone.now()
        job_application.save()
        client.force_login(employer)
        url = reverse("apply:eligibility", kwargs={"job_application_id": job_application.pk})
        response = client.get(url)
        assert response.status_code == 404
        client.logout()

    @pytest.mark.parametrize(
        "eligibility_trait,expected_msg",
        [
            ("subject_to_eligibility", IAE_CANCELLATION_CONFIRMATION),
            ("not_subject_to_eligibility", NON_IAE_CANCELLATION_CONFIRMATION),
        ],
    )
    def test_cancel(self, client, eligibility_trait, expected_msg):
        # Hiring date is today: cancellation should be possible.
        job_application = JobApplicationFactory(with_approval=True, **{f"to_company__{eligibility_trait}": True})
        employer = job_application.to_company.members.first()
        client.force_login(employer)
        detail_url = reverse("apply:details_for_company", kwargs={"job_application_id": job_application.pk})
        cancel_url = reverse("apply:cancel", kwargs={"job_application_id": job_application.pk})
        response = client.get(detail_url)
        assertContains(response, "Confirmer l’annulation de l’embauche")
        for msg in [IAE_CANCELLATION_CONFIRMATION, NON_IAE_CANCELLATION_CONFIRMATION]:
            if msg == expected_msg:
                assertContains(response, msg)
            else:
                assertNotContains(response, msg)

        response = client.post(cancel_url)
        next_url = reverse("apply:details_for_company", kwargs={"job_application_id": job_application.pk})
        assertRedirects(response, next_url)

        job_application.refresh_from_db()
        assert job_application.state.is_cancelled
        assertMessages(response, [messages.Message(messages.SUCCESS, "L'embauche a bien été annulée.")])

    def test_cancel_clean_back_url(self, client):
        job_application = JobApplicationFactory(with_approval=True, to_company__subject_to_eligibility=True)
        employer = job_application.to_company.members.first()
        client.force_login(employer)

        employee_url = reverse("employees:detail", args=(job_application.job_seeker.public_id,))
        response = client.get(employee_url)

        detail_url = reverse("apply:details_for_company", kwargs={"job_application_id": job_application.pk})
        detail_url_with_back_url = f"{detail_url}?back_url={urlencode_filter(employee_url)}"
        assertContains(response, detail_url_with_back_url)

        client.get(detail_url_with_back_url)
        assertContains(response, employee_url)

        cancel_url = reverse("apply:cancel", kwargs={"job_application_id": job_application.pk})
        response = client.post(cancel_url)
        assertRedirects(response, detail_url)

        response = client.get(detail_url)
        # employee_url is not available anymore so we cleaned it
        assertNotContains(response, employee_url)

    def test_cannot_cancel(self, client):
        job_application = JobApplicationFactory(
            with_approval=True,
            hiring_start_at=timezone.localdate() + relativedelta(days=1),
        )
        employer = job_application.to_company.members.first()
        # Add a blocking employee record
        EmployeeRecordTransitionLog.log_transition(
            transition=factory.fuzzy.FuzzyChoice(EmployeeRecordTransition.without_asp_exchange()),
            from_state=factory.fuzzy.FuzzyChoice(Status),
            to_state=factory.fuzzy.FuzzyChoice(Status),
            modified_object=EmployeeRecordFactory(job_application=job_application, status=Status.PROCESSED),
        )

        client.force_login(employer)
        detail_url = reverse("apply:details_for_company", kwargs={"job_application_id": job_application.pk})
        cancel_url = reverse("apply:cancel", kwargs={"job_application_id": job_application.pk})
        response = client.get(detail_url)
        assertNotContains(response, "Confirmer l’annulation de l’embauche")
        assertNotContains(response, IAE_CANCELLATION_CONFIRMATION)
        assertNotContains(response, NON_IAE_CANCELLATION_CONFIRMATION)

        response = client.post(cancel_url)
        next_url = reverse("apply:details_for_company", kwargs={"job_application_id": job_application.pk})
        assertRedirects(response, next_url)

        job_application.refresh_from_db()
        assert not job_application.state.is_cancelled
        assertMessages(response, [messages.Message(messages.ERROR, "Vous ne pouvez pas annuler cette embauche.")])

    def test_diagoriente_section_as_job_seeker(self, client):
        job_application = JobApplicationFactory(with_approval=True, resume=None)

        client.force_login(job_application.job_seeker)
        response = client.get(
            reverse("apply:details_for_jobseeker", kwargs={"job_application_id": job_application.pk})
        )
        assertTemplateNotUsed(response, "apply/includes/job_application_diagoriente_invite.html")
        assertNotContains(response, self.DIAGORIENTE_INVITE_TITLE)
        assertNotContains(response, self.DIAGORIENTE_INVITE_PRESCRIBER_MESSAGE)
        assertNotContains(response, self.DIAGORIENTE_INVITE_JOB_SEEKER_MESSAGE)
        assertNotContains(response, self.DIAGORIENTE_INVITE_BUTTON_TITLE)

    def test_diagoriente_section_as_prescriber(self, client):
        job_application = JobApplicationFactory(
            with_approval=True,
            sent_by_authorized_prescriber_organisation=True,
            resume=None,
        )
        prescriber = job_application.sender_prescriber_organization.members.first()
        client.force_login(prescriber)

        response = client.get(
            reverse("apply:details_for_prescriber", kwargs={"job_application_id": job_application.pk})
        )
        assertTemplateNotUsed(response, "apply/includes/job_application_diagoriente_invite.html")
        assertNotContains(response, self.DIAGORIENTE_INVITE_TITLE)
        assertNotContains(response, self.DIAGORIENTE_INVITE_PRESCRIBER_MESSAGE)
        assertNotContains(response, self.DIAGORIENTE_INVITE_JOB_SEEKER_MESSAGE)
        assertNotContains(response, self.DIAGORIENTE_INVITE_BUTTON_TITLE)

        # Un-authorize prescriber (ie. considered as "orienteur")
        job_application.sender_prescriber_organization.authorization_status = PrescriberAuthorizationStatus.REFUSED
        job_application.sender_prescriber_organization.save(update_fields=["authorization_status", "updated_at"])
        response = client.get(
            reverse("apply:details_for_prescriber", kwargs={"job_application_id": job_application.pk})
        )
        assertTemplateNotUsed(response, "apply/includes/job_application_diagoriente_invite.html")
        assertNotContains(response, self.DIAGORIENTE_INVITE_TITLE)
        assertNotContains(response, self.DIAGORIENTE_INVITE_PRESCRIBER_MESSAGE)
        assertNotContains(response, self.DIAGORIENTE_INVITE_JOB_SEEKER_MESSAGE)
        assertNotContains(response, self.DIAGORIENTE_INVITE_BUTTON_TITLE)

        # Remove prescriber's organization membership (ie. considered as "orienteur solo")
        job_application.sender_prescriber_organization.members.clear()
        job_application.sender_prescriber_organization = None
        job_application.save(update_fields=["sender_prescriber_organization", "updated_at"])
        response = client.get(
            reverse("apply:details_for_prescriber", kwargs={"job_application_id": job_application.pk})
        )
        assertTemplateNotUsed(response, "apply/includes/job_application_diagoriente_invite.html")
        assertNotContains(response, self.DIAGORIENTE_INVITE_TITLE)
        assertNotContains(response, self.DIAGORIENTE_INVITE_PRESCRIBER_MESSAGE)
        assertNotContains(response, self.DIAGORIENTE_INVITE_JOB_SEEKER_MESSAGE)
        assertNotContains(response, self.DIAGORIENTE_INVITE_BUTTON_TITLE)

    def test_diagoriente_section_as_employee_for_prescriber(self, client):
        job_application = JobApplicationFactory(
            sent_by_authorized_prescriber_organisation=True,
        )
        company = job_application.to_company
        employee = company.members.first()
        client.force_login(employee)

        # Test with resume
        response = client.get(reverse("apply:details_for_company", kwargs={"job_application_id": job_application.pk}))
        assertTemplateNotUsed(response, "apply/includes/job_application_diagoriente_invite.html")

        # Unset resume on job application, should now include Diagoriente section
        job_application.resume = None
        job_application.save(update_fields=["resume", "updated_at"])
        response = client.get(reverse("apply:details_for_company", kwargs={"job_application_id": job_application.pk}))
        assertTemplateUsed(response, "apply/includes/job_application_diagoriente_invite.html")
        assertContains(response, self.DIAGORIENTE_INVITE_TITLE)
        assertContains(response, self.DIAGORIENTE_INVITE_PRESCRIBER_MESSAGE)
        assertNotContains(response, self.DIAGORIENTE_INVITE_JOB_SEEKER_MESSAGE)
        assertContains(response, self.DIAGORIENTE_INVITE_BUTTON_TITLE)
        assertNotContains(response, self.DIAGORIENTE_INVITE_TOOLTIP)

    def test_diagoriente_section_as_employee_for_job_seeker(self, client):
        job_application = JobApplicationFactory(
            with_approval=True,
            sender=factory.SelfAttribute(".job_seeker"),
        )
        company = job_application.to_company
        employee = company.members.first()
        client.force_login(employee)

        # Test with resume
        response = client.get(reverse("apply:details_for_company", kwargs={"job_application_id": job_application.pk}))
        assertTemplateNotUsed(response, "apply/includes/job_application_diagoriente_invite.html")

        # Unset resume on job application, should now include Diagoriente section
        job_application.resume = None
        job_application.save(update_fields=["resume", "updated_at"])
        response = client.get(reverse("apply:details_for_company", kwargs={"job_application_id": job_application.pk}))
        assertTemplateUsed(response, "apply/includes/job_application_diagoriente_invite.html")
        assertContains(response, self.DIAGORIENTE_INVITE_TITLE)
        assertNotContains(response, self.DIAGORIENTE_INVITE_PRESCRIBER_MESSAGE)
        assertContains(response, self.DIAGORIENTE_INVITE_JOB_SEEKER_MESSAGE)
        assertContains(response, self.DIAGORIENTE_INVITE_BUTTON_TITLE)
        assertNotContains(response, self.DIAGORIENTE_INVITE_TOOLTIP)

    def test_diagoriente_invite_as_job_seeker(self, client, mailoutbox):
        job_application = JobApplicationFactory(with_approval=True, resume=None)

        client.force_login(job_application.job_seeker)
        response = client.post(
            reverse("apply:send_diagoriente_invite", kwargs={"job_application_id": job_application.pk})
        )
        assert response.status_code == 403
        assert len(mailoutbox) == 0

    def test_diagoriente_invite_as_job_prescriber(self, client, mailoutbox):
        job_application = JobApplicationFactory(
            with_approval=True,
            sent_by_authorized_prescriber_organisation=True,
            resume=None,
        )
        prescriber = job_application.sender_prescriber_organization.members.first()

        client.force_login(prescriber)
        response = client.post(
            reverse("apply:send_diagoriente_invite", kwargs={"job_application_id": job_application.pk})
        )
        assert response.status_code == 403
        assert len(mailoutbox) == 0

    def test_diagoriente_invite_as_employee_for_authorized_prescriber(self, client, mailoutbox):
        with freeze_time("2023-12-12 13:37:00") as frozen_time:
            job_application = JobApplicationFactory(sent_by_authorized_prescriber_organisation=True)
            company = job_application.to_company
            employee = company.members.first()
            client.force_login(employee)

            # Should not perform any action if a resume is set
            response = client.post(
                reverse("apply:send_diagoriente_invite", kwargs={"job_application_id": job_application.pk}),
                follow=True,
            )
            assertMessages(response, [])
            assertTemplateNotUsed(response, "apply/includes/job_application_diagoriente_invite.html")
            assertNotContains(response, self.DIAGORIENTE_INVITE_TITLE)
            assertNotContains(response, self.DIAGORIENTE_INVITE_PRESCRIBER_MESSAGE)
            assertNotContains(response, self.DIAGORIENTE_INVITE_JOB_SEEKER_MESSAGE)
            assertNotContains(response, self.DIAGORIENTE_INVITE_BUTTON_TITLE)
            assertNotContains(response, self.DIAGORIENTE_INVITE_TOOLTIP)
            job_application.refresh_from_db()
            assert job_application.diagoriente_invite_sent_at is None
            assert len(mailoutbox) == 0

            # Unset resume, should now update the timestamp and send the mail
            job_application.resume = None
            job_application.save(update_fields=["resume", "updated_at"])
            frozen_time.tick()
            initial_invite_time = frozen_time()
            response = client.post(
                reverse("apply:send_diagoriente_invite", kwargs={"job_application_id": job_application.pk}),
                follow=True,
            )
            assertMessages(
                response, [messages.Message(messages.SUCCESS, "L'invitation à utiliser Diagoriente a été envoyée.")]
            )
            assertTemplateUsed(response, "apply/includes/job_application_diagoriente_invite.html")
            assertNotContains(response, self.DIAGORIENTE_INVITE_TITLE)
            assertNotContains(response, self.DIAGORIENTE_INVITE_PRESCRIBER_MESSAGE)
            assertNotContains(response, self.DIAGORIENTE_INVITE_JOB_SEEKER_MESSAGE)
            assertNotContains(response, self.DIAGORIENTE_INVITE_BUTTON_TITLE)
            assertContains(response, self.DIAGORIENTE_INVITE_TOOLTIP)
            job_application.refresh_from_db()
            assert job_application.diagoriente_invite_sent_at == initial_invite_time.replace(tzinfo=datetime.UTC)
            assert len(mailoutbox) == 1
            assert self.DIAGORIENTE_INVITE_EMAIL_SUBJECT in mailoutbox[0].subject
            assert (
                self.DIAGORIENTE_INVITE_EMAIL_PRESCRIBER_BODY_HEADER_LINE_1.format(
                    company_name=job_application.to_company.display_name,
                    job_seeker_name=job_application.job_seeker.get_full_name(),
                )
                in mailoutbox[0].body
            )
            assert self.DIAGORIENTE_INVITE_EMAIL_PRESCRIBER_BODY_HEADER_LINE_2 in mailoutbox[0].body
            assert (
                self.DIAGORIENTE_INVITE_EMAIL_JOB_SEEKER_BODY_HEADER_LINE_1.format(
                    company_name=job_application.to_company.display_name
                )
                not in mailoutbox[0].body
            )
            assert self.DIAGORIENTE_INVITE_EMAIL_JOB_SEEKER_BODY_HEADER_LINE_2 not in mailoutbox[0].body

            # Concurrent/subsequent calls should not perform any action
            frozen_time.tick()
            response = client.post(
                reverse("apply:send_diagoriente_invite", kwargs={"job_application_id": job_application.pk}),
                follow=True,
            )
            assertMessages(response, [])
            assertTemplateUsed(response, "apply/includes/job_application_diagoriente_invite.html")
            assertNotContains(response, self.DIAGORIENTE_INVITE_TITLE)
            assertNotContains(response, self.DIAGORIENTE_INVITE_PRESCRIBER_MESSAGE)
            assertNotContains(response, self.DIAGORIENTE_INVITE_JOB_SEEKER_MESSAGE)
            assertNotContains(response, self.DIAGORIENTE_INVITE_BUTTON_TITLE)
            assertContains(response, self.DIAGORIENTE_INVITE_TOOLTIP)
            job_application.refresh_from_db()
            assert job_application.diagoriente_invite_sent_at == initial_invite_time.replace(tzinfo=datetime.UTC)
            assert len(mailoutbox) == 1

    def test_diagoriente_invite_as_employee_for_unauthorized_prescriber(self, client, mailoutbox):
        job_application = JobApplicationFactory(resume=None)
        company = job_application.to_company
        employee = company.members.first()
        client.force_login(employee)

        with freeze_time("2023-12-12 13:37:00") as initial_invite_time:
            response = client.post(
                reverse("apply:send_diagoriente_invite", kwargs={"job_application_id": job_application.pk}),
                follow=True,
            )
        assertMessages(
            response, [messages.Message(messages.SUCCESS, "L'invitation à utiliser Diagoriente a été envoyée.")]
        )
        assertTemplateUsed(response, "apply/includes/job_application_diagoriente_invite.html")
        assertNotContains(response, self.DIAGORIENTE_INVITE_TITLE)
        assertNotContains(response, self.DIAGORIENTE_INVITE_PRESCRIBER_MESSAGE)
        assertNotContains(response, self.DIAGORIENTE_INVITE_JOB_SEEKER_MESSAGE)
        assertNotContains(response, self.DIAGORIENTE_INVITE_BUTTON_TITLE)
        assertContains(response, self.DIAGORIENTE_INVITE_TOOLTIP)
        job_application.refresh_from_db()
        assert job_application.diagoriente_invite_sent_at == initial_invite_time().replace(tzinfo=datetime.UTC)
        assert len(mailoutbox) == 1
        assert self.DIAGORIENTE_INVITE_EMAIL_SUBJECT in mailoutbox[0].subject
        assert (
            self.DIAGORIENTE_INVITE_EMAIL_PRESCRIBER_BODY_HEADER_LINE_1.format(
                company_name=job_application.to_company.display_name,
                job_seeker_name=job_application.job_seeker.get_full_name(),
            )
            in mailoutbox[0].body
        )
        assert self.DIAGORIENTE_INVITE_EMAIL_PRESCRIBER_BODY_HEADER_LINE_2 in mailoutbox[0].body
        assert (
            self.DIAGORIENTE_INVITE_EMAIL_JOB_SEEKER_BODY_HEADER_LINE_1.format(
                company_name=job_application.to_company.display_name
            )
            not in mailoutbox[0].body
        )
        assert self.DIAGORIENTE_INVITE_EMAIL_JOB_SEEKER_BODY_HEADER_LINE_2 not in mailoutbox[0].body

    def test_diagoriente_invite_as_employee_for_job_seeker(self, client, mailoutbox):
        job_application = JobApplicationFactory(
            with_approval=True,
            resume=None,
            sender=factory.SelfAttribute(".job_seeker"),
        )
        company = job_application.to_company
        employee = company.members.first()
        client.force_login(employee)

        with freeze_time("2023-12-12 13:37:00") as initial_invite_time:
            response = client.post(
                reverse("apply:send_diagoriente_invite", kwargs={"job_application_id": job_application.pk}),
                follow=True,
            )
        assertMessages(
            response, [messages.Message(messages.SUCCESS, "L'invitation à utiliser Diagoriente a été envoyée.")]
        )
        assertTemplateUsed(response, "apply/includes/job_application_diagoriente_invite.html")
        assertNotContains(response, self.DIAGORIENTE_INVITE_TITLE)
        assertNotContains(response, self.DIAGORIENTE_INVITE_PRESCRIBER_MESSAGE)
        assertNotContains(response, self.DIAGORIENTE_INVITE_JOB_SEEKER_MESSAGE)
        assertNotContains(response, self.DIAGORIENTE_INVITE_BUTTON_TITLE)
        assertContains(response, self.DIAGORIENTE_INVITE_TOOLTIP)
        job_application.refresh_from_db()
        assert job_application.diagoriente_invite_sent_at == initial_invite_time().replace(tzinfo=datetime.UTC)
        assert len(mailoutbox) == 1
        assert self.DIAGORIENTE_INVITE_EMAIL_SUBJECT in mailoutbox[0].subject
        assert (
            self.DIAGORIENTE_INVITE_EMAIL_PRESCRIBER_BODY_HEADER_LINE_1.format(
                company_name=job_application.to_company.display_name,
                job_seeker_name=job_application.job_seeker.get_full_name(),
            )
            not in mailoutbox[0].body
        )
        assert self.DIAGORIENTE_INVITE_EMAIL_PRESCRIBER_BODY_HEADER_LINE_2 not in mailoutbox[0].body
        assert (
            self.DIAGORIENTE_INVITE_EMAIL_JOB_SEEKER_BODY_HEADER_LINE_1.format(
                company_name=job_application.to_company.display_name
            )
            in mailoutbox[0].body
        )
        assert self.DIAGORIENTE_INVITE_EMAIL_JOB_SEEKER_BODY_HEADER_LINE_2 in mailoutbox[0].body


class TestProcessAcceptViews:
    BIRTH_COUNTRY_LABEL = "Pays de naissance"
    BIRTH_PLACE_LABEL = "Commune de naissance"

    @pytest.fixture(autouse=True)
    def setup_method(self, settings, mocker):
        self.company = CompanyFactory(with_membership=True, with_jobs=True, name="La brigade - entreprise par défaut")
        self.job_seeker = JobSeekerFactory(
            with_pole_emploi_id=True,
            with_ban_api_mocked_address=True,
        )

        settings.API_BAN_BASE_URL = "http://ban-api"
        settings.TALLY_URL = "https://tally.so"
        mocker.patch(
            "itou.utils.apis.geocoding.get_geocoding_data",
            side_effect=mock_get_geocoding_data_by_ban_api_resolved,
        )

    def create_job_application(self, *args, **kwargs):
        kwargs = {
            "selected_jobs": self.company.jobs.all(),
            "state": JobApplicationState.PROCESSING,
            "job_seeker": self.job_seeker,
            "to_company": self.company,
            "hiring_end_at": None,
        } | kwargs
        return JobApplicationSentByJobSeekerFactory(**kwargs)

    def _accept_view_post_data(self, job_application, post_data=None):
        extra_post_data = post_data or {}
        job_seeker = job_application.job_seeker
        # JobSeekerAddressForm
        address_default_fields = {
            "ban_api_resolved_address": job_seeker.geocoding_address,
            "address_line_1": job_seeker.address_line_1,
            "post_code": job_seeker.insee_city.post_codes[0],
            "insee_code": job_seeker.insee_city.code_insee,
            "city": job_seeker.insee_city.name,
            "fill_mode": "ban_api",
            # Select the first and only one option
            "address_for_autocomplete": "0",
            "geocoding_score": 0.9714,
        }
        # JobSeekerPersonalDataForm
        birth_place = (
            Commune.objects.filter(
                start_date__lte=job_seeker.jobseeker_profile.birthdate,
                end_date__gte=job_seeker.jobseeker_profile.birthdate,
            )
            .first()
            .pk
        )
        personal_data_default_fields = {
            "birthdate": job_seeker.jobseeker_profile.birthdate,
            "birth_country": extra_post_data.setdefault("birth_country", Country.france_id),
            "birth_place": extra_post_data.setdefault("birth_place", birth_place),
            "pole_emploi_id": job_seeker.jobseeker_profile.pole_emploi_id,
        }
        # AcceptForm
        job_description = job_application.selected_jobs.first()
        hiring_start_at = timezone.localdate()
        hiring_end_at = Approval.get_default_end_date(hiring_start_at)
        accept_default_fields = {
            "hiring_start_at": hiring_start_at.strftime(DuetDatePickerWidget.INPUT_DATE_FORMAT),
            "hiring_end_at": hiring_end_at.strftime(DuetDatePickerWidget.INPUT_DATE_FORMAT),
            "answer": "",
            "hired_job": job_description.pk,
        }
        # GEIQ-only mandatory fields
        if job_application.to_company.kind == CompanyKind.GEIQ:
            accept_default_fields |= {
                "prehiring_guidance_days": 10,
                "contract_type": ContractType.APPRENTICESHIP,
                "nb_hours_per_week": 10,
                "qualification_type": QualificationType.CQP,
                "qualification_level": QualificationLevel.LEVEL_4,
                "planned_training_hours": 20,
            }
        return {
            **personal_data_default_fields,
            **address_default_fields,
            **accept_default_fields,
        } | extra_post_data

    def accept_job_application(self, client, job_application, post_data=None, assert_successful=True):
        """
        This is not a test. It's a shortcut to process "apply:accept" view steps:
        - GET
        - POST: show the confirmation modal
        - POST: hide the modal and redirect to the next url.

        If needed a job description can be passed as parameter, as it is now mandatory for each hiring.
        If not provided, a new one will be created and linked to the given job application.
        """
        url_accept = reverse("apply:accept", kwargs={"job_application_id": job_application.pk})
        response = client.get(url_accept)
        assertContains(response, "Confirmation de l’embauche")
        # Make sure modal is hidden.
        assert response.headers.get("HX-Trigger") is None

        post_data = self._accept_view_post_data(job_application=job_application, post_data=post_data)
        response = client.post(url_accept, headers={"hx-request": "true"}, data=post_data)

        if assert_successful:
            # Easier to debug than just a « sorry, the modal goes on a strike ».
            if response.context["has_form_error"]:
                forms = [
                    response.context["form_accept"],
                    response.context["form_user_address"],
                    response.context["form_personal_data"],
                    response.context.get("form_birth_place"),
                ]
                for form in forms:
                    if form:
                        logger.error(f"{form.errors=}")
            assert not response.context["has_form_error"]
            assert (
                response.headers["HX-Trigger"] == '{"modalControl": {"id": "js-confirmation-modal", "action": "show"}}'
            )
        else:
            assert response.headers.get("HX-Trigger") is None

        post_data = post_data | {"confirmed": "True"}
        response = client.post(url_accept, headers={"hx-request": "true"}, data=post_data)
        next_url = reverse("apply:details_for_company", kwargs={"job_application_id": job_application.pk})
        # django-htmx triggers a client side redirect when it receives a response with the HX-Redirect header.
        # It renders an HttpResponseRedirect subclass which, unfortunately, responds with a 200 status code.
        # I guess it's normal as it's an AJAX response.
        # See https://django-htmx.readthedocs.io/en/latest/http.html#django_htmx.http.HttpResponseClientRedirect # noqa
        if assert_successful:
            assertRedirects(response, next_url, status_code=200, fetch_redirect_response=False)
        return response, next_url

    _nominal_cases = list(
        product(
            [Approval.get_default_end_date(timezone.localdate()), None],
            JobApplicationWorkflow.CAN_BE_ACCEPTED_STATES,
        )
    )

    @pytest.mark.parametrize(
        "hiring_end_at,state",
        _nominal_cases,
        ids=[state + ("_no_end_date" if not end_at else "") for end_at, state in _nominal_cases],
    )
    def test_nominal_case(self, client, hiring_end_at, state):
        today = timezone.localdate()
        job_application = self.create_job_application(state=state, with_iae_eligibility_diagnosis=True)
        previous_last_checked_at = self.job_seeker.last_checked_at

        employer = self.company.members.first()
        client.force_login(employer)
        # Good duration.
        hiring_start_at = today
        post_data = {
            "hiring_end_at": hiring_end_at.strftime(DuetDatePickerWidget.INPUT_DATE_FORMAT) if hiring_end_at else ""
        }

        _, next_url = self.accept_job_application(client, job_application, post_data=post_data)

        job_application = JobApplication.objects.get(pk=job_application.pk)
        assert job_application.hiring_start_at == hiring_start_at
        assert job_application.hiring_end_at == hiring_end_at
        assert job_application.state.is_accepted

        # test how hiring_end_date is displayed
        response = client.get(next_url)
        assertNotContains(response, users_test_constants.CERTIFIED_FORM_READONLY_HTML, html=True)
        # test case hiring_end_at
        if hiring_end_at:
            assertContains(
                response,
                f"<small>Fin</small><strong>{date_format(hiring_end_at, 'd F Y')}</strong>",
                html=True,
            )
        else:
            assertContains(response, '<small>Fin</small><i class="text-disabled">Non renseigné</i>', html=True)
        # last_checked_at has been updated
        assert job_application.job_seeker.last_checked_at > previous_last_checked_at

    @freeze_time("2024-09-11")
    def test_select_other_job_description_for_job_application(self, client, mocker):
        criteria_kind = random.choice(list(CERTIFIABLE_ADMINISTRATIVE_CRITERIA_KINDS))
        mocked_request = mocker.patch(
            "itou.utils.apis.api_particulier._request",
            return_value=RESPONSES[criteria_kind][ResponseKind.CERTIFIED],
        )
        create_test_romes_and_appellations(["M1805"], appellations_per_rome=1)
        diagnosis = IAEEligibilityDiagnosisFactory(
            job_seeker=self.job_seeker,
            author_siae=self.company,
            certifiable=True,
            criteria_kinds=[criteria_kind],
        )
        job_application = self.create_job_application(eligibility_diagnosis=diagnosis)

        employer = self.company.members.first()
        client.force_login(employer)

        url = reverse("apply:accept", kwargs={"job_application_id": job_application.pk})
        response = client.get(url)

        assertContains(response, "Postes ouverts au recrutement")
        assertNotContains(response, "Postes fermés au recrutement")
        assertNotContains(response, "Préciser le nom du poste (code ROME)")

        # Selecting "Autre" must enable the employer to create a new job description
        # linked to the accepted job application.
        post_data = {
            "birthdate": "2002-02-20",  # Required to certify the criteria later.
            "hired_job": AcceptForm.OTHER_HIRED_JOB,
        }
        post_data = self._accept_view_post_data(job_application=job_application, post_data=post_data)
        response = client.post(url, data=post_data)
        assertContains(response, "Localisation du poste")
        assertContains(response, "Préciser le nom du poste (code ROME)")

        city = City.objects.order_by("?").first()
        appellation = Appellation.objects.get(rome_id="M1805")
        post_data |= {"location": city.pk, "appellation": appellation.pk}
        response = client.post(
            url,
            data=post_data,
            headers={"hx-request": "true"},
        )
        assertTemplateUsed(response, "apply/includes/job_application_accept_form.html")
        assert response.status_code == 200

        # Modal window
        post_data |= {"confirmed": True}
        response = client.post(url, data=post_data, follow=False, headers={"hx-request": "true"})
        # Caution: should redirect after that point, but done via HTMX we get a 200 status code
        assert response.status_code == 200
        assert response.url == reverse("apply:details_for_company", kwargs={"job_application_id": job_application.pk})
        mocked_request.assert_called_once()

        # Perform some checks on job description now attached to job application
        job_application.refresh_from_db()
        assert job_application.hired_job
        assert job_application.hired_job.creation_source == JobDescriptionSource.HIRING
        assert not job_application.hired_job.is_active
        assert job_application.hired_job.description == "La structure n’a pas encore renseigné cette rubrique"

    def test_select_job_description_for_job_application(self, client, snapshot):
        job_application = self.create_job_application(with_iae_eligibility_diagnosis=True)
        employer = self.company.members.first()
        client.force_login(employer)

        url = reverse("apply:accept", kwargs={"job_application_id": job_application.pk})
        response = client.get(url)

        response = client.get(reverse("apply:accept", kwargs={"job_application_id": job_application.pk}))

        # Check optgroup labels
        job_description = JobDescriptionFactory(company=job_application.to_company, is_active=True)
        response = client.get(reverse("apply:accept", kwargs={"job_application_id": job_application.pk}))
        assert response.status_code == 200
        assertContains(response, f"{job_description.display_name} - {job_description.display_location}", html=True)
        assertContains(response, "Postes ouverts au recrutement")
        assertNotContains(response, "Postes fermés au recrutement")
        assertNotContains(response, "Préciser le nom du poste (code ROME)")

        # Inactive job description must also appear in select
        job_description = JobDescriptionFactory(company=job_application.to_company, is_active=False)
        with assertSnapshotQueries(snapshot(name="accept view SQL queries")):
            response = client.get(reverse("apply:accept", kwargs={"job_application_id": job_application.pk}))
        assert response.status_code == 200
        assertContains(response, f"{job_description.display_name} - {job_description.display_location}", html=True)
        assertContains(response, "Postes ouverts au recrutement")
        assertContains(response, "Postes fermés au recrutement")
        assertNotContains(response, "Préciser le nom du poste (code ROME)")

    def test_no_job_description_for_job_application(self, client):
        self.company.jobs.clear()
        job_application = self.create_job_application(with_iae_eligibility_diagnosis=True)
        employer = self.company.members.first()
        client.force_login(employer)
        response = client.get(reverse("apply:accept", kwargs={"job_application_id": job_application.pk}))
        assertNotContains(response, "Postes ouverts au recrutement")
        assertNotContains(response, "Postes fermés au recrutement")
        assertNotContains(response, "Préciser le nom du poste (code ROME)")

    def test_wrong_dates(self, client):
        today = timezone.localdate()
        job_application = self.create_job_application(with_iae_eligibility_diagnosis=True)
        hiring_start_at = today
        hiring_end_at = Approval.get_default_end_date(hiring_start_at)
        # Force `hiring_start_at` in past.
        hiring_start_at = hiring_start_at - relativedelta(days=1)

        employer = self.company.members.first()
        client.force_login(employer)
        post_data = {
            "hiring_start_at": hiring_start_at.strftime(DuetDatePickerWidget.INPUT_DATE_FORMAT),
            "hiring_end_at": hiring_end_at.strftime(DuetDatePickerWidget.INPUT_DATE_FORMAT),
        }
        response, _ = self.accept_job_application(
            client, job_application, post_data=post_data, assert_successful=False
        )
        assertFormError(response.context["form_accept"], "hiring_start_at", JobApplication.ERROR_START_IN_PAST)

        # Wrong dates: end < start.
        hiring_start_at = today
        hiring_end_at = hiring_start_at - relativedelta(days=1)
        post_data = {
            "hiring_start_at": hiring_start_at.strftime(DuetDatePickerWidget.INPUT_DATE_FORMAT),
            "hiring_end_at": hiring_end_at.strftime(DuetDatePickerWidget.INPUT_DATE_FORMAT),
        }
        response, _ = self.accept_job_application(
            client, job_application, post_data=post_data, assert_successful=False
        )
        assertFormError(response.context["form_accept"], None, JobApplication.ERROR_END_IS_BEFORE_START)

    def test_accept_hiring_date_after_approval(self, client, mocker):
        # Jobseeker has an approval, but it ends after the start date of the job.
        approval = ApprovalFactory(end_at=timezone.localdate() + datetime.timedelta(days=1))
        self.job_seeker.approvals.add(approval)
        job_application = self.create_job_application(
            job_seeker=self.job_seeker,
            to_company=self.company,
            sent_by_authorized_prescriber_organisation=True,
            approval=approval,
            hiring_start_at=approval.end_at + datetime.timedelta(days=1),
        )

        employer = self.company.members.first()
        client.force_login(employer)

        post_data = self._accept_view_post_data(
            job_application=job_application,
            post_data={
                "hiring_start_at": job_application.hiring_start_at.strftime(DuetDatePickerWidget.INPUT_DATE_FORMAT)
            },
        )
        response, _ = self.accept_job_application(
            client, job_application, post_data=post_data, assert_successful=False
        )
        assertFormError(
            response.context["form_accept"],
            "hiring_start_at",
            JobApplication.ERROR_HIRES_AFTER_APPROVAL_EXPIRES,
        )

        # employer amends the situation by submitting a different hiring start date
        post_data["hiring_start_at"] = timezone.localdate().strftime(DuetDatePickerWidget.INPUT_DATE_FORMAT)
        response, _ = self.accept_job_application(client, job_application, post_data=post_data, assert_successful=True)

    def test_no_address(self, client):
        job_application = self.create_job_application(with_iae_eligibility_diagnosis=True)
        employer = self.company.members.first()
        client.force_login(employer)

        post_data = {
            "ban_api_resolved_address": "",
            "address_line_1": "",
            "post_code": "",
            "insee_code": "",
            "city": "",
            "geocoding_score": "",
            "fill_mode": "ban_api",
            "address_for_autocomplete": "",
        }

        response, _ = self.accept_job_application(
            client, job_application, post_data=post_data, assert_successful=False
        )
        assertFormError(response.context["form_user_address"], "address_for_autocomplete", "Ce champ est obligatoire.")

    def test_no_diagnosis_on_job_application(self, client):
        diagnosis = IAEEligibilityDiagnosisFactory(from_prescriber=True)
        job_application = self.create_job_application(with_iae_eligibility_diagnosis=False)
        self.job_seeker.eligibility_diagnoses.add(diagnosis)
        # No eligibility diagnosis -> if job_seeker has a valid eligibility diagnosis, it's OK
        assert job_application.eligibility_diagnosis is None

        employer = self.company.members.first()
        client.force_login(employer)
        self.accept_job_application(client, job_application, assert_successful=True, post_data={})

    def test_no_diagnosis(self, client):
        # if no, should not see the confirm button, nor accept posted data
        job_application = self.create_job_application(with_iae_eligibility_diagnosis=False)
        assert job_application.eligibility_diagnosis is None
        job_application.job_seeker.eligibility_diagnoses.all().delete()

        employer = self.company.members.first()
        client.force_login(employer)
        url_accept = reverse("apply:accept", kwargs={"job_application_id": job_application.pk})
        response = client.get(url_accept, follow=True)
        assertRedirects(
            response, reverse("apply:details_for_company", kwargs={"job_application_id": job_application.pk})
        )
        assert "Cette candidature requiert un diagnostic d'éligibilité pour être acceptée." == str(
            list(response.context["messages"])[-1]
        )

    def test_with_active_suspension(self, client):
        """Test the `accept` transition with active suspension for active user"""
        employer = self.company.members.first()
        today = timezone.localdate()
        # Old job application of job seeker
        old_job_application = self.create_job_application(
            with_iae_eligibility_diagnosis=True, with_approval=True, hiring_start_at=today - relativedelta(days=100)
        )
        job_seeker = old_job_application.job_seeker
        # Create suspension for the job seeker
        approval = old_job_application.approval
        susension_start_at = today
        suspension_end_at = today + relativedelta(days=50)

        SuspensionFactory(
            approval=approval,
            start_at=susension_start_at,
            end_at=suspension_end_at,
            created_by=employer,
            reason=Suspension.Reason.BROKEN_CONTRACT.value,
        )

        # Now, another company wants to hire the job seeker
        other_company = CompanyFactory(with_membership=True, with_jobs=True)
        job_application = JobApplicationFactory(
            approval=approval,
            state=job_applications_enums.JobApplicationState.PROCESSING,
            job_seeker=job_seeker,
            to_company=other_company,
            selected_jobs=other_company.jobs.all(),
        )
        other_employer = job_application.to_company.members.first()

        # login with other company
        client.force_login(other_employer)
        hiring_start_at = today + relativedelta(days=20)

        post_data = {
            "hiring_start_at": hiring_start_at.strftime(DuetDatePickerWidget.INPUT_DATE_FORMAT),
        }
        self.accept_job_application(client, job_application, post_data=post_data)

        job_application = JobApplication.objects.get(pk=job_application.pk)
        suspension = job_application.approval.suspension_set.in_progress().last()

        # The end date of suspension is set to d-1 of hiring start day.
        assert suspension.end_at == job_application.hiring_start_at - relativedelta(days=1)
        # Check if the duration of approval was updated correctly.
        assert job_application.approval.end_at == approval.end_at + relativedelta(
            days=(suspension.end_at - suspension.start_at).days
        )

    def test_with_manual_approval_delivery(self, client):
        """
        Test the "manual approval delivery mode" path of the view.
        """

        jobseeker_profile = self.job_seeker.jobseeker_profile
        # The state of the 3 `pole_emploi_*` fields will trigger a manual delivery.
        jobseeker_profile.nir = ""
        jobseeker_profile.pole_emploi_id = ""
        jobseeker_profile.lack_of_pole_emploi_id_reason = LackOfPoleEmploiId.REASON_FORGOTTEN
        jobseeker_profile.save()
        job_application = self.create_job_application(with_iae_eligibility_diagnosis=True)

        employer = self.company.members.first()
        client.force_login(employer)

        post_data = {
            # Data for `JobSeekerPersonalDataForm`.
            "pole_emploi_id": job_application.job_seeker.jobseeker_profile.pole_emploi_id,
            "lack_of_pole_emploi_id_reason": jobseeker_profile.lack_of_pole_emploi_id_reason,
            "lack_of_nir": True,
            "lack_of_nir_reason": LackOfNIRReason.TEMPORARY_NUMBER,
        }

        self.accept_job_application(client, job_application, post_data=post_data)
        job_application.refresh_from_db()
        assert job_application.approval_delivery_mode == job_application.APPROVAL_DELIVERY_MODE_MANUAL

    def test_update_hiring_start_date_of_two_job_applications(self, client):
        hiring_start_at = timezone.localdate() + relativedelta(months=2)
        hiring_end_at = hiring_start_at + relativedelta(months=2)
        approval_default_ending = Approval.get_default_end_date(start_at=hiring_start_at)
        # Send 3 job applications to 3 different structures
        job_application = self.create_job_application(hiring_start_at=hiring_start_at, hiring_end_at=hiring_end_at)
        job_seeker = job_application.job_seeker

        wall_e = CompanyFactory(with_membership=True, with_jobs=True, name="WALL-E")
        job_app_starting_earlier = JobApplicationFactory(
            job_seeker=job_seeker,
            state=job_applications_enums.JobApplicationState.PROCESSING,
            to_company=wall_e,
            selected_jobs=wall_e.jobs.all(),
        )
        vice_versa = CompanyFactory(with_membership=True, with_jobs=True, name="Vice-versa")
        job_app_starting_later = JobApplicationFactory(
            job_seeker=job_seeker,
            state=job_applications_enums.JobApplicationState.PROCESSING,
            to_company=vice_versa,
            selected_jobs=vice_versa.jobs.all(),
        )

        # company 1 logs in and accepts the first job application.
        # The delivered approval should start at the same time as the contract.
        employer = self.company.members.first()
        client.force_login(employer)
        post_data = {
            "hiring_start_at": hiring_start_at.strftime(DuetDatePickerWidget.INPUT_DATE_FORMAT),
            "hiring_end_at": hiring_end_at.strftime(DuetDatePickerWidget.INPUT_DATE_FORMAT),
        }

        self.accept_job_application(client, job_application, post_data=post_data)

        # First job application has been accepted.
        # All other job applications are obsolete.
        job_application.refresh_from_db()
        assert job_application.state.is_accepted
        assert job_application.approval.start_at == job_application.hiring_start_at
        assert job_application.approval.end_at == approval_default_ending
        client.logout()

        # company 2 accepts the second job application
        # but its contract starts earlier than the approval delivered the first time.
        # Approval's starting date should be brought forward.
        employer = wall_e.members.first()
        hiring_start_at = hiring_start_at - relativedelta(months=1)
        hiring_end_at = hiring_start_at + relativedelta(months=2)
        approval_default_ending = Approval.get_default_end_date(start_at=hiring_start_at)
        job_app_starting_earlier.refresh_from_db()
        assert job_app_starting_earlier.state.is_obsolete

        client.force_login(employer)
        post_data = {
            "hiring_start_at": hiring_start_at.strftime(DuetDatePickerWidget.INPUT_DATE_FORMAT),
            "hiring_end_at": hiring_end_at.strftime(DuetDatePickerWidget.INPUT_DATE_FORMAT),
        }
        self.accept_job_application(client, job_app_starting_earlier, post_data=post_data)
        job_app_starting_earlier.refresh_from_db()

        # Second job application has been accepted.
        # The job seeker has now two part-time jobs at the same time.
        assert job_app_starting_earlier.state.is_accepted
        assert job_app_starting_earlier.approval.start_at == job_app_starting_earlier.hiring_start_at
        assert job_app_starting_earlier.approval.end_at == approval_default_ending
        client.logout()

        # company 3 accepts the third job application.
        # Its contract starts later than the corresponding approval.
        # Approval's starting date should not be updated.
        employer = vice_versa.members.first()
        hiring_start_at = hiring_start_at + relativedelta(months=5)
        hiring_end_at = hiring_start_at + relativedelta(months=2)
        job_app_starting_later.refresh_from_db()
        assert job_app_starting_later.state.is_obsolete

        client.force_login(employer)
        post_data = {
            "hiring_start_at": hiring_start_at.strftime(DuetDatePickerWidget.INPUT_DATE_FORMAT),
            "hiring_end_at": hiring_end_at.strftime(DuetDatePickerWidget.INPUT_DATE_FORMAT),
        }
        self.accept_job_application(client, job_app_starting_later, post_data=post_data)
        job_app_starting_later.refresh_from_db()

        # Third job application has been accepted.
        # The job seeker has now three part-time jobs at the same time.
        assert job_app_starting_later.state.is_accepted
        assert job_app_starting_later.approval.start_at == job_app_starting_earlier.hiring_start_at

    def test_nir_readonly(self, client):
        job_application = self.create_job_application(with_iae_eligibility_diagnosis=True)

        employer = self.company.members.first()
        client.force_login(employer)
        url_accept = reverse("apply:accept", kwargs={"job_application_id": job_application.pk})
        response = client.get(url_accept)
        assertContains(response, "Confirmation de l’embauche")
        # Check that the NIR field is disabled
        assertContains(response, DISABLED_NIR)
        assertContains(
            response,
            "Ce candidat a pris le contrôle de son compte utilisateur. Vous ne pouvez pas modifier ses informations.",
            html=True,
        )

        job_application.job_seeker.last_login = None
        job_application.job_seeker.created_by = PrescriberFactory()
        job_application.job_seeker.save()
        response = client.get(url_accept)
        assertContains(response, "Confirmation de l’embauche")
        # Check that the NIR field is disabled
        assertContains(response, DISABLED_NIR)
        assertContains(
            response,
            (
                f'<a href="https://tally.so/r/wzxQlg?jobapplication={job_application.pk}" target="_blank" '
                'rel="noopener">Demander la correction du numéro de sécurité sociale</a>'
            ),
            html=True,
        )

    def test_no_nir_update(self, client):
        jobseeker_profile = self.job_seeker.jobseeker_profile
        jobseeker_profile.nir = ""
        jobseeker_profile.save()
        job_application = self.create_job_application(with_iae_eligibility_diagnosis=True)

        employer = self.company.members.first()
        client.force_login(employer)
        url_accept = reverse("apply:accept", kwargs={"job_application_id": job_application.pk})
        response = client.get(url_accept)
        assertContains(response, "Confirmation de l’embauche")
        # Check that the NIR field is not disabled
        assertNotContains(response, DISABLED_NIR)

        post_data = self._accept_view_post_data(job_application)
        response, _ = self.accept_job_application(
            client, job_application, assert_successful=False, post_data=post_data
        )
        assertContains(response, "Le numéro de sécurité sociale n'est pas valide", html=True)

        post_data["nir"] = "1234"
        response, _ = self.accept_job_application(
            client, job_application, assert_successful=False, post_data=post_data
        )
        assertContains(response, "Le numéro de sécurité sociale n'est pas valide", html=True)
        assertFormError(
            response.context["form_personal_data"],
            "nir",
            "Le numéro de sécurité sociale est trop court (15 caractères autorisés).",
        )

        NEW_NIR = "197013625838386"
        post_data["nir"] = NEW_NIR
        self.accept_job_application(client, job_application, post_data=post_data)
        jobseeker_profile.refresh_from_db()
        assert jobseeker_profile.nir == NEW_NIR

    def test_no_nir_other_user(self, client):
        jobseeker_profile = self.job_seeker.jobseeker_profile
        jobseeker_profile.nir = ""
        jobseeker_profile.save()
        job_application = self.create_job_application(with_iae_eligibility_diagnosis=True)
        other_job_seeker = JobSeekerFactory(
            with_pole_emploi_id=True,
            with_ban_api_mocked_address=True,
        )

        employer = self.company.members.first()
        client.force_login(employer)

        post_data = {
            "pole_emploi_id": jobseeker_profile.pole_emploi_id,
            "nir": other_job_seeker.jobseeker_profile.nir,
        }
        response, _ = self.accept_job_application(
            client, job_application, assert_successful=False, post_data=post_data
        )
        assertContains(response, "Le numéro de sécurité sociale est déjà associé à un autre utilisateur", html=True)
        assertFormError(
            response.context["form_personal_data"],
            None,
            "Ce numéro de sécurité sociale est déjà associé à un autre utilisateur.",
        )

    def test_no_nir_update_with_reason(self, client):
        jobseeker_profile = self.job_seeker.jobseeker_profile
        jobseeker_profile.nir = ""
        jobseeker_profile.save()
        job_application = self.create_job_application(with_iae_eligibility_diagnosis=True)

        employer = self.company.members.first()
        client.force_login(employer)

        post_data = self._accept_view_post_data(job_application=job_application)
        response, _ = self.accept_job_application(
            client, job_application, assert_successful=False, post_data=post_data
        )
        assertContains(response, "Le numéro de sécurité sociale n'est pas valide", html=True)

        # Check the box
        post_data["lack_of_nir"] = True
        response, _ = self.accept_job_application(
            client, job_application, assert_successful=False, post_data=post_data
        )
        assertContains(response, "Le numéro de sécurité sociale n'est pas valide", html=True)
        assertContains(response, "Veuillez sélectionner un motif pour continuer", html=True)

        post_data["lack_of_nir_reason"] = LackOfNIRReason.NO_NIR
        self.accept_job_application(client, job_application, post_data=post_data, assert_successful=True)
        job_application.job_seeker.jobseeker_profile.refresh_from_db()
        assert job_application.job_seeker.jobseeker_profile.lack_of_nir_reason == LackOfNIRReason.NO_NIR

    def test_lack_of_nir_reason_update(self, client):
        jobseeker_profile = self.job_seeker.jobseeker_profile
        jobseeker_profile.nir = ""
        jobseeker_profile.lack_of_nir_reason = LackOfNIRReason.TEMPORARY_NUMBER
        jobseeker_profile.save()
        job_application = self.create_job_application(with_iae_eligibility_diagnosis=True)

        employer = self.company.members.first()
        client.force_login(employer)

        url_accept = reverse("apply:accept", kwargs={"job_application_id": job_application.pk})
        response = client.get(url_accept)
        assertContains(response, "Confirmation de l’embauche")
        # Check that the NIR field is initially disabled
        # since the job seeker has a lack_of_nir_reason
        assert response.context["form_personal_data"].fields["nir"].disabled
        NEW_NIR = "197013625838386"

        post_data = {
            "nir": NEW_NIR,
            "lack_of_nir_reason": jobseeker_profile.lack_of_nir_reason,
            "pole_emploi_id": jobseeker_profile.pole_emploi_id,
            "lack_of_pole_emploi_id_reason": jobseeker_profile.lack_of_pole_emploi_id_reason,
        }
        post_data = self._accept_view_post_data(job_application=job_application, post_data=post_data)
        self.accept_job_application(
            client, job_application=job_application, post_data=post_data, assert_successful=True
        )
        job_application.job_seeker.refresh_from_db()
        # New NIR is set and the lack_of_nir_reason is cleaned
        assert not job_application.job_seeker.jobseeker_profile.lack_of_nir_reason
        assert job_application.job_seeker.jobseeker_profile.nir == NEW_NIR

    def test_lack_of_nir_reason_other_user(self, client):
        jobseeker_profile = self.job_seeker.jobseeker_profile
        jobseeker_profile.nir = ""
        jobseeker_profile.lack_of_nir_reason = LackOfNIRReason.NIR_ASSOCIATED_TO_OTHER
        jobseeker_profile.save()
        job_application = self.create_job_application(with_iae_eligibility_diagnosis=True)

        url_accept = reverse("apply:accept", kwargs={"job_application_id": job_application.pk})

        employer = self.company.members.first()
        client.force_login(employer)

        response = client.get(url_accept)
        assertContains(response, "Confirmation de l’embauche")
        # Check that the NIR field is initially disabled
        # since the job seeker has a lack_of_nir_reason
        assert response.context["form_personal_data"].fields["nir"].disabled

        # Check that the tally link is there
        assertContains(
            response,
            (
                f'<a href="https://tally.so/r/wzxQlg?jobapplication={job_application.pk}" target="_blank" '
                'rel="noopener">Demander la correction du numéro de sécurité sociale</a>'
            ),
            html=True,
        )

    def test_accept_after_cancel(self, client):
        # A canceled job application is not linked to an approval
        # unless the job seeker has an accepted job application.
        job_application = self.create_job_application(
            state=job_applications_enums.JobApplicationState.CANCELLED, with_iae_eligibility_diagnosis=True
        )

        employer = self.company.members.first()
        client.force_login(employer)
        self.accept_job_application(client, job_application=job_application)

        job_application.refresh_from_db()
        assert job_application.job_seeker.approvals.count() == 1
        approval = job_application.job_seeker.approvals.first()
        assert approval.start_at == job_application.hiring_start_at
        assert job_application.state.is_accepted

    @freeze_time("2024-09-11")
    def test_accept_iae_criteria_can_be_certified(self, client, mocker):
        criteria_kind = random.choice(list(CERTIFIABLE_ADMINISTRATIVE_CRITERIA_KINDS))
        mocked_request = mocker.patch(
            "itou.utils.apis.api_particulier._request",
            return_value=RESPONSES[criteria_kind][ResponseKind.CERTIFIED],
        )
        ######### Case 1: if CRITERIA_KIND is one of the diagnosis criteria,
        ######### birth place and birth country are required.
        birthdate = datetime.date(1995, 12, 27)
        diagnosis = IAEEligibilityDiagnosisFactory(
            job_seeker=self.job_seeker,
            author_siae=self.company,
            certifiable=True,
            criteria_kinds=[criteria_kind, AdministrativeCriteriaKind.CAP_BEP],
        )
        job_application = self.create_job_application(
            eligibility_diagnosis=diagnosis,
            job_seeker__jobseeker_profile__birthdate=birthdate,
        )
        to_be_certified_criteria = diagnosis.selected_administrative_criteria.filter(
            administrative_criteria__kind__in=criteria_kind
        )
        url_accept = reverse("apply:accept", kwargs={"job_application_id": job_application.pk})

        employer = job_application.to_company.members.first()
        client.force_login(employer)

        response = client.get(url_accept)
        assertContains(response, self.BIRTH_COUNTRY_LABEL)
        assertContains(response, self.BIRTH_PLACE_LABEL)

        # CertifiedCriteriaForm
        # Birth country is mandatory.
        post_data = self._accept_view_post_data(job_application=job_application)
        post_data = {
            "birth_country": "",
            "birth_place": "",
        }
        response, _ = self.accept_job_application(
            client, job_application, post_data=post_data, assert_successful=False
        )

        # Wrong birth country and birth place.
        post_data["birth_country"] = "0012345"
        post_data["birth_place"] = "008765"
        response, _ = self.accept_job_application(
            client, job_application, post_data=post_data, assert_successful=False
        )
        assert response.context["form_personal_data"].errors == {
            "birth_place": ["Sélectionnez un choix valide. Ce choix ne fait pas partie de ceux disponibles."],
            "birth_country": [
                "Sélectionnez un choix valide. Ce choix ne fait pas partie de ceux disponibles.",
                "Le pays de naissance est obligatoire.",
            ],
        }

        birth_country = Country.objects.get(name="FRANCE")
        birth_place = Commune.objects.by_insee_code_and_period(
            "07141", job_application.job_seeker.jobseeker_profile.birthdate
        )
        # Field is disabled with Javascript on birth country input.
        # Elements with the disabled attribute are not submitted thus are not part of POST data.
        # See https://html.spec.whatwg.org/multipage/form-control-infrastructure.html#constructing-the-form-data-set
        post_data = {
            "birthdate": birthdate.isoformat(),
            "birth_country": "",
            "birth_place": birth_place.pk,
        }
        self.accept_job_application(client, job_application, post_data=post_data, assert_successful=True)
        mocked_request.assert_called_once()

        jobseeker_profile = job_application.job_seeker.jobseeker_profile
        jobseeker_profile.refresh_from_db()
        assert jobseeker_profile.birth_country == birth_country
        assert jobseeker_profile.birth_place == birth_place

        # certification
        for criterion in to_be_certified_criteria:
            criterion.refresh_from_db()
            assert criterion.certified
            assert criterion.data_returned_by_api == RESPONSES[criteria_kind][ResponseKind.CERTIFIED]
            assert criterion.certification_period == InclusiveDateRange(
                datetime.date(2024, 8, 1), datetime.date(2024, 12, 12)
            )
            assert criterion.certified_at

    @freeze_time("2024-09-11")
    def test_accept_geiq_criteria_can_be_certified(self, client, mocker):
        criteria_kind = random.choice(list(CERTIFIABLE_ADMINISTRATIVE_CRITERIA_KINDS))
        mocked_request = mocker.patch(
            "itou.utils.apis.api_particulier._request",
            return_value=RESPONSES[criteria_kind][ResponseKind.CERTIFIED],
        )
        birthdate = datetime.date(1995, 12, 27)
        self.company.kind = CompanyKind.GEIQ
        self.company.save()
        diagnosis = GEIQEligibilityDiagnosisFactory(
            job_seeker=self.job_seeker,
            author_geiq=self.company,
            from_employer=True,
            criteria_kinds=[criteria_kind],
        )
        job_application = self.create_job_application(
            geiq_eligibility_diagnosis=diagnosis,
            job_seeker__jobseeker_profile__birthdate=birthdate,
        )
        to_be_certified_criteria = GEIQSelectedAdministrativeCriteria.objects.filter(
            administrative_criteria__kind__in=CERTIFIABLE_ADMINISTRATIVE_CRITERIA_KINDS,
            eligibility_diagnosis=job_application.geiq_eligibility_diagnosis,
        ).all()
        url_accept = reverse("apply:accept", kwargs={"job_application_id": job_application.pk})

        employer = job_application.to_company.members.first()
        client.force_login(employer)

        response = client.get(url_accept)
        assertContains(response, self.BIRTH_COUNTRY_LABEL)
        assertContains(response, self.BIRTH_PLACE_LABEL)

        # CertifiedCriteriaForm
        # Birth country is mandatory.
        post_data = self._accept_view_post_data(job_application=job_application)
        post_data = {
            "birth_country": "",
            "birth_place": "",
        }
        response, _ = self.accept_job_application(
            client, job_application, post_data=post_data, assert_successful=False
        )

        # Then set it.
        birth_country = Country.objects.get(name="FRANCE")
        birth_place = Commune.objects.by_insee_code_and_period(
            "07141", job_application.job_seeker.jobseeker_profile.birthdate
        )
        post_data = {
            "birth_country": "",
            "birth_place": birth_place.pk,
        }
        response, _ = self.accept_job_application(client, job_application, post_data=post_data, assert_successful=True)
        mocked_request.assert_called_once()

        jobseeker_profile = job_application.job_seeker.jobseeker_profile
        jobseeker_profile.refresh_from_db()
        assert jobseeker_profile.birth_country == birth_country
        assert jobseeker_profile.birth_place == birth_place

        # certification
        for criterion in to_be_certified_criteria:
            criterion.refresh_from_db()
            assert criterion.certified
            assert criterion.data_returned_by_api == RESPONSES[criteria_kind][ResponseKind.CERTIFIED]
            assert criterion.certification_period == InclusiveDateRange(
                datetime.date(2024, 8, 1), datetime.date(2024, 12, 12)
            )
            assert criterion.certified_at

    @freeze_time("2024-09-11")
    def test_accept_no_siae_criteria_can_be_certified(self, client, mocker):
        mocker.patch(
            "itou.utils.apis.api_particulier._request",
            return_value=RESPONSES[AdministrativeCriteriaKind.RSA][ResponseKind.CERTIFIED],
        )
        company = CompanyFactory(not_subject_to_eligibility=True, with_membership=True, with_jobs=True)
        diagnosis = IAEEligibilityDiagnosisFactory(
            job_seeker=self.job_seeker,
            author_siae=self.company,
            certifiable=True,
            criteria_kinds=[AdministrativeCriteriaKind.RSA],
        )
        job_application = self.create_job_application(
            eligibility_diagnosis=diagnosis,
            selected_jobs=company.jobs.all(),
            to_company=company,
        )
        url_accept = reverse("apply:accept", kwargs={"job_application_id": job_application.pk})

        employer = job_application.to_company.members.first()
        client.force_login(employer)

        response = client.get(url_accept)
        assertNotContains(response, self.BIRTH_COUNTRY_LABEL)
        assertNotContains(response, self.BIRTH_PLACE_LABEL)

        post_data = self._accept_view_post_data(job_application=job_application)
        del post_data["birth_country"]
        del post_data["birth_place"]
        self.accept_job_application(client, job_application, post_data=post_data, assert_successful=True)

        jobseeker_profile = job_application.job_seeker.jobseeker_profile
        jobseeker_profile.refresh_from_db()
        assert not jobseeker_profile.birth_country
        assert not jobseeker_profile.birth_place

    @freeze_time("2024-09-11")
    def test_accept_updated_birthdate_invalidating_birth_place(self, client, mocker):
        mocker.patch(
            "itou.utils.apis.api_particulier._request",
            return_value=RESPONSES[AdministrativeCriteriaKind.RSA][ResponseKind.CERTIFIED],
        )
        diagnosis = IAEEligibilityDiagnosisFactory(
            job_seeker=self.job_seeker,
            author_siae=self.company,
            certifiable=True,
            criteria_kinds=[AdministrativeCriteriaKind.RSA],
        )
        # tests for a rare case where the birthdate will be cleaned for sharing between forms during the accept process
        job_application = self.create_job_application(eligibility_diagnosis=diagnosis)

        # required assumptions for the test case
        assert self.company.is_subject_to_eligibility_rules
        ed = EligibilityDiagnosis.objects.last_considered_valid(job_seeker=self.job_seeker, for_siae=self.company)
        assert ed and ed.criteria_can_be_certified()

        employer = self.company.members.first()
        client.force_login(employer)

        birthdate = self.job_seeker.jobseeker_profile.birthdate
        birth_place = (
            Commune.objects.filter(
                # The birthdate must be >= 1900-01-01, and we’re removing 1 day from start_date.
                Q(start_date__gt=datetime.date(1900, 1, 1)),
                # Must be a valid choice for the user current birthdate.
                Q(start_date__lte=birthdate),
                Q(end_date__gte=birthdate) | Q(end_date=None),
            )
            .exclude(
                Exists(
                    # The same code must not exists at the early_date.
                    Commune.objects.exclude(pk=OuterRef("pk")).filter(
                        code=OuterRef("code"),
                        start_date__lt=OuterRef("start_date"),
                    )
                )
            )
            .first()
        )
        early_date = birth_place.start_date - datetime.timedelta(days=1)
        post_data = {
            "birth_place": birth_place.pk,
            "birthdate": early_date,  # invalidates birth_place lookup, triggering error
        }

        response, _ = self.accept_job_application(
            client, job_application, post_data=post_data, assert_successful=False
        )
        expected_msg = (
            f"Le code INSEE {birth_place.code} n'est pas référencé par l'ASP en date du {early_date:%d/%m/%Y}"
        )

        assert response.context["form_personal_data"].errors == {"birth_place": [expected_msg]}

        # assert malformed birthdate does not crash view
        post_data["birthdate"] = "20240-001-001"
        response, _ = self.accept_job_application(
            client, job_application, post_data=post_data, assert_successful=False
        )

        assert response.context["form_personal_data"].errors == {"birthdate": ["Saisissez une date valide."]}

        # test that fixing the birthdate fixes the form submission
        post_data["birthdate"] = birth_place.start_date + datetime.timedelta(days=1)
        response, _ = self.accept_job_application(client, job_application, post_data=post_data, assert_successful=True)

    @freeze_time("2024-09-11")
    def test_accept_born_in_france_no_birth_place(self, client, mocker):
        birthdate = datetime.date(1995, 12, 27)
        diagnosis = IAEEligibilityDiagnosisFactory(
            job_seeker=self.job_seeker,
            author_siae=self.company,
            certifiable=True,
            criteria_kinds=[AdministrativeCriteriaKind.RSA],
        )
        job_application = self.create_job_application(
            eligibility_diagnosis=diagnosis,
            job_seeker__jobseeker_profile__birthdate=birthdate,
        )
        client.force_login(job_application.to_company.members.get())
        post_data = self._accept_view_post_data(job_application=job_application)
        post_data["birth_country"] = Country.objects.get(code=Country.INSEE_CODE_FRANCE).pk
        del post_data["birth_place"]
        response = client.post(
            reverse("apply:accept", kwargs={"job_application_id": job_application.pk}),
            headers={"hx-request": "true"},
            data=post_data,
        )
        assertContains(
            response,
            """
            <div class="alert alert-danger" role="alert" tabindex="0" data-emplois-give-focus-if-exist>
                <p>
                    <strong>Votre formulaire contient une erreur</strong>
                </p>
                <ul class="mb-0">
                    <li>Si le pays de naissance est la France, la commune de naissance est obligatoire.</li>
                </ul>
            </div>""",
            html=True,
            count=1,
        )

    @freeze_time("2024-09-11")
    def test_accept_born_outside_of_france_specifies_birth_place(self, client, mocker):
        birthdate = datetime.date(1995, 12, 27)
        diagnosis = IAEEligibilityDiagnosisFactory(
            job_seeker=self.job_seeker,
            author_siae=self.company,
            certifiable=True,
            criteria_kinds=[AdministrativeCriteriaKind.RSA],
        )
        job_application = self.create_job_application(
            eligibility_diagnosis=diagnosis,
            job_seeker__jobseeker_profile__birthdate=birthdate,
        )
        client.force_login(job_application.to_company.members.get())
        post_data = self._accept_view_post_data(job_application=job_application)
        post_data["birth_country"] = Country.objects.order_by("?").exclude(group=Country.Group.FRANCE).first().pk
        response = client.post(
            reverse("apply:accept", kwargs={"job_application_id": job_application.pk}),
            headers={"hx-request": "true"},
            data=post_data,
        )
        assertContains(
            response,
            """
            <div class="alert alert-danger" role="alert" tabindex="0" data-emplois-give-focus-if-exist>
                <p>
                    <strong>Votre formulaire contient une erreur</strong>
                </p>
                <ul class="mb-0">
                    <li>Il n'est pas possible de saisir une commune de naissance hors de France.</li>
                </ul>
            </div>""",
            html=True,
            count=1,
        )

    @freeze_time("2024-09-11")
    def test_accept_personal_data_readonly_with_certified_criteria(self, client):
        job_seeker = JobSeekerFactory(
            born_in_france=True,
            with_pole_emploi_id=True,
            with_ban_api_mocked_address=True,
        )
        selected_criteria = IAESelectedAdministrativeCriteriaFactory(
            eligibility_diagnosis__job_seeker=job_seeker,
            eligibility_diagnosis__author_siae=self.company,
            certified=True,
        )
        job_application = JobApplicationSentByJobSeekerFactory(
            job_seeker=job_seeker,
            to_company=self.company,
            state=JobApplicationState.PROCESSING,
            eligibility_diagnosis=selected_criteria.eligibility_diagnosis,
            selected_jobs=[self.company.jobs.first()],
        )
        client.force_login(self.company.members.get())

        url_accept = reverse("apply:accept", kwargs={"job_application_id": job_application.pk})
        response = client.get(url_accept)
        assertContains(response, users_test_constants.CERTIFIED_FORM_READONLY_HTML, html=True, count=1)
        post_data = {
            "title": Title.M if job_seeker.title is Title.MME else Title.MME,
            "first_name": "Léon",
            "last_name": "Munitionette",
            "birth_place": Commune.objects.by_insee_code_and_period("07141", datetime.date(1990, 1, 1)).pk,
            "birthdate": "1990-01-01",
        }
        self.accept_job_application(client, job_application, post_data=post_data)

        refreshed_job_seeker = User.objects.select_related("jobseeker_profile").get(pk=job_seeker.pk)
        for attr in ["title", "first_name", "last_name"]:
            assert getattr(refreshed_job_seeker, attr) == getattr(job_seeker, attr)
        for attr in ["birthdate", "birth_place", "birth_country"]:
            assert getattr(refreshed_job_seeker.jobseeker_profile, attr) == getattr(job_seeker.jobseeker_profile, attr)


class TestProcessTemplates:
    """
    Test actions available in the details template for the different.
    states of a job application.
    """

    @pytest.fixture(autouse=True)
    def setup_method(self, client):
        self.job_application = JobApplicationFactory(eligibility_diagnosis=None)
        self.employer = self.job_application.to_company.members.first()

        kwargs = {"job_application_id": self.job_application.pk}
        self.url_details = reverse("apply:details_for_company", kwargs=kwargs)
        self.url_process = reverse("apply:process", kwargs=kwargs)
        self.url_eligibility = reverse("apply:eligibility", kwargs=kwargs)
        self.url_refuse = reverse("apply:refuse", kwargs=kwargs)
        self.url_postpone = reverse("apply:postpone", kwargs=kwargs)
        self.url_accept = reverse("apply:accept", kwargs=kwargs)

    def test_details_template_for_state_new(self, client):
        """Test actions available when the state is new."""
        client.force_login(self.employer)
        response = client.get(self.url_details)
        # Test template content.
        assertContains(response, self.url_process)
        assertNotContains(response, self.url_eligibility)
        assertContains(response, self.url_refuse)
        assertNotContains(response, self.url_postpone)
        assertNotContains(response, self.url_accept)

    def test_details_template_for_state_processing(self, client):
        """Test actions available when the state is processing."""
        client.force_login(self.employer)
        self.job_application.state = job_applications_enums.JobApplicationState.PROCESSING
        self.job_application.save()
        response = client.get(self.url_details)
        # Test template content.
        assertNotContains(response, self.url_process)
        assertContains(response, self.url_eligibility)
        assertContains(response, self.url_refuse)
        assertContains(response, self.url_postpone)
        assertNotContains(response, self.url_accept)

    def test_details_template_for_state_prior_to_hire(self, client):
        """Test actions available when the state is prior_to_hire."""
        client.force_login(self.employer)
        self.job_application.state = job_applications_enums.JobApplicationState.PRIOR_TO_HIRE
        self.job_application.save()
        response = client.get(self.url_details)
        # Test template content.
        assertNotContains(response, self.url_process)
        assertContains(response, self.url_eligibility)
        assertContains(response, self.url_refuse)
        assertContains(response, self.url_postpone)
        assertNotContains(response, self.url_accept)

    def test_details_template_for_state_processing_but_suspended_siae(self, client):
        """Test actions available when the state is processing but SIAE is suspended"""
        Sanctions.objects.create(
            evaluated_siae=EvaluatedSiaeFactory(siae=self.job_application.to_company),
            suspension_dates=InclusiveDateRange(timezone.localdate() - relativedelta(days=1)),
        )
        client.force_login(self.employer)
        self.job_application.state = job_applications_enums.JobApplicationState.PROCESSING
        self.job_application.save()
        response = client.get(self.url_details)
        # Test template content.
        assertNotContains(response, self.url_process)
        assertNotContains(response, self.url_eligibility)
        assertContains(
            response,
            (
                "Vous ne pouvez pas valider les critères d'éligibilité suite aux "
                "mesures prises dans le cadre du contrôle a posteriori"
            ),
        )
        assertContains(response, self.url_refuse)
        assertContains(response, self.url_postpone)
        assertNotContains(response, self.url_accept)

    def test_details_template_for_state_postponed(self, client):
        """Test actions available when the state is postponed."""
        client.force_login(self.employer)
        self.job_application.state = job_applications_enums.JobApplicationState.POSTPONED
        self.job_application.save()
        response = client.get(self.url_details)
        # Test template content.
        assertNotContains(response, self.url_process)
        assertContains(response, self.url_eligibility)
        assertContains(response, self.url_refuse)
        assertNotContains(response, self.url_postpone)
        assertNotContains(response, self.url_accept)

    def test_details_template_for_state_postponed_valid_diagnosis(self, client):
        """Test actions available when the state is postponed."""
        client.force_login(self.employer)
        IAEEligibilityDiagnosisFactory(from_prescriber=True, job_seeker=self.job_application.job_seeker)
        self.job_application.state = job_applications_enums.JobApplicationState.POSTPONED
        self.job_application.save()
        response = client.get(self.url_details)
        # Test template content.
        assertNotContains(response, self.url_process)
        assertNotContains(response, self.url_eligibility)
        assertContains(response, self.url_refuse)
        assertNotContains(response, self.url_postpone)
        assertContains(response, self.url_accept)

    def test_details_template_for_state_obsolete(self, client):
        client.force_login(self.employer)
        self.job_application.state = job_applications_enums.JobApplicationState.OBSOLETE
        self.job_application.processed_at = timezone.now()
        self.job_application.save()

        response = client.get(self.url_details)

        # Test template content.
        assertNotContains(response, self.url_process)
        assertContains(response, self.url_eligibility)
        assertNotContains(response, self.url_refuse)
        assertNotContains(response, self.url_postpone)
        assertNotContains(response, self.url_accept)

    def test_details_template_for_state_obsolete_valid_diagnosis(self, client):
        client.force_login(self.employer)
        IAEEligibilityDiagnosisFactory(from_prescriber=True, job_seeker=self.job_application.job_seeker)
        self.job_application.state = job_applications_enums.JobApplicationState.OBSOLETE
        self.job_application.processed_at = timezone.now()
        self.job_application.save()

        response = client.get(self.url_details)

        # Test template content.
        assertNotContains(response, self.url_process)
        assertNotContains(response, self.url_eligibility)
        assertNotContains(response, self.url_refuse)
        assertNotContains(response, self.url_postpone)
        assertContains(response, self.url_accept)

    def test_details_template_for_state_refused(self, client):
        """Test actions available for other states."""
        client.force_login(self.employer)
        self.job_application.state = job_applications_enums.JobApplicationState.REFUSED
        self.job_application.processed_at = timezone.now()
        self.job_application.save()
        response = client.get(self.url_details)
        # Test template content.
        assertNotContains(response, self.url_process)
        assertContains(response, self.url_eligibility)
        assertNotContains(response, self.url_refuse)
        assertNotContains(response, self.url_postpone)
        assertNotContains(response, self.url_accept)

    def test_details_template_for_state_refused_valid_diagnosis(self, client):
        """Test actions available for other states."""
        client.force_login(self.employer)
        IAEEligibilityDiagnosisFactory(from_prescriber=True, job_seeker=self.job_application.job_seeker)
        self.job_application.state = job_applications_enums.JobApplicationState.REFUSED
        self.job_application.processed_at = timezone.now()
        self.job_application.save()
        response = client.get(self.url_details)
        # Test template content.
        assertNotContains(response, self.url_process)
        assertNotContains(response, self.url_eligibility)
        assertNotContains(response, self.url_refuse)
        assertNotContains(response, self.url_postpone)
        assertContains(response, self.url_accept)

    def test_details_template_for_state_canceled(self, client):
        """Test actions available for other states."""
        client.force_login(self.employer)
        self.job_application.state = job_applications_enums.JobApplicationState.CANCELLED
        self.job_application.processed_at = timezone.now()
        self.job_application.save()
        response = client.get(self.url_details)
        # Test template content.
        assertNotContains(response, self.url_process)
        assertContains(response, self.url_eligibility)
        assertNotContains(response, self.url_refuse)
        assertNotContains(response, self.url_postpone)
        assertNotContains(response, self.url_accept)

    def test_details_template_for_state_canceled_valid_diagnosis(self, client):
        """Test actions available for other states."""
        client.force_login(self.employer)
        IAEEligibilityDiagnosisFactory(from_prescriber=True, job_seeker=self.job_application.job_seeker)
        self.job_application.state = job_applications_enums.JobApplicationState.CANCELLED
        self.job_application.processed_at = timezone.now()
        self.job_application.save()
        response = client.get(self.url_details)
        # Test template content.
        assertNotContains(response, self.url_process)
        assertNotContains(response, self.url_eligibility)
        assertNotContains(response, self.url_refuse)
        assertNotContains(response, self.url_postpone)
        assertContains(response, self.url_accept)

    def test_details_template_for_state_accepted(self, client):
        """Test actions available for other states."""
        client.force_login(self.employer)
        self.job_application.state = job_applications_enums.JobApplicationState.ACCEPTED
        self.job_application.processed_at = timezone.now()
        self.job_application.save()
        response = client.get(self.url_details)
        # Test template content.
        assertNotContains(response, self.url_process)
        assertNotContains(response, self.url_eligibility)
        assertNotContains(response, self.url_refuse)
        assertNotContains(response, self.url_postpone)
        assertNotContains(response, self.url_accept)


class TestProcessTransferJobApplication:
    TRANSFER_TO_OTHER_COMPANY_SENTENCE = "Transférer cette candidature vers"

    def test_job_application_external_transfer_only_for_lone_users(self, client, snapshot):
        # A user member of only one company will see the button but with
        # only the "+ autre structure" link
        company = CompanyFactory(with_membership=True)
        user = company.members.first()
        job_application = JobApplicationFactory(
            sent_by_authorized_prescriber_organisation=True,
            to_company=company,
            state=job_applications_enums.JobApplicationState.REFUSED,
        )

        client.force_login(user)
        response = client.get(reverse("apply:details_for_company", kwargs={"job_application_id": job_application.pk}))
        assertContains(response, self.TRANSFER_TO_OTHER_COMPANY_SENTENCE)
        assert (
            str(
                parse_response_to_soup(
                    response,
                    ".c-box--action .dropdown-structure",
                    replace_in_attr=[
                        (
                            "href",
                            f"/apply/{job_application.pk}/siae/external-transfer/1",
                            "/apply/[PK of JobApplication]/siae/external-transfer/1",
                        )
                    ],
                )
            )
            == snapshot
        )

    def test_job_application_external_transfer_disabled_for_bad_state(self, client, snapshot):
        # external transfer is disabled for non refused job applications
        company = CompanyFactory(with_membership=True)
        user = company.members.first()
        job_application = JobApplicationFactory(
            sent_by_authorized_prescriber_organisation=True,
            to_company=company,
            state=job_applications_enums.JobApplicationState.PROCESSING,
        )

        client.force_login(user)
        response = client.get(reverse("apply:details_for_company", kwargs={"job_application_id": job_application.pk}))
        assertContains(response, self.TRANSFER_TO_OTHER_COMPANY_SENTENCE)
        assert str(parse_response_to_soup(response, ".c-box--action .dropdown-structure")) == snapshot

    def test_job_application_transfer_disabled_for_bad_state(self, client):
        # A user member of multiple companies must not be able to transfer
        # an accepted job application to another company
        company = CompanyFactory(with_membership=True)
        user = company.members.first()
        CompanyMembershipFactory(user=user)
        job_application = JobApplicationFactory(
            sent_by_authorized_prescriber_organisation=True,
            to_company=company,
            state=job_applications_enums.JobApplicationState.ACCEPTED,
        )

        client.force_login(user)
        response = client.get(reverse("apply:details_for_company", kwargs={"job_application_id": job_application.pk}))
        assertNotContains(response, self.TRANSFER_TO_OTHER_COMPANY_SENTENCE)

    def test_job_application_transfer_enabled(self, client):
        # A user member of several company can transfer a job application
        company = CompanyFactory(with_membership=True)
        other_company = CompanyFactory(with_membership=True)
        user = company.members.first()
        other_company.members.add(user)
        job_application = JobApplicationFactory(
            sent_by_authorized_prescriber_organisation=True,
            to_company=company,
            state=job_applications_enums.JobApplicationState.PROCESSING,
        )

        assert 2 == user.companymembership_set.count()

        client.force_login(user)
        response = client.get(reverse("apply:details_for_company", kwargs={"job_application_id": job_application.pk}))
        assertContains(response, self.TRANSFER_TO_OTHER_COMPANY_SENTENCE)

    def test_job_application_transfer_redirection(self, client, snapshot):
        # After transfering a job application,
        # user must be redirected to job application list
        # with a nice message
        company = CompanyFactory(with_membership=True)
        other_company = CompanyFactory(with_membership=True, for_snapshot=True)
        user = company.members.first()
        other_company.members.add(user)
        job_application = JobApplicationFactory(
            sent_by_authorized_prescriber_organisation=True,
            to_company=company,
            state=job_applications_enums.JobApplicationState.PROCESSING,
            job_seeker__for_snapshot=True,
            job_seeker__first_name="<>html escaped<>",
        )
        transfer_url = reverse("apply:transfer", kwargs={"job_application_id": job_application.pk})

        client.force_login(user)
        response = client.get(reverse("apply:details_for_company", kwargs={"job_application_id": job_application.pk}))

        assertContains(response, self.TRANSFER_TO_OTHER_COMPANY_SENTENCE)
        assertContains(response, f"transfer_confirmation_modal_{other_company.pk}")
        assertContains(response, "target_company_id")
        assertContains(response, transfer_url)

        # Confirm from modal window
        post_data = {"target_company_id": other_company.pk}
        response = client.post(transfer_url, data=post_data, follow=True)
        messages = list(response.context.get("messages"))

        assertRedirects(response, reverse("apply:list_for_siae"))
        assert messages
        assert len(messages) == 1
        assert str(messages[0]) == snapshot(name="job application transfer message")

        job_application.refresh_from_db()
        assert job_application.state == job_applications_enums.JobApplicationState.NEW
        assert job_application.logs.get().transition == "transfer"
        assert job_application.to_company_id == other_company.pk

    def test_job_application_transfer_without_rights(self, client):
        company = CompanyFactory()
        other_company = CompanyFactory()
        user = JobSeekerFactory()
        job_application = JobApplicationFactory(
            sent_by_authorized_prescriber_organisation=True,
            to_company=company,
            state=job_applications_enums.JobApplicationState.PROCESSING,
        )
        # Forge query
        client.force_login(user)
        post_data = {"target_company_id": other_company.pk}
        transfer_url = reverse("apply:transfer", kwargs={"job_application_id": job_application.pk})
        response = client.post(transfer_url, data=post_data)
        assert response.status_code == 403


@pytest.mark.parametrize("reason", ["prevent_objectives", "non_eligible"])
def test_refuse_jobapplication_geiq_reasons(client, reason):
    job_application = JobApplicationFactory(
        sent_by_authorized_prescriber_organisation=True,
        state=job_applications_enums.JobApplicationState.PROCESSING,
        to_company__kind=CompanyKind.GEIQ,
    )
    assert job_application.state.is_processing
    employer = job_application.to_company.members.first()
    client.force_login(employer)

    url = reverse("apply:refuse", kwargs={"job_application_id": job_application.pk})
    response = client.get(url)
    refuse_session_name = get_session_name(client.session, RefuseWizardView.expected_session_kind)
    assert client.session[refuse_session_name] == {
        "config": {
            "tunnel": "single",
            "reset_url": reverse("apply:details_for_company", kwargs={"job_application_id": job_application.pk}),
        },
        "application_ids": [job_application.pk],
    }
    refusal_reason_url = reverse(
        "apply:batch_refuse_steps", kwargs={"session_uuid": refuse_session_name, "step": "reason"}
    )
    assertRedirects(response, refusal_reason_url)

    post_data = {
        "refusal_reason": reason,
    }
    response = client.post(refusal_reason_url, data=post_data)
    assert response.context["form"].errors == {
        "refusal_reason": [f"Sélectionnez un choix valide. {reason} n’en fait pas partie."]
    }


@pytest.mark.ignore_unknown_variable_template_error("with_matomo_event")
def test_details_for_prescriber_not_can_have_prior_actions(client):
    kind = random.choice(list(set(CompanyKind) - {CompanyKind.GEIQ}))
    job_application = JobApplicationFactory(
        sent_by_authorized_prescriber_organisation=True,
        state=job_applications_enums.JobApplicationState.PROCESSING,
        to_company__kind=kind,
    )
    client.force_login(job_application.sender)

    url = reverse("apply:details_for_prescriber", kwargs={"job_application_id": job_application.pk})
    response = client.get(url)
    assertNotContains(response, PRIOR_ACTION_SECTION_TITLE)


@pytest.mark.ignore_unknown_variable_template_error("with_matomo_event")
def test_details_for_prescriber_geiq_without_prior_actions(client):
    job_application = JobApplicationFactory(
        sent_by_authorized_prescriber_organisation=True,
        state=job_applications_enums.JobApplicationState.PROCESSING,
        with_geiq_eligibility_diagnosis_from_prescriber=True,
    )
    prescriber = job_application.sender_prescriber_organization.members.first()
    client.force_login(prescriber)

    url = reverse("apply:details_for_prescriber", kwargs={"job_application_id": job_application.pk})
    response = client.get(url)
    assert response.status_code == 200

    assert response.context["geiq_eligibility_diagnosis"] == job_application.geiq_eligibility_diagnosis
    assertNotContains(response, PRIOR_ACTION_SECTION_TITLE)


@pytest.mark.ignore_unknown_variable_template_error("with_matomo_event")
def test_details_for_prescriber_geiq_with_prior_actions(client):
    job_application = JobApplicationFactory(
        sent_by_authorized_prescriber_organisation=True,
        state=job_applications_enums.JobApplicationState.PROCESSING,
        with_geiq_eligibility_diagnosis_from_prescriber=True,
    )
    prior_action = PriorActionFactory(
        job_application=job_application, action=job_applications_enums.Prequalification.AFPR
    )
    prescriber = job_application.sender_prescriber_organization.members.first()
    delete_button = (
        '<button class="btn btn-link" data-bs-toggle="modal" '
        f'data-bs-target="#delete_prior_action_{prior_action.id}_modal">'
    )
    client.force_login(prescriber)

    url = reverse("apply:details_for_prescriber", kwargs={"job_application_id": job_application.pk})
    response = client.get(url)

    assertContains(response, PRIOR_ACTION_SECTION_TITLE)
    assertContains(response, prior_action.action.label)
    assertNotContains(response, delete_button)


@pytest.mark.ignore_unknown_variable_template_error("with_matomo_event")
def test_details_for_jobseeker_geiq_with_prior_actions(client):
    job_application = JobApplicationFactory(
        sent_by_authorized_prescriber_organisation=True,
        state=job_applications_enums.JobApplicationState.PROCESSING,
        with_geiq_eligibility_diagnosis_from_prescriber=True,
    )
    prior_action = PriorActionFactory(
        job_application=job_application, action=job_applications_enums.Prequalification.AFPR
    )
    job_seeker = job_application.job_seeker
    delete_button = (
        '<button class="btn btn-link" data-bs-toggle="modal" '
        f'data-bs-target="#delete_prior_action_{prior_action.id}_modal">'
    )

    client.force_login(job_seeker)

    url = reverse("apply:details_for_jobseeker", kwargs={"job_application_id": job_application.pk})
    response = client.get(url)

    assertContains(response, PRIOR_ACTION_SECTION_TITLE)
    assertContains(response, prior_action.action.label)
    assertNotContains(response, delete_button)


@pytest.mark.ignore_unknown_variable_template_error("with_matomo_event")
def test_details_sender_email_display_for_job_seeker(client):
    SENDER_EMAIL_HIDDEN = "<small>Adresse e-mail</small><strong>Non communiquée</strong>"

    # Email hidden for prescriber
    job_application = JobApplicationFactory(sent_by_authorized_prescriber_organisation=True)
    job_seeker = job_application.job_seeker

    client.force_login(job_seeker)

    url = reverse("apply:details_for_jobseeker", kwargs={"job_application_id": job_application.pk})
    response = client.get(url)
    assertNotContains(
        response, f"<small>Adresse e-mail</small><strong>{job_application.sender.email}</strong>", html=True
    )
    assertContains(response, SENDER_EMAIL_HIDDEN, html=True)

    # Email hidden for employer
    employer = job_application.to_company.members.first()
    job_application.sender = employer
    job_application.sender_kind = job_applications_enums.SenderKind.EMPLOYER
    job_application.save(update_fields=["sender", "sender_kind", "updated_at"])
    response = client.get(url)
    assertNotContains(
        response, f"<small>Adresse e-mail</small><strong>{job_application.sender.email}</strong>", html=True
    )
    assertContains(response, SENDER_EMAIL_HIDDEN, html=True)

    # Email shown for job seeker
    job_application.sender = job_seeker
    job_application.sender_kind = job_applications_enums.SenderKind.JOB_SEEKER
    job_application.save(update_fields=["sender", "sender_kind", "updated_at"])
    response = client.get(url)
    assertContains(
        response, f"<small>Adresse e-mail</small><strong>{job_application.sender.email}</strong>", html=True
    )
    assertNotContains(response, SENDER_EMAIL_HIDDEN, html=True)


def test_accept_button(client):
    job_application = JobApplicationFactory(
        state=job_applications_enums.JobApplicationState.PROCESSING,
        to_company__kind=CompanyKind.GEIQ,
    )
    accept_url = reverse("apply:accept", kwargs={"job_application_id": job_application.pk})
    DIRECT_ACCEPT_BUTTON = (
        f'<a href="{accept_url}" class="btn btn-lg btn-white btn-block btn-ico" '
        'data-matomo-event="true" data-matomo-category="candidature" '
        'data-matomo-action="clic" data-matomo-option="accept_application">'
        '\n            <i class="ri-check-line fw-medium" aria-hidden="true"></i>'
        "\n            <span>Accepter</span>"
        "\n        </a>"
    )
    client.force_login(job_application.to_company.members.first())
    response = client.get(reverse("apply:details_for_company", kwargs={"job_application_id": job_application.pk}))
    # GEIQ without GEIQ diagnosis: we get the modals
    assertNotContains(response, DIRECT_ACCEPT_BUTTON, html=True)

    job_application.to_company.kind = CompanyKind.AI
    job_application.to_company.save(update_fields=("kind", "updated_at"))

    response = client.get(reverse("apply:details_for_company", kwargs={"job_application_id": job_application.pk}))
    assertContains(response, DIRECT_ACCEPT_BUTTON, html=True)


def test_add_prior_action_new(client):
    # State is new
    job_application = JobApplicationFactory(to_company__kind=CompanyKind.GEIQ)
    client.force_login(job_application.to_company.members.first())
    add_prior_action_url = reverse("apply:add_prior_action", kwargs={"job_application_id": job_application.pk})
    today = timezone.localdate()
    response = client.post(
        add_prior_action_url,
        data={
            "action": job_applications_enums.Prequalification.AFPR,
            "start_at": today,
            "end_at": today + relativedelta(days=2),
        },
    )
    assert response.status_code == 403
    assert not job_application.prior_actions.exists()


@freeze_time("2023-12-12 13:37:00", tz_offset=-1)
def test_add_prior_action_processing(client, snapshot):
    job_application = JobApplicationFactory(
        for_snapshot=True,
        to_company__kind=CompanyKind.GEIQ,
        state=job_applications_enums.JobApplicationState.PROCESSING,
        created_at=datetime.datetime(2023, 12, 10, 10, 11, 11, tzinfo=datetime.UTC),
    )
    client.force_login(job_application.to_company.members.first())
    add_prior_action_url = reverse("apply:add_prior_action", kwargs={"job_application_id": job_application.pk})
    today = timezone.localdate()
    response = client.post(
        add_prior_action_url,
        data={
            "action": job_applications_enums.Prequalification.AFPR,
            "start_at": today,
            "end_at": today + relativedelta(days=2),
        },
    )
    assert response.status_code == 200
    job_application.refresh_from_db()
    assert job_application.state.is_prior_to_hire
    prior_action = job_application.prior_actions.get()
    assert prior_action.action == job_applications_enums.Prequalification.AFPR
    assert prior_action.dates.lower == today
    assert prior_action.dates.upper == today + relativedelta(days=2)
    soup = parse_response_to_soup(response, selector=f"#transition_logs_{job_application.pk}")
    assert str(soup) == snapshot

    # State is accepted
    job_application.state = job_applications_enums.JobApplicationState.ACCEPTED
    job_application.processed_at = timezone.now()
    job_application.save(update_fields=("state", "processed_at", "updated_at"))
    today = timezone.localdate()
    response = client.post(
        add_prior_action_url,
        data={
            "action": job_applications_enums.Prequalification.POE,
            "start_at": today,
            "end_at": today + relativedelta(days=2),
        },
    )
    assert response.status_code == 403
    assert not job_application.prior_actions.filter(action=job_applications_enums.Prequalification.POE).exists()

    # State is processing but company is not a GEIQ
    job_application = JobApplicationFactory(
        to_company__kind=CompanyKind.AI, state=job_applications_enums.JobApplicationState.PROCESSING
    )
    client.force_login(job_application.to_company.members.first())
    today = timezone.localdate()
    response = client.post(
        add_prior_action_url,
        data={
            "action": job_applications_enums.Prequalification.AFPR,
            "start_at": today,
            "end_at": today + relativedelta(days=2),
        },
    )
    assert response.status_code == 404
    assert not job_application.prior_actions.exists()


def test_modify_prior_action(client):
    job_application = JobApplicationFactory(
        to_company__kind=CompanyKind.GEIQ, state=job_applications_enums.JobApplicationState.POSTPONED
    )
    prior_action = PriorActionFactory(
        job_application=job_application, action=job_applications_enums.Prequalification.AFPR
    )
    client.force_login(job_application.to_company.members.first())
    modify_prior_action_url = reverse(
        "apply:modify_prior_action",
        kwargs={"job_application_id": job_application.pk, "prior_action_id": prior_action.pk},
    )
    new_start_date = timezone.localdate() - relativedelta(days=10)
    new_end_date = new_start_date + relativedelta(days=6)
    response = client.post(
        modify_prior_action_url,
        data={
            "action": job_applications_enums.ProfessionalSituationExperience.PMSMP,
            "start_at": new_start_date,
            "end_at": new_end_date,
        },
    )
    assert response.status_code == 200
    prior_action.refresh_from_db()
    assert prior_action.dates.lower == new_start_date
    assert prior_action.dates.upper == new_end_date
    assert prior_action.action == job_applications_enums.ProfessionalSituationExperience.PMSMP

    job_application.state = job_applications_enums.JobApplicationState.ACCEPTED
    job_application.processed_at = timezone.now()
    job_application.save(update_fields=("state", "processed_at", "updated_at"))
    response = client.post(
        modify_prior_action_url,
        data={
            "action": job_applications_enums.ProfessionalSituationExperience.MRS,
            "start_at": new_start_date,
            "end_at": new_end_date,
        },
    )
    assert response.status_code == 403
    prior_action.refresh_from_db()
    assert prior_action.action == job_applications_enums.ProfessionalSituationExperience.PMSMP


def test_delete_prior_action_accepted(client):
    job_application = JobApplicationFactory(
        to_company__kind=CompanyKind.GEIQ, state=job_applications_enums.JobApplicationState.ACCEPTED
    )
    prior_action = PriorActionFactory(
        job_application=job_application, action=job_applications_enums.Prequalification.AFPR
    )
    client.force_login(job_application.to_company.members.first())
    delete_prior_action_url = reverse(
        "apply:delete_prior_action",
        kwargs={"job_application_id": job_application.pk, "prior_action_id": prior_action.pk},
    )
    response = client.post(delete_prior_action_url, data={})
    # Once the application is accepted you cannot delete prior actions
    assert response.status_code == 403
    prior_action.refresh_from_db()


@pytest.mark.parametrize("with_geiq_diagnosis", [True, False])
@freeze_time("2023-12-12 13:37:00", tz_offset=-1)
def test_delete_prior_action(client, snapshot, with_geiq_diagnosis):
    job_application = JobApplicationFactory(
        for_snapshot=True,
        to_company__kind=CompanyKind.GEIQ,
        state=job_applications_enums.JobApplicationState.PROCESSING,
        created_at=datetime.datetime(2023, 12, 10, 10, 11, 11, tzinfo=datetime.UTC),
    )
    prior_action1 = PriorActionFactory(
        job_application=job_application, action=job_applications_enums.Prequalification.AFPR
    )
    prior_action2 = PriorActionFactory(
        job_application=job_application, action=job_applications_enums.Prequalification.AFPR
    )
    user = job_application.to_company.members.first()
    if with_geiq_diagnosis:
        GEIQEligibilityDiagnosisFactory(
            job_seeker=job_application.job_seeker,
            author_geiq=job_application.to_company,
            author=user,
            author_kind=AuthorKind.GEIQ,
        )
    # Create transition logs
    with freeze_time(timezone.now() + datetime.timedelta(minutes=3)):
        job_application.move_to_prior_to_hire(user=user)
    delete_prior_action1_url = reverse(
        "apply:delete_prior_action",
        kwargs={"job_application_id": job_application.pk, "prior_action_id": prior_action1.pk},
    )
    delete_prior_action2_url = reverse(
        "apply:delete_prior_action",
        kwargs={"job_application_id": job_application.pk, "prior_action_id": prior_action2.pk},
    )
    client.force_login(user)
    details_url = reverse("apply:details_for_company", kwargs={"job_application_id": job_application.pk})
    response = client.get(details_url)
    simulated_page = parse_response_to_soup(response, selector="#main")

    # Delete first action
    response = client.post(delete_prior_action1_url, data={})
    assert response.status_code == 200
    update_page_with_htmx(
        simulated_page,
        f"form[hx-post='{delete_prior_action1_url}']",
        response,
    )
    job_application.refresh_from_db()
    assert job_application.prior_actions.count() == 1
    assert job_application.state.is_prior_to_hire

    # Check that a fresh reload gets us in the same state
    response = client.get(details_url)
    assertSoupEqual(parse_response_to_soup(response, selector="#main"), simulated_page)

    # Delete second action
    response = client.post(delete_prior_action2_url, data={})
    assert response.status_code == 200
    soup = parse_response_to_soup(response, selector=f"#transition_logs_{job_application.pk}")
    assert str(soup) == snapshot
    update_page_with_htmx(
        simulated_page,
        f"#delete_prior_action_{prior_action2.pk}_modal > div > div > div > form",
        response,
    )
    job_application.refresh_from_db()
    assert job_application.prior_actions.count() == 0
    assert job_application.state.is_processing

    # Check that a fresh reload gets us in the same state
    response = client.get(details_url)
    assertSoupEqual(parse_response_to_soup(response, selector="#main"), simulated_page)


def test_htmx_add_prior_action_and_cancel(client):
    job_application = JobApplicationFactory(
        to_company__kind=CompanyKind.GEIQ, state=job_applications_enums.JobApplicationState.PROCESSING
    )
    client.force_login(job_application.to_company.members.first())
    details_url = reverse("apply:details_for_company", kwargs={"job_application_id": job_application.pk})
    response = client.get(details_url)
    simulated_page = parse_response_to_soup(response, selector="#main")

    add_prior_action_url = reverse("apply:add_prior_action", kwargs={"job_application_id": job_application.pk})
    response = client.post(
        add_prior_action_url,
        data={
            "action": job_applications_enums.Prequalification.AFPR,
        },
    )
    update_page_with_htmx(simulated_page, "#add_prior_action > form", response)
    # Click on Annuler
    response = client.get(add_prior_action_url)
    update_page_with_htmx(
        simulated_page,
        "#add_prior_action > form > div > button[hx-get]",
        response,
    )

    # Check that a fresh reload gets us in the same state
    response = client.get(details_url)
    assertSoupEqual(parse_response_to_soup(response, selector="#main"), simulated_page)


def test_htmx_modify_prior_action_and_cancel(client):
    job_application = JobApplicationFactory(
        to_company__kind=CompanyKind.GEIQ, state=job_applications_enums.JobApplicationState.PROCESSING
    )
    prior_action = PriorActionFactory(job_application=job_application)
    client.force_login(job_application.to_company.members.first())
    details_url = reverse("apply:details_for_company", kwargs={"job_application_id": job_application.pk})
    response = client.get(details_url)
    simulated_page = parse_response_to_soup(response, selector="#main")

    modify_prior_action_url = reverse(
        "apply:modify_prior_action",
        kwargs={"job_application_id": job_application.pk, "prior_action_id": prior_action.pk},
    )
    response = client.get(modify_prior_action_url + "?modify=")
    update_page_with_htmx(
        simulated_page,
        f"#prior-action-{prior_action.pk}-modify-btn",
        response,
    )
    # Click on Annuler
    response = client.get(modify_prior_action_url)
    update_page_with_htmx(simulated_page, f"#prior-action-{prior_action.pk} > form > div > button[hx-get]", response)

    # Check that a fresh reload gets us in the same state
    response = client.get(details_url)
    assertSoupEqual(parse_response_to_soup(response, selector="#main"), simulated_page)


@pytest.mark.parametrize("with_geiq_diagnosis", [True, False])
def test_details_for_company_with_prior_action(client, with_geiq_diagnosis):
    job_application = JobApplicationFactory(
        to_company__kind=CompanyKind.GEIQ,
        to_company__not_in_territorial_experimentation=True,
    )
    user = job_application.to_company.members.first()
    client.force_login(user)
    if with_geiq_diagnosis:
        GEIQEligibilityDiagnosisFactory(
            job_seeker=job_application.job_seeker,
            author_geiq=job_application.to_company,
            author=user,
            author_kind=AuthorKind.GEIQ,
        )

    details_url = reverse("apply:details_for_company", kwargs={"job_application_id": job_application.pk})
    response = client.get(details_url)
    # The job application is still new
    assertNotContains(response, PRIOR_ACTION_SECTION_TITLE)

    # Switch state to processing
    response = client.post(reverse("apply:process", kwargs={"job_application_id": job_application.pk}))
    assertRedirects(response, details_url)
    job_application.refresh_from_db()
    assert job_application.state == job_applications_enums.JobApplicationState.PROCESSING

    END_AT_LABEL = "Date de fin prévisionnelle"
    MISSING_FIELD_MESSAGE = "Ce champ est obligatoire"
    ADD_AN_ACTION_SELECTED = '<option value="" selected>Ajouter une action</option>'

    # Now the prior action section is visible
    response = client.get(details_url)
    assertContains(response, PRIOR_ACTION_SECTION_TITLE)
    # With PriorActionForm
    assertContains(response, ADD_AN_ACTION_SELECTED)
    # but not the dates fields
    assertNotContains(response, END_AT_LABEL)

    simulated_page = parse_response_to_soup(response, selector="#main")

    add_prior_action_url = reverse("apply:add_prior_action", kwargs={"job_application_id": job_application.pk})
    # Select the action type
    response = client.post(add_prior_action_url, data={"action": job_applications_enums.Prequalification.AFPR})
    update_page_with_htmx(simulated_page, "#add_prior_action > form", response)

    # To get access to date fields
    assertContains(response, END_AT_LABEL)
    assertNotContains(response, MISSING_FIELD_MESSAGE)
    assertNotContains(response, ADD_AN_ACTION_SELECTED)  # since AFPR is selected

    # Check when posting with missing fields
    response = client.post(
        add_prior_action_url, data={"action": job_applications_enums.Prequalification.AFPR, "start_at": ""}
    )
    assertContains(response, END_AT_LABEL)
    assert response.context["form"].has_error("start_at")
    assert response.context["form"].has_error("end_at")
    assertContains(response, MISSING_FIELD_MESSAGE)
    update_page_with_htmx(simulated_page, "#add_prior_action > form", response)

    # Check basic consistency on dates
    response = client.post(
        add_prior_action_url,
        data={
            "action": job_applications_enums.Prequalification.AFPR,
            "start_at": timezone.localdate(),
            "end_at": timezone.localdate() - relativedelta(days=2),
        },
    )
    assertContains(response, "La date de fin prévisionnelle doit être postérieure à la date de début")
    update_page_with_htmx(simulated_page, "#add_prior_action > form", response)

    today = timezone.localdate()
    response = client.post(
        add_prior_action_url,
        data={
            "action": job_applications_enums.Prequalification.AFPR,
            "start_at": today,
            "end_at": today + relativedelta(days=2),
        },
    )
    assertContains(response, "Type : <b>Pré-qualification</b>", html=True)
    assertContains(response, "Nom : <b>AFPR</b>", html=True)
    # A new form accepting a new action is back
    assertContains(response, ADD_AN_ACTION_SELECTED)
    update_page_with_htmx(simulated_page, "#add_prior_action > form", response)

    job_application.refresh_from_db()
    assert job_application.state == job_applications_enums.JobApplicationState.PRIOR_TO_HIRE
    prior_action = job_application.prior_actions.get()
    assert prior_action.action == job_applications_enums.Prequalification.AFPR

    # Check that a full reload gets us an equivalent HTML
    response = client.get(details_url)
    assertSoupEqual(parse_response_to_soup(response, selector="#main"), simulated_page)
    # Let's modify the prior action
    modify_prior_action_url = reverse(
        "apply:modify_prior_action",
        kwargs={"job_application_id": job_application.pk, "prior_action_id": prior_action.pk},
    )
    response = client.get(modify_prior_action_url + "?modify=")
    update_page_with_htmx(simulated_page, f"#prior-action-{prior_action.pk}-modify-btn", response)
    today = timezone.localdate()
    response = client.post(
        modify_prior_action_url,
        data={
            "action": job_applications_enums.Prequalification.POE,
            "start_at": today,
            "end_at": today + relativedelta(days=2),
        },
    )
    update_page_with_htmx(simulated_page, f"#prior-action-{prior_action.pk} > form", response)
    prior_action.refresh_from_db()
    assert prior_action.action == job_applications_enums.Prequalification.POE
    # Check that a full reload gets us an equivalent HTML
    response = client.get(details_url)
    assertSoupEqual(parse_response_to_soup(response, selector="#main"), simulated_page)


@pytest.mark.ignore_unknown_variable_template_error("with_matomo_event")
def test_precriber_details_with_older_valid_approval(client, faker):
    # Ensure that the approval details are displayed for a prescriber
    # when the job seeker has a valid approval created on an older approval
    old_job_application = JobApplicationFactory(with_approval=True, hiring_start_at=faker.past_date(start_date="-3m"))
    new_job_application = JobApplicationSentByPrescriberOrganizationFactory(job_seeker=old_job_application.job_seeker)
    po_member = new_job_application.sender_prescriber_organization.members.first()
    client.force_login(po_member)
    response = client.get(
        reverse("apply:details_for_prescriber", kwargs={"job_application_id": new_job_application.pk})
    )
    # Must display approval status template (tested in many other places)
    assertTemplateUsed(response, template_name="approvals/includes/box.html")


@pytest.mark.parametrize(
    "inverted_vae_contract,expected_predicate", [(True, assertContains), (False, assertNotContains)]
)
def test_details_for_geiq_with_inverted_vae_contract(client, inverted_vae_contract, expected_predicate):
    # GEIQ: check that contract type is displayed in details
    job_application = JobApplicationFactory(
        state=job_applications_enums.JobApplicationState.ACCEPTED,
        to_company__kind=CompanyKind.GEIQ,
        contract_type=ContractType.PROFESSIONAL_TRAINING,
        inverted_vae_contract=inverted_vae_contract,
    )

    user = job_application.to_company.members.first()
    client.force_login(user)

    response = client.get(reverse("apply:details_for_company", kwargs={"job_application_id": job_application.pk}))

    inverted_vae_text = "associé à une VAE inversée"

    assertContains(response, job_application.get_contract_type_display())
    expected_predicate(response, inverted_vae_text)


@pytest.mark.parametrize("qualification_type", job_applications_enums.QualificationType)
def test_reload_qualification_fields(qualification_type, client, snapshot):
    company = CompanyFactory(pk=10, kind=CompanyKind.GEIQ, with_membership=True)
    employer = company.members.first()
    client.force_login(employer)
    job_seeker = JobSeekerFactory(for_snapshot=True)
    url = reverse(
        "apply:reload_qualification_fields",
        kwargs={"company_pk": company.pk, "job_seeker_public_id": job_seeker.public_id},
    )
    response = client.post(
        url,
        data={
            "guidance_days": "0",
            "contract_type": ContractType.APPRENTICESHIP,
            "contract_type_details": "",
            "nb_hours_per_week": "",
            "hiring_start_at": "",
            "qualification_type": qualification_type,
            "qualification_level": "",
            "planned_training_hours": "0",
            "hiring_end_at": "",
            "answer": "",
        },
    )
    assert response.content.decode() == snapshot()


@pytest.mark.parametrize("missing_field", [("company_pk", 0), ("job_seeker_public_id", str(uuid.uuid4()))])
def test_reload_qualification_fields_404(client, missing_field):
    company = CompanyFactory(kind=CompanyKind.GEIQ, with_membership=True)
    employer = company.members.first()
    client.force_login(employer)
    job_seeker = JobSeekerFactory(for_snapshot=True)
    kwargs = {"company_pk": company.pk, "job_seeker_public_id": job_seeker.public_id}
    kwargs[missing_field[0]] = missing_field[1]
    url = reverse("apply:reload_qualification_fields", kwargs=kwargs)
    response = client.post(
        url,
        data={
            "guidance_days": "0",
            "contract_type": ContractType.APPRENTICESHIP,
            "contract_type_details": "",
            "nb_hours_per_week": "",
            "hiring_start_at": "",
            "qualification_type": job_applications_enums.QualificationType.CQP,
            "qualification_level": "",
            "planned_training_hours": "0",
            "hiring_end_at": "",
            "answer": "",
        },
    )
    assert response.status_code == 404


@pytest.mark.parametrize(
    "contract_type",
    [value for value, _label in ContractType.choices_for_company_kind(CompanyKind.GEIQ)],
)
def test_reload_contract_type_and_options(contract_type, client, snapshot):
    company = CompanyFactory(pk=10, kind=CompanyKind.GEIQ, with_membership=True)
    employer = company.members.first()
    client.force_login(employer)
    job_seeker = JobSeekerFactory(for_snapshot=True)
    url = reverse(
        "apply:reload_contract_type_and_options",
        kwargs={"company_pk": company.pk, "job_seeker_public_id": job_seeker.public_id},
    )
    response = client.post(
        url,
        data={
            "guidance_days": "0",
            "contract_type": contract_type,
            "contract_type_details": "",
            "nb_hours_per_week": "",
            "hiring_start_at": "",
            "qualification_type": "CQP",
            "qualification_level": "",
            "planned_training_hours": "0",
            "hiring_end_at": "",
            "answer": "",
        },
    )
    assert response.content.decode() == snapshot()


@pytest.mark.parametrize("missing_field", [("company_pk", 0), ("job_seeker_public_id", str(uuid.uuid4()))])
def test_reload_contract_type_and_options_404(client, missing_field):
    company = CompanyFactory(kind=CompanyKind.GEIQ, with_membership=True)
    employer = company.members.first()
    client.force_login(employer)
    job_seeker = JobSeekerFactory(for_snapshot=True)
    kwargs = {"company_pk": company.pk, "job_seeker_public_id": job_seeker.public_id}
    kwargs[missing_field[0]] = missing_field[1]
    url = reverse("apply:reload_contract_type_and_options", kwargs=kwargs)
    response = client.post(
        url,
        data={
            "guidance_days": "0",
            "contract_type": ContractType.APPRENTICESHIP,
            "contract_type_details": "",
            "nb_hours_per_week": "",
            "hiring_start_at": "",
            "qualification_type": "CQP",
            "qualification_level": "",
            "planned_training_hours": "0",
            "hiring_end_at": "",
            "answer": "",
        },
    )
    assert response.status_code == 404


def test_htmx_reload_contract_type_and_options(client):
    job_application = JobApplicationFactory(
        to_company__kind=CompanyKind.GEIQ,
        state=job_applications_enums.JobApplicationState.PROCESSING,
        job_seeker__for_snapshot=True,
    )
    employer = job_application.to_company.members.first()
    client.force_login(employer)
    accept_url = reverse("apply:accept", kwargs={"job_application_id": job_application.pk})
    data = {
        "guidance_days": "1",
        "contract_type": ContractType.PROFESSIONAL_TRAINING,
        "contract_type_details": "",
        "nb_hours_per_week": "2",
        "hiring_start_at": "",  # No date to ensure error
        "qualification_type": "CQP",
        "qualification_level": job_applications_enums.QualificationLevel.LEVEL_3,
        "prehiring_guidance_days": "0",
        "planned_training_hours": "0",
        "hiring_end_at": "",
        "answer": "",
    }
    response = client.post(accept_url, data=data)
    form_soup = parse_response_to_soup(response, selector="#acceptForm")

    # Update form soup with htmx call
    reload_url = reverse(
        "apply:reload_contract_type_and_options",
        kwargs={
            "company_pk": job_application.to_company.pk,
            "job_seeker_public_id": job_application.job_seeker.public_id,
        },
    )
    data["contract_type"] = ContractType.PERMANENT
    htmx_response = client.post(
        reload_url,
        data=data,
    )
    update_page_with_htmx(form_soup, "#id_contract_type", htmx_response)

    # Check that a complete re-POST returns the exact same form
    response = client.post(accept_url, data=data)
    reloaded_form_soup = parse_response_to_soup(response, selector="#acceptForm")
    assertSoupEqual(form_soup, reloaded_form_soup)


class TestJobApplicationSenderLeftOrg:
    def test_sender_left_org_prescriber(self):
        prescriber_membership = PrescriberMembershipFactory()
        job_app = JobApplicationFactory(
            sender=prescriber_membership.user, sender_prescriber_organization=prescriber_membership.organization
        )
        assert job_application_sender_left_org(job_app) is False

        # membership is inactive
        prescriber_membership.is_active = False
        prescriber_membership.save(update_fields=["is_active", "updated_at"])
        assert job_application_sender_left_org(job_app) is True

        # prescriber is inactive
        prescriber_membership.is_active = True
        prescriber_membership.save(update_fields=["is_active", "updated_at"])
        prescriber_membership.user.is_active = False
        prescriber_membership.user.save(update_fields=["is_active"])
        assert job_application_sender_left_org(job_app) is True

        # membership was removed
        prescriber_membership.user.is_active = True
        prescriber_membership.user.save(update_fields=["is_active"])
        prescriber_membership.delete()
        assert job_application_sender_left_org(job_app) is True

    def test_sender_left_org_employer(self):
        company_membership = CompanyMembershipFactory()
        job_app = JobApplicationFactory(sender=company_membership.user, sender_company=company_membership.company)
        assert job_application_sender_left_org(job_app) is False

        # membership is inactive
        company_membership.is_active = False
        company_membership.save(update_fields=["is_active", "updated_at"])
        assert job_application_sender_left_org(job_app) is True

        # prescriber is inactive
        company_membership.is_active = True
        company_membership.save(update_fields=["is_active", "updated_at"])
        company_membership.user.is_active = False
        company_membership.user.save(update_fields=["is_active"])
        assert job_application_sender_left_org(job_app) is True

        # membership was removed
        company_membership.user.is_active = True
        company_membership.user.save(update_fields=["is_active"])
        company_membership.delete()
        assert job_application_sender_left_org(job_app) is True

    def test_sender_left_org_job_seeker(self):
        job_app = JobApplicationSentByJobSeekerFactory()
        assert job_application_sender_left_org(job_app) is False
