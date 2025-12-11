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
from itou.eligibility.models import (
    AdministrativeCriteria,
    EligibilityDiagnosis,
)
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
from itou.users.enums import IdentityCertificationAuthorities, LackOfNIRReason, LackOfPoleEmploiId, UserKind
from itou.users.models import IdentityCertification, User
from itou.utils.mocks.address_format import mock_get_first_geocoding_data, mock_get_geocoding_data_by_ban_api_resolved
from itou.utils.mocks.api_particulier import RESPONSES, ResponseKind
from itou.utils.models import InclusiveDateRange
from itou.utils.templatetags.format_filters import format_nir, format_phone
from itou.utils.templatetags.str_filters import mask_unless
from itou.utils.urls import get_zendesk_form_url
from itou.utils.widgets import DuetDatePickerWidget
from itou.www.apply.forms import AcceptForm
from itou.www.apply.views.batch_views import RefuseWizardView
from itou.www.apply.views.process_views import (
    ACCEPT_SESSION_KIND,
    initialize_accept_session,
    job_application_sender_left_org,
)
from tests.approvals.factories import ApprovalFactory, SuspensionFactory
from tests.cities.factories import create_city_geispolsheim, create_test_cities
from tests.companies.factories import CompanyFactory, JobDescriptionFactory, SiaeConventionFactory
from tests.eligibility.factories import (
    GEIQEligibilityDiagnosisFactory,
    IAEEligibilityDiagnosisFactory,
    IAESelectedAdministrativeCriteriaFactory,
)
from tests.employee_record.factories import EmployeeRecordFactory
from tests.gps.factories import FollowUpGroupMembershipFactory
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
from tests.utils.htmx.testing import assertSoupEqual, update_page_with_htmx
from tests.utils.testing import (
    assert_previous_step,
    assertSnapshotQueries,
    get_session_name,
    parse_response_to_soup,
    pretty_indented,
)
from tests.www.eligibility_views.utils import (
    CERTIFICATION_ERROR_BADGE_HTML,
    CERTIFIED_BADGE_HTML,
    IN_PROGRESS_BADGE_HTML,
)


logger = logging.getLogger(__name__)

NIR_FIELD_ID = 'id="id_nir"'
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

EMPLOYER_PRIVATE_COMMENT_MARKUP = "<small>Commentaire privé de l'employeur</small>"

