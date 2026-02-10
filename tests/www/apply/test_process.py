import datetime
import logging
import random

import factory
import pytest
from bs4 import BeautifulSoup
from dateutil.relativedelta import relativedelta
from django.contrib import messages
from django.template.defaultfilters import urlencode as urlencode_filter
from django.urls import reverse
from django.utils import timezone
from freezegun import freeze_time
from itoutils.django.testing import assertSnapshotQueries
from pytest_django.asserts import (
    assertContains,
    assertMessages,
    assertNotContains,
    assertRedirects,
    assertTemplateNotUsed,
    assertTemplateUsed,
)

from itou.asp.models import AllocationDuration
from itou.companies.enums import CompanyKind, ContractType
from itou.eligibility.enums import AdministrativeCriteriaKind, AuthorKind
from itou.eligibility.models import AdministrativeCriteria, EligibilityDiagnosis
from itou.eligibility.models.common import AbstractSelectedAdministrativeCriteria
from itou.employee_record.enums import Status
from itou.employee_record.models import EmployeeRecordTransition, EmployeeRecordTransitionLog
from itou.job_applications import enums as job_applications_enums
from itou.job_applications.enums import SenderKind
from itou.job_applications.models import JobApplication, JobApplicationWorkflow
from itou.jobs.models import Appellation
from itou.prescribers.enums import PrescriberAuthorizationStatus
from itou.siae_evaluations.models import Sanctions
from itou.users.enums import LackOfNIRReason
from itou.utils.models import InclusiveDateRange
from itou.utils.templatetags.format_filters import format_nir, format_phone
from itou.utils.templatetags.str_filters import mask_unless
from itou.www.apply.views.batch_views import RefuseWizardView
from itou.www.apply.views.process_views import job_application_sender_left_org
from tests.approvals.factories import ApprovalFactory
from tests.cities.factories import create_test_cities
from tests.companies.factories import CompanyFactory
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
from tests.users.factories import EmployerFactory, JobSeekerFactory, LaborInspectorFactory, PrescriberFactory
from tests.utils.htmx.testing import assertSoupEqual, update_page_with_htmx
from tests.utils.testing import assert_previous_step, get_session_name, parse_response_to_soup, pretty_indented
from tests.www.eligibility_views.utils import (
    CERTIFICATION_ERROR_BADGE_HTML,
    CERTIFIED_BADGE_HTML,
    IN_PROGRESS_BADGE_HTML,
)