BACK_BUTTON_ARIA_LABEL = "Retourner à l’étape précédente"
LINK_RESET_MARKUP = (
    '<a href="%s" class="btn btn-link btn-ico ps-lg-0 w-100 w-lg-auto"'
    ' aria-label="Annuler la saisie de ce formulaire">'
)
CONFIRM_RESET_MARKUP = '<a href="%s" class="btn btn-sm btn-danger">Confirmer l\'annulation</a>'


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
    IAE_ELIGIBILITY_NO_CRITERIA_MENTION = "Le prescripteur habilité n’a pas renseigné de critères."
    IAE_ELIGIBILITY_WITH_CRITERIA_MENTION = (
        "Ces critères reflètent la situation du candidat lors de l’établissement du diagnostic "
        "ayant permis la délivrance d’un PASS IAE"
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
        url = reverse(
            "apply:details_for_company",
            kwargs={"job_application_id": job_application.pk},
            query={"back_url": back_url},
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

        assertNotContains(response, self.IAE_ELIGIBILITY_WITH_CRITERIA_MENTION)
        assertContains(response, self.IAE_ELIGIBILITY_NO_CRITERIA_MENTION)

        job_application.job_seeker.jobseeker_profile.lack_of_nir_reason = LackOfNIRReason.NO_NIR
        job_application.job_seeker.jobseeker_profile.save()

        url = reverse("apply:details_for_company", kwargs={"job_application_id": job_application.pk})
        response = client.get(url)
        assertContains(response, LackOfNIRReason.NO_NIR.label)

        # Test resume presence:
        job_application = JobApplicationSentByJobSeekerFactory(to_company=company)
        url = reverse("apply:details_for_company", kwargs={"job_application_id": job_application.pk})
        response = client.get(url)
        assertContains(response, job_application.resume_link)
        assertNotContains(response, PRIOR_ACTION_SECTION_TITLE)

        # Has a button to copy-paste job_seeker public_id
        content = parse_response_to_soup(
            response,
            selector="#copy_public_id",
            replace_in_attr=[("data-it-copy-to-clipboard", str(job_application.job_seeker.public_id), "PUBLIC_ID")],
        )
        assert pretty_indented(content) == snapshot(name="copy_public_id")

    def test_details_for_company_from_list(self, client, snapshot):
        """Display the details of a job application coming from the job applications list."""

        certified_criterion = IAESelectedAdministrativeCriteriaFactory(
            eligibility_diagnosis__from_employer=False,
            eligibility_diagnosis__from_prescriber=True,
            certified=True,
        )
        job_application = JobApplicationFactory(
            eligibility_diagnosis=certified_criterion.eligibility_diagnosis,
            sent_by_authorized_prescriber_organisation=True,
            resume=None,
            with_approval=True,
        )
        company = job_application.to_company
        employer = company.members.first()
        client.force_login(employer)

        back_url = f"{reverse('apply:list_for_siae')}?job_seeker_public_id={job_application.job_seeker.id}"
        url = reverse(
            "apply:details_for_company",
            kwargs={"job_application_id": job_application.pk},
            query={"back_url": back_url},
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

        assertContains(response, self.IAE_ELIGIBILITY_WITH_CRITERIA_MENTION)
        assertNotContains(response, self.IAE_ELIGIBILITY_NO_CRITERIA_MENTION)

        job_application.job_seeker.jobseeker_profile.lack_of_nir_reason = LackOfNIRReason.NO_NIR
        job_application.job_seeker.jobseeker_profile.save()

        url = reverse("apply:details_for_company", kwargs={"job_application_id": job_application.pk})
        response = client.get(url)
        assertContains(response, LackOfNIRReason.NO_NIR.label)

        # Test resume presence:
        job_application = JobApplicationSentByJobSeekerFactory(to_company=company)
        url = reverse("apply:details_for_company", kwargs={"job_application_id": job_application.pk})
        response = client.get(url)
        assertContains(response, job_application.resume_link)
        assertNotContains(response, PRIOR_ACTION_SECTION_TITLE)

    def test_details_for_company_with_expired_approval(self, client, subtests):
        # Expired but still retrieved by job_seerk.latest_approval
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
                assertNotContains(response, self.IAE_ELIGIBILITY_WITH_CRITERIA_MENTION)
                assertContains(response, self.IAE_ELIGIBILITY_NO_CRITERIA_MENTION)

    def test_details_for_company_certified_criteria_after_expiration(self, client):
        company = CompanyFactory(subject_to_iae_rules=True, with_membership=True)
        now = timezone.now()
        today = timezone.localdate(now)
        job_seeker = JobSeekerFactory()
        certification_grace_period = datetime.timedelta(
            days=AbstractSelectedAdministrativeCriteria.CERTIFICATION_GRACE_PERIOD_DAYS
        )
        created_at = now - certification_grace_period - datetime.timedelta(days=1)
        expires_at = today - datetime.timedelta(days=1)
        selected_criteria = IAESelectedAdministrativeCriteriaFactory(
            eligibility_diagnosis__author_siae=company,
            eligibility_diagnosis__job_seeker=job_seeker,
            eligibility_diagnosis__created_at=created_at,
            eligibility_diagnosis__expires_at=expires_at,
            criteria_certified=True,
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

        tomorrow = today + datetime.timedelta(days=1)
        eligibility_diagnosis.expires_at = tomorrow
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

    def test_details_for_prescriber(self, client, snapshot):
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
        assertNotContains(response, self.IAE_ELIGIBILITY_WITH_CRITERIA_MENTION)
        assertContains(response, self.IAE_ELIGIBILITY_NO_CRITERIA_MENTION)
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

        # Has a button to copy-paste job_seeker public_id
        content = parse_response_to_soup(
            response,
            selector="#copy_public_id",
            replace_in_attr=[("data-it-copy-to-clipboard", str(job_application.job_seeker.public_id), "PUBLIC_ID")],
        )
        assert pretty_indented(content) == snapshot(name="copy_public_id")

    def test_details_for_prescriber_certified_criteria(self, client):
        certified_crit = IAESelectedAdministrativeCriteriaFactory(
            eligibility_diagnosis__from_employer=False,
            eligibility_diagnosis__from_prescriber=True,
            criteria_certified=True,
        )
        job_application = JobApplicationFactory(
            eligibility_diagnosis=certified_crit.eligibility_diagnosis,
            sent_by_authorized_prescriber_organisation=True,
            to_company__subject_to_iae_rules=True,
        )
        prescriber = job_application.sender_prescriber_organization.members.get()

        client.force_login(prescriber)
        response = client.get(
            reverse(
                "apply:details_for_prescriber",
                kwargs={"job_application_id": job_application.pk},
            )
        )
        assertContains(response, CERTIFIED_BADGE_HTML, html=True, count=1)
        assertContains(response, self.IAE_ELIGIBILITY_WITH_CRITERIA_MENTION)
        assertNotContains(response, self.IAE_ELIGIBILITY_NO_CRITERIA_MENTION)

    def test_details_for_prescriber_certifiable_criteria(self, client):
        certifiable_crit = IAESelectedAdministrativeCriteriaFactory(
            eligibility_diagnosis__from_employer=False,
            eligibility_diagnosis__from_prescriber=True,
        )
        job_application = JobApplicationFactory(
            eligibility_diagnosis=certifiable_crit.eligibility_diagnosis,
            sent_by_authorized_prescriber_organisation=True,
            to_company__subject_to_iae_rules=True,
        )
        prescriber = job_application.sender_prescriber_organization.members.get()

        client.force_login(prescriber)
        response = client.get(
            reverse(
                "apply:details_for_prescriber",
                kwargs={"job_application_id": job_application.pk},
            )
        )
        assertContains(response, IN_PROGRESS_BADGE_HTML, html=True, count=1)

    def test_details_for_prescriber_certification_error(self, client):
        certifiable_crit = IAESelectedAdministrativeCriteriaFactory(
            eligibility_diagnosis__from_employer=False,
            eligibility_diagnosis__from_prescriber=True,
            criteria_certification_error=True,
        )
        job_application = JobApplicationFactory(
            eligibility_diagnosis=certifiable_crit.eligibility_diagnosis,
            sent_by_authorized_prescriber_organisation=True,
            to_company__subject_to_iae_rules=True,
        )
        prescriber = job_application.sender_prescriber_organization.members.get()

        client.force_login(prescriber)
        response = client.get(
            reverse(
                "apply:details_for_prescriber",
                kwargs={"job_application_id": job_application.pk},
            )
        )
        assertContains(response, CERTIFICATION_ERROR_BADGE_HTML, html=True, count=1)

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

        job_application = JobApplicationFactory(job_seeker=job_seeker, with_iae_eligibility_diagnosis=True)
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

        assertNotContains(response, self.IAE_ELIGIBILITY_WITH_CRITERIA_MENTION)
        assertContains(response, self.IAE_ELIGIBILITY_NO_CRITERIA_MENTION)

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
            EmployerFactory(membership=True),
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
                with_iae_eligibility_diagnosis=True,
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

        assert pretty_indented(html_fragment) == snapshot

    def test_details_for_job_seeker_with_transition_logs(self, client, snapshot):
        with freeze_time("2023-12-10 11:11:00", tz_offset=-1):
            job_application = JobApplicationFactory(
                for_snapshot=True,
                sent_by_authorized_prescriber_organisation=True,
                with_iae_eligibility_diagnosis=True,
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

        assert pretty_indented(html_fragment) == snapshot

    def test_details_for_company_with_transition_logs(self, client, snapshot):
        with freeze_time("2023-12-10 11:11:00", tz_offset=-1):
            job_application = JobApplicationFactory(
                for_snapshot=True,
                sent_by_authorized_prescriber_organisation=True,
                with_iae_eligibility_diagnosis=True,
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

        assert pretty_indented(html_fragment) == snapshot(name="transition_logs")

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

        assert pretty_indented(html_fragment) == snapshot

    def test_details_for_company_transition_logs_hides_hired_by_other(self, client, snapshot):
        job_seeker = JobSeekerFactory()
        with freeze_time("2023-12-10 11:11:00", tz_offset=-1):
            job_app1 = JobApplicationFactory(
                for_snapshot=True,
                job_seeker=job_seeker,
                sent_by_authorized_prescriber_organisation=True,
                with_iae_eligibility_diagnosis=True,
            )
            job_app2 = JobApplicationFactory(
                job_seeker=job_seeker,
                sent_by_authorized_prescriber_organisation=True,
                with_iae_eligibility_diagnosis=True,
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

        assert pretty_indented(html_fragment) == snapshot

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
        assertNotContains(response, EMPLOYER_PRIVATE_COMMENT_MARKUP)
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
        assertContains(response, EMPLOYER_PRIVATE_COMMENT_MARKUP)
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
        assertContains(response, EMPLOYER_PRIVATE_COMMENT_MARKUP)
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
            "refusal_reason": job_applications_enums.RefusalReason.HIRED_ELSEWHERE,
        }
        client.post(refusal_reason_url_2, data=post_data)
        assert client.session[refuse_session_name_2] == {
            "config": {
                "tunnel": "single",
                "reset_url": reverse("apply:details_for_company", kwargs={"job_application_id": job_application_2.pk}),
            },
            "application_ids": [job_application_2.pk],
            "reason": {
                "refusal_reason": job_applications_enums.RefusalReason.HIRED_ELSEWHERE,
                "refusal_reason_shared_with_job_seeker": False,
            },
        }
        # Session for 1st application is still here & untouched
        assert refuse_session_name in client.session
        assert client.session[refuse_session_name] == expected_session

    def test_refuse_from_prescriber(self, client):
        """Ensure that the `refuse` transition is triggered through the expected workflow for a prescriber."""

        state = random.choice(JobApplicationWorkflow.CAN_BE_REFUSED_STATES)
        job_application = JobApplicationFactory(sent_by_authorized_prescriber_organisation=True, state=state)
        reason, reason_label = random.choice(
            job_applications_enums.RefusalReason.displayed_choices(kind=job_application.to_company.kind)
        )
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
        job_application = JobApplicationSentByJobSeekerFactory(state=state)
        reason, reason_label = random.choice(
            job_applications_enums.RefusalReason.displayed_choices(kind=job_application.to_company.kind)
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

    @pytest.mark.parametrize("is_authorized_prescriber", [False, True])
    def test_add_to_pool_from_prescriber(self, is_authorized_prescriber, client, snapshot, mailoutbox):
        initial_state = random.choice(JobApplicationWorkflow.CAN_BE_ADDED_TO_POOL_STATES)

        job_seeker = JobSeekerFactory(for_snapshot=True)
        company = CompanyFactory(for_snapshot=True, with_membership=True)

        # Unauthorized prescriber is the default sender
        extra_kwargs = {"sent_by_authorized_prescriber_organisation": True} if is_authorized_prescriber else {}
        job_application = JobApplicationFactory(
            job_seeker=job_seeker,
            to_company=company,
            state=initial_state,
            **extra_kwargs,
        )
        employer = job_application.to_company.members.first()
        client.force_login(employer)

        url = reverse("apply:add_to_pool", kwargs={"job_application_id": job_application.pk})
        response = client.get(url)
        assert response.status_code == 200

        post_data = {"answer": ""}
        response = client.post(url, data=post_data)
        next_url = reverse("apply:details_for_company", kwargs={"job_application_id": job_application.pk})
        assertRedirects(response, next_url)

        job_application = JobApplication.objects.get(pk=job_application.pk)
        assert job_application.state.is_pool

        [mail_to_job_seeker, mail_to_prescriber] = mailoutbox
        assert mail_to_job_seeker.to == [job_application.job_seeker.email]
        assert mail_to_job_seeker.subject == snapshot(name="add_to_pool_email_to_job_seeker_subject")
        assert mail_to_job_seeker.body == snapshot(name="add_to_pool_email_to_job_seeker_body")
        assert mail_to_prescriber.to == [job_application.sender.email]
        assert mail_to_prescriber.subject == snapshot(name="add_to_pool_email_to_proxy_subject")
        assert mail_to_prescriber.body == snapshot(name="add_to_pool_email_to_proxy_body")

    def test_add_to_pool_from_job_seeker(self, client, snapshot, mailoutbox):
        initial_state = random.choice(JobApplicationWorkflow.CAN_BE_ADDED_TO_POOL_STATES)

        job_seeker = JobSeekerFactory(for_snapshot=True)
        company = CompanyFactory(for_snapshot=True, with_membership=True)

        job_application = JobApplicationFactory(
            job_seeker=job_seeker,
            to_company=company,
            sender_kind=SenderKind.JOB_SEEKER,
            sender=job_seeker,
            state=initial_state,
        )
        employer = job_application.to_company.members.first()
        client.force_login(employer)

        url = reverse("apply:add_to_pool", kwargs={"job_application_id": job_application.pk})
        response = client.get(url)
        assert response.status_code == 200

        post_data = {"answer": "On vous rappellera."}
        response = client.post(url, data=post_data)
        next_url = reverse("apply:details_for_company", kwargs={"job_application_id": job_application.pk})
        assertRedirects(response, next_url)

        job_application = JobApplication.objects.get(pk=job_application.pk)
        assert job_application.state.is_pool

        [mail_to_job_seeker] = mailoutbox
        assert mail_to_job_seeker.to == [job_application.job_seeker.email]
        assert mail_to_job_seeker.subject == snapshot(name="add_to_pool_email_to_job_seeker_subject")
        assert mail_to_job_seeker.body == snapshot(name="add_to_pool_email_to_job_seeker_body")

    def test_add_to_pool_from_employer_orienter(self, client, snapshot, mailoutbox):
        initial_state = random.choice(JobApplicationWorkflow.CAN_BE_ADDED_TO_POOL_STATES)

        job_seeker = JobSeekerFactory(for_snapshot=True)
        company = CompanyFactory(for_snapshot=True, with_membership=True)

        job_application = JobApplicationFactory(
            job_seeker=job_seeker,
            to_company=company,
            sent_by_another_employer=True,
            state=initial_state,
        )
        employer = job_application.to_company.members.first()
        client.force_login(employer)

        url = reverse("apply:add_to_pool", kwargs={"job_application_id": job_application.pk})
        response = client.get(url)
        assert response.status_code == 200

        post_data = {"answer": "On vous rappellera."}
        response = client.post(url, data=post_data)
        next_url = reverse("apply:details_for_company", kwargs={"job_application_id": job_application.pk})
        assertRedirects(response, next_url)

        job_application = JobApplication.objects.get(pk=job_application.pk)
        assert job_application.state.is_pool

        [mail_to_job_seeker, mail_to_other_employer] = mailoutbox
        assert mail_to_job_seeker.to == [job_application.job_seeker.email]
        assert mail_to_job_seeker.subject == snapshot(name="add_to_pool_email_to_job_seeker_subject")
        assert mail_to_job_seeker.body == snapshot(name="add_to_pool_email_to_job_seeker_body")
        assert mail_to_other_employer.to == [job_application.sender.email]
        assert mail_to_other_employer.subject == snapshot(name="add_to_pool_email_to_proxy_subject")
        assert mail_to_other_employer.body == snapshot(name="add_to_pool_email_to_proxy_body")

    @pytest.mark.parametrize("is_authorized_prescriber", [False, True])
    def test_postpone_from_prescriber(self, is_authorized_prescriber, client, snapshot, mailoutbox):
        """Ensure that the `postpone` transition is triggered."""
        initial_state = random.choice(JobApplicationWorkflow.CAN_BE_POSTPONED_STATES)

        job_seeker = JobSeekerFactory(for_snapshot=True)
        company = CompanyFactory(for_snapshot=True, with_membership=True)

        # Unauthorized prescriber is the default sender
        extra_kwargs = {"sent_by_authorized_prescriber_organisation": True} if is_authorized_prescriber else {}
        job_application = JobApplicationFactory(
            job_seeker=job_seeker,
            to_company=company,
            state=initial_state,
            **extra_kwargs,
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

    def test_postpone_from_job_seeker(self, client, snapshot, mailoutbox):
        """Ensure that the `postpone` transition is triggered."""
        initial_state = random.choice(JobApplicationWorkflow.CAN_BE_POSTPONED_STATES)

        job_seeker = JobSeekerFactory(for_snapshot=True)
        company = CompanyFactory(for_snapshot=True, with_membership=True)

        job_application = JobApplicationFactory(
            job_seeker=job_seeker,
            to_company=company,
            sender_kind=SenderKind.JOB_SEEKER,
            sender=job_seeker,
            state=initial_state,
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

    def test_postpone_from_employer_orienter(self, client, snapshot, mailoutbox):
        """Ensure that the `postpone` transition is triggered."""
        initial_state = random.choice(JobApplicationWorkflow.CAN_BE_POSTPONED_STATES)

        job_seeker = JobSeekerFactory(for_snapshot=True)
        company = CompanyFactory(for_snapshot=True, with_membership=True)

        job_application = JobApplicationFactory(
            job_seeker=job_seeker,
            to_company=company,
            sent_by_another_employer=True,
            state=initial_state,
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
            to_company__subject_to_iae_rules=True,
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
        next_url = reverse("apply:start-accept", kwargs={"job_application_id": job_application.pk})
        assertRedirects(response, next_url, target_status_code=302)

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

    def test_eligibility_with_next_url(self, client):
        """Test the page propagates the next url to the accept view"""
        job_application = JobApplicationSentByPrescriberOrganizationFactory(
            state=job_applications_enums.JobApplicationState.PROCESSING,
            job_seeker=JobSeekerFactory(with_address_in_qpv=True),
            to_company__subject_to_iae_rules=True,
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

        next_url = reverse("apply:list_for_siae")
        url = reverse(
            "apply:eligibility",
            kwargs={"job_application_id": job_application.pk},
            query={"next_url": next_url},
        )
        response = client.get(url)
        assert response.status_code == 200
        assertTemplateUsed(response, "apply/includes/known_criteria.html", count=1)
        assertContains(
            response,
            f"""
            <a href="{next_url}"
               class="btn btn-link btn-ico ps-lg-0 w-100 w-lg-auto"
               aria-label="Annuler la saisie de ce formulaire">
                <i class="ri-close-line ri-lg" aria-hidden="true"></i>
                <span>Annuler</span>
            </a>
            """,
            html=True,
        )

        post_data = {
            # Administrative criteria level 1.
            f"{criterion1.key}": "true",
            # Administrative criteria level 2.
            f"{criterion2.key}": "true",
            f"{criterion3.key}": "true",
        }
        response = client.post(url, data=post_data)
        url = reverse(
            "apply:start-accept", kwargs={"job_application_id": job_application.pk}, query={"next_url": next_url}
        )
        assertRedirects(response, url, target_status_code=302)

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
            to_company__evaluable_kind=True,
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
        company = CompanyFactory(with_membership=True, subject_to_iae_rules=True)
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
            ("subject_to_iae_rules", IAE_CANCELLATION_CONFIRMATION),
            ("not_subject_to_iae_rules", NON_IAE_CANCELLATION_CONFIRMATION),
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
        job_application = JobApplicationFactory(with_approval=True, to_company__subject_to_iae_rules=True)
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
                job_seeker_name=mask_unless(job_application.job_seeker.get_full_name(), predicate=False),
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

    def test_display_referent_info_for_company(self, client, snapshot):
        job_seeker = JobSeekerFactory(for_snapshot=True)
        company = CompanyFactory(for_snapshot=True, with_membership=True)

        job_application = JobApplicationFactory(
            job_seeker=job_seeker,
            to_company=company,
            sent_by_another_employer=True,
        )
        employer = job_application.to_company.members.first()
        client.force_login(employer)

        url = reverse("apply:details_for_company", kwargs={"job_application_id": job_application.pk})
        response = client.get(url)

        no_referent_str = f"L’accompagnateur de {job_seeker.get_full_name()} n’est pas connu de nos services"

        # No referent found
        assertContains(response, no_referent_str)

        membership = FollowUpGroupMembershipFactory(
            follow_up_group__beneficiary=job_seeker,
            member=employer,
            started_at=datetime.date(2024, 1, 1),
        )
        group = membership.follow_up_group

        # Referent is present
        response = client.get(url)
        assertNotContains(response, no_referent_str)

        content = parse_response_to_soup(
            response,
            selector=f"#card-{membership.member.public_id}",
            replace_in_attr=[
                ("href", f"/gps/groups/{group.pk}/memberships", "/gps/groups/[PK of FollowUpGroup]"),
                ("href", f"/gps/groups/{group.pk}/edition", "/gps/groups/[PK of FollowUpGroup]/edition"),
                ("id", f"card-{employer.public_id}", "card-[Public ID of prescriber]"),
                (
                    "hx-post",
                    f"/gps/display/{group.pk}/{employer.public_id}/phone",
                    "/gps/display/[PK of group]/[Public ID of participant]/phone",
                ),
                (
                    "hx-post",
                    f"/gps/display/{group.pk}/{employer.public_id}/email",
                    "/gps/display/[PK of group]/[Public ID of participant]/email",
                ),
                ("id", f"phone-{employer.pk}", "phone-[PK of participant]"),
                ("id", f"email-{employer.pk}", "email-[PK of participant]"),
            ],
        )

        assert pretty_indented(content) == snapshot()

    def test_display_referent_info_for_prescriber(self, client, snapshot):
        job_seeker = JobSeekerFactory(for_snapshot=True)
        prescriber = PrescriberFactory(
            membership=True,
            for_snapshot=True,
            membership__organization__name="Les Olivades",
            membership__organization__authorized=True,
        )
        job_application = JobApplicationFactory(job_seeker=job_seeker, sender=prescriber)
        membership = FollowUpGroupMembershipFactory(
            follow_up_group__beneficiary=job_seeker,
            member=prescriber,
            started_at=datetime.date(2024, 1, 1),
        )
        group = membership.follow_up_group

        client.force_login(prescriber)

        url = reverse("apply:details_for_prescriber", kwargs={"job_application_id": job_application.pk})
        response = client.get(url)

        content = parse_response_to_soup(
            response,
            selector=f"#card-{membership.member.public_id}",
            replace_in_attr=[
                ("href", f"/gps/groups/{group.pk}/memberships", "/gps/groups/[PK of FollowUpGroup]"),
                ("href", f"/gps/groups/{group.pk}/edition", "/gps/groups/[PK of FollowUpGroup]/edition"),
                ("id", f"card-{prescriber.public_id}", "card-[Public ID of prescriber]"),
                (
                    "hx-post",
                    f"/gps/display/{group.pk}/{prescriber.public_id}/phone",
                    "/gps/display/[PK of group]/[Public ID of participant]/phone",
                ),
                (
                    "hx-post",
                    f"/gps/display/{group.pk}/{prescriber.public_id}/email",
                    "/gps/display/[PK of group]/[Public ID of participant]/email",
                ),
                ("id", f"phone-{prescriber.pk}", "phone-[PK of participant]"),
                ("id", f"email-{prescriber.pk}", "email-[PK of participant]"),
            ],
        )

        assert pretty_indented(content) == snapshot()


class TestProcessAcceptViewsInWizard:
    BIRTH_COUNTRY_LABEL = "Pays de naissance"
    BIRTH_PLACE_LABEL = "Commune de naissance"
    OPEN_JOBS_TEXT = "Postes ouverts au recrutement"
    CLOSED_JOBS_TEXT = "Postes fermés au recrutement"
    SPECIFY_JOB_TEXT = "Préciser le nom du poste (code ROME)"

    @pytest.fixture(autouse=True)
    def setup_method(self, settings, mocker):
        self.company = CompanyFactory(
            with_membership=True, with_jobs=True, name="La brigade - entreprise par défaut", subject_to_iae_rules=True
        )
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

    def create_job_application(self, **kwargs):
        kwargs = {
            "selected_jobs": self.company.jobs.all(),
            "state": JobApplicationState.PROCESSING,
            "job_seeker": self.job_seeker,
            "to_company": self.company,
            "hiring_end_at": None,
        } | kwargs
        return JobApplicationSentByJobSeekerFactory(**kwargs)

    def _accept_jobseeker_post_data(self, job_application, post_data=None):
        if post_data is not None:
            return post_data
        job_seeker = job_application.job_seeker
        # JobSeekerPersonalDataForm
        birth_place = (
            Commune.objects.filter(
                start_date__lte=job_seeker.jobseeker_profile.birthdate,
                end_date__gte=job_seeker.jobseeker_profile.birthdate,
            )
            .first()
            .pk
        )
        return {
            "birthdate": job_seeker.jobseeker_profile.birthdate,
            "birth_country": Country.FRANCE_ID,
            "birth_place": birth_place,
        }

    def _accept_contract_post_data(self, job_application, post_data=None):
        extra_post_data = post_data or {}
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
        return accept_default_fields | extra_post_data

    def get_job_seeker_info_step_url(self, session_uuid):
        return reverse("apply:accept_fill_job_seeker_infos", kwargs={"session_uuid": session_uuid})

    def get_contract_info_step_url(self, session_uuid):
        return reverse("apply:accept_contract_infos", kwargs={"session_uuid": session_uuid})

    def start_accept_job_application(self, client, job_application, next_url=None):
        url_accept = reverse(
            "apply:start-accept",
            kwargs={"job_application_id": job_application.pk},
        )
        response = client.get(url_accept, data={"next_url": next_url} if next_url else {})
        session_uuid = get_session_name(client.session, ACCEPT_SESSION_KIND)
        assert session_uuid is not None
        assertRedirects(
            response,
            self.get_job_seeker_info_step_url(session_uuid),
            fetch_redirect_response=False,  # Either a 302 or a 200
        )
        return session_uuid

    def fill_job_seeker_info_step(self, client, job_application, session_uuid, post_data=None):
        url_job_seeker_info = self.get_job_seeker_info_step_url(session_uuid)
        post_data = self._accept_jobseeker_post_data(job_application=job_application, post_data=post_data)
        return client.post(url_job_seeker_info, data=post_data)

    def fill_contract_info_step(
        self,
        client,
        job_application,
        session_uuid,
        post_data=None,
        assert_successful=True,
        next_url=None,
        with_previous_step=True,
    ):
        """
        This is not a test. It's a shortcut to process "apply:start-accept" wizard steps:
        - GET: start the accept process and redirect to job seeker infos step
        - POST: handle job seeker infos step
        - POST: show the confirmation modal
        - POST: hide the modal and redirect to the next url.

        """
        next_url = next_url or reverse("apply:details_for_company", kwargs={"job_application_id": job_application.pk})
        contract_info_url = self.get_contract_info_step_url(session_uuid)
        response = client.get(contract_info_url)
        assertContains(response, "Confirmation de l’embauche")
        if with_previous_step:
            assertContains(response, CONFIRM_RESET_MARKUP % next_url)
            assertContains(response, BACK_BUTTON_ARIA_LABEL)
        else:
            assertContains(response, LINK_RESET_MARKUP % next_url)
            assertNotContains(response, BACK_BUTTON_ARIA_LABEL)
        # Make sure modal is hidden.
        assert response.headers.get("HX-Trigger") is None

        post_data = self._accept_contract_post_data(job_application=job_application, post_data=post_data)
        response = client.post(contract_info_url, headers={"hx-request": "true"}, data=post_data)

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
        response = client.post(contract_info_url, headers={"hx-request": "true"}, data=post_data)
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

        session_uuid = self.start_accept_job_application(client, job_application)
        response = client.get(self.get_job_seeker_info_step_url(session_uuid))
        assertContains(response, "Valider les informations")
        assertContains(response, LINK_RESET_MARKUP % reverse("apply:details_for_company", args=[job_application.pk]))
        assertNotContains(response, BACK_BUTTON_ARIA_LABEL)
        response = self.fill_job_seeker_info_step(client, job_application, session_uuid)
        assertRedirects(response, self.get_contract_info_step_url(session_uuid), fetch_redirect_response=False)

        _, next_url = self.fill_contract_info_step(client, job_application, session_uuid, post_data=post_data)

        job_application = JobApplication.objects.get(pk=job_application.pk)
        assert job_application.hiring_start_at == hiring_start_at
        assert job_application.hiring_end_at == hiring_end_at
        assert job_application.state.is_accepted

        # test how hiring_end_date is displayed
        response = client.get(next_url)
        assertNotContains(
            response,
            users_test_constants.CERTIFIED_FORM_READONLY_HTML.format(url=get_zendesk_form_url(response.wsgi_request)),
            html=True,
        )
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

    def test_accept_with_next_url(self, client):
        today = timezone.localdate()
        job_application = self.create_job_application(
            state=JobApplicationState.PROCESSING, with_iae_eligibility_diagnosis=True
        )

        employer = self.company.members.first()
        client.force_login(employer)
        # Good duration.
        hiring_start_at = today
        post_data = {"hiring_end_at": ""}

        next_url = reverse("apply:list_for_siae")
        session_uuid = self.start_accept_job_application(client, job_application, next_url=next_url)
        assert client.session[session_uuid] == {
            "job_application_id": job_application.pk,
            "reset_url": next_url,
        }
        response = client.get(self.get_job_seeker_info_step_url(session_uuid))
        assertContains(response, "Valider les informations")
        assertContains(response, LINK_RESET_MARKUP % next_url)
        assertNotContains(response, BACK_BUTTON_ARIA_LABEL)
        response = self.fill_job_seeker_info_step(client, job_application, session_uuid)
        assertRedirects(response, self.get_contract_info_step_url(session_uuid), fetch_redirect_response=False)

        _, next_url = self.fill_contract_info_step(
            client, job_application, session_uuid, post_data=post_data, next_url=next_url
        )

        job_application = JobApplication.objects.get(pk=job_application.pk)
        assert job_application.hiring_start_at == hiring_start_at
        assert job_application.hiring_end_at is None
        assert job_application.state.is_accepted

    @pytest.mark.usefixtures("api_particulier_settings")
    @freeze_time("2024-09-11")
    def test_select_other_job_description_for_job_application(self, client, mocker):
        criteria_kind = random.choice(list(CERTIFIABLE_ADMINISTRATIVE_CRITERIA_KINDS))
        mocked_request = mocker.patch(
            "itou.utils.apis.api_particulier._request",
            return_value=RESPONSES[criteria_kind][ResponseKind.CERTIFIED]["json"],
        )
        create_test_romes_and_appellations(["M1805"], appellations_per_rome=1)
        diagnosis = IAEEligibilityDiagnosisFactory(
            job_seeker=self.job_seeker,
            author_siae=self.company,
            certifiable=True,
            criteria_kinds=[criteria_kind],
        )
        job_application = self.create_job_application(
            eligibility_diagnosis=diagnosis,
            job_seeker__jobseeker_profile__birthdate=datetime.date(
                2002, 2, 20
            ),  # Required to certify the criteria later.
        )

        employer = self.company.members.first()
        client.force_login(employer)

        session_uuid = self.start_accept_job_application(client, job_application)
        response = client.get(self.get_job_seeker_info_step_url(session_uuid))
        assertContains(response, "Valider les informations")
        response = self.fill_job_seeker_info_step(client, job_application, session_uuid)
        contract_infos_url = self.get_contract_info_step_url(session_uuid)
        assertRedirects(response, contract_infos_url, fetch_redirect_response=False)

        response = client.get(contract_infos_url)
        assertContains(response, self.OPEN_JOBS_TEXT)
        assertNotContains(response, self.CLOSED_JOBS_TEXT)
        assertNotContains(response, self.SPECIFY_JOB_TEXT)

        # Selecting "Autre" must enable the employer to create a new job description
        # linked to the accepted job application.
        post_data = {
            "hired_job": AcceptForm.OTHER_HIRED_JOB,
        }
        post_data = self._accept_contract_post_data(job_application=job_application, post_data=post_data)
        response = client.post(contract_infos_url, data=post_data)
        assertContains(response, "Localisation du poste")
        assertContains(response, self.SPECIFY_JOB_TEXT)

        city = City.objects.order_by("?").first()
        appellation = Appellation.objects.get(rome_id="M1805")
        post_data |= {"location": city.pk, "appellation": appellation.pk}
        response = client.post(
            contract_infos_url,
            data=post_data,
            headers={"hx-request": "true"},
        )
        assertTemplateUsed(response, "apply/includes/job_application_accept_form.html")
        assert response.status_code == 200

        # Modal window
        post_data |= {"confirmed": True}
        response = client.post(contract_infos_url, data=post_data, follow=False, headers={"hx-request": "true"})
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

        session_uuid = self.start_accept_job_application(client, job_application)
        response = client.get(self.get_job_seeker_info_step_url(session_uuid))
        assertContains(response, "Valider les informations")
        response = self.fill_job_seeker_info_step(client, job_application, session_uuid)
        contract_infos_url = self.get_contract_info_step_url(session_uuid)
        assertRedirects(response, contract_infos_url, fetch_redirect_response=False)

        # Check optgroup labels
        job_description = JobDescriptionFactory(company=job_application.to_company, is_active=True)
        response = client.get(contract_infos_url)
        assertContains(response, f"{job_description.display_name} - {job_description.display_location}", html=True)
        assertContains(response, self.OPEN_JOBS_TEXT)
        assertNotContains(response, self.CLOSED_JOBS_TEXT)
        assertNotContains(response, self.SPECIFY_JOB_TEXT)

        # Inactive job description must also appear in select
        job_description = JobDescriptionFactory(company=job_application.to_company, is_active=False)
        with assertSnapshotQueries(snapshot(name="accept view SQL queries")):
            response = client.get(contract_infos_url)
        assertContains(response, f"{job_description.display_name} - {job_description.display_location}", html=True)
        assertContains(response, self.OPEN_JOBS_TEXT)
        assertContains(response, self.CLOSED_JOBS_TEXT)
        assertNotContains(response, self.SPECIFY_JOB_TEXT)

    def test_no_job_description_for_job_application(self, client):
        self.company.jobs.clear()
        job_application = self.create_job_application(with_iae_eligibility_diagnosis=True)
        employer = self.company.members.first()
        client.force_login(employer)
        session_uuid = self.start_accept_job_application(client, job_application)
        response = client.get(self.get_job_seeker_info_step_url(session_uuid))
        assertContains(response, "Valider les informations")
        response = self.fill_job_seeker_info_step(client, job_application, session_uuid)
        contract_infos_url = self.get_contract_info_step_url(session_uuid)
        assertRedirects(response, contract_infos_url, fetch_redirect_response=False)

        response = client.get(contract_infos_url)
        assertNotContains(response, self.OPEN_JOBS_TEXT)
        assertNotContains(response, self.CLOSED_JOBS_TEXT)
        assertNotContains(response, self.SPECIFY_JOB_TEXT)

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

        session_uuid = self.start_accept_job_application(client, job_application)
        response = client.get(self.get_job_seeker_info_step_url(session_uuid))
        assertContains(response, "Valider les informations")
        response = self.fill_job_seeker_info_step(client, job_application, session_uuid)
        assertRedirects(response, self.get_contract_info_step_url(session_uuid), fetch_redirect_response=False)

        response, _ = self.fill_contract_info_step(
            client, job_application, session_uuid, post_data=post_data, assert_successful=False
        )

        assertFormError(response.context["form_accept"], "hiring_start_at", JobApplication.ERROR_START_IN_PAST)

        # Wrong dates: end < start.
        hiring_start_at = today
        hiring_end_at = hiring_start_at - relativedelta(days=1)
        post_data = {
            "hiring_start_at": hiring_start_at.strftime(DuetDatePickerWidget.INPUT_DATE_FORMAT),
            "hiring_end_at": hiring_end_at.strftime(DuetDatePickerWidget.INPUT_DATE_FORMAT),
        }
        response, _ = self.fill_contract_info_step(
            client, job_application, session_uuid, post_data=post_data, assert_successful=False
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

        session_uuid = self.start_accept_job_application(client, job_application)
        response = client.get(self.get_job_seeker_info_step_url(session_uuid))
        assertContains(response, "Valider les informations")
        response = self.fill_job_seeker_info_step(client, job_application, session_uuid)
        assertRedirects(response, self.get_contract_info_step_url(session_uuid), fetch_redirect_response=False)

        post_data = self._accept_contract_post_data(
            job_application=job_application,
            post_data={
                "hiring_start_at": job_application.hiring_start_at.strftime(DuetDatePickerWidget.INPUT_DATE_FORMAT)
            },
        )
        response, _ = self.fill_contract_info_step(
            client, job_application, session_uuid, post_data=post_data, assert_successful=False
        )
        assertFormError(
            response.context["form_accept"],
            "hiring_start_at",
            JobApplication.ERROR_HIRES_AFTER_APPROVAL_EXPIRES,
        )

        # employer amends the situation by submitting a different hiring start date
        post_data["hiring_start_at"] = timezone.localdate().strftime(DuetDatePickerWidget.INPUT_DATE_FORMAT)
        self.fill_contract_info_step(
            client, job_application, session_uuid, post_data=post_data, assert_successful=True
        )

    def test_no_address(self, client):
        job_application = self.create_job_application(with_iae_eligibility_diagnosis=True)
        employer = self.company.members.first()
        client.force_login(employer)

        # Remove job seeker address to force address form presence
        self.job_seeker.address_line_1 = ""
        self.job_seeker.city = ""
        self.job_seeker.post_code = ""
        self.job_seeker.save(update_fields=["address_line_1", "city", "post_code"])
        # And add birth info since it is not the purpose of this test
        self.job_seeker.jobseeker_profile.birth_country = (
            Country.objects.exclude(pk=Country.FRANCE_ID).order_by("?").first()
        )
        self.job_seeker.jobseeker_profile.birthdate = datetime.date(1990, 1, 1)
        self.job_seeker.jobseeker_profile.save(update_fields=["birth_country", "birthdate"])

        session_uuid = self.start_accept_job_application(client, job_application)
        response = client.get(self.get_job_seeker_info_step_url(session_uuid))
        assertContains(response, "Valider les informations")
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

        response = self.fill_job_seeker_info_step(client, job_application, session_uuid, post_data=post_data)
        assertFormError(response.context["form_user_address"], "address_for_autocomplete", "Ce champ est obligatoire.")

        # Trying to skip to contract step must redirect back to job seeker info step
        response = client.get(self.get_contract_info_step_url(session_uuid))
        assertRedirects(response, self.get_job_seeker_info_step_url(session_uuid), fetch_redirect_response=False)
        assertMessages(
            response,
            [messages.Message(messages.ERROR, "Certaines informations sont manquantes ou invalides")],
        )

        post_data = {
            "birthdate": self.job_seeker.jobseeker_profile.birthdate.strftime(DuetDatePickerWidget.INPUT_DATE_FORMAT),
            "birth_place": "",
            "birth_country": self.job_seeker.jobseeker_profile.birth_country.pk,
            "address_line_1": "37 B Rue du Général De Gaulle",
            "address_line_2": "",
            "post_code": "67118",
            "city": "Geispolsheim",
            "fill_mode": "ban_api",
            "insee_code": "67152",
            "ban_api_resolved_address": "37 B Rue du Général De Gaulle, 67118 Geispolsheim",
            "address_for_autocomplete": "67152_1234_00037",
        }
        response = client.post(self.get_job_seeker_info_step_url(session_uuid), data=post_data)
        assertRedirects(response, reverse("apply:accept_contract_infos", kwargs={"session_uuid": session_uuid}))
        self.fill_contract_info_step(client, job_application, session_uuid)
        self.job_seeker.refresh_from_db()
        assert self.job_seeker.address_line_1 == "37 B Rue du Général De Gaulle"

    def test_no_diagnosis_on_job_application(self, client):
        diagnosis = IAEEligibilityDiagnosisFactory(from_prescriber=True)
        job_application = self.create_job_application(with_iae_eligibility_diagnosis=False)
        self.job_seeker.eligibility_diagnoses.add(diagnosis)
        # No eligibility diagnosis -> if job_seeker has a valid eligibility diagnosis, it's OK
        assert job_application.eligibility_diagnosis is None

        employer = self.company.members.first()
        client.force_login(employer)

        session_uuid = self.start_accept_job_application(client, job_application)
        response = client.get(self.get_job_seeker_info_step_url(session_uuid))
        assertContains(response, "Valider les informations")
        response = self.fill_job_seeker_info_step(client, job_application, session_uuid)
        assertRedirects(response, self.get_contract_info_step_url(session_uuid), fetch_redirect_response=False)

        self.fill_contract_info_step(client, job_application, session_uuid, assert_successful=True, post_data={})

    def test_no_diagnosis(self, client):
        # if no, should not see the confirm button, nor accept posted data
        job_application = self.create_job_application(with_iae_eligibility_diagnosis=False)
        assert job_application.eligibility_diagnosis is None
        job_application.job_seeker.eligibility_diagnoses.all().delete()

        employer = self.company.members.first()
        client.force_login(employer)
        url_accept = reverse("apply:start-accept", kwargs={"job_application_id": job_application.pk})
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
        other_company = CompanyFactory(with_membership=True, with_jobs=True, subject_to_iae_rules=True)
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
        session_uuid = self.start_accept_job_application(client, job_application)
        response = client.get(self.get_job_seeker_info_step_url(session_uuid))
        assertContains(response, "Valider les informations")
        response = self.fill_job_seeker_info_step(client, job_application, session_uuid)
        assertRedirects(response, self.get_contract_info_step_url(session_uuid), fetch_redirect_response=False)

        hiring_start_at = today + relativedelta(days=20)

        post_data = {
            "hiring_start_at": hiring_start_at.strftime(DuetDatePickerWidget.INPUT_DATE_FORMAT),
        }
        self.fill_contract_info_step(client, job_application, session_uuid, post_data=post_data)

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
        jobseeker_profile.birth_country = Country.objects.exclude(pk=Country.FRANCE_ID).order_by("?").first()
        jobseeker_profile.save()
        job_application = self.create_job_application(with_iae_eligibility_diagnosis=True)

        employer = self.company.members.first()
        client.force_login(employer)

        session_uuid = self.start_accept_job_application(client, job_application)
        response = client.get(self.get_job_seeker_info_step_url(session_uuid))
        assertContains(response, "Valider les informations")

        post_data = {
            # Data for `JobSeekerPersonalDataForm`.
            "pole_emploi_id": job_application.job_seeker.jobseeker_profile.pole_emploi_id,
            "lack_of_pole_emploi_id_reason": jobseeker_profile.lack_of_pole_emploi_id_reason,
            "lack_of_nir": True,
            "lack_of_nir_reason": LackOfNIRReason.NO_NIR,
        }
        response = self.fill_job_seeker_info_step(client, job_application, session_uuid, post_data=post_data)
        assertRedirects(response, self.get_contract_info_step_url(session_uuid), fetch_redirect_response=False)

        self.fill_contract_info_step(client, job_application, session_uuid)
        job_application.refresh_from_db()
        assert job_application.approval_delivery_mode == job_application.APPROVAL_DELIVERY_MODE_MANUAL

    def test_update_hiring_start_date_of_two_job_applications(self, client):
        hiring_start_at = timezone.localdate() + relativedelta(months=2)
        hiring_end_at = hiring_start_at + relativedelta(months=2)
        approval_default_ending = Approval.get_default_end_date(start_at=hiring_start_at)
        # Send 3 job applications to 3 different structures
        job_application = self.create_job_application(
            hiring_start_at=hiring_start_at, hiring_end_at=hiring_end_at, with_iae_eligibility_diagnosis=True
        )
        job_seeker = job_application.job_seeker

        wall_e = CompanyFactory(with_membership=True, with_jobs=True, name="WALL-E", subject_to_iae_rules=True)
        job_app_starting_earlier = JobApplicationFactory(
            job_seeker=job_seeker,
            state=job_applications_enums.JobApplicationState.PROCESSING,
            to_company=wall_e,
            selected_jobs=wall_e.jobs.all(),
        )
        vice_versa = CompanyFactory(with_membership=True, with_jobs=True, name="Vice-versa", subject_to_iae_rules=True)
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

        session_uuid = self.start_accept_job_application(client, job_application)
        response = client.get(self.get_job_seeker_info_step_url(session_uuid))
        assertContains(response, "Valider les informations")
        response = self.fill_job_seeker_info_step(client, job_application, session_uuid)
        assertRedirects(response, self.get_contract_info_step_url(session_uuid), fetch_redirect_response=False)
        post_data = {
            "hiring_start_at": hiring_start_at.strftime(DuetDatePickerWidget.INPUT_DATE_FORMAT),
            "hiring_end_at": hiring_end_at.strftime(DuetDatePickerWidget.INPUT_DATE_FORMAT),
        }
        self.fill_contract_info_step(
            client, job_application, session_uuid, post_data=post_data, with_previous_step=True
        )

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
        session_uuid = self.start_accept_job_application(client, job_app_starting_earlier)
        response = client.get(self.get_job_seeker_info_step_url(session_uuid))
        assertRedirects(response, self.get_contract_info_step_url(session_uuid), fetch_redirect_response=False)
        post_data = {
            "hiring_start_at": hiring_start_at.strftime(DuetDatePickerWidget.INPUT_DATE_FORMAT),
            "hiring_end_at": hiring_end_at.strftime(DuetDatePickerWidget.INPUT_DATE_FORMAT),
        }
        self.fill_contract_info_step(
            client, job_app_starting_earlier, session_uuid, post_data=post_data, with_previous_step=False
        )
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
        session_uuid = self.start_accept_job_application(client, job_app_starting_later)
        response = client.get(self.get_job_seeker_info_step_url(session_uuid))
        assertRedirects(response, self.get_contract_info_step_url(session_uuid), fetch_redirect_response=False)
        post_data = {
            "hiring_start_at": hiring_start_at.strftime(DuetDatePickerWidget.INPUT_DATE_FORMAT),
            "hiring_end_at": hiring_end_at.strftime(DuetDatePickerWidget.INPUT_DATE_FORMAT),
        }
        self.fill_contract_info_step(
            client, job_app_starting_later, session_uuid, post_data=post_data, with_previous_step=False
        )
        job_app_starting_later.refresh_from_db()

        # Third job application has been accepted.
        # The job seeker has now three part-time jobs at the same time.
        assert job_app_starting_later.state.is_accepted
        assert job_app_starting_later.approval.start_at == job_app_starting_earlier.hiring_start_at

    def test_nir_readonly(self, client):
        job_application = self.create_job_application(with_iae_eligibility_diagnosis=True)

        employer = self.company.members.first()
        client.force_login(employer)
        session_uuid = self.start_accept_job_application(client, job_application)
        jobseeker_info_url = self.get_job_seeker_info_step_url(session_uuid)
        response = client.get(jobseeker_info_url)
        assertContains(response, "Valider les informations")
        # Check that the NIR field has been removed
        assertNotContains(response, NIR_FIELD_ID)

        job_application.job_seeker.last_login = None
        job_application.job_seeker.created_by = PrescriberFactory()
        job_application.job_seeker.save()
        response = client.get(jobseeker_info_url)
        assertContains(response, "Valider les informations")
        # Check that the NIR field has been removed
        assertNotContains(response, NIR_FIELD_ID)

    def test_no_nir_update(self, client):
        jobseeker_profile = self.job_seeker.jobseeker_profile
        jobseeker_profile.nir = ""
        jobseeker_profile.save()
        job_application = self.create_job_application(with_iae_eligibility_diagnosis=True)

        employer = self.company.members.first()
        client.force_login(employer)
        session_uuid = self.start_accept_job_application(client, job_application)
        jobseeker_info_url = self.get_job_seeker_info_step_url(session_uuid)
        response = client.get(jobseeker_info_url)
        assertContains(response, "Valider les informations")
        # Check that the NIR field is present
        assertContains(response, NIR_FIELD_ID)

        post_data = self._accept_jobseeker_post_data(job_application)
        response = self.fill_job_seeker_info_step(client, job_application, session_uuid, post_data=post_data)
        assertContains(response, "Le numéro de sécurité sociale n'est pas valide", html=True)

        post_data["nir"] = "1234"
        response = self.fill_job_seeker_info_step(client, job_application, session_uuid, post_data=post_data)
        assertContains(response, "Le numéro de sécurité sociale n'est pas valide", html=True)
        assertFormError(
            response.context["form_personal_data"],
            "nir",
            "Le numéro de sécurité sociale est trop court (15 caractères autorisés).",
        )

        NEW_NIR = "197013625838386"
        post_data["nir"] = NEW_NIR
        response = self.fill_job_seeker_info_step(client, job_application, session_uuid, post_data=post_data)
        assertRedirects(response, self.get_contract_info_step_url(session_uuid), fetch_redirect_response=False)
        jobseeker_profile.refresh_from_db()
        assert jobseeker_profile.nir != NEW_NIR  # Not saved yet

        self.fill_contract_info_step(client, job_application, session_uuid)
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
        session_uuid = self.start_accept_job_application(client, job_application)
        jobseeker_info_url = self.get_job_seeker_info_step_url(session_uuid)
        response = client.get(jobseeker_info_url)
        assertContains(response, "Valider les informations")

        post_data = {
            "pole_emploi_id": jobseeker_profile.pole_emploi_id,
            "nir": other_job_seeker.jobseeker_profile.nir,
        }
        response = self.fill_job_seeker_info_step(client, job_application, session_uuid, post_data=post_data)
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

        session_uuid = self.start_accept_job_application(client, job_application)
        jobseeker_info_url = self.get_job_seeker_info_step_url(session_uuid)
        response = client.get(jobseeker_info_url)
        assertContains(response, "Valider les informations")

        post_data = self._accept_jobseeker_post_data(job_application=job_application)
        response = self.fill_job_seeker_info_step(client, job_application, session_uuid, post_data=post_data)
        assertContains(response, "Le numéro de sécurité sociale n'est pas valide", html=True)

        # Check the box
        post_data["lack_of_nir"] = True
        response = self.fill_job_seeker_info_step(client, job_application, session_uuid, post_data=post_data)
        assertContains(response, "Le numéro de sécurité sociale n'est pas valide", html=True)
        assertContains(response, "Veuillez sélectionner un motif pour continuer", html=True)

        post_data["lack_of_nir_reason"] = LackOfNIRReason.NO_NIR
        response = self.fill_job_seeker_info_step(client, job_application, session_uuid, post_data=post_data)
        assertRedirects(response, self.get_contract_info_step_url(session_uuid), fetch_redirect_response=False)

        job_application.job_seeker.jobseeker_profile.refresh_from_db()
        assert (
            job_application.job_seeker.jobseeker_profile.lack_of_nir_reason != LackOfNIRReason.NO_NIR
        )  # Not saved yet

        self.fill_contract_info_step(client, job_application, session_uuid)
        job_application.job_seeker.jobseeker_profile.refresh_from_db()
        assert job_application.job_seeker.jobseeker_profile.lack_of_nir_reason == LackOfNIRReason.NO_NIR

    def test_lack_of_nir_reason_update(self, client):
        jobseeker_profile = self.job_seeker.jobseeker_profile
        jobseeker_profile.nir = ""
        jobseeker_profile.lack_of_nir_reason = LackOfNIRReason.NO_NIR
        jobseeker_profile.save()
        job_application = self.create_job_application(with_iae_eligibility_diagnosis=True)

        employer = self.company.members.first()
        client.force_login(employer)

        session_uuid = self.start_accept_job_application(client, job_application)
        jobseeker_info_url = self.get_job_seeker_info_step_url(session_uuid)
        response = client.get(jobseeker_info_url)
        assertContains(response, "Valider les informations")

        # Check that the NIR field is initially disabled
        # since the job seeker has a lack_of_nir_reason
        assert response.context["form_personal_data"].fields["nir"].disabled
        NEW_NIR = "197013625838386"

        post_data = {
            "nir": NEW_NIR,
            "lack_of_nir_reason": jobseeker_profile.lack_of_nir_reason,
            "birth_country": Country.objects.exclude(pk=Country.FRANCE_ID).order_by("?").first().pk,
        }
        post_data = self._accept_jobseeker_post_data(job_application=job_application, post_data=post_data)
        response = self.fill_job_seeker_info_step(client, job_application, session_uuid, post_data=post_data)
        assertRedirects(response, self.get_contract_info_step_url(session_uuid), fetch_redirect_response=False)

        job_application.job_seeker.refresh_from_db()
        # No change yet
        assert job_application.job_seeker.jobseeker_profile.lack_of_nir_reason
        assert job_application.job_seeker.jobseeker_profile.nir != NEW_NIR

        self.fill_contract_info_step(client, job_application, session_uuid)
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

        employer = self.company.members.first()
        client.force_login(employer)

        session_uuid = self.start_accept_job_application(client, job_application)
        jobseeker_info_url = self.get_job_seeker_info_step_url(session_uuid)
        response = client.get(jobseeker_info_url)
        assertContains(response, "Valider les informations")
        # Check that the NIR field is initially disabled
        # since the job seeker has a lack_of_nir_reason
        assert response.context["form_personal_data"].fields["nir"].disabled

        # Check that the NIR modification link is there
        assertContains(
            response,
            (
                '<a href="'
                f'{
                    reverse(
                        "job_seekers_views:nir_modification_request",
                        kwargs={"public_id": job_application.job_seeker.public_id},
                        query={"back_url": jobseeker_info_url},
                    )
                }">Demander la correction du numéro de sécurité sociale</a>'
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
        session_uuid = self.start_accept_job_application(client, job_application)
        response = client.get(self.get_job_seeker_info_step_url(session_uuid))
        assertContains(response, "Valider les informations")
        response = self.fill_job_seeker_info_step(client, job_application, session_uuid)
        assertRedirects(response, self.get_contract_info_step_url(session_uuid), fetch_redirect_response=False)
        self.fill_contract_info_step(client, job_application, session_uuid)

        job_application.refresh_from_db()
        assert job_application.job_seeker.approvals.count() == 1
        approval = job_application.job_seeker.approvals.first()
        assert approval.start_at == job_application.hiring_start_at
        assert job_application.state.is_accepted

    @pytest.mark.usefixtures("api_particulier_settings")
    @pytest.mark.parametrize("from_kind", {UserKind.EMPLOYER, UserKind.PRESCRIBER})
    @freeze_time("2024-09-11")
    def test_accept_iae_criteria_can_be_certified(self, client, mocker, from_kind):
        criteria_kind = random.choice(list(CERTIFIABLE_ADMINISTRATIVE_CRITERIA_KINDS))
        mocked_request = mocker.patch(
            "itou.utils.apis.api_particulier._request",
            return_value=RESPONSES[criteria_kind][ResponseKind.CERTIFIED]["json"],
        )
        ######### Case 1: if CRITERIA_KIND is one of the diagnosis criteria,
        ######### birth place and birth country are required.
        birthdate = datetime.date(1995, 12, 27)
        diagnosis = IAEEligibilityDiagnosisFactory(
            job_seeker=self.job_seeker,
            author_siae=self.company if from_kind is UserKind.EMPLOYER else None,
            certifiable=True,
            **{f"from_{from_kind}": True},
            criteria_kinds=[criteria_kind, AdministrativeCriteriaKind.CAP_BEP],
        )
        job_application = self.create_job_application(
            eligibility_diagnosis=diagnosis,
            job_seeker__jobseeker_profile__birthdate=birthdate,
        )
        to_be_certified_criteria = diagnosis.selected_administrative_criteria.filter(
            administrative_criteria__kind__in=criteria_kind
        )
        employer = job_application.to_company.members.first()
        client.force_login(employer)

        session_uuid = self.start_accept_job_application(client, job_application)
        response = client.get(self.get_job_seeker_info_step_url(session_uuid))
        assertContains(response, "Valider les informations")
        assertContains(response, self.BIRTH_COUNTRY_LABEL)
        assertContains(response, self.BIRTH_PLACE_LABEL)

        # CertifiedCriteriaForm
        # Birth country is mandatory.
        post_data = {
            "birth_country": "",
            "birth_place": "",
        }
        response = self.fill_job_seeker_info_step(client, job_application, session_uuid, post_data=post_data)
        assertFormError(response.context["form_birth_data"], "birth_country", "Le pays de naissance est obligatoire.")

        # Wrong birth country and birth place.
        post_data["birth_country"] = "0012345"
        post_data["birth_place"] = "008765"
        response = self.fill_job_seeker_info_step(client, job_application, session_uuid, post_data=post_data)
        assert response.context["form_birth_data"].errors == {
            "birth_place": ["Sélectionnez un choix valide. Ce choix ne fait pas partie de ceux disponibles."],
            "birth_country": [
                "Sélectionnez un choix valide. Ce choix ne fait pas partie de ceux disponibles.",
                "Le pays de naissance est obligatoire.",
            ],
        }

        birth_country = Country.objects.get(pk=Country.FRANCE_ID)
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
        response = self.fill_job_seeker_info_step(client, job_application, session_uuid, post_data=post_data)
        assertRedirects(response, self.get_contract_info_step_url(session_uuid), fetch_redirect_response=False)

        jobseeker_profile = job_application.job_seeker.jobseeker_profile
        jobseeker_profile.refresh_from_db()
        # Not saved yet
        assert jobseeker_profile.birth_country != birth_country
        assert jobseeker_profile.birth_place != birth_place

        self.fill_contract_info_step(client, job_application, session_uuid, assert_successful=True)
        mocked_request.assert_called_once()
        jobseeker_profile = job_application.job_seeker.jobseeker_profile
        jobseeker_profile.refresh_from_db()
        assert jobseeker_profile.birth_country == birth_country
        assert jobseeker_profile.birth_place == birth_place

        # certification
        for criterion in to_be_certified_criteria:
            criterion.refresh_from_db()
            assert criterion.certified
            assert criterion.data_returned_by_api == RESPONSES[criteria_kind][ResponseKind.CERTIFIED]["json"]
            assert criterion.certification_period == InclusiveDateRange(datetime.date(2024, 8, 1))
            assert criterion.certified_at

    @pytest.mark.usefixtures("api_particulier_settings")
    @pytest.mark.parametrize("from_kind", {UserKind.EMPLOYER, UserKind.PRESCRIBER})
    @freeze_time("2024-09-11")
    def test_accept_iae_criteria_can_be_certified_no_missing_data(self, client, mocker, from_kind):
        criteria_kind = random.choice(list(CERTIFIABLE_ADMINISTRATIVE_CRITERIA_KINDS))
        mocked_request = mocker.patch(
            "itou.utils.apis.api_particulier._request",
            return_value=RESPONSES[criteria_kind][ResponseKind.CERTIFIED]["json"],
        )
        diagnosis = IAEEligibilityDiagnosisFactory(
            job_seeker=self.job_seeker,
            author_siae=self.company if from_kind is UserKind.EMPLOYER else None,
            certifiable=True,
            **{f"from_{from_kind}": True},
            criteria_kinds=[criteria_kind, AdministrativeCriteriaKind.CAP_BEP],
        )
        job_application = self.create_job_application(
            eligibility_diagnosis=diagnosis,
        )
        birthdate = datetime.date(1995, 12, 27)
        job_application.job_seeker.jobseeker_profile.birthdate = birthdate
        job_application.job_seeker.jobseeker_profile.birth_country = Country.objects.get(pk=Country.FRANCE_ID)
        job_application.job_seeker.jobseeker_profile.birth_place = Commune.objects.by_insee_code_and_period(
            "07141", job_application.job_seeker.jobseeker_profile.birthdate
        )
        job_application.job_seeker.jobseeker_profile.save(update_fields=["birthdate", "birth_country", "birth_place"])
        to_be_certified_criteria = diagnosis.selected_administrative_criteria.filter(
            administrative_criteria__kind__in=criteria_kind
        )
        employer = job_application.to_company.members.first()
        client.force_login(employer)

        session_uuid = self.start_accept_job_application(client, job_application)
        response = client.get(self.get_job_seeker_info_step_url(session_uuid))
        assertRedirects(response, self.get_contract_info_step_url(session_uuid), fetch_redirect_response=False)
        self.fill_contract_info_step(
            client, job_application, session_uuid, assert_successful=True, with_previous_step=False
        )
        mocked_request.assert_called_once()

        # certification
        for criterion in to_be_certified_criteria:
            criterion.refresh_from_db()
            assert criterion.certified
            assert criterion.data_returned_by_api == RESPONSES[criteria_kind][ResponseKind.CERTIFIED]["json"]
            assert criterion.certification_period == InclusiveDateRange(datetime.date(2024, 8, 1))
            assert criterion.certified_at

    @pytest.mark.usefixtures("api_particulier_settings")
    @pytest.mark.parametrize("from_kind", {UserKind.EMPLOYER, UserKind.PRESCRIBER})
    @freeze_time("2024-09-11")
    def test_accept_geiq_criteria_can_be_certified_no_missing_data(self, client, mocker, from_kind):
        criteria_kind = random.choice(list(CERTIFIABLE_ADMINISTRATIVE_CRITERIA_KINDS))
        mocked_request = mocker.patch(
            "itou.utils.apis.api_particulier._request",
            return_value=RESPONSES[criteria_kind][ResponseKind.CERTIFIED]["json"],
        )
        self.company.kind = CompanyKind.GEIQ
        self.company.save()
        diagnosis = GEIQEligibilityDiagnosisFactory(
            job_seeker=self.job_seeker,
            author_geiq=self.company if from_kind is UserKind.EMPLOYER else None,
            certifiable=True,
            **{f"from_{from_kind}": True},
            criteria_kinds=[criteria_kind],
        )
        job_application = self.create_job_application(
            geiq_eligibility_diagnosis=diagnosis,
        )
        birthdate = datetime.date(1995, 12, 27)
        job_application.job_seeker.jobseeker_profile.birthdate = birthdate
        job_application.job_seeker.jobseeker_profile.birth_country = Country.objects.get(pk=Country.FRANCE_ID)
        job_application.job_seeker.jobseeker_profile.birth_place = Commune.objects.by_insee_code_and_period(
            "07141", job_application.job_seeker.jobseeker_profile.birthdate
        )
        job_application.job_seeker.jobseeker_profile.save(update_fields=["birthdate", "birth_country", "birth_place"])
        to_be_certified_criteria = GEIQSelectedAdministrativeCriteria.objects.filter(
            administrative_criteria__kind__in=CERTIFIABLE_ADMINISTRATIVE_CRITERIA_KINDS,
            eligibility_diagnosis=job_application.geiq_eligibility_diagnosis,
        ).all()

        employer = job_application.to_company.members.first()
        client.force_login(employer)

        session_uuid = self.start_accept_job_application(client, job_application)
        response = client.get(self.get_job_seeker_info_step_url(session_uuid))
        assertRedirects(response, self.get_contract_info_step_url(session_uuid), fetch_redirect_response=False)
        self.fill_contract_info_step(
            client, job_application, session_uuid, assert_successful=True, with_previous_step=False
        )
        mocked_request.assert_called_once()
        # certification
        for criterion in to_be_certified_criteria:
            criterion.refresh_from_db()
            assert criterion.certified
            assert criterion.data_returned_by_api == RESPONSES[criteria_kind][ResponseKind.CERTIFIED]["json"]
            assert criterion.certification_period == InclusiveDateRange(datetime.date(2024, 8, 1))
            assert criterion.certified_at

    @pytest.mark.usefixtures("api_particulier_settings")
    @pytest.mark.parametrize("from_kind", {UserKind.EMPLOYER, UserKind.PRESCRIBER})
    @freeze_time("2024-09-11")
    def test_accept_geiq_criteria_can_be_certified(self, client, mocker, from_kind):
        criteria_kind = random.choice(list(CERTIFIABLE_ADMINISTRATIVE_CRITERIA_KINDS))
        mocked_request = mocker.patch(
            "itou.utils.apis.api_particulier._request",
            return_value=RESPONSES[criteria_kind][ResponseKind.CERTIFIED]["json"],
        )
        birthdate = datetime.date(1995, 12, 27)
        self.company.kind = CompanyKind.GEIQ
        self.company.save()
        diagnosis = GEIQEligibilityDiagnosisFactory(
            job_seeker=self.job_seeker,
            author_geiq=self.company if from_kind is UserKind.EMPLOYER else None,
            certifiable=True,
            **{f"from_{from_kind}": True},
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

        employer = job_application.to_company.members.first()
        client.force_login(employer)

        session_uuid = self.start_accept_job_application(client, job_application)
        response = client.get(self.get_job_seeker_info_step_url(session_uuid))
        assertContains(response, "Valider les informations")
        assertContains(response, self.BIRTH_COUNTRY_LABEL)
        assertContains(response, self.BIRTH_PLACE_LABEL)

        # CertifiedCriteriaForm
        # Birth country is mandatory.
        post_data = {
            "birth_country": "",
            "birth_place": "",
        }
        response = self.fill_job_seeker_info_step(client, job_application, session_uuid, post_data=post_data)
        assertFormError(response.context["form_birth_data"], "birth_country", "Le pays de naissance est obligatoire.")

        # Then set it.
        birth_country = Country.objects.get(pk=Country.FRANCE_ID)
        birth_place = Commune.objects.by_insee_code_and_period(
            "07141", job_application.job_seeker.jobseeker_profile.birthdate
        )
        post_data = {
            "birth_country": "",
            "birth_place": birth_place.pk,
        }
        response = self.fill_job_seeker_info_step(client, job_application, session_uuid, post_data=post_data)
        assertRedirects(response, self.get_contract_info_step_url(session_uuid), fetch_redirect_response=False)
        jobseeker_profile = job_application.job_seeker.jobseeker_profile
        # Not saved yet
        jobseeker_profile.refresh_from_db()
        assert jobseeker_profile.birth_country != birth_country
        assert jobseeker_profile.birth_place != birth_place

        self.fill_contract_info_step(client, job_application, session_uuid, assert_successful=True)
        mocked_request.assert_called_once()
        jobseeker_profile.refresh_from_db()
        assert jobseeker_profile.birth_country == birth_country
        assert jobseeker_profile.birth_place == birth_place

        # certification
        for criterion in to_be_certified_criteria:
            criterion.refresh_from_db()
            assert criterion.certified
            assert criterion.data_returned_by_api == RESPONSES[criteria_kind][ResponseKind.CERTIFIED]["json"]
            assert criterion.certification_period == InclusiveDateRange(datetime.date(2024, 8, 1))
            assert criterion.certified_at

    @pytest.mark.parametrize("from_kind", {UserKind.EMPLOYER, UserKind.PRESCRIBER})
    @freeze_time("2024-09-11")
    def test_accept_not_an_siae_or_geiq_cannot_be_certified(self, client, mocker, from_kind):
        mocker.patch(
            "itou.utils.apis.api_particulier._request",
            return_value=RESPONSES[AdministrativeCriteriaKind.RSA][ResponseKind.CERTIFIED]["json"],
        )
        # No eligibility diagnosis for other company kinds.
        kind = random.choice([x for x in CompanyKind if x not in [*CompanyKind.siae_kinds(), CompanyKind.GEIQ]])
        company = CompanyFactory(kind=kind, with_membership=True, with_jobs=True)
        diagnosis = IAEEligibilityDiagnosisFactory(
            job_seeker=self.job_seeker,
            author_siae=self.company if from_kind is UserKind.EMPLOYER else None,
            certifiable=True,
            **{f"from_{from_kind}": True},
            criteria_kinds=[AdministrativeCriteriaKind.RSA],
        )
        job_application = self.create_job_application(
            eligibility_diagnosis=diagnosis,
            selected_jobs=company.jobs.all(),
            to_company=company,
        )

        employer = job_application.to_company.members.first()
        client.force_login(employer)

        session_uuid = self.start_accept_job_application(client, job_application)
        response = client.get(self.get_job_seeker_info_step_url(session_uuid))
        assertContains(response, "Valider les informations")
        assertContains(response, self.BIRTH_COUNTRY_LABEL)
        assertContains(response, self.BIRTH_PLACE_LABEL)

        birth_place = Commune.objects.by_insee_code_and_period(
            "07141", job_application.job_seeker.jobseeker_profile.birthdate
        )
        post_data = {
            "birth_country": "",
            "birth_place": birth_place.pk,
        }
        response = self.fill_job_seeker_info_step(client, job_application, session_uuid, post_data=post_data)
        assertRedirects(response, self.get_contract_info_step_url(session_uuid), fetch_redirect_response=False)

        post_data = self._accept_contract_post_data(job_application=job_application)
        self.fill_contract_info_step(
            client,
            job_application,
            session_uuid,
            post_data=post_data,
            assert_successful=True,
            with_previous_step=True,
        )

        jobseeker_profile = job_application.job_seeker.jobseeker_profile
        jobseeker_profile.refresh_from_db()
        assert jobseeker_profile.birth_country_id == Country.FRANCE_ID
        assert jobseeker_profile.birth_place_id == birth_place.id

    def test_accept_with_job_seeker_update(self, client):
        diagnosis = IAEEligibilityDiagnosisFactory(job_seeker=self.job_seeker, from_prescriber=True)
        job_application = self.create_job_application(
            eligibility_diagnosis=diagnosis,
            job_seeker__jobseeker_profile__birthdate=datetime.date(1995, 12, 27),
        )
        job_seeker = job_application.job_seeker
        # Remove birthdate to have the form available
        job_seeker.jobseeker_profile.birthdate = None
        job_seeker.jobseeker_profile.save(update_fields=["birthdate"])
        IdentityCertification.objects.create(
            jobseeker_profile=job_seeker.jobseeker_profile,
            certifier=IdentityCertificationAuthorities.API_PARTICULIER,
        )
        birth_country = Country.objects.get(name="BORA-BORA")

        employer = job_application.to_company.members.get()
        client.force_login(employer)

        session_uuid = self.start_accept_job_application(client, job_application)
        response = client.get(self.get_job_seeker_info_step_url(session_uuid))
        assertContains(response, "Valider les informations")

        post_data = {
            "ban_api_resolved_address": job_seeker.geocoding_address,
            "address_line_1": job_seeker.address_line_1,
            "post_code": job_seeker.insee_city.post_codes[0],
            "insee_code": job_seeker.insee_city.code_insee,
            "city": job_seeker.insee_city.name,
            "fill_mode": "ban_api",
            # Select the first and only one option
            "address_for_autocomplete": "0",
            "geocoding_score": 0.9714,
            "birthdate": "",
            "birth_country": birth_country.pk,
            "pole_emploi_id": job_seeker.jobseeker_profile.pole_emploi_id,
        }
        response = self.fill_job_seeker_info_step(client, job_application, session_uuid, post_data=post_data)
        assert response.status_code == 200
        soup = parse_response_to_soup(response, selector="#id_birth_country")
        assert soup.attrs.get("disabled", False) is False
        [selected_option] = soup.find_all(attrs={"selected": True})
        assert selected_option.text == "BORA-BORA"

    @freeze_time("2024-09-11")
    def test_accept_updated_birthdate_invalidating_birth_place(self, client, mocker):
        mocker.patch(
            "itou.utils.apis.api_particulier._request",
            return_value=RESPONSES[AdministrativeCriteriaKind.RSA][ResponseKind.CERTIFIED]["json"],
        )
        diagnosis = IAEEligibilityDiagnosisFactory(
            job_seeker=self.job_seeker,
            author_siae=self.company,
            certifiable=True,
            criteria_kinds=[AdministrativeCriteriaKind.RSA],
        )
        # tests for a rare case where the birthdate will be cleaned for sharing between forms during the accept process
        job_application = self.create_job_application(eligibility_diagnosis=diagnosis)
        # Remove birth related infos to have the forms available
        birthdate = self.job_seeker.jobseeker_profile.birthdate
        self.job_seeker.jobseeker_profile.birthdate = None
        self.job_seeker.jobseeker_profile.birth_place = None
        self.job_seeker.jobseeker_profile.birth_country = None
        self.job_seeker.jobseeker_profile.save(update_fields=["birthdate", "birth_place", "birth_country"])

        # required assumptions for the test case
        assert self.company.is_subject_to_iae_rules
        ed = EligibilityDiagnosis.objects.last_considered_valid(job_seeker=self.job_seeker, for_siae=self.company)
        assert ed and ed.criteria_can_be_certified()

        employer = self.company.members.first()
        client.force_login(employer)

        session_uuid = self.start_accept_job_application(client, job_application)
        response = client.get(self.get_job_seeker_info_step_url(session_uuid))
        assertContains(response, "Valider les informations")

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

        response = self.fill_job_seeker_info_step(client, job_application, session_uuid, post_data=post_data)
        expected_msg = (
            f"Le code INSEE {birth_place.code} n'est pas référencé par l'ASP en date du {early_date:%d/%m/%Y}"
        )

        assert response.context["form_birth_data"].errors == {
            "birth_place": [expected_msg],
        }

        # assert malformed birthdate does not crash view
        post_data["birthdate"] = "20240-001-001"
        response = self.fill_job_seeker_info_step(client, job_application, session_uuid, post_data=post_data)
        assert response.context["form_birth_data"].errors == {"birthdate": ["Saisissez une date valide."]}

        # test that fixing the birthdate fixes the form submission
        post_data["birthdate"] = birth_place.start_date + datetime.timedelta(days=1)
        response = self.fill_job_seeker_info_step(client, job_application, session_uuid, post_data=post_data)
        assertRedirects(response, self.get_contract_info_step_url(session_uuid), fetch_redirect_response=False)
        self.fill_contract_info_step(client, job_application, session_uuid, assert_successful=True)

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
        session_uuid = self.start_accept_job_application(client, job_application)
        response = client.get(self.get_job_seeker_info_step_url(session_uuid))
        assertContains(response, "Valider les informations")

        post_data = self._accept_jobseeker_post_data(job_application=job_application)
        post_data["birth_country"] = Country.FRANCE_ID
        post_data["birth_place"] = ""
        response = self.fill_job_seeker_info_step(client, job_application, session_uuid, post_data=post_data)
        assertContains(
            response,
            """
            <div class="alert alert-danger" role="alert" tabindex="0" data-emplois-give-focus-if-exist>
                <p>
                    <strong>Votre formulaire contient une erreur</strong>
                </p>
                <ul class="mb-0">
                    <li>
                        La commune de naissance doit être spécifiée si et seulement si le pays de naissance
                        est la France.
                    </li>
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

        session_uuid = self.start_accept_job_application(client, job_application)
        response = client.get(self.get_job_seeker_info_step_url(session_uuid))
        assertContains(response, "Valider les informations")
        post_data = self._accept_jobseeker_post_data(job_application=job_application)
        post_data["birth_country"] = Country.objects.order_by("?").exclude(group=Country.Group.FRANCE).first().pk
        response = self.fill_job_seeker_info_step(client, job_application, session_uuid, post_data=post_data)
        assertContains(
            response,
            """
            <div class="alert alert-danger" role="alert" tabindex="0" data-emplois-give-focus-if-exist>
                <p>
                    <strong>Votre formulaire contient une erreur</strong>
                </p>
                <ul class="mb-0">
                    <li>
                        La commune de naissance doit être spécifiée si et seulement si le pays de naissance
                        est la France.
                    </li>
                </ul>
            </div>""",
            html=True,
            count=1,
        )

    @freeze_time("2025-06-06")
    def test_certified_criteria_birth_fields_not_readonly_if_empty(self, client):
        birth_place = Commune.objects.by_insee_code_and_period("07141", datetime.date(1990, 1, 1))

        job_seeker = JobSeekerFactory(
            with_pole_emploi_id=True,
            with_ban_api_mocked_address=True,
            jobseeker_profile__birth_place=None,
            jobseeker_profile__birth_country=None,
        )
        selected_criteria = IAESelectedAdministrativeCriteriaFactory(
            eligibility_diagnosis__job_seeker=job_seeker,
            eligibility_diagnosis__author_siae=self.company,
            criteria_certified=True,
        )
        job_application = JobApplicationSentByJobSeekerFactory(
            job_seeker=job_seeker,
            to_company=self.company,
            state=JobApplicationState.PROCESSING,
            eligibility_diagnosis=selected_criteria.eligibility_diagnosis,
            selected_jobs=[self.company.jobs.first()],
        )
        client.force_login(self.company.members.get())

        session_uuid = self.start_accept_job_application(client, job_application)
        response = client.get(self.get_job_seeker_info_step_url(session_uuid))
        assertContains(response, "Valider les informations")
        form = response.context["form_birth_data"]
        assert form.fields["birth_place"].disabled is False
        assert form.fields["birth_country"].disabled is False
        post_data = {
            "title": job_seeker.title,
            "first_name": job_seeker.first_name,
            "last_name": job_seeker.last_name,
            "birth_place": birth_place.pk,
            "birth_country": Country.FRANCE_ID,
            "birthdate": job_seeker.jobseeker_profile.birthdate,
        }
        response = self.fill_job_seeker_info_step(client, job_application, session_uuid, post_data=post_data)
        assertRedirects(response, self.get_contract_info_step_url(session_uuid), fetch_redirect_response=False)
        # Not saved yet
        refreshed_job_seeker = User.objects.select_related("jobseeker_profile").get(pk=job_seeker.pk)
        assert refreshed_job_seeker.jobseeker_profile.birth_place_id != birth_place.pk
        assert refreshed_job_seeker.jobseeker_profile.birth_country_id != Country.FRANCE_ID

        self.fill_contract_info_step(client, job_application, session_uuid)
        refreshed_job_seeker = User.objects.select_related("jobseeker_profile").get(pk=job_seeker.pk)
        assert refreshed_job_seeker.jobseeker_profile.birth_place_id == birth_place.pk
        assert refreshed_job_seeker.jobseeker_profile.birth_country_id == Country.FRANCE_ID


class TestFillJobSeekerInfosForAccept:
    @pytest.fixture(autouse=True)
    def setup_method(self, settings, mocker):
        self.job_seeker = JobSeekerFactory(
            first_name="Clara",
            last_name="Sion",
            with_pole_emploi_id=True,
            with_ban_geoloc_address=True,
            born_in_france=True,
        )
        self.company = CompanyFactory(with_membership=True)
        if self.company.is_subject_to_iae_rules:
            IAEEligibilityDiagnosisFactory(from_prescriber=True, job_seeker=self.job_seeker)
        elif self.company.kind == CompanyKind.GEIQ:
            GEIQEligibilityDiagnosisFactory(from_prescriber=True, job_seeker=self.job_seeker)
        # This is the city matching with_ban_geoloc_address trait
        self.city = create_city_geispolsheim()

        settings.API_BAN_BASE_URL = "http://ban-api"
        mocker.patch(
            "itou.utils.apis.geocoding.get_geocoding_data",
            side_effect=mock_get_first_geocoding_data,
        )

    def accept_contract(self, client, job_application, session_uuid):
        post_data = {
            "hiring_start_at": timezone.localdate().strftime(DuetDatePickerWidget.INPUT_DATE_FORMAT),
            "hiring_end_at": "",
            "answer": "",
            "confirmed": True,
        }
        if job_application.to_company.kind == CompanyKind.GEIQ:
            create_test_romes_and_appellations(["N1101"], appellations_per_rome=1)  # For hired_job field
            post_data.update(
                {
                    "prehiring_guidance_days": 10,
                    "contract_type": ContractType.APPRENTICESHIP,
                    "nb_hours_per_week": 10,
                    "qualification_type": QualificationType.CQP,
                    "qualification_level": QualificationLevel.LEVEL_4,
                    "planned_training_hours": 20,
                    "hired_job": JobDescriptionFactory(company=self.company).pk,
                }
            )
        response = client.post(
            reverse("apply:accept_contract_infos", kwargs={"session_uuid": session_uuid}),
            data=post_data,
            headers={"hx-request": "true"},
        )
        assertRedirects(
            response,
            reverse("apply:details_for_company", kwargs={"job_application_id": job_application.pk}),
            status_code=200,
            fetch_redirect_response=False,
        )

    def test_no_missing_data_iae(self, client, snapshot):
        # Ensure company is SIAE kind since it will trigger an extra query for eligibility diagnosis
        # changing the SQL queries snapshot
        if not self.company.is_subject_to_iae_rules:
            self.company.kind = random.choice(list(CompanyKind.siae_kinds()))
            self.company.convention = SiaeConventionFactory(kind=self.company.kind)
            self.company.save(update_fields=["convention", "kind", "updated_at"])
            IAEEligibilityDiagnosisFactory(from_prescriber=True, job_seeker=self.job_seeker)
        job_application = JobApplicationSentByJobSeekerFactory(
            state=JobApplicationState.PROCESSING,
            job_seeker=self.job_seeker,
            to_company=self.company,
        )
        client.force_login(self.company.members.first())

        url_accept = reverse(
            "apply:start-accept",
            kwargs={"job_application_id": job_application.pk},
        )
        response = client.get(url_accept)
        session_uuid = get_session_name(client.session, ACCEPT_SESSION_KIND)
        assert session_uuid is not None
        fill_job_seeker_infos_url = reverse(
            "apply:accept_fill_job_seeker_infos", kwargs={"session_uuid": session_uuid}
        )
        assertRedirects(
            response,
            fill_job_seeker_infos_url,
            fetch_redirect_response=False,
        )

        with assertSnapshotQueries(snapshot(name="view queries")):
            response = client.get(fill_job_seeker_infos_url)
        assertRedirects(response, reverse("apply:accept_contract_infos", kwargs={"session_uuid": session_uuid}))

    @pytest.mark.parametrize("address", ["empty", "incomplete"])
    def test_no_address(self, client, address):
        job_application = JobApplicationSentByJobSeekerFactory(
            state=JobApplicationState.PROCESSING,
            job_seeker=self.job_seeker,
            to_company=self.company,
        )
        address_kwargs = {
            "address_line_1": "",
            "city": "",
            "post_code": "",
        }
        if address == "incomplete":
            address_kwargs.pop(random.choice(list(address_kwargs.keys())))

        # Remove job seeker address
        for key, value in address_kwargs.items():
            setattr(self.job_seeker, key, value)
        self.job_seeker.save(update_fields=address_kwargs.keys())

        client.force_login(self.company.members.first())

        url_accept = reverse(
            "apply:start-accept",
            kwargs={"job_application_id": job_application.pk},
        )
        response = client.get(url_accept)
        session_uuid = get_session_name(client.session, ACCEPT_SESSION_KIND)
        assert session_uuid is not None
        fill_job_seeker_infos_url = reverse(
            "apply:accept_fill_job_seeker_infos", kwargs={"session_uuid": session_uuid}
        )
        assertRedirects(
            response,
            fill_job_seeker_infos_url,
            fetch_redirect_response=False,
        )

        response = client.get(fill_job_seeker_infos_url)
        assertContains(response, "Accepter la candidature de Clara SION")

        post_data = {
            "address_line_1": "128 Rue de Grenelle",
            "address_line_2": "",
            "post_code": "67118",
            "city": "Geispolsheim",
            "fill_mode": "ban_api",
            "insee_code": "67152",
            "ban_api_resolved_address": "128 Rue de Grenelle 67118 Geispolsheim",
            "address_for_autocomplete": "67152_1234_00128",
        }
        # Test with invalid data
        response = client.post(
            fill_job_seeker_infos_url,
            data=post_data | {"address_line_1": "", "address_for_autocomplete": ""},
        )
        assert response.status_code == 200
        assertFormError(response.context["form_user_address"], "address_for_autocomplete", "Ce champ est obligatoire.")
        response = client.post(fill_job_seeker_infos_url, data=post_data)
        assertRedirects(response, reverse("apply:accept_contract_infos", kwargs={"session_uuid": session_uuid}))
        assert client.session[session_uuid]["job_seeker_info_forms_data"] == {
            "user_address": {
                "address_line_1": "128 Rue de Grenelle",
                "address_line_2": "",
                "post_code": "67118",
                "city": "Geispolsheim",
                "fill_mode": "ban_api",
                "insee_code": "67152",
                "ban_api_resolved_address": "128 Rue de Grenelle 67118 Geispolsheim",
                "address_for_autocomplete": "67152_1234_00128",
            },
        }
        # If you come back to the view, it is pre-filled with session data
        response = client.get(fill_job_seeker_infos_url)
        assertContains(response, "128 Rue de Grenelle")

        # Check that address infos are saved (if modified) after filling contract info step
        self.accept_contract(client, job_application, session_uuid)
        self.job_seeker.refresh_from_db()
        assert self.job_seeker.address_line_1 == "128 Rue de Grenelle"
        assert self.job_seeker.post_code == "67118"
        assert self.job_seeker.city == "Geispolsheim"

    @pytest.mark.parametrize("birth_country", [None, "france", "other"])
    def test_no_birthdate(self, client, birth_country):
        client.force_login(self.company.members.first())
        job_application = JobApplicationSentByJobSeekerFactory(
            state=JobApplicationState.PROCESSING,
            job_seeker=self.job_seeker,
            to_company=self.company,
        )
        self.job_seeker.jobseeker_profile.birthdate = None
        if birth_country == "france":
            self.job_seeker.jobseeker_profile.birth_country_id = Country.FRANCE_ID
            self.job_seeker.jobseeker_profile.birth_place = Commune.objects.by_insee_code_and_period(
                "59183", datetime.date(1990, 1, 1)
            )
        elif birth_country == "other":
            self.job_seeker.jobseeker_profile.birth_country = (
                Country.objects.exclude(pk=Country.FRANCE_ID).order_by("?").first()
            )
            self.job_seeker.jobseeker_profile.birth_place = None
        else:
            self.job_seeker.jobseeker_profile.birth_country = None
            self.job_seeker.jobseeker_profile.birth_place = None
        self.job_seeker.jobseeker_profile.save(update_fields=["birthdate", "birth_country", "birth_place"])

        url_accept = reverse(
            "apply:start-accept",
            kwargs={"job_application_id": job_application.pk},
        )
        response = client.get(url_accept)
        session_uuid = get_session_name(client.session, ACCEPT_SESSION_KIND)
        assert session_uuid is not None
        fill_job_seeker_infos_url = reverse(
            "apply:accept_fill_job_seeker_infos", kwargs={"session_uuid": session_uuid}
        )
        accept_contract_infos_url = reverse("apply:accept_contract_infos", kwargs={"session_uuid": session_uuid})
        assertRedirects(
            response,
            fill_job_seeker_infos_url,
            fetch_redirect_response=False,
        )

        response = client.get(fill_job_seeker_infos_url)
        assertContains(response, "Accepter la candidature de Clara SION")
        assertContains(response, "Valider les informations")

        COUNTRY_FIELD_ID = 'id="id_birth_country"'
        PLACE_FIELD_ID = 'id="id_birth_place"'
        NEW_BIRTHDATE = datetime.date(1990, 1, 1)
        if birth_country == "other":
            assertNotContains(response, COUNTRY_FIELD_ID)
            assertNotContains(response, PLACE_FIELD_ID)
            invalid_post_data = {"birthdate": ""}

            def assertForm(form):
                assertFormError(form, "birthdate", "Ce champ est obligatoire.")

            valid_post_data = {"birthdate": NEW_BIRTHDATE}
            birth_place = None
        else:
            assertContains(response, COUNTRY_FIELD_ID)
            assertContains(response, PLACE_FIELD_ID)
            birth_place = (
                Commune.objects.filter(
                    # The birthdate must be >= 1900-01-01, and we’re removing 1 day from start_date.
                    Q(start_date__gt=datetime.date(1900, 1, 1)),
                    # Must be a valid choice for the user current birthdate.
                    Q(start_date__lte=NEW_BIRTHDATE),
                    Q(end_date__gte=NEW_BIRTHDATE) | Q(end_date=None),
                )
                .order_by("?")
                .first()
            )

            bad_birthdate = birth_place.start_date - datetime.timedelta(days=1)
            invalid_post_data = {
                "birthdate": bad_birthdate,
                "birth_place": birth_place.pk,
                "birth_country": Country.FRANCE_ID,
            }

            def assertForm(form):
                assertFormError(
                    form,
                    "birth_place",
                    (
                        f"Le code INSEE {birth_place.code} n'est pas référencé par l'ASP en date "
                        f"du {bad_birthdate:%d/%m/%Y}"
                    ),
                )

            valid_post_data = {
                "birthdate": NEW_BIRTHDATE,
                "birth_place": birth_place.pk,
                "birth_country": Country.FRANCE_ID,
            }

        # Test with invalid data
        response = client.post(fill_job_seeker_infos_url, data=invalid_post_data)
        assert response.status_code == 200
        assertForm(response.context["form_birth_data"])
        # Then with valid data
        response = client.post(fill_job_seeker_infos_url, data=valid_post_data)
        assertRedirects(response, accept_contract_infos_url)
        assert client.session[session_uuid]["job_seeker_info_forms_data"] == {
            "birth_data": valid_post_data,
        }
        # If you come back to the view, it is pre-filled with session data
        response = client.get(fill_job_seeker_infos_url)
        assertContains(response, NEW_BIRTHDATE)

        # Check that birth infos are saved (if modified) after filling contract info step
        self.accept_contract(client, job_application, session_uuid)
        self.job_seeker.jobseeker_profile.refresh_from_db()
        assert self.job_seeker.jobseeker_profile.birthdate == NEW_BIRTHDATE
        assert self.job_seeker.jobseeker_profile.birth_place == birth_place
        if birth_country != "other":
            assert self.job_seeker.jobseeker_profile.birth_country_id == Country.FRANCE_ID

    @pytest.mark.parametrize("in_france", [True, False])
    def test_company_no_birth_country(self, client, in_france):
        job_application = JobApplicationSentByJobSeekerFactory(
            state=JobApplicationState.PROCESSING,
            job_seeker=self.job_seeker,
            to_company=self.company,
        )

        assert self.job_seeker.jobseeker_profile.birthdate
        self.job_seeker.jobseeker_profile.birth_country = None
        self.job_seeker.jobseeker_profile.birth_place = None
        self.job_seeker.jobseeker_profile.save(update_fields=["birth_country", "birth_place"])

        client.force_login(self.company.members.first())
        url_accept = reverse(
            "apply:start-accept",
            kwargs={"job_application_id": job_application.pk},
        )
        response = client.get(url_accept)
        session_uuid = get_session_name(client.session, ACCEPT_SESSION_KIND)
        assert session_uuid is not None
        fill_job_seeker_infos_url = reverse(
            "apply:accept_fill_job_seeker_infos", kwargs={"session_uuid": session_uuid}
        )
        accept_contract_infos_url = reverse("apply:accept_contract_infos", kwargs={"session_uuid": session_uuid})
        assertRedirects(
            response,
            fill_job_seeker_infos_url,
            fetch_redirect_response=False,
        )

        response = client.get(fill_job_seeker_infos_url)
        assertContains(response, "Accepter la candidature de Clara SION")
        assertContains(response, "Valider les informations")

        if in_france:
            new_country = Country.objects.get(pk=Country.FRANCE_ID)
            new_place = (
                Commune.objects.filter(
                    # The birthdate must be >= 1900-01-01, and we’re removing 1 day from start_date.
                    Q(start_date__gt=datetime.date(1900, 1, 1)),
                    # Must be a valid choice for the user current birthdate.
                    Q(start_date__lte=self.job_seeker.jobseeker_profile.birthdate),
                    Q(end_date__gte=self.job_seeker.jobseeker_profile.birthdate) | Q(end_date=None),
                )
                .order_by("?")
                .first()
            )

            invalid_post_data = {
                "birth_place": "",
                "birth_country": Country.FRANCE_ID,
            }

            def assertForm(form):
                assertFormError(
                    form,
                    None,
                    (
                        "La commune de naissance doit être spécifiée si et seulement si le pays de naissance est "
                        "la France."
                    ),
                )

            valid_post_data = {
                "birth_place": new_place.pk,
            }
        else:
            new_country = Country.objects.exclude(pk=Country.FRANCE_ID).order_by("?").first()
            new_place = None

            invalid_post_data = {"birth_country": ""}

            def assertForm(form):
                assertFormError(form, "birth_country", "Le pays de naissance est obligatoire.")

            valid_post_data = {"birth_country": new_country.pk}

        # Test with invalid data
        response = client.post(fill_job_seeker_infos_url, data=invalid_post_data)
        assert response.status_code == 200
        assertForm(response.context["form_birth_data"])
        # Then with valid data
        response = client.post(fill_job_seeker_infos_url, data=valid_post_data)
        assertRedirects(response, accept_contract_infos_url)
        assert client.session[session_uuid]["job_seeker_info_forms_data"] == {
            "birth_data": {
                "birth_place": new_place and new_place.pk,
                "birth_country": new_country.pk,
            }
        }
        # If you come back to the view, it is pre-filled with session data
        response = client.get(fill_job_seeker_infos_url)
        assertContains(response, f'<option value="{new_country.pk}" selected>')

        # Check that birth infos are saved (if modified) after filling contract info step
        self.accept_contract(client, job_application, session_uuid)
        self.job_seeker.jobseeker_profile.refresh_from_db()
        assert self.job_seeker.jobseeker_profile.birth_country_id == new_country.pk
        assert self.job_seeker.jobseeker_profile.birth_place == new_place

    @pytest.mark.parametrize("with_lack_of_nir_reason", [True, False])
    def test_company_no_nir(self, client, with_lack_of_nir_reason):
        client.force_login(self.company.members.first())
        job_application = JobApplicationSentByJobSeekerFactory(
            state=JobApplicationState.PROCESSING,
            job_seeker=self.job_seeker,
            to_company=self.company,
        )
        # Remove job seeker nir, with or without a reason
        self.job_seeker.jobseeker_profile.nir = ""
        if with_lack_of_nir_reason:
            self.job_seeker.jobseeker_profile.lack_of_nir_reason = random.choice(
                [LackOfNIRReason.NO_NIR, LackOfNIRReason.NIR_ASSOCIATED_TO_OTHER]
            )
        else:
            self.job_seeker.jobseeker_profile.lack_of_nir_reason = ""
        self.job_seeker.jobseeker_profile.save(update_fields=["nir", "lack_of_nir_reason"])

        url_accept = reverse(
            "apply:start-accept",
            kwargs={"job_application_id": job_application.pk},
        )
        response = client.get(url_accept)
        session_uuid = get_session_name(client.session, ACCEPT_SESSION_KIND)
        assert session_uuid is not None
        fill_job_seeker_infos_url = reverse(
            "apply:accept_fill_job_seeker_infos", kwargs={"session_uuid": session_uuid}
        )
        accept_contract_infos_url = reverse("apply:accept_contract_infos", kwargs={"session_uuid": session_uuid})
        assertRedirects(
            response,
            fill_job_seeker_infos_url,
            fetch_redirect_response=False,
        )

        response = client.get(fill_job_seeker_infos_url)
        assertContains(response, "Accepter la candidature de Clara SION")
        assertContains(response, "Valider les informations")

        # Trying to skip to contract step must redirect back to job seeker info step if a reason is missing
        response = client.get(accept_contract_infos_url)
        if with_lack_of_nir_reason:
            # With a reason, it's OK since the form is valid
            assert response.status_code == 200
        else:
            assertRedirects(response, fill_job_seeker_infos_url, fetch_redirect_response=False)
            assertMessages(
                response,
                [messages.Message(messages.ERROR, "Certaines informations sont manquantes ou invalides")],
            )

        # Test with invalid data
        response = client.post(fill_job_seeker_infos_url, data={"nir": ""})
        assert response.status_code == 200
        assertFormError(
            response.context["form_personal_data"], "nir", "Le numéro de sécurité sociale n'est pas valide"
        )

        # Fill new nir
        NEW_NIR = "197013625838386"
        response = client.post(
            fill_job_seeker_infos_url,
            data={"nir": NEW_NIR, "lack_of_nir": False, "lack_of_nir_reason": ""},
        )
        assertRedirects(response, accept_contract_infos_url)

        assert client.session[session_uuid]["job_seeker_info_forms_data"] == {
            "personal_data": {
                "nir": NEW_NIR,
                "lack_of_nir": False,
                "lack_of_nir_reason": "",
            },
        }
        # If you come back to the view, it is pre-filled with session data
        response = client.get(fill_job_seeker_infos_url)
        assertContains(response, NEW_NIR)

        # Check that nir is saved after filling contract info step
        self.accept_contract(client, job_application, session_uuid)
        self.job_seeker.jobseeker_profile.refresh_from_db()
        assert self.job_seeker.jobseeker_profile.nir == NEW_NIR

    @pytest.mark.parametrize("with_lack_of_pole_emploi_id_reason", [True, False])
    def test_company_no_pole_emploi_id(self, client, with_lack_of_pole_emploi_id_reason):
        POLE_EMPLOI_FIELD_MARKER = 'id="id_pole_emploi_id"'
        client.force_login(self.company.members.first())
        job_application = JobApplicationSentByJobSeekerFactory(
            state=JobApplicationState.PROCESSING,
            job_seeker=self.job_seeker,
            to_company=self.company,
        )
        # Remove job seeker nir, with or without a reason
        self.job_seeker.jobseeker_profile.pole_emploi_id = ""
        if with_lack_of_pole_emploi_id_reason:
            self.job_seeker.jobseeker_profile.lack_of_pole_emploi_id_reason = random.choice(
                [LackOfPoleEmploiId.REASON_NOT_REGISTERED, LackOfPoleEmploiId.REASON_FORGOTTEN]
            )
        else:
            self.job_seeker.jobseeker_profile.lack_of_pole_emploi_id_reason = ""
        self.job_seeker.jobseeker_profile.save(update_fields=["pole_emploi_id", "lack_of_pole_emploi_id_reason"])

        url_accept = reverse(
            "apply:start-accept",
            kwargs={"job_application_id": job_application.pk},
        )
        response = client.get(url_accept)
        session_uuid = get_session_name(client.session, ACCEPT_SESSION_KIND)
        assert session_uuid is not None
        fill_job_seeker_infos_url = reverse(
            "apply:accept_fill_job_seeker_infos", kwargs={"session_uuid": session_uuid}
        )
        accept_contract_infos_url = reverse("apply:accept_contract_infos", kwargs={"session_uuid": session_uuid})
        assertRedirects(
            response,
            fill_job_seeker_infos_url,
            fetch_redirect_response=False,
        )

        response = client.get(fill_job_seeker_infos_url)

        NEW_POLE_EMPLOI_ID = "1234567A"
        PERSONAL_DATA_SESSION_KEY = "job_seeker_info_forms_data"
        if with_lack_of_pole_emploi_id_reason:
            assertRedirects(response, accept_contract_infos_url)
            assert PERSONAL_DATA_SESSION_KEY not in client.session[session_uuid]
        else:
            assertContains(response, "Accepter la candidature de Clara SION")
            assertContains(response, "Valider les informations")
            # If no reason is present, the pole_emploi_id field is shown
            assertContains(response, POLE_EMPLOI_FIELD_MARKER)
            # Trying to skip to contract step must redirect back to job seeker info step if a reason is missing
            response = client.get(accept_contract_infos_url)
            assertRedirects(response, fill_job_seeker_infos_url, fetch_redirect_response=False)
            assertMessages(
                response,
                [messages.Message(messages.ERROR, "Certaines informations sont manquantes ou invalides")],
            )
            # Test with invalid data
            response = client.post(
                fill_job_seeker_infos_url, data={"pole_emploi_id": "", "lack_of_pole_emploi_id_reason": ""}
            )
            assert response.status_code == 200
            assertFormError(
                response.context["form_personal_data"],
                None,
                "Renseignez soit un identifiant France Travail, soit la raison de son absence.",
            )
            response = client.post(
                fill_job_seeker_infos_url,
                data={"pole_emploi_id": NEW_POLE_EMPLOI_ID, "lack_of_pole_emploi_id_reason": ""},
            )
            assertRedirects(response, accept_contract_infos_url)
            assert client.session[session_uuid][PERSONAL_DATA_SESSION_KEY] == {
                "personal_data": {
                    "pole_emploi_id": NEW_POLE_EMPLOI_ID,
                    "lack_of_pole_emploi_id_reason": "",
                },
            }
            # If you come back to the view, it is pre-filled with session data
            response = client.get(fill_job_seeker_infos_url)
            assertContains(response, NEW_POLE_EMPLOI_ID)

        # Check that pole_emploi_id is saved (if modified) after filling contract info step
        self.accept_contract(client, job_application, session_uuid)
        self.job_seeker.jobseeker_profile.refresh_from_db()
        if not with_lack_of_pole_emploi_id_reason:
            assert self.job_seeker.jobseeker_profile.pole_emploi_id == NEW_POLE_EMPLOI_ID
            assert self.job_seeker.jobseeker_profile.lack_of_pole_emploi_id_reason == ""
        else:
            assert self.job_seeker.jobseeker_profile.pole_emploi_id == ""
            assert self.job_seeker.jobseeker_profile.lack_of_pole_emploi_id_reason != ""


class TestProcessTemplates:
    """
    Test actions available in the details template for the different.
    states of a job application.
    """

    @pytest.fixture(autouse=True)
    def setup_method(self):
        self.job_application = JobApplicationFactory(to_company__subject_to_iae_rules=True)
        self.employer = self.job_application.to_company.members.first()
        self.url_details = reverse("apply:details_for_company", kwargs={"job_application_id": self.job_application.pk})

    def compare_to_snapshot(self, client, snapshot):
        client.force_login(self.employer)
        response = client.get(self.url_details)
        assert (
            pretty_indented(parse_response_to_soup(response, ".c-box--action")).replace(
                str(self.job_application.pk), "[PK of JobApplication]"
            )
            == snapshot
        )

    def test_details_template_for_state_new(self, client, snapshot):
        self.compare_to_snapshot(client, snapshot)

    def test_details_template_for_state_processing(self, client, snapshot):
        self.job_application.state = job_applications_enums.JobApplicationState.PROCESSING
        self.job_application.save()
        self.compare_to_snapshot(client, snapshot)

    def test_details_template_for_state_prior_to_hire(self, client, snapshot):
        self.job_application.state = job_applications_enums.JobApplicationState.PRIOR_TO_HIRE
        self.job_application.save()
        self.compare_to_snapshot(client, snapshot)

    @freeze_time("2025-06-27")
    def test_details_template_for_state_processing_but_suspended_siae(self, client, snapshot):
        Sanctions.objects.create(
            evaluated_siae=EvaluatedSiaeFactory(siae=self.job_application.to_company),
            suspension_dates=InclusiveDateRange(timezone.localdate() - relativedelta(days=1)),
        )
        self.job_application.state = job_applications_enums.JobApplicationState.PROCESSING
        self.job_application.save()
        self.compare_to_snapshot(client, snapshot)

    def test_details_template_for_state_pool(self, client, snapshot):
        self.job_application.state = job_applications_enums.JobApplicationState.POOL
        self.job_application.save()
        self.compare_to_snapshot(client, snapshot)

    def test_details_template_for_state_postponed(self, client, snapshot):
        self.job_application.state = job_applications_enums.JobApplicationState.POSTPONED
        self.job_application.save()
        self.compare_to_snapshot(client, snapshot)

    def test_details_template_for_state_postponed_valid_diagnosis(self, client, snapshot):
        IAEEligibilityDiagnosisFactory(from_prescriber=True, job_seeker=self.job_application.job_seeker)
        self.job_application.state = job_applications_enums.JobApplicationState.POSTPONED
        self.job_application.save()
        self.compare_to_snapshot(client, snapshot)

    def test_details_template_for_state_obsolete(self, client, snapshot):
        self.job_application.state = job_applications_enums.JobApplicationState.OBSOLETE
        self.job_application.processed_at = timezone.now()
        self.job_application.save()
        self.compare_to_snapshot(client, snapshot)

    def test_details_template_for_state_obsolete_valid_diagnosis(self, client, snapshot):
        IAEEligibilityDiagnosisFactory(from_prescriber=True, job_seeker=self.job_application.job_seeker)
        self.job_application.state = job_applications_enums.JobApplicationState.OBSOLETE
        self.job_application.processed_at = timezone.now()
        self.job_application.save()
        self.compare_to_snapshot(client, snapshot)

    def test_details_template_for_state_refused(self, client, snapshot):
        self.job_application.state = job_applications_enums.JobApplicationState.REFUSED
        self.job_application.processed_at = timezone.now()
        self.job_application.save()
        self.compare_to_snapshot(client, snapshot)

    def test_details_template_for_state_refused_valid_diagnosis(self, client, snapshot):
        IAEEligibilityDiagnosisFactory(from_prescriber=True, job_seeker=self.job_application.job_seeker)
        self.job_application.state = job_applications_enums.JobApplicationState.REFUSED
        self.job_application.processed_at = timezone.now()
        self.job_application.save()
        self.compare_to_snapshot(client, snapshot)

    def test_details_template_for_state_canceled(self, client, snapshot):
        self.job_application.state = job_applications_enums.JobApplicationState.CANCELLED
        self.job_application.processed_at = timezone.now()
        self.job_application.save()
        self.compare_to_snapshot(client, snapshot)

    def test_details_template_for_state_canceled_valid_diagnosis(self, client, snapshot):
        IAEEligibilityDiagnosisFactory(from_prescriber=True, job_seeker=self.job_application.job_seeker)
        self.job_application.state = job_applications_enums.JobApplicationState.CANCELLED
        self.job_application.processed_at = timezone.now()
        self.job_application.save()
        self.compare_to_snapshot(client, snapshot)

    def test_details_template_for_state_accepted(self, client, snapshot):
        self.job_application.state = job_applications_enums.JobApplicationState.ACCEPTED
        self.job_application.processed_at = timezone.now()
        self.job_application.save()
        self.compare_to_snapshot(client, snapshot)

    def test_geiq_missing_eligibility(self, client, snapshot):
        self.job_application.to_company.kind = CompanyKind.GEIQ
        self.job_application.to_company.save()
        self.job_application.state = job_applications_enums.JobApplicationState.PROCESSING
        self.job_application.save()
        self.compare_to_snapshot(client, snapshot)


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
    job_application.sender_company = job_application.to_company
    job_application.sender_prescriber_organization = None
    job_application.save(
        update_fields=["sender", "sender_kind", "sender_company", "sender_prescriber_organization", "updated_at"]
    )
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
    accept_url = reverse("apply:start-accept", kwargs={"job_application_id": job_application.pk})
    DIRECT_ACCEPT_BUTTON = (
        f'<a href="{accept_url}" class="btn btn-lg btn-link-white btn-block btn-ico justify-content-center" '
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

    job_application.to_company = CompanyFactory(kind=CompanyKind.AI, with_membership=True)
    client.force_login(job_application.to_company.members.first())
    job_application.eligibility_diagnosis = IAEEligibilityDiagnosisFactory(
        from_prescriber=True, job_seeker=job_application.job_seeker
    )
    job_application.save()
    response = client.get(reverse("apply:details_for_company", kwargs={"job_application_id": job_application.pk}))
    assertContains(response, DIRECT_ACCEPT_BUTTON, html=True)


@freeze_time("2023-12-12 13:37:00", tz_offset=-1)
def test_add_prior_action(client, snapshot):
    job_application = JobApplicationFactory(
        for_snapshot=True,
        to_company__kind=CompanyKind.GEIQ,
        state=job_applications_enums.JobApplicationState.PROCESSING,
        created_at=datetime.datetime(2023, 12, 10, 10, 11, 11, tzinfo=datetime.UTC),
    )
    client.force_login(job_application.to_company.members.first())
    add_prior_action_url = reverse("apply:add_prior_action", kwargs={"job_application_id": job_application.pk})
    today = timezone.localdate()

    def add_prior_action():
        return client.post(
            add_prior_action_url,
            data={
                "action": job_applications_enums.Prequalification.AFPR,
                "start_at": today,
                "end_at": today + relativedelta(days=2),
            },
        )

    response = add_prior_action()
    assert response.status_code == 200
    job_application.refresh_from_db()
    assert job_application.state.is_prior_to_hire
    prior_action = job_application.prior_actions.get()
    assert prior_action.action == job_applications_enums.Prequalification.AFPR
    assert prior_action.dates.lower == today
    assert prior_action.dates.upper == today + relativedelta(days=2)
    soup = parse_response_to_soup(response, selector=f"#transition_logs_{job_application.pk}")
    assert pretty_indented(soup) == snapshot

    # State is accepted
    job_application.state = job_applications_enums.JobApplicationState.ACCEPTED
    job_application.processed_at = timezone.now()
    job_application.save(update_fields=("state", "processed_at", "updated_at"))
    response = add_prior_action()
    assert response.status_code == 403
    assert not job_application.prior_actions.filter(action=job_applications_enums.Prequalification.POE).exists()

    # State is processing but company is not a GEIQ
    job_application = JobApplicationFactory(
        to_company__kind=CompanyKind.AI, state=job_applications_enums.JobApplicationState.PROCESSING
    )
    client.force_login(job_application.to_company.members.first())
    response = add_prior_action()
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
    assert pretty_indented(soup) == snapshot
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

    END_AT_LABEL = "Date de fin prévisionnelle"
    MISSING_FIELD_MESSAGE = "Ce champ est obligatoire"
    ADD_AN_ACTION_SELECTED = '<option value="" selected>Ajouter une action</option>'

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
        add_prior_action_url,
        data={"action": job_applications_enums.Prequalification.AFPR, "start_at": "", "end_at": timezone.localdate()},
    )
    assertContains(response, END_AT_LABEL)
    assert response.context["form"].has_error("start_at")
    assertContains(response, MISSING_FIELD_MESSAGE)
    update_page_with_htmx(simulated_page, "#add_prior_action > form", response)

    # Check again posting with other missing field
    response = client.post(
        add_prior_action_url,
        data={"action": job_applications_enums.Prequalification.AFPR, "start_at": timezone.localdate(), "end_at": ""},
    )
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


def test_prescriber_details_with_older_valid_approval(client, faker):
    # Ensure that the approval details are displayed for a prescriber
    # when the job seeker has a valid approval created on an older approval
    old_job_application = JobApplicationFactory(with_approval=True, hiring_start_at=faker.past_date(start_date="-3m"))
    new_job_application = JobApplicationSentByPrescriberOrganizationFactory(
        job_seeker=old_job_application.job_seeker,
        to_company__subject_to_iae_rules=True,
    )
    po_member = new_job_application.sender_prescriber_organization.members.first()
    client.force_login(po_member)
    response = client.get(
        reverse("apply:details_for_prescriber", kwargs={"job_application_id": new_job_application.pk})
    )
    # Must display approval status template (tested in many other places)
    assertTemplateUsed(response, template_name="utils/templatetags/approval_box.html")


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
    assert response.text == snapshot()


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
    assert response.text == snapshot()


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


def test_htmx_reload_contract_type_and_options_in_wizard(client):
    job_application = JobApplicationFactory(
        to_company__kind=CompanyKind.GEIQ,
        state=job_applications_enums.JobApplicationState.PROCESSING,
        job_seeker__for_snapshot=True,
        job_seeker__with_address=True,
        job_seeker__with_pole_emploi_id=True,
        job_seeker__born_in_france=True,  # To avoid job seeker infos step
    )
    employer = job_application.to_company.members.first()
    client.force_login(employer)
    accept_session = initialize_accept_session(
        client,
        {
            "job_application_id": job_application.pk,
            "reset_url": reverse("apply:details_for_company", kwargs={"job_application_id": job_application.pk}),
        },
    )
    accept_session.save()
    contract_url = reverse("apply:accept_contract_infos", kwargs={"session_uuid": accept_session.name})
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
    response = client.post(contract_url, data=data)
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
    response = client.post(contract_url, data=data)
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
        job_app = JobApplicationFactory(sent_by_company=True)
        company_membership = job_app.sender_company.memberships.get()
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