logger = logging.getLogger(__name__)

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

        assertContains(response, self.IAE_ELIGIBILITY_WITH_CRITERIA_MENTION)
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

        criterion = IAESelectedAdministrativeCriteriaFactory(
            eligibility_diagnosis__from_employer=False,
            eligibility_diagnosis__from_prescriber=True,
        )
        job_application = JobApplicationFactory(
            eligibility_diagnosis=criterion.eligibility_diagnosis,
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
                assertContains(response, self.IAE_ELIGIBILITY_WITH_CRITERIA_MENTION)
                assertContains(response, self.IAE_ELIGIBILITY_NO_CRITERIA_MENTION)

    def test_details_for_company_with_identity_certified_by_api_particulier_after_expiration(self, client):
        company = CompanyFactory(subject_to_iae_rules=True, with_membership=True)
        now = timezone.now()
        today = timezone.localdate(now)
        job_seeker = JobSeekerFactory()
        certification_grace_period = datetime.timedelta(
            days=AbstractSelectedAdministrativeCriteria.CERTIFICATION_GRACE_PERIOD_DAYS
        )
        created_at = now - certification_grace_period - datetime.timedelta(days=1)
        expires_at = today + datetime.timedelta(days=1)
        selected_criteria = IAESelectedAdministrativeCriteriaFactory(
            eligibility_diagnosis__author_siae=company,
            eligibility_diagnosis__job_seeker=job_seeker,
            eligibility_diagnosis__created_at=created_at,
            eligibility_diagnosis__expires_at=expires_at,
            criteria_certified=True,
            certifiable_by_api_particulier=True,
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
                Cette candidature a été archivée par PARDOUX Gilles le 2 septembre 2024 à 11:11.
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
                Cette candidature a été archivée par PARDOUX Gilles le 2 septembre 2024 à 11:11.
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
        assertContains(response, self.IAE_ELIGIBILITY_WITH_CRITERIA_MENTION)
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
        assertContains(response, reverse("companies_views:card", kwargs={"company_pk": job_application.to_company.pk}))

        # Has a button to copy-paste job_seeker public_id
        content = parse_response_to_soup(
            response,
            selector="#copy_public_id",
            replace_in_attr=[("data-it-copy-to-clipboard", str(job_application.job_seeker.public_id), "PUBLIC_ID")],
        )
        assert pretty_indented(content) == snapshot(name="copy_public_id")

    def test_details_for_prescriber_identity_certified_by_api_particulier(self, client):
        certified_crit = IAESelectedAdministrativeCriteriaFactory(
            eligibility_diagnosis__from_employer=False,
            eligibility_diagnosis__from_prescriber=True,
            criteria_certified=True,
            certifiable_by_api_particulier=True,
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
        prescriber = PrescriberFactory(phone="0612345678", email="prescriber@mailinator.com")
        job_application = JobApplicationFactory(
            job_seeker__first_name="Supersecretname",
            job_seeker__last_name="Unknown",
            job_seeker__jobseeker_profile__nir="11111111111111",
            job_seeker__post_code="59140",
            sender=prescriber,
            sender_kind=job_applications_enums.SenderKind.PRESCRIBER,
        )
        client.force_login(prescriber)
        url = reverse("apply:details_for_prescriber", kwargs={"job_application_id": job_application.pk})
        response = client.get(url)
        assertNotContains(response, format_nir(job_application.job_seeker.jobseeker_profile.nir))
        assertContains(response, "<small>Prénom</small><strong>S…</strong>", html=True)
        assertContains(response, "<small>Nom</small><strong>U…</strong>", html=True)
        assertContains(response, "U… S…")
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
        assertContains(response, reverse("companies_views:card", kwargs={"company_pk": job_application.to_company.pk}))

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
                        "La candidature de BOND Jean ne peut pas être refusée car elle est au statut "
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
                        "La candidature de BOND Jean ne peut pas être refusée car elle est au statut "
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
        PREFILLED_TEMPLATE = "eligibility/includes/iae/criteria_filled_from_job_seeker.html"
        """Test eligibility."""
        job_application = JobApplicationSentByPrescriberOrganizationFactory(
            state=job_applications_enums.JobApplicationState.PROCESSING,
            job_seeker=JobSeekerFactory(
                with_address_in_qpv=True,
                last_checked_at=timezone.now() - datetime.timedelta(hours=25),  # Prevent prefilled criteria
            ),
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
        assertTemplateNotUsed(response, PREFILLED_TEMPLATE)

        # Update profile to now have some pre-filled criteria
        job_application.job_seeker.jobseeker_profile.aah_allocation_since = AllocationDuration.FROM_6_TO_11_MONTHS
        job_application.job_seeker.jobseeker_profile.rqth_employee = True
        job_application.job_seeker.jobseeker_profile.save(update_fields=["aah_allocation_since", "rqth_employee"])
        job_application.job_seeker.last_checked_at = timezone.now()
        job_application.job_seeker.save(update_fields=["last_checked_at"])
        response = client.get(url)
        assert response.status_code == 200
        assertTemplateNotUsed(response, "apply/includes/known_criteria.html")
        assertTemplateUsed(response, PREFILLED_TEMPLATE, count=1)
        prefilled_criteria = [c.kind for c in response.context["form"].initial["administrative_criteria"]]
        assert AdministrativeCriteriaKind.AAH in prefilled_criteria
        assert AdministrativeCriteriaKind.TH in prefilled_criteria
        assert response.context["form"].initial["level_1_3"] is True  # AAH criterion
        assert response.context["form"].initial["level_2_10"] is True  # TH / rqth_employee criterion

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
        assertTemplateUsed(response, "eligibility/includes/iae/criteria_filled_from_job_seeker.html", count=1)
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
                    job_seeker_name=job_application.job_seeker.get_inverted_full_name(),
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
                job_seeker_name=mask_unless(job_application.job_seeker.get_inverted_full_name(), predicate=False),
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
        company = CompanyFactory(with_membership=True)

        job_application = JobApplicationFactory(
            job_seeker=job_seeker,
            to_company=company,
            sent_by_company=True,
        )
        employer = job_application.to_company.members.first()
        client.force_login(employer)

        url = reverse("apply:details_for_company", kwargs={"job_application_id": job_application.pk})
        response = client.get(url)

        no_referent_str = f"L’accompagnateur de {job_seeker.get_inverted_full_name()} n’est pas connu de nos services"

        # No referent found
        assertContains(response, no_referent_str)

        membership = FollowUpGroupMembershipFactory(
            follow_up_group__beneficiary=job_seeker,
            member=employer,
            started_at=datetime.date(2024, 1, 1),
        )

        group = membership.follow_up_group

        # Referent is present but not displayed
        response = client.get(url)
        assertNotContains(response, no_referent_str)
        assertNotContains(response, "<h3>Qui d'autre accompagne cet usager ?</h3>", html=True)

        prescriber = PrescriberFactory(
            membership=True,
            for_snapshot=True,
            membership__organization__name="Les Olivades",
            membership__organization__authorized=True,
        )

        membership = FollowUpGroupMembershipFactory(
            follow_up_group=group,
            member=prescriber,
            started_at=datetime.date(2025, 1, 1),
        )

        # Referent is present but and displayed
        response = client.get(url)

        content = parse_response_to_soup(
            response,
            selector=f"#card-{prescriber.public_id}",
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

    def test_display_prescriber_count(self, client, snapshot):
        job_seeker = JobSeekerFactory()

        # text displayed if 2 prescribers are following this job seeker
        TWO_PRESCRIBERS_TEXT = (
            f"Découvrez l'autre intervenant qui a accompagné {job_seeker.last_name.upper()} {job_seeker.first_name}"
        )
        # text displayed if more than 2 prescribers are following this job seeker
        MORE_THAN_2_PRESCRIBERS_TEXT = (
            "Découvrez les 2 autres intervenants qui ont accompagné "
            f"{job_seeker.last_name.upper()} {job_seeker.first_name}"
        )

        prescriber = PrescriberFactory(
            membership=True,
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

        assertNotContains(response, TWO_PRESCRIBERS_TEXT)
        assertNotContains(response, MORE_THAN_2_PRESCRIBERS_TEXT)

        FollowUpGroupMembershipFactory(
            follow_up_group=group,
            member=PrescriberFactory(membership=True),
            started_at=datetime.date(2024, 1, 1),
        )
        response = client.get(url)

        assertContains(response, TWO_PRESCRIBERS_TEXT)
        assertNotContains(response, MORE_THAN_2_PRESCRIBERS_TEXT)

        FollowUpGroupMembershipFactory(
            follow_up_group=group,
            member=PrescriberFactory(membership=True),
            started_at=datetime.date(2024, 1, 1),
        )
        response = client.get(url)

        assertNotContains(response, TWO_PRESCRIBERS_TEXT)
        assertContains(response, MORE_THAN_2_PRESCRIBERS_TEXT)


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
