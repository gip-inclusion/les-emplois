import datetime
import io
import random
import uuid
from unittest import mock

import pytest
from dateutil.relativedelta import relativedelta
from django.contrib import messages
from django.template.defaultfilters import date, time
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

from itou.asp.models import AllocationDuration, Commune, Country, EducationLevel, RSAAllocation
from itou.companies.enums import CompanyKind
from itou.eligibility.enums import AdministrativeCriteriaKind, AuthorKind
from itou.eligibility.models import EligibilityDiagnosis, GEIQEligibilityDiagnosis
from itou.gps.models import FollowUpGroup, FollowUpGroupMembership
from itou.job_applications.enums import JobApplicationState, SenderKind
from itou.job_applications.models import JobApplication
from itou.siae_evaluations.models import Sanctions
from itou.users.enums import ActionKind, LackOfNIRReason, LackOfPoleEmploiId
from itou.users.models import JobSeekerAssignment, JobSeekerProfile, User
from itou.utils.mocks.address_format import mock_get_first_geocoding_data, mock_get_geocoding_data_by_ban_api_resolved
from itou.utils.models import InclusiveDateRange
from itou.utils.templatetags.format_filters import format_nir
from itou.utils.templatetags.str_filters import mask_unless
from itou.www.apply.views import constants as apply_view_constants
from itou.www.apply.views.submit_views import APPLY_SESSION_KIND, initialize_apply_session
from itou.www.job_seekers_views.enums import JobSeekerSessionKinds
from tests.approvals.factories import ApprovalFactory
from tests.cities.factories import create_city_geispolsheim, create_city_partially_in_zrr, create_test_cities
from tests.companies.factories import CompanyFactory, CompanyMembershipFactory, JobDescriptionFactory
from tests.eligibility.factories import GEIQEligibilityDiagnosisFactory, IAEEligibilityDiagnosisFactory
from tests.geo.factories import ZRRFactory
from tests.institutions.factories import InstitutionFactory
from tests.job_applications.factories import JobApplicationFactory
from tests.prescribers.factories import PrescriberMembershipFactory, PrescriberOrganizationFactory
from tests.siae_evaluations.factories import EvaluatedSiaeFactory
from tests.users.factories import (
    EmployerFactory,
    ItouStaffFactory,
    JobSeekerFactory,
    JobSeekerProfileFactory,
    PrescriberFactory,
)
from tests.utils.testing import default_storage_ls_files, get_session_name, parse_response_to_soup, pretty_indented


BACK_BUTTON_ARIA_LABEL = "Retourner à l’étape précédente"
LINK_RESET_MARKUP = (
    '<a href="%s" class="btn btn-link btn-ico ps-lg-0 w-100 w-lg-auto"'
    ' aria-label="Annuler la saisie de ce formulaire">'
)
CONFIRM_RESET_MARKUP = '<a href="%s" class="btn btn-sm btn-danger">Confirmer l\'annulation</a>'
CONFIRM_BUTTON_MARKUP = (
    '<button type="submit" class="btn btn-block btn-primary" aria-label="Confirmer l’embauche de %s">'
    "<span>Confirmer l’embauche</span>"
    "</button>"
)
NEXT_BUTTON_MARKUP = (
    '<button type="submit" class="btn btn-block btn-primary" aria-label="Passer à l’étape suivante">'
    "<span>Suivant</span>"
    "</button>"
)


def fake_session_initialization(client, company, job_seeker, data):
    data.setdefault("reset_url", reverse("dashboard:index"))
    data.setdefault("company_pk", company.pk)
    if job_seeker:
        data["job_seeker_public_id"] = str(job_seeker.public_id)
    # The first argument is supposed to be a request, but we only need it to have a session attribute so client works
    session = initialize_apply_session(client, data)
    session.save()
    return session


def assert_contains_apply_nir_modal(response, job_seeker, with_personal_information=True):
    assertContains(
        response,
        f"""
        <div class="modal-body">
            <p>
                Le numéro {format_nir(job_seeker.jobseeker_profile.nir)} est associé au compte de
                <b>{mask_unless(job_seeker.get_inverted_full_name(), with_personal_information)}</b>.
            </p>
            <p>
                Si cette candidature n'est pas pour
                <b>{mask_unless(job_seeker.get_inverted_full_name(), with_personal_information)}</b>,
                cliquez sur « Ce n'est pas mon candidat » afin de modifier le numéro de sécurité sociale.
            </p>
        </div>
        <div class="modal-footer">
            <button class="btn btn-sm btn-outline-primary" name="cancel" type="submit" value="1">
            Ce n'est pas mon candidat</button>
            <button class="btn btn-sm btn-primary" name="confirm" type="submit" value="1">Continuer</button>
        </div>
        """,
        html=True,
    )


def assert_contains_apply_email_modal(response, job_seeker, with_personal_information=True, nir_to_add=None):
    add_nir_text = (
        f"""
        <p>
            En cliquant sur « Continuer », <b>vous acceptez que le numéro de sécurité sociale
            {format_nir(nir_to_add)} soit associé à ce candidat.</b>
        </p>
        """
        if nir_to_add is not None
        else ""
    )
    assertContains(
        response,
        f"""
        <div class="modal-body">
            <p>
                L'adresse {job_seeker.email} est associée au compte de
                <b>{mask_unless(job_seeker.get_inverted_full_name(), with_personal_information)}</b>.
            </p>
            <p>
                L'identité du candidat est une information clé pour la structure.
                Si cette candidature n'est pas pour
                <b>{mask_unless(job_seeker.get_inverted_full_name(), with_personal_information)}</b>,
                cliquez sur « Ce n'est pas mon candidat » afin d'enregistrer ses informations personnelles.
            </p>
            {add_nir_text}
        </div>
        <div class="modal-footer">
            <button class="btn btn-sm btn-outline-primary" name="cancel" type="submit" value="1">
            Ce n'est pas mon candidat</button>
            <button class="btn btn-sm btn-primary" name="confirm" type="submit" value="1">Continuer</button>
        </div>
        """,
        html=True,
    )


class TestApply:
    def test_company_with_no_members(self, client):
        company = CompanyFactory()
        user = JobSeekerFactory()
        client.force_login(user)
        url = reverse("apply:start", kwargs={"company_pk": company.pk})
        response = client.get(url)
        assert response.status_code == 403
        assertContains(
            response,
            '<p class="mb-0">'
            "Cet employeur n&#x27;est pas inscrit, vous ne pouvez pas déposer de candidatures en ligne."
            "</p>",
            status_code=403,
            count=1,
        )

    def test_anonymous_access(self, client):
        company = CompanyFactory(with_jobs=True, with_membership=True)
        url = reverse("apply:start", kwargs={"company_pk": company.pk})
        response = client.get(url)
        assertRedirects(response, reverse("account_login") + f"?next={url}")

        job_seeker = JobSeekerFactory()
        apply_session = fake_session_initialization(client, company, job_seeker, {})
        for viewname in (
            "apply:pending_authorization_for_sender",
            "job_seekers_views:check_job_seeker_info",
            "apply:step_check_prev_applications",
            "apply:application_jobs",
            "apply:application_iae_eligibility",
            "apply:application_geiq_eligibility",
            "apply:application_resume",
        ):
            url = reverse(viewname, kwargs={"session_uuid": apply_session.name})
            response = client.get(url)
            assertRedirects(response, reverse("account_login") + f"?next={url}")

    def test_we_raise_a_404_on_missing_session(self, client):
        user = JobSeekerFactory()
        client.force_login(user)

        response = client.get(
            reverse(
                "job_seekers_views:search_by_email_for_hire",
                kwargs={"session_uuid": str(uuid.uuid4())},
            )
        )
        assert response.status_code == 404

    def test_we_raise_a_404_on_missing_temporary_session_for_create_job_seeker(self, client, subtests):
        routes = {
            "job_seekers_views:create_job_seeker_step_1_for_sender",
            "job_seekers_views:create_job_seeker_step_2_for_sender",
            "job_seekers_views:create_job_seeker_step_3_for_sender",
            "job_seekers_views:create_job_seeker_step_end_for_sender",
        }
        user = JobSeekerFactory()
        client.force_login(user)
        for route in routes:
            with subtests.test(route=route):
                response = client.get(reverse(route, kwargs={"session_uuid": uuid.uuid4()}))
                assert response.status_code == 404

    def test_404_when_trying_to_apply_for_a_prescriber(self, client):
        company = CompanyFactory(with_jobs=True)
        prescriber = PrescriberFactory()
        client.force_login(prescriber)
        apply_session = fake_session_initialization(client, company, prescriber, {})
        for viewname in (
            "job_seekers_views:check_job_seeker_info",
            "apply:step_check_prev_applications",
            "apply:application_jobs",
            "apply:application_iae_eligibility",
            "apply:application_geiq_eligibility",
            "apply:application_resume",
        ):
            url = reverse(viewname, kwargs={"session_uuid": apply_session.name})
            response = client.get(url)
            assert response.status_code == 404

    def test_access_without_session(self, client):
        job_seeker = JobSeekerFactory()
        client.force_login(job_seeker)
        response = client.post(
            reverse("apply:application_resume", kwargs={"session_uuid": uuid.uuid4()}),
            {"message": "Hire me?"},
        )
        assert JobApplication.objects.exists() is False
        assert response.status_code == 404

    @pytest.mark.parametrize(
        "view_name,post_data",
        [
            ("apply:application_iae_eligibility", {"level_1_1": True}),
            ("apply:application_resume", {"message": "Hire me?"}),
        ],
    )
    def test_blocked_application(self, client, view_name, post_data):
        # It's possible that for example the user loaded this page before spontaneous applications were closed.
        company = CompanyFactory(
            with_jobs=True, with_membership=True, block_job_applications=True, subject_to_iae_rules=True
        )
        job_seeker = JobSeekerFactory()
        client.force_login(PrescriberFactory(membership__organization__authorized=True))
        apply_session = fake_session_initialization(client, company, job_seeker, {"selected_jobs": []})

        response = client.post(reverse(view_name, kwargs={"session_uuid": apply_session.name}), post_data)
        assert JobApplication.objects.exists() is False
        assertRedirects(response, reverse("dashboard:index"))
        assertMessages(
            response,
            [messages.Message(messages.ERROR, apply_view_constants.ERROR_EMPLOYER_BLOCKING_APPLICATIONS)],
        )

    @pytest.mark.parametrize(
        "view_name,post_data",
        [
            ("apply:application_iae_eligibility", {"level_1_1": True}),
            ("apply:application_resume", {"message": "Hire me?"}),
        ],
    )
    def test_spontaneous_application_blocked(self, client, view_name, post_data):
        company = CompanyFactory(
            with_jobs=True, with_membership=True, spontaneous_applications_open_since=None, subject_to_iae_rules=True
        )
        job_seeker = JobSeekerFactory()
        client.force_login(PrescriberFactory(membership__organization__authorized=True))
        apply_session = fake_session_initialization(client, company, job_seeker, {"selected_jobs": []})

        response = client.post(reverse(view_name, kwargs={"session_uuid": apply_session.name}), post_data)
        assert JobApplication.objects.exists() is False
        assertRedirects(response, reverse("apply:application_jobs", kwargs={"session_uuid": apply_session.name}))
        assertMessages(
            response,
            [messages.Message(messages.ERROR, apply_view_constants.ERROR_EMPLOYER_BLOCKING_SPONTANEOUS_APPLICATIONS)],
        )

    @pytest.mark.parametrize(
        "view_name,post_data",
        [
            ("apply:application_iae_eligibility", {"level_1_1": True}),
            ("apply:application_resume", {"message": "Hire me?"}),
        ],
    )
    def test_recruitment_closed_on_position(self, client, view_name, post_data):
        # No block is active, but one of the selected jobs is no longer active.
        company = CompanyFactory(with_jobs=True, with_membership=True, subject_to_iae_rules=True)
        job_seeker = JobSeekerFactory()
        client.force_login(PrescriberFactory(membership__organization__authorized=True))

        jobs = company.job_description_through.all()
        inactive_job = jobs[0]
        inactive_job.is_active = False
        inactive_job.save(update_fields=["is_active", "updated_at"])
        apply_session = fake_session_initialization(
            client, company, job_seeker, {"selected_jobs": [jobs[0].pk, jobs[1].pk]}
        )

        response = client.post(reverse(view_name, kwargs={"session_uuid": apply_session.name}), post_data)
        assert JobApplication.objects.exists() is False
        assertRedirects(response, reverse("apply:application_jobs", kwargs={"session_uuid": apply_session.name}))
        assertMessages(
            response,
            [
                messages.Message(
                    messages.ERROR, apply_view_constants.ERROR_EMPLOYER_BLOCKING_APPLICATIONS_FOR_JOB_DESCRIPTION
                )
            ],
        )

    def test_application_block_ineffective_against_company_member(self, client):
        # A member of the SIAE can bypass the block.
        company = CompanyFactory(with_jobs=True, with_membership=True, block_job_applications=True)
        job_seeker = JobSeekerFactory()
        client.force_login(company.members.first())
        apply_session = fake_session_initialization(client, company, job_seeker, {"selected_jobs": []})

        client.post(
            reverse("apply:application_resume", kwargs={"session_uuid": apply_session.name}),
            {"message": "Hire me?"},
        )
        assert JobApplication.objects.get().message == "Hire me?"

    def test_resume_is_optional(self, client):
        company = CompanyFactory(with_jobs=True, with_membership=True)
        job_seeker = JobSeekerFactory()
        client.force_login(job_seeker)
        apply_session = fake_session_initialization(client, company, job_seeker, {"selected_jobs": []})
        response = client.post(
            reverse("apply:application_resume", kwargs={"session_uuid": apply_session.name}),
            {"message": "Hire me?"},
        )
        job_application = JobApplication.objects.get()
        assertRedirects(response, reverse("apply:application_end", kwargs={"application_pk": job_application.pk}))

    @pytest.mark.parametrize(
        "with_job_description,back_url",
        [
            pytest.param(False, "", id="empty"),
            pytest.param(True, "", id="with_selected_jobs"),
            pytest.param(
                True,
                "/une/url/quelconque",
                id="with_selected_jobs_and_reset_url",
            ),
            pytest.param(False, "/une/url/quelconque", id="with_reset_url"),
        ],
    )
    def test_start_view_initializes_session(self, client, with_job_description, back_url):
        company = CompanyFactory(with_jobs=True, with_membership=True)

        params = {"back_url": back_url}
        expected_session = {
            "reset_url": back_url if back_url else reverse("dashboard:index"),
            "company_pk": company.pk,
        }
        if with_job_description:
            job_description = JobDescriptionFactory(company=company)
            params |= {"job_description_id": job_description.pk}
            expected_session |= {"selected_jobs": [job_description.pk]}

        client.force_login(PrescriberFactory())
        url = reverse("apply:start", kwargs={"company_pk": company.pk})
        client.get(url, params)

        apply_session_name = get_session_name(client.session, APPLY_SESSION_KIND)
        assert client.session[apply_session_name] == expected_session


def test_check_nir_job_seeker_with_lack_of_nir_reason(client):
    """Apply as jobseeker."""

    company = CompanyFactory(romes=("N1101", "N1105"), with_membership=True, with_jobs=True)

    user = JobSeekerFactory(
        jobseeker_profile__birthdate=None,
        jobseeker_profile__nir="",
        jobseeker_profile__lack_of_nir_reason=LackOfNIRReason.NO_NIR,
    )
    client.force_login(user)

    # Entry point.
    # ----------------------------------------------------------------------

    response = client.get(reverse("apply:start", kwargs={"company_pk": company.pk}))

    job_seeker_session_name = get_session_name(client.session, JobSeekerSessionKinds.CHECK_NIR_JOB_SEEKER)
    next_url = reverse("job_seekers_views:check_nir_for_job_seeker", kwargs={"session_uuid": job_seeker_session_name})
    assertRedirects(response, next_url)

    # Step check job seeker NIR.
    # ----------------------------------------------------------------------

    response = client.get(next_url)
    assert response.status_code == 200

    nir = "141068078200557"
    post_data = {"nir": nir, "confirm": 1}

    response = client.post(next_url, data=post_data)
    assert response.status_code == 302

    user.jobseeker_profile.refresh_from_db()
    assert user.jobseeker_profile.nir == nir
    assert user.jobseeker_profile.lack_of_nir_reason == ""


class TestApplyAsJobSeeker:
    def test_apply_as_job_seeker_with_suspension_sanction(self, client):
        company = CompanyFactory(romes=("N1101", "N1105"), with_membership=True, with_jobs=True)
        Sanctions.objects.create(
            evaluated_siae=EvaluatedSiaeFactory(siae=company),
            suspension_dates=InclusiveDateRange(timezone.localdate() - relativedelta(days=1)),
        )

        user = JobSeekerFactory(jobseeker_profile__birthdate=None, jobseeker_profile__nir="")
        client.force_login(user)

        response = client.get(reverse("apply:start", kwargs={"company_pk": company.pk}))
        job_seeker_session_name = get_session_name(client.session, JobSeekerSessionKinds.CHECK_NIR_JOB_SEEKER)
        # The suspension does not prevent access to the process
        assertRedirects(
            response,
            expected_url=reverse(
                "job_seekers_views:check_nir_for_job_seeker", kwargs={"session_uuid": job_seeker_session_name}
            ),
        )

    @pytest.mark.usefixtures("temporary_bucket")
    def test_apply_as_jobseeker(self, client, pdf_file):
        """Apply as jobseeker."""

        company = CompanyFactory(romes=("N1101", "N1105"), with_membership=True, with_jobs=True)
        reset_url_company = reverse("companies_views:card", kwargs={"company_pk": company.pk})

        user = JobSeekerFactory(jobseeker_profile__birthdate=None, jobseeker_profile__nir="", phone="")
        client.force_login(user)

        # Entry point.
        # ----------------------------------------------------------------------

        response = client.get(
            reverse("apply:start", kwargs={"company_pk": company.pk}),
            {"back_url": reset_url_company},
        )

        job_seeker_session_name = get_session_name(client.session, JobSeekerSessionKinds.CHECK_NIR_JOB_SEEKER)
        apply_session_name = get_session_name(client.session, APPLY_SESSION_KIND)
        next_url = reverse(
            "job_seekers_views:check_nir_for_job_seeker", kwargs={"session_uuid": job_seeker_session_name}
        )
        assertRedirects(response, next_url)

        # Step check job seeker NIR.
        # ----------------------------------------------------------------------

        response = client.get(next_url)
        assertContains(response, LINK_RESET_MARKUP % reset_url_company)

        nir = "178122978200508"
        post_data = {"nir": nir, "confirm": 1}

        response = client.post(next_url, data=post_data)

        user = User.objects.get(pk=user.pk)
        assert user.jobseeker_profile.nir == nir

        next_url = reverse(
            "job_seekers_views:check_job_seeker_info",
            kwargs={"session_uuid": apply_session_name},
            query={"job_seeker_public_id": user.public_id},
        )
        assertRedirects(response, next_url)

        # Step check job seeker info.
        # ----------------------------------------------------------------------

        response = client.get(next_url)
        assertContains(response, LINK_RESET_MARKUP % reset_url_company)

        post_data = {"birthdate": "20/12/1978", "phone": "0610203040", "pole_emploi_id": "1234567A"}

        response = client.post(next_url, data=post_data)

        user = User.objects.get(pk=user.pk)
        assert user.jobseeker_profile.birthdate.strftime("%d/%m/%Y") == post_data["birthdate"]
        assert user.phone == post_data["phone"]

        assert user.jobseeker_profile.pole_emploi_id == post_data["pole_emploi_id"]

        next_url = reverse("apply:step_check_prev_applications", kwargs={"session_uuid": apply_session_name})
        assertRedirects(response, next_url, target_status_code=302, fetch_redirect_response=False)

        # Step check previous job applications.
        # ----------------------------------------------------------------------

        response = client.get(next_url)

        next_url = reverse("apply:application_jobs", kwargs={"session_uuid": apply_session_name})
        assertRedirects(response, next_url)

        # Step application's jobs.
        # ----------------------------------------------------------------------

        response = client.get(next_url)
        assertContains(response, LINK_RESET_MARKUP % reset_url_company)

        selected_job = company.job_description_through.first()
        response = client.post(next_url, data={"selected_jobs": [selected_job.pk]})

        assert client.session[apply_session_name] == {
            "selected_jobs": [selected_job.pk],
            "reset_url": reset_url_company,
            "company_pk": company.pk,
        }

        next_url = reverse("apply:application_resume", kwargs={"session_uuid": apply_session_name})
        assertRedirects(response, next_url)

        # Step application's resume (skip eligibility step as the user is not a authorized prescriber)
        # ----------------------------------------------------------------------
        response = client.get(next_url)
        assertContains(response, "Envoyer la candidature")
        assertContains(response, CONFIRM_RESET_MARKUP % reset_url_company)

        with mock.patch(
            "itou.files.models.uuid.uuid4",
            return_value=uuid.UUID("11111111-1111-1111-1111-111111111111"),
        ):
            response = client.post(
                next_url,
                data={
                    "message": "Lorem ipsum dolor sit amet, consectetur adipiscing elit.",
                    "resume": pdf_file,
                },
            )

        job_application = JobApplication.objects.get(sender=user, to_company=company)
        assert job_application.job_seeker == user
        assert job_application.sender_kind == SenderKind.JOB_SEEKER
        assert job_application.sender_company is None
        assert job_application.sender_prescriber_organization is None
        assert job_application.state == JobApplicationState.NEW
        assert job_application.message == "Lorem ipsum dolor sit amet, consectetur adipiscing elit."
        assert job_application.selected_jobs.get() == selected_job
        assert job_application.resume.key == "resume/11111111-1111-1111-1111-111111111111.pdf"
        assert default_storage_ls_files() == [job_application.resume.key]

        assert apply_session_name not in client.session

        next_url = reverse("apply:application_end", kwargs={"application_pk": job_application.pk})
        assertRedirects(response, next_url)

        # Step application's end.
        # ----------------------------------------------------------------------
        response = client.get(next_url)
        # 1 in desktop header
        # + 1 in mobile header
        # + 1 in the page content
        assertContains(response, reverse("dashboard:edit_user_info"), count=3)

        # GPS : a job seeker must not follow himself
        # ----------------------------------------------------------------------
        assert not FollowUpGroup.objects.exists()

        # Check JobSeekerAssignment: no assignment is created when a job seeker applies
        # ----------------------------------------------------------------------
        assert not JobSeekerAssignment.objects.exists()

    def test_apply_as_job_seeker_invalid_nir(self, client):
        """
        Full path is tested above. See test_apply_as_job_seeker.
        """
        company = CompanyFactory(romes=("N1101", "N1105"), with_membership=True, with_jobs=True)

        user = JobSeekerFactory(jobseeker_profile__nir="", jobseeker_profile__with_pole_emploi_id=True)
        client.force_login(user)

        # Entry point.
        # ----------------------------------------------------------------------

        response = client.get(reverse("apply:start", kwargs={"company_pk": company.pk}), follow=True)
        assert response.status_code == 200

        # Follow all redirections until NIR.
        # ----------------------------------------------------------------------
        job_seeker_session_name = get_session_name(client.session, JobSeekerSessionKinds.CHECK_NIR_JOB_SEEKER)
        apply_session_name = get_session_name(client.session, APPLY_SESSION_KIND)
        next_url = reverse(
            "job_seekers_views:check_nir_for_job_seeker", kwargs={"session_uuid": job_seeker_session_name}
        )

        response = client.post(next_url, data={"nir": "123456789KLOIU"})
        assert response.status_code == 200
        assert not response.context["form"].is_valid()
        user.jobseeker_profile.refresh_from_db()
        assert not user.jobseeker_profile.nir
        check_job_seeker_info_url = reverse(
            "job_seekers_views:check_job_seeker_info",
            kwargs={"session_uuid": apply_session_name},
            query={"job_seeker_public_id": user.public_id},
        )
        assertContains(
            response,
            f"""
            <a href="{check_job_seeker_info_url}"
                class="btn btn-link p-0"
                data-matomo-event="true"
                data-matomo-category="nir-temporaire"
                data-matomo-action="etape-suivante"
                data-matomo-option="candidature">
               Cliquez ici pour accéder à l'étape suivante.
            </a>
            """,
            html=True,
        )

    def test_apply_as_job_seeker_from_job_description(self, client):
        company = CompanyFactory(romes=("N1101", "N1105"), with_membership=True, with_jobs=True)
        job_description = company.job_description_through.first()
        reset_url_job_description = reverse(
            "companies_views:job_description_card", kwargs={"job_description_id": job_description.pk}
        )

        job_seeker = JobSeekerFactory(
            jobseeker_profile__nir="141068078200557",
            jobseeker_profile__with_pole_emploi_id=True,
            jobseeker_profile__birthdate=datetime.date(1941, 6, 12),
        )
        client.force_login(job_seeker)

        # Follow the application process.
        response = client.get(
            reverse("apply:start", kwargs={"company_pk": company.pk}),
            {"job_description_id": job_description.pk, "back_url": reset_url_job_description},
        )
        job_seeker_session_name = get_session_name(client.session, JobSeekerSessionKinds.CHECK_NIR_JOB_SEEKER)
        apply_session_name = get_session_name(client.session, APPLY_SESSION_KIND)
        next_url = reverse(
            "job_seekers_views:check_nir_for_job_seeker", kwargs={"session_uuid": job_seeker_session_name}
        )
        assertRedirects(response, next_url, target_status_code=302, fetch_redirect_response=False)
        response = client.get(next_url)

        next_url = reverse(
            "job_seekers_views:check_job_seeker_info",
            kwargs={"session_uuid": apply_session_name},
            query={"job_seeker_public_id": job_seeker.public_id},
        )
        assertRedirects(response, next_url, target_status_code=302, fetch_redirect_response=False)
        response = client.get(next_url)

        next_url = reverse("apply:step_check_prev_applications", kwargs={"session_uuid": apply_session_name})
        assertRedirects(response, next_url, target_status_code=302, fetch_redirect_response=False)
        response = client.get(next_url)

        next_url = reverse("apply:application_jobs", kwargs={"session_uuid": apply_session_name})
        assertRedirects(response, next_url)
        response = client.get(next_url)

        assertContains(response, LINK_RESET_MARKUP % reset_url_job_description)

    @pytest.mark.usefixtures("temporary_bucket")
    def test_apply_as_job_seeker_sent_emails(self, client, pdf_file, mailoutbox):
        company = CompanyFactory(romes=["N1101"], with_membership=True, with_jobs=True)
        employer = company.members.get()
        # Inactive user that should not receive an email
        CompanyMembershipFactory(company=company, user__is_active=False)
        user = JobSeekerFactory()
        client.force_login(user)
        apply_session = fake_session_initialization(client, company, user, {"selected_jobs": []})

        with mock.patch(
            "itou.files.models.uuid.uuid4",
            return_value=uuid.UUID("11111111-1111-1111-1111-111111111111"),
        ):
            response = client.post(
                reverse("apply:application_resume", kwargs={"session_uuid": apply_session.name}),
                data={
                    "message": "Lorem ipsum dolor sit amet, consectetur adipiscing elit.",
                    "resume": pdf_file,
                },
            )
        job_application = JobApplication.objects.get()
        assertRedirects(
            response,
            reverse("apply:application_end", kwargs={"application_pk": job_application.pk}),
        )

        assert JobApplication.objects.filter(sender=user, to_company=company).exists()
        assert len(mailoutbox) == 2
        assert mailoutbox[0].to == [employer.email]
        assert mailoutbox[1].to == [user.email]

    def test_apply_as_job_seeker_resume_not_pdf(self, client):
        company = CompanyFactory(romes=["N1101"], with_membership=True, with_jobs=True)
        user = JobSeekerFactory()
        client.force_login(user)
        apply_session = fake_session_initialization(client, company, user, {"selected_jobs": []})
        with io.BytesIO(b"Plain text") as text_file:
            text_file.name = "cv.txt"
            response = client.post(
                reverse("apply:application_resume", kwargs={"session_uuid": apply_session.name}),
                data={
                    "message": "Lorem ipsum dolor sit amet.",
                    "resume": text_file,
                },
            )
        assertContains(
            response,
            """
            <div id="form_errors">
                <div class="alert alert-danger" role="alert" tabindex="0" data-emplois-give-focus-if-exist>
                    <p class="mb-2">
                        <strong>Votre formulaire contient une erreur</strong>
                    </p>
                    <ul class="mb-0">
                        <li>L&#x27;extension de fichier « txt » n’est pas autorisée.
                        Les extensions autorisées sont : pdf.</li>
                    </ul>
                </div>
            </div>
            """,
            html=True,
            count=1,
        )
        assert JobApplication.objects.exists() is False

    def test_apply_as_job_seeker_resume_not_pdf_disguised_as_pdf(self, client):
        company = CompanyFactory(romes=["N1101"], with_membership=True, with_jobs=True)
        user = JobSeekerFactory()
        client.force_login(user)
        apply_session = fake_session_initialization(client, company, user, {"selected_jobs": []})
        with io.BytesIO(b"Plain text") as text_file:
            text_file.name = "cv.pdf"
            response = client.post(
                reverse("apply:application_resume", kwargs={"session_uuid": apply_session.name}),
                data={
                    "message": "Lorem ipsum dolor sit amet.",
                    "resume": text_file,
                },
            )
        assertContains(
            response,
            """
            <div id="form_errors">
                <div class="alert alert-danger" role="alert" tabindex="0" data-emplois-give-focus-if-exist>
                    <p class="mb-2">
                        <strong>Votre formulaire contient une erreur</strong>
                    </p>
                    <ul class="mb-0">
                        <li>Le fichier doit être un fichier PDF valide.</li>
                    </ul>
                </div>
            </div>
            """,
            html=True,
            count=1,
        )
        assert JobApplication.objects.exists() is False

    def test_apply_as_job_seeker_resume_too_large(self, client):
        company = CompanyFactory(romes=["N1101"], with_membership=True, with_jobs=True)
        user = JobSeekerFactory()
        client.force_login(user)
        apply_session = fake_session_initialization(client, company, user, {"selected_jobs": []})
        with io.BytesIO(b"A" * (5 * 1024 * 1024 + 1)) as text_file:
            text_file.name = "cv.pdf"
            response = client.post(
                reverse("apply:application_resume", kwargs={"session_uuid": apply_session.name}),
                data={
                    "message": "Lorem ipsum dolor sit amet.",
                    "resume": text_file,
                },
            )
        assertContains(
            response,
            """
            <div id="form_errors">
                <div class="alert alert-danger" role="alert" tabindex="0" data-emplois-give-focus-if-exist>
                    <p class="mb-2">
                        <strong>Votre formulaire contient une erreur</strong>
                    </p>
                    <ul class="mb-0">
                        <li>Le fichier doit faire moins de 5,0 Mo.</li>
                    </ul>
                </div>
            </div>
            """,
            html=True,
            count=1,
        )
        assert JobApplication.objects.exists() is False


class TestApplyAsAuthorizedPrescriber:
    @pytest.fixture(autouse=True)
    def setup_method(self, settings, mocker):
        [self.city] = create_test_cities(["67"], num_per_department=1)
        settings.API_GEOPF_BASE_URL = "http://ban-api"
        mocker.patch(
            "itou.utils.apis.geocoding.get_geocoding_data",
            side_effect=mock_get_geocoding_data_by_ban_api_resolved,
        )

    @pytest.mark.usefixtures("temporary_bucket")
    def test_apply_as_prescriber_with_pending_authorization(self, client, pdf_file):
        """Apply as prescriber that has pending authorization."""

        company = CompanyFactory(romes=("N1101", "N1105"), with_membership=True, with_jobs=True)
        from_url = reverse("companies_views:card", kwargs={"company_pk": company.pk})

        prescriber_organization = PrescriberOrganizationFactory(with_pending_authorization=True, with_membership=True)
        user = prescriber_organization.members.first()
        client.force_login(user)

        dummy_job_seeker = JobSeekerFactory.build(
            jobseeker_profile__with_hexa_address=True,
            jobseeker_profile__with_education_level=True,
            with_ban_geoloc_address=True,
        )
        existing_job_seeker = JobSeekerFactory()

        # Entry point.
        # ----------------------------------------------------------------------

        response = client.get(reverse("apply:start", kwargs={"company_pk": company.pk}), {"back_url": from_url})
        apply_session_name = get_session_name(client.session, APPLY_SESSION_KIND)

        next_url = reverse(
            "apply:pending_authorization_for_sender",
            kwargs={"session_uuid": apply_session_name},
        )
        assertRedirects(response, next_url)

        # Step show warning message about pending authorization.
        # ----------------------------------------------------------------------

        response = client.get(next_url)

        params = {
            "tunnel": "sender",
            "company": company.pk,
            "from_url": from_url,
            "apply_session_uuid": apply_session_name,
        }
        next_url = reverse("job_seekers_views:get_or_create_start", query=params)
        assertContains(response, "Statut de prescripteur habilité non vérifié")
        assertContains(
            response,
            f"""
            <a href="{next_url}" class="btn btn-block btn-primary" aria-label="Passer à l’étape suivante">
                <span>Suivant</span>
            </a>
            """,
            html=True,
        )

        response = client.get(next_url)
        job_seeker_session_name = get_session_name(client.session, JobSeekerSessionKinds.GET_OR_CREATE)
        next_url = reverse("job_seekers_views:check_nir_for_sender", kwargs={"session_uuid": job_seeker_session_name})
        assertRedirects(response, next_url)

        # Step determine the job seeker with a NIR. First try: NIR is found
        # ----------------------------------------------------------------------

        response = client.get(next_url)
        assertContains(response, LINK_RESET_MARKUP % from_url)

        response = client.post(next_url, data={"nir": existing_job_seeker.jobseeker_profile.nir, "preview": 1})
        assert_contains_apply_nir_modal(response, existing_job_seeker, with_personal_information=False)

        # Step determine the job seeker with a NIR. Second try: NIR is not found
        # ----------------------------------------------------------------------

        response = client.post(next_url, data={"nir": dummy_job_seeker.jobseeker_profile.nir, "confirm": 1})

        next_url = reverse(
            "job_seekers_views:search_by_email_for_sender",
            kwargs={"session_uuid": job_seeker_session_name},
        )
        expected_job_seeker_session = {
            "config": {
                "tunnel": "sender",
                "from_url": params["from_url"],
            },
            "apply": {
                "company_pk": company.pk,
                "session_uuid": apply_session_name,
            },
            "profile": {
                "nir": dummy_job_seeker.jobseeker_profile.nir,
            },
        }
        assertRedirects(response, next_url)
        assert client.session[job_seeker_session_name] == expected_job_seeker_session

        # Step get job seeker e-mail. First try: email is found
        # ----------------------------------------------------------------------

        response = client.post(
            next_url,
            data={"email": existing_job_seeker.email, "preview": 1},
        )
        assert_contains_apply_email_modal(response, existing_job_seeker, with_personal_information=False)

        # Step get job seeker e-mail. Second try: email is not found
        # ----------------------------------------------------------------------

        response = client.get(next_url)
        assert response.status_code == 200

        response = client.post(next_url, data={"email": dummy_job_seeker.email, "confirm": "1"})

        expected_job_seeker_session |= {
            "user": {
                "email": dummy_job_seeker.email,
            },
        }
        assert client.session[job_seeker_session_name] == expected_job_seeker_session

        next_url = reverse(
            "job_seekers_views:create_job_seeker_step_1_for_sender",
            kwargs={"session_uuid": job_seeker_session_name},
        )
        assertRedirects(response, next_url)

        # Step create a job seeker.
        # ----------------------------------------------------------------------

        response = client.get(next_url)
        # The NIR is prefilled
        assertContains(response, dummy_job_seeker.jobseeker_profile.nir)
        # The back_url is correct
        assertContains(
            response,
            reverse(
                "job_seekers_views:search_by_email_for_sender",
                kwargs={"session_uuid": job_seeker_session_name},
            ),
        )

        geispolsheim = create_city_geispolsheim()
        birthdate = dummy_job_seeker.jobseeker_profile.birthdate

        post_data = {
            "title": dummy_job_seeker.title,
            "first_name": dummy_job_seeker.first_name,
            "last_name": dummy_job_seeker.last_name,
            "birthdate": birthdate,
            "lack_of_nir": False,
            "lack_of_nir_reason": "",
            "birth_place": Commune.objects.by_insee_code_and_period(geispolsheim.code_insee, birthdate).id,
            "birth_country": Country.FRANCE_ID,
        }
        response = client.post(next_url, data=post_data)
        expected_job_seeker_session["profile"]["birthdate"] = post_data.pop("birthdate")
        expected_job_seeker_session["profile"]["lack_of_nir_reason"] = post_data.pop("lack_of_nir_reason")
        expected_job_seeker_session["profile"]["birth_place"] = post_data.pop("birth_place")
        expected_job_seeker_session["profile"]["birth_country"] = post_data.pop("birth_country")
        expected_job_seeker_session["user"] |= post_data
        assert client.session[job_seeker_session_name] == expected_job_seeker_session

        next_url = reverse(
            "job_seekers_views:create_job_seeker_step_2_for_sender",
            kwargs={"session_uuid": job_seeker_session_name},
        )
        assertRedirects(response, next_url)

        response = client.get(next_url)
        assert response.status_code == 200

        post_data = {
            "ban_api_resolved_address": dummy_job_seeker.geocoding_address,
            "address_line_1": dummy_job_seeker.address_line_1,
            "post_code": self.city.post_codes[0],
            "insee_code": self.city.code_insee,
            "city": self.city.name,
            "phone": dummy_job_seeker.phone,
            "fill_mode": "ban_api",
        }

        response = client.post(next_url, data=post_data)

        expected_job_seeker_session["user"] |= post_data | {"address_line_2": "", "address_for_autocomplete": None}
        assert client.session[job_seeker_session_name] == expected_job_seeker_session

        next_url = reverse(
            "job_seekers_views:create_job_seeker_step_3_for_sender",
            kwargs={"session_uuid": job_seeker_session_name},
        )
        assertRedirects(response, next_url)

        response = client.get(next_url)
        assert response.status_code == 200

        post_data = {
            "education_level": dummy_job_seeker.jobseeker_profile.education_level,
            "ase_exit": False,
        }
        response = client.post(next_url, data=post_data)
        expected_job_seeker_session["profile"] |= post_data | {
            "pole_emploi_id": "",
            "lack_of_pole_emploi_id_reason": LackOfPoleEmploiId.REASON_NOT_REGISTERED.value,
            "resourceless": False,
            "rqth_employee": False,
            "oeth_employee": False,
            "pole_emploi": False,
            "pole_emploi_id_forgotten": "",
            "pole_emploi_since": "",
            "unemployed": False,
            "unemployed_since": "",
            "rsa_allocation": False,
            "has_rsa_allocation": RSAAllocation.NO.value,
            "rsa_allocation_since": "",
            "ass_allocation": False,
            "ass_allocation_since": "",
            "aah_allocation": False,
            "aah_allocation_since": "",
            "ase_exit": False,
            "isolated_parent": False,
            "housing_issue": False,
            "refugee": False,
            "detention_exit_or_ppsmj": False,
            "low_level_in_french": False,
            "mobility_issue": False,
        }
        assert client.session[job_seeker_session_name] == expected_job_seeker_session

        next_url = reverse(
            "job_seekers_views:create_job_seeker_step_end_for_sender",
            kwargs={"session_uuid": job_seeker_session_name},
        )
        assertRedirects(response, next_url)

        response = client.get(next_url)
        assertContains(response, "Créer le compte candidat")

        response = client.post(next_url)

        assert job_seeker_session_name not in client.session
        new_job_seeker = User.objects.get(email=dummy_job_seeker.email)
        assert new_job_seeker.jobseeker_profile.created_by_prescriber_organization == prescriber_organization

        # Check JobSeekerAssignment
        # ----------------------------------------------------------------------
        assignment = JobSeekerAssignment.objects.filter(
            job_seeker=new_job_seeker,
            professional=user,
            prescriber_organization=prescriber_organization,
            last_action_kind=ActionKind.CREATE,
        ).get()
        assignment.delete()  # delete it to check it is created again when applying

        next_url = reverse(
            "apply:application_jobs",
            kwargs={"session_uuid": apply_session_name},
            query={"job_seeker_public_id": new_job_seeker.public_id},
        )
        assertRedirects(response, next_url)

        # Step application's jobs.
        # ----------------------------------------------------------------------

        response = client.get(next_url)
        assert response.status_code == 200

        selected_job = company.job_description_through.first()
        response = client.post(next_url, data={"selected_jobs": [selected_job.pk]})

        assert client.session[apply_session_name] == {
            "selected_jobs": [selected_job.pk],
            "reset_url": from_url,
            "company_pk": company.pk,
            "job_seeker_public_id": str(new_job_seeker.public_id),
        }

        next_url = reverse("apply:application_resume", kwargs={"session_uuid": apply_session_name})
        assertRedirects(response, next_url)

        # Step application's resume (skip eligibility step as the user in not an authorized prescriber)
        # ----------------------------------------------------------------------
        response = client.get(next_url)
        assertContains(response, "Postuler")

        with mock.patch(
            "itou.files.models.uuid.uuid4",
            return_value=uuid.UUID("11111111-1111-1111-1111-111111111111"),
        ):
            response = client.post(
                next_url,
                data={
                    "message": "Lorem ipsum dolor sit amet, consectetur adipiscing elit.",
                    "resume": pdf_file,
                },
            )

        job_application = JobApplication.objects.get(sender=user, to_company=company)
        assert job_application.job_seeker == new_job_seeker
        assert job_application.sender_kind == SenderKind.PRESCRIBER
        assert job_application.sender_company is None
        assert job_application.sender_prescriber_organization == prescriber_organization
        assert job_application.state == JobApplicationState.NEW
        assert job_application.message == "Lorem ipsum dolor sit amet, consectetur adipiscing elit."
        assert job_application.selected_jobs.get() == selected_job
        assert job_application.resume.key == "resume/11111111-1111-1111-1111-111111111111.pdf"
        assert default_storage_ls_files() == [job_application.resume.key]

        assert apply_session_name not in client.session

        next_url = reverse("apply:application_end", kwargs={"application_pk": job_application.pk})
        assertRedirects(response, next_url)

        # Step application's end.
        # ----------------------------------------------------------------------
        response = client.get(next_url)
        assert response.status_code == 200

        # Check JobSeekerAssignment again
        # ----------------------------------------------------------------------
        assert JobSeekerAssignment.objects.filter(
            job_seeker=new_job_seeker,
            professional=user,
            prescriber_organization=prescriber_organization,
            last_action_kind=ActionKind.APPLY,
        ).exists()

    @freeze_time()
    @pytest.mark.usefixtures("temporary_bucket")
    def test_apply_as_authorized_prescriber(self, client, pdf_file, snapshot):
        company = CompanyFactory(romes=("N1101", "N1105"), for_snapshot=True, with_membership=True, with_jobs=True)
        reset_url_company = reverse("companies_views:card", kwargs={"company_pk": company.pk})

        # test ZRR / QPV template loading
        city = create_city_partially_in_zrr()  # Avoid auto-filled criteria
        ZRRFactory(insee_code=city.code_insee)

        prescriber_organization = PrescriberOrganizationFactory(authorized=True, with_membership=True)
        user = prescriber_organization.members.first()
        client.force_login(user)

        dummy_job_seeker = JobSeekerFactory.build(
            jobseeker_profile__with_hexa_address=True,
            jobseeker_profile__with_education_level_above_cap_bep=True,  # Avoid auto-filled criteria
            jobseeker_profile__birthdate=timezone.localdate() - relativedelta(years=30),  # Avoid auto-filled criteria
            with_ban_geoloc_address=True,
            first_name="John",
            last_name="DOE",
        )
        existing_job_seeker = JobSeekerFactory()

        # Entry point.
        # ----------------------------------------------------------------------

        response = client.get(
            reverse("apply:start", kwargs={"company_pk": company.pk}),
            {"back_url": reset_url_company},
        )
        apply_session_name = get_session_name(client.session, APPLY_SESSION_KIND)

        params = {
            "tunnel": "sender",
            "apply_session_uuid": apply_session_name,
            "company": company.pk,
            "from_url": reset_url_company,
        }
        next_url = reverse("job_seekers_views:get_or_create_start", query=params)
        assertRedirects(response, next_url, target_status_code=302, fetch_redirect_response=False)

        response = client.get(next_url)
        job_seeker_session_name = get_session_name(client.session, JobSeekerSessionKinds.GET_OR_CREATE)
        next_url = reverse("job_seekers_views:check_nir_for_sender", kwargs={"session_uuid": job_seeker_session_name})
        assertRedirects(response, next_url)

        # Step determine the job seeker with a NIR. First try: NIR is found
        # ----------------------------------------------------------------------

        response = client.get(next_url)
        assertContains(response, LINK_RESET_MARKUP % reset_url_company)

        response = client.post(next_url, data={"nir": existing_job_seeker.jobseeker_profile.nir, "preview": 1})
        assert_contains_apply_nir_modal(response, existing_job_seeker)

        # Step determine the job seeker with a NIR. Second try: NIR is not found
        # ----------------------------------------------------------------------

        response = client.post(next_url, data={"nir": dummy_job_seeker.jobseeker_profile.nir, "confirm": 1})

        next_url = reverse(
            "job_seekers_views:search_by_email_for_sender",
            kwargs={"session_uuid": job_seeker_session_name},
        )
        assertRedirects(response, next_url)

        # Step get job seeker e-mail. First try: email is found
        # ----------------------------------------------------------------------

        response = client.post(
            next_url,
            data={"email": existing_job_seeker.email, "preview": 1},
        )
        assert_contains_apply_email_modal(response, existing_job_seeker)

        # Step get job seeker e-mail. Second try: email is found, attached to a
        # user without NIR
        # ----------------------------------------------------------------------
        existing_job_seeker_without_nir = JobSeekerFactory(jobseeker_profile__nir="")

        response = client.post(
            next_url,
            data={"email": existing_job_seeker_without_nir.email, "preview": 1},
        )
        assert_contains_apply_email_modal(
            response, existing_job_seeker_without_nir, nir_to_add=dummy_job_seeker.jobseeker_profile.nir
        )

        # Step get job seeker e-mail. Third try: email is not found
        # ----------------------------------------------------------------------

        response = client.post(next_url, data={"email": dummy_job_seeker.email, "confirm": "1"})

        expected_job_seeker_session = {
            "config": {
                "tunnel": "sender",
                "from_url": reset_url_company,
            },
            "apply": {
                "company_pk": company.pk,
                "session_uuid": apply_session_name,
            },
            "user": {
                "email": dummy_job_seeker.email,
            },
            "profile": {
                "nir": dummy_job_seeker.jobseeker_profile.nir,
            },
        }
        assert client.session[job_seeker_session_name] == expected_job_seeker_session

        next_url = reverse(
            "job_seekers_views:create_job_seeker_step_1_for_sender",
            kwargs={"session_uuid": job_seeker_session_name},
        )
        assertRedirects(response, next_url)

        # Step create a job seeker.
        # ----------------------------------------------------------------------

        response = client.get(next_url)
        # Check that the back url is correct
        assertContains(
            response,
            reverse(
                "job_seekers_views:search_by_email_for_sender",
                kwargs={"session_uuid": job_seeker_session_name},
            ),
        )
        assertContains(response, CONFIRM_RESET_MARKUP % reset_url_company)

        geispolsheim = create_city_geispolsheim()
        birthdate = dummy_job_seeker.jobseeker_profile.birthdate

        post_data = {
            "title": dummy_job_seeker.title,
            "first_name": dummy_job_seeker.first_name,
            "last_name": dummy_job_seeker.last_name,
            "birthdate": birthdate,
            "nir": dummy_job_seeker.jobseeker_profile.nir,
            "lack_of_nir": False,
            "lack_of_nir_reason": "",
            "birth_place": Commune.objects.by_insee_code_and_period(geispolsheim.code_insee, birthdate).id,
            "birth_country": Country.FRANCE_ID,
        }
        response = client.post(next_url, data=post_data)
        expected_job_seeker_session["profile"]["birthdate"] = post_data.pop("birthdate")
        expected_job_seeker_session["profile"]["lack_of_nir_reason"] = post_data.pop("lack_of_nir_reason")
        expected_job_seeker_session["profile"]["birth_place"] = post_data.pop("birth_place")
        expected_job_seeker_session["profile"]["birth_country"] = post_data.pop("birth_country")
        post_data.pop("nir")
        expected_job_seeker_session["user"] |= post_data
        assert client.session[job_seeker_session_name] == expected_job_seeker_session

        next_url = reverse(
            "job_seekers_views:create_job_seeker_step_2_for_sender",
            kwargs={"session_uuid": job_seeker_session_name},
        )
        assertRedirects(response, next_url)

        response = client.get(next_url)
        assertContains(response, CONFIRM_RESET_MARKUP % reset_url_company)

        post_data = {
            "ban_api_resolved_address": dummy_job_seeker.geocoding_address,
            "address_line_1": dummy_job_seeker.address_line_1,
            "post_code": self.city.post_codes[0],
            "insee_code": self.city.code_insee,
            "city": self.city.name,
            "phone": dummy_job_seeker.phone,
            "fill_mode": "ban_api",
        }

        response = client.post(next_url, data=post_data)
        expected_job_seeker_session["user"] |= post_data | {"address_for_autocomplete": None, "address_line_2": ""}
        assert client.session[job_seeker_session_name] == expected_job_seeker_session

        next_url = reverse(
            "job_seekers_views:create_job_seeker_step_3_for_sender",
            kwargs={"session_uuid": job_seeker_session_name},
        )
        assertRedirects(response, next_url)

        response = client.get(next_url)
        assertContains(response, CONFIRM_RESET_MARKUP % reset_url_company)

        post_data = {
            "education_level": dummy_job_seeker.jobseeker_profile.education_level,
        }
        response = client.post(next_url, data=post_data)
        expected_job_seeker_session["profile"] |= post_data | {
            "pole_emploi_id": "",
            "lack_of_pole_emploi_id_reason": LackOfPoleEmploiId.REASON_NOT_REGISTERED.value,
            "resourceless": False,
            "rqth_employee": False,
            "oeth_employee": False,
            "pole_emploi": False,
            "pole_emploi_id_forgotten": "",
            "pole_emploi_since": "",
            "unemployed": False,
            "unemployed_since": "",
            "rsa_allocation": False,
            "has_rsa_allocation": RSAAllocation.NO.value,
            "rsa_allocation_since": "",
            "ass_allocation": False,
            "ass_allocation_since": "",
            "aah_allocation": False,
            "aah_allocation_since": "",
            "ase_exit": False,
            "isolated_parent": False,
            "housing_issue": False,
            "refugee": False,
            "detention_exit_or_ppsmj": False,
            "low_level_in_french": False,
            "mobility_issue": False,
        }
        assert client.session[job_seeker_session_name] == expected_job_seeker_session

        next_url = reverse(
            "job_seekers_views:create_job_seeker_step_end_for_sender",
            kwargs={"session_uuid": job_seeker_session_name},
        )
        assertRedirects(response, next_url)

        response = client.get(next_url)
        assertContains(response, "Créer le compte candidat")

        response = client.post(next_url)

        assert job_seeker_session_name not in client.session
        new_job_seeker = User.objects.get(email=dummy_job_seeker.email)

        assert new_job_seeker.jobseeker_profile.created_by_prescriber_organization == prescriber_organization

        next_url = reverse(
            "apply:application_jobs",
            kwargs={"session_uuid": apply_session_name},
            query={"job_seeker_public_id": new_job_seeker.public_id},
        )
        assertRedirects(response, next_url)

        # Check GPS group
        # ----------------------------------------------------------------------
        membership = FollowUpGroupMembership.objects.filter(
            follow_up_group__beneficiary=new_job_seeker, member=user
        ).get()
        membership.delete()  # delete it to check it is created again when applying

        # Check JobSeekerAssignment
        # ----------------------------------------------------------------------
        assignment = JobSeekerAssignment.objects.filter(
            job_seeker=new_job_seeker,
            professional=user,
            prescriber_organization=prescriber_organization,
            last_action_kind=ActionKind.CREATE,
        ).get()
        assignment.delete()  # delete it to check it is created again when applying

        # Step application's jobs.
        # ----------------------------------------------------------------------

        response = client.get(next_url)
        assertContains(response, LINK_RESET_MARKUP % reset_url_company)

        selected_job = company.job_description_through.first()
        response = client.post(next_url, data={"selected_jobs": [selected_job.pk]})

        assert client.session[apply_session_name] == {
            "selected_jobs": [selected_job.pk],
            "reset_url": reset_url_company,
            "company_pk": company.pk,
            "job_seeker_public_id": str(new_job_seeker.public_id),
        }

        next_url = reverse("apply:application_iae_eligibility", kwargs={"session_uuid": apply_session_name})
        assertRedirects(response, next_url)

        # Step application's eligibility.
        # ----------------------------------------------------------------------

        # Simulate address in qpv. If the address is in qpv, the criteria_filled_from_job_seeker template
        # should be used: QPV will be automatically checked.
        with mock.patch(
            "itou.common_apps.address.models.QPV.in_qpv",
            return_value=True,
        ):
            response = client.get(next_url)
            assertContains(response, CONFIRM_RESET_MARKUP % reset_url_company)
            assert not EligibilityDiagnosis.objects.has_considered_valid(new_job_seeker, for_siae=company)
            assertTemplateUsed(response, "eligibility/includes/iae/criteria_filled_from_job_seeker.html", count=1)

        expected_snapshot = pretty_indented(
            parse_response_to_soup(
                response,
                "#main",
                replace_in_attr=[
                    ("href", apply_session_name, "[SessionUUID]"),
                    ("href", str(new_job_seeker.public_id), "[Public ID of JobSeeker]"),
                    ("href", f"/company/{company.pk}", "company/[PK of Company]"),
                ],
            )
        )
        now = timezone.localtime()
        expected_snapshot = expected_snapshot.replace(f"{date(now)} à {time(now)}", "Day Month Year à HH:MM")
        assert expected_snapshot == snapshot(name="eligibility_step")

        response = client.post(next_url, {"level_1_1": True})
        diag = EligibilityDiagnosis.objects.last_considered_valid(job_seeker=new_job_seeker, for_siae=company)
        assert diag.is_valid is True
        assert diag.expires_at == timezone.localdate() + relativedelta(months=6)

        # Check JobSeekerAssignment
        # ----------------------------------------------------------------------
        assignment = JobSeekerAssignment.objects.filter(
            job_seeker=new_job_seeker,
            professional=user,
            prescriber_organization=prescriber_organization,
            last_action_kind=ActionKind.IAE_ELIGIBILITY,
        ).get()
        assignment.delete()  # delete it to check it is created again when applying

        next_url = reverse("apply:application_resume", kwargs={"session_uuid": apply_session_name})
        assertRedirects(response, next_url)

        # Step application's resume.
        # ----------------------------------------------------------------------
        response = client.get(next_url)
        assertContains(response, "Postuler")
        assertContains(response, CONFIRM_RESET_MARKUP % reset_url_company)

        with mock.patch(
            "itou.files.models.uuid.uuid4",
            return_value=uuid.UUID("11111111-1111-1111-1111-111111111111"),
        ):
            response = client.post(
                next_url,
                data={
                    "message": "Lorem ipsum dolor sit amet, consectetur adipiscing elit.",
                    "resume": pdf_file,
                },
            )

        job_application = JobApplication.objects.get(sender=user, to_company=company)
        assert job_application.job_seeker == new_job_seeker
        assert job_application.sender_kind == SenderKind.PRESCRIBER
        assert job_application.sender_company is None
        assert job_application.sender_prescriber_organization == prescriber_organization
        assert job_application.state == JobApplicationState.NEW
        assert job_application.message == "Lorem ipsum dolor sit amet, consectetur adipiscing elit."
        assert job_application.selected_jobs.get() == selected_job
        assert job_application.resume.key == "resume/11111111-1111-1111-1111-111111111111.pdf"
        assert default_storage_ls_files() == [job_application.resume.key]

        assert apply_session_name not in client.session

        next_url = reverse("apply:application_end", kwargs={"application_pk": job_application.pk})
        assertRedirects(response, next_url)

        # Step application's end.
        # ----------------------------------------------------------------------
        response = client.get(next_url)
        assert response.status_code == 200

        # Check GPS group again
        # ----------------------------------------------------------------------
        assert FollowUpGroupMembership.objects.filter(
            follow_up_group__beneficiary=new_job_seeker, member=user
        ).exists()

        # Check JobSeekerAssignment again
        # ----------------------------------------------------------------------
        assert JobSeekerAssignment.objects.filter(
            job_seeker=new_job_seeker,
            professional=user,
            prescriber_organization=prescriber_organization,
            last_action_kind=ActionKind.APPLY,
        ).exists()

    def test_cannot_create_job_seeker_with_pole_emploi_email(self, client):
        company = CompanyMembershipFactory().company

        prescriber_organization = PrescriberOrganizationFactory(authorized=True, with_membership=True)
        user = prescriber_organization.members.first()
        client.force_login(user)

        # Init session
        start_url = reverse("apply:start", kwargs={"company_pk": company.pk})
        client.get(start_url, follow=True)
        job_seeker_session_name = get_session_name(client.session, JobSeekerSessionKinds.GET_OR_CREATE)
        nir_url = reverse("job_seekers_views:check_nir_for_sender", kwargs={"session_uuid": job_seeker_session_name})
        response = client.get(nir_url)
        assert response.status_code == 200

        response = client.post(nir_url, data={"nir": JobSeekerProfileFactory.build().nir, "confirm": 1})

        email_url = reverse(
            "job_seekers_views:search_by_email_for_sender",
            kwargs={"session_uuid": job_seeker_session_name},
        )
        assertRedirects(response, email_url)

        # Step get job seeker e-mail.
        # ----------------------------------------------------------------------

        response = client.get(email_url)
        assert response.status_code == 200

        response = client.post(email_url, data={"email": "toto@pole-emploi.fr", "confirm": "1"})
        assertContains(response, "Vous ne pouvez pas utiliser un e-mail Pôle emploi pour un candidat.")

        response = client.post(email_url, data={"email": "titi@francetravail.fr", "confirm": "1"})
        assertContains(response, "Vous ne pouvez pas utiliser un e-mail France Travail pour un candidat.")

    def test_apply_step_eligibility_does_not_show_employer_diagnosis(self, client):
        company = CompanyFactory(name="Les petits pains", with_membership=True, subject_to_iae_rules=True)
        job_seeker = JobSeekerFactory()
        IAEEligibilityDiagnosisFactory(from_employer=True, author_siae=company, job_seeker=job_seeker)
        prescriber_organization = PrescriberOrganizationFactory(authorized=True, with_membership=True)
        prescriber = prescriber_organization.members.get()
        client.force_login(prescriber)
        apply_session = fake_session_initialization(client, company, job_seeker, {"selected_jobs": []})
        response = client.get(
            reverse("apply:application_iae_eligibility", kwargs={"session_uuid": apply_session.name})
        )
        assert response.status_code == 200
        assert response.context["eligibility_diagnosis"] is None

    def test_apply_with_invalid_nir(self, client):
        company = CompanyFactory(romes=["N1101"], with_membership=True, with_jobs=True)
        prescriber_organization = PrescriberOrganizationFactory(authorized=True, with_membership=True)
        user = prescriber_organization.members.get()
        reset_url_company = reverse("companies_views:card", kwargs={"company_pk": company.pk})
        client.force_login(user)

        response = client.get(
            reverse("apply:start", kwargs={"company_pk": company.pk}), {"back_url": reset_url_company}
        )
        apply_session_name = get_session_name(client.session, APPLY_SESSION_KIND)

        params = {
            "tunnel": "sender",
            "apply_session_uuid": apply_session_name,
            "company": company.pk,
            "from_url": reverse("companies_views:card", kwargs={"company_pk": company.pk}),
        }
        next_url = reverse("job_seekers_views:get_or_create_start", query=params)
        assertRedirects(response, next_url, target_status_code=302, fetch_redirect_response=False)

        response = client.get(next_url)
        job_seeker_session_name = get_session_name(client.session, JobSeekerSessionKinds.GET_OR_CREATE)
        assertRedirects(
            response,
            reverse("job_seekers_views:check_nir_for_sender", kwargs={"session_uuid": job_seeker_session_name}),
        )

        response = client.post(response.url, {"nir": "invalid"})

        search_by_email_url = reverse(
            "job_seekers_views:search_by_email_for_sender",
            kwargs={"session_uuid": job_seeker_session_name},
        )
        assertContains(
            response,
            f"""
            <a href="{search_by_email_url}"
                class="btn btn-link p-0"
                data-matomo-event="true"
                data-matomo-category="nir-temporaire"
                data-matomo-action="etape-suivante"
                data-matomo-option="candidature">
               Cliquez ici pour accéder à l'étape suivante.
            </a>
            """,
            html=True,
        )


class TestApplyAsPrescriber:
    @pytest.fixture(autouse=True)
    def setup_method(self, settings, mocker):
        [self.city] = create_test_cities(["67"], num_per_department=1)
        settings.API_GEOPF_BASE_URL = "http://ban-api"
        mocker.patch(
            "itou.utils.apis.geocoding.get_geocoding_data",
            side_effect=mock_get_geocoding_data_by_ban_api_resolved,
        )

    def test_apply_as_prescriber_with_suspension_sanction(self, client):
        company = CompanyFactory(romes=("N1101", "N1105"), with_membership=True, with_jobs=True)
        Sanctions.objects.create(
            evaluated_siae=EvaluatedSiaeFactory(siae=company),
            suspension_dates=InclusiveDateRange(timezone.localdate() - relativedelta(days=1)),
        )

        user = PrescriberFactory()
        client.force_login(user)

        response = client.get(reverse("apply:start", kwargs={"company_pk": company.pk}), follow=True)
        job_seeker_session_name = get_session_name(client.session, JobSeekerSessionKinds.GET_OR_CREATE)

        # The suspension does not prevent the access to the process
        assertRedirects(
            response,
            expected_url=reverse(
                "job_seekers_views:check_nir_for_sender", kwargs={"session_uuid": job_seeker_session_name}
            ),
        )

    @pytest.mark.usefixtures("temporary_bucket")
    def test_apply_as_prescriber(self, client, pdf_file):
        company = CompanyFactory(romes=("N1101", "N1105"), with_membership=True, with_jobs=True)
        reset_url_company = reverse("companies_views:card", kwargs={"company_pk": company.pk})
        with_nia = random.choice([True, False])  # NIA = numéro d'immatriculation d'attente

        user = PrescriberFactory()
        client.force_login(user)

        dummy_job_seeker = JobSeekerFactory.build(
            jobseeker_profile__with_hexa_address=True,
            jobseeker_profile__with_education_level=True,
            with_ban_geoloc_address=True,
            jobseeker_profile__nir="714612105555578" if with_nia else "178122978200508",
            jobseeker_profile__birthdate=datetime.date(1978, 12, 20),
            title="M",
        )
        existing_job_seeker = JobSeekerFactory()

        # Entry point.
        # ----------------------------------------------------------------------

        response = client.get(
            reverse("apply:start", kwargs={"company_pk": company.pk}), {"back_url": reset_url_company}
        )
        apply_session_name = get_session_name(client.session, APPLY_SESSION_KIND)
        params = {
            "tunnel": "sender",
            "apply_session_uuid": apply_session_name,
            "company": company.pk,
            "from_url": reset_url_company,
        }
        next_url = reverse("job_seekers_views:get_or_create_start", query=params)
        assertRedirects(response, next_url, target_status_code=302, fetch_redirect_response=False)

        response = client.get(next_url)
        job_seeker_session_name = get_session_name(client.session, JobSeekerSessionKinds.GET_OR_CREATE)
        next_url = reverse("job_seekers_views:check_nir_for_sender", kwargs={"session_uuid": job_seeker_session_name})
        assertRedirects(response, next_url)

        # Step determine the job seeker with a NIR. First try: NIR is found
        # ----------------------------------------------------------------------

        response = client.get(next_url)
        assertContains(response, LINK_RESET_MARKUP % reset_url_company)

        response = client.post(next_url, data={"nir": existing_job_seeker.jobseeker_profile.nir, "preview": 1})
        assert_contains_apply_nir_modal(response, existing_job_seeker, with_personal_information=False)

        # Step determine the job seeker with a NIR. Second try: NIR is not found
        # ----------------------------------------------------------------------

        response = client.post(next_url, data={"nir": dummy_job_seeker.jobseeker_profile.nir, "confirm": 1})

        next_url = reverse(
            "job_seekers_views:search_by_email_for_sender",
            kwargs={"session_uuid": job_seeker_session_name},
        )
        assertRedirects(response, next_url)

        expected_job_seeker_session = {
            "config": {
                "tunnel": "sender",
                "from_url": reset_url_company,
            },
            "apply": {
                "company_pk": company.pk,
                "session_uuid": apply_session_name,
            },
            "profile": {"nir": dummy_job_seeker.jobseeker_profile.nir},
        }

        assert client.session[job_seeker_session_name] == expected_job_seeker_session

        # Step get job seeker e-mail. First try: email is found
        # ----------------------------------------------------------------------

        response = client.get(next_url)
        assertContains(response, CONFIRM_RESET_MARKUP % reset_url_company)

        response = client.post(
            next_url,
            data={"email": existing_job_seeker.email, "preview": 1},
        )
        assert_contains_apply_email_modal(response, existing_job_seeker, with_personal_information=False)

        # Step get job seeker e-mail. Second try: email is not found
        # ----------------------------------------------------------------------

        response = client.post(next_url, data={"email": dummy_job_seeker.email, "confirm": "1"})

        expected_job_seeker_session |= {
            "user": {
                "email": dummy_job_seeker.email,
            },
        }
        assert client.session[job_seeker_session_name] == expected_job_seeker_session

        next_url = reverse(
            "job_seekers_views:create_job_seeker_step_1_for_sender",
            kwargs={"session_uuid": job_seeker_session_name},
        )
        assertRedirects(response, next_url)

        # Step create a job seeker.
        # ----------------------------------------------------------------------

        response = client.get(next_url)
        # The NIR is prefilled
        assertContains(response, dummy_job_seeker.jobseeker_profile.nir)
        # Check that the back url is correct
        assertContains(
            response,
            reverse(
                "job_seekers_views:search_by_email_for_sender",
                kwargs={"session_uuid": job_seeker_session_name},
            ),
        )
        assertContains(response, CONFIRM_RESET_MARKUP % reset_url_company)

        geispolsheim = create_city_geispolsheim()
        birthdate = dummy_job_seeker.jobseeker_profile.birthdate

        # Let's check for consistency between the NIR, the birthdate and the title.
        # ----------------------------------------------------------------------

        post_data = {
            "title": "MME",  # inconsistent title
            "first_name": dummy_job_seeker.first_name,
            "last_name": dummy_job_seeker.last_name,
            "birthdate": birthdate,
            "lack_of_nir": False,
            "lack_of_nir_reason": "",
        }
        response = client.post(next_url, data=post_data)
        assertContains(response, JobSeekerProfile.ERROR_JOBSEEKER_INCONSISTENT_NIR_TITLE % "")

        post_data = {
            "title": "M",
            "first_name": dummy_job_seeker.first_name,
            "last_name": dummy_job_seeker.last_name,
            "birthdate": datetime.date(1978, 11, 20),  # inconsistent birthdate
            "lack_of_nir": False,
            "lack_of_nir_reason": "",
        }
        response = client.post(next_url, data=post_data)
        assertion = assertNotContains if with_nia else assertContains
        assertion(response, JobSeekerProfile.ERROR_JOBSEEKER_INCONSISTENT_NIR_BIRTHDATE % "")

        # Resume to valid data and proceed with "normal" flow.
        # ----------------------------------------------------------------------

        post_data = {
            "title": dummy_job_seeker.title,
            "first_name": dummy_job_seeker.first_name,
            "last_name": dummy_job_seeker.last_name,
            "birthdate": birthdate,
            "lack_of_nir": False,
            "lack_of_nir_reason": "",
            "birth_place": Commune.objects.by_insee_code_and_period(geispolsheim.code_insee, birthdate).id,
            "birth_country": Country.FRANCE_ID,
        }
        response = client.post(next_url, data=post_data)
        expected_job_seeker_session["profile"]["birthdate"] = post_data.pop("birthdate")
        expected_job_seeker_session["profile"]["lack_of_nir_reason"] = post_data.pop("lack_of_nir_reason")
        expected_job_seeker_session["profile"]["birth_place"] = post_data.pop("birth_place")
        expected_job_seeker_session["profile"]["birth_country"] = post_data.pop("birth_country")
        expected_job_seeker_session["user"] |= post_data
        assert client.session[job_seeker_session_name] == expected_job_seeker_session

        next_url = reverse(
            "job_seekers_views:create_job_seeker_step_2_for_sender",
            kwargs={"session_uuid": job_seeker_session_name},
        )
        assertRedirects(response, next_url)

        response = client.get(next_url)
        assertContains(response, CONFIRM_RESET_MARKUP % reset_url_company)

        post_data = {
            "ban_api_resolved_address": dummy_job_seeker.geocoding_address,
            "address_line_1": dummy_job_seeker.address_line_1,
            "post_code": self.city.post_codes[0],
            "insee_code": self.city.code_insee,
            "city": self.city.name,
            "phone": dummy_job_seeker.phone,
            "fill_mode": "ban_api",
        }
        response = client.post(next_url, data=post_data)
        expected_job_seeker_session["user"] |= post_data | {"address_line_2": "", "address_for_autocomplete": None}
        assert client.session[job_seeker_session_name] == expected_job_seeker_session

        next_url = reverse(
            "job_seekers_views:create_job_seeker_step_3_for_sender",
            kwargs={"session_uuid": job_seeker_session_name},
        )
        assertRedirects(response, next_url)

        response = client.get(next_url)
        assertContains(response, CONFIRM_RESET_MARKUP % reset_url_company)

        post_data = {
            "education_level": dummy_job_seeker.jobseeker_profile.education_level,
        }
        response = client.post(next_url, data=post_data)
        expected_job_seeker_session["profile"] |= post_data | {
            "pole_emploi_id": "",
            "lack_of_pole_emploi_id_reason": LackOfPoleEmploiId.REASON_NOT_REGISTERED.value,
            "resourceless": False,
            "rqth_employee": False,
            "oeth_employee": False,
            "pole_emploi": False,
            "pole_emploi_id_forgotten": "",
            "pole_emploi_since": "",
            "unemployed": False,
            "unemployed_since": "",
            "rsa_allocation": False,
            "has_rsa_allocation": RSAAllocation.NO.value,
            "rsa_allocation_since": "",
            "ass_allocation": False,
            "ass_allocation_since": "",
            "aah_allocation": False,
            "aah_allocation_since": "",
            "ase_exit": False,
            "isolated_parent": False,
            "housing_issue": False,
            "refugee": False,
            "detention_exit_or_ppsmj": False,
            "low_level_in_french": False,
            "mobility_issue": False,
        }
        assert client.session[job_seeker_session_name] == expected_job_seeker_session

        next_url = reverse(
            "job_seekers_views:create_job_seeker_step_end_for_sender",
            kwargs={"session_uuid": job_seeker_session_name},
        )
        assertRedirects(response, next_url)

        response = client.get(next_url)
        assertContains(response, "Créer le compte candidat")

        # Let's add another job seeker with exactly the same NIR, in the middle of the process.
        # ----------------------------------------------------------------------
        other_job_seeker = JobSeekerFactory(jobseeker_profile__nir=dummy_job_seeker.jobseeker_profile.nir)

        response = client.post(next_url)
        assertMessages(
            response,
            [
                messages.Message(
                    messages.ERROR, "Ce numéro de sécurité sociale est déjà associé à un autre utilisateur."
                )
            ],
        )
        assertRedirects(response, reverse("dashboard:index"))

        # Remove that extra job seeker and proceed with "normal" flow
        # ----------------------------------------------------------------------
        other_job_seeker.delete()

        response = client.post(next_url)

        assert job_seeker_session_name not in client.session
        new_job_seeker = User.objects.get(email=dummy_job_seeker.email)

        assert new_job_seeker.jobseeker_profile.created_by_prescriber_organization is None

        next_url = reverse(
            "apply:application_jobs",
            kwargs={"session_uuid": apply_session_name},
            query={"job_seeker_public_id": new_job_seeker.public_id},
        )
        assertRedirects(response, next_url)

        # Check GPS group
        # ----------------------------------------------------------------------
        membership = FollowUpGroupMembership.objects.filter(
            follow_up_group__beneficiary=new_job_seeker, member=user
        ).get()
        membership.delete()  # delete it to check it is created again when applying

        # Check JobSeekerAssignment
        # ----------------------------------------------------------------------
        assignment = JobSeekerAssignment.objects.filter(
            job_seeker=new_job_seeker,
            professional=user,
            prescriber_organization=None,
            last_action_kind=ActionKind.CREATE,
        ).get()
        assignment.delete()  # delete it to check it is created again when applying

        # Step application's jobs.
        # ----------------------------------------------------------------------

        response = client.get(next_url)
        assertContains(response, LINK_RESET_MARKUP % reset_url_company)

        selected_job = company.job_description_through.first()
        response = client.post(next_url, data={"selected_jobs": [selected_job.pk]})

        assert client.session[apply_session_name] == {
            "company_pk": company.pk,
            "selected_jobs": [selected_job.pk],
            "reset_url": reset_url_company,
            "job_seeker_public_id": str(new_job_seeker.public_id),
        }

        next_url = reverse("apply:application_resume", kwargs={"session_uuid": apply_session_name})
        assertRedirects(response, next_url)

        # Step application's resume (skip eligibility step as the user is not an authorized prescriber)
        # ----------------------------------------------------------------------
        response = client.get(next_url)
        assertContains(response, "Postuler")
        assertContains(response, CONFIRM_RESET_MARKUP % reset_url_company)

        with mock.patch(
            "itou.files.models.uuid.uuid4",
            return_value=uuid.UUID("11111111-1111-1111-1111-111111111111"),
        ):
            response = client.post(
                next_url,
                data={
                    "message": "Lorem ipsum dolor sit amet, consectetur adipiscing elit.",
                    "resume": pdf_file,
                },
            )

        job_application = JobApplication.objects.get(sender=user, to_company=company)
        assert job_application.job_seeker == new_job_seeker
        assert job_application.sender_kind == SenderKind.PRESCRIBER
        assert job_application.sender_company is None
        assert job_application.sender_prescriber_organization is None
        assert job_application.state == JobApplicationState.NEW
        assert job_application.message == "Lorem ipsum dolor sit amet, consectetur adipiscing elit."
        assert job_application.selected_jobs.get() == selected_job
        assert job_application.resume.key == "resume/11111111-1111-1111-1111-111111111111.pdf"
        assert default_storage_ls_files() == [job_application.resume.key]

        assert apply_session_name not in client.session

        next_url = reverse("apply:application_end", kwargs={"application_pk": job_application.pk})
        assertRedirects(response, next_url)

        # Step application's end.
        # ----------------------------------------------------------------------
        response = client.get(next_url)
        assert response.status_code == 200

        # Check GPS group again
        # ----------------------------------------------------------------------
        assert FollowUpGroupMembership.objects.filter(
            follow_up_group__beneficiary=new_job_seeker, member=user
        ).exists()

        # Check JobSeekerAssignment again
        # ----------------------------------------------------------------------
        assert JobSeekerAssignment.objects.filter(
            job_seeker=new_job_seeker,
            professional=user,
            prescriber_organization=None,
            last_action_kind=ActionKind.APPLY,
        ).exists()

    def test_check_info_as_prescriber_for_job_seeker_with_incomplete_info(self, client):
        company = CompanyFactory(with_membership=True, with_jobs=True, romes=("N1101", "N1105"))
        user = PrescriberMembershipFactory(organization__authorized=True).user
        client.force_login(user)
        dummy_job_seeker = JobSeekerFactory(
            jobseeker_profile__with_hexa_address=True,
            jobseeker_profile__with_education_level=True,
            with_ban_geoloc_address=True,
            jobseeker_profile__nir="178122978200508",
            jobseeker_profile__birthdate=None,
            title="M",
        )
        apply_session = fake_session_initialization(client, company, dummy_job_seeker, {})

        next_url = reverse("job_seekers_views:check_job_seeker_info", kwargs={"session_uuid": apply_session.name})

        post_data = {
            "phone": "",
            "birthdate": datetime.date(1978, 11, 20),  # inconsistent birthdate
            "pole_emploi_id": "3454471C",
        }
        response = client.post(next_url, data=post_data)
        assertContains(
            response,
            (
                "Une erreur a été détectée. "
                "La date de naissance renseignée ne correspond pas au numéro de sécurité "
                "sociale 178122978200508 enregistré."
            ),
        )

    @pytest.mark.parametrize("handled_by_proxy", [True, False])
    def test_check_info_as_unauthorized_prescriber_for_job_seeker_with_birthdate(self, client, handled_by_proxy):
        company = CompanyFactory(with_membership=True)
        prescriber = PrescriberFactory()
        client.force_login(prescriber)
        job_seeker = JobSeekerFactory(
            jobseeker_profile__birthdate=datetime.date(1990, 12, 1),
            jobseeker_profile__pole_emploi_id="",  # Make sure the view is accessible
            created_by=prescriber,
            last_login=timezone.now() if not handled_by_proxy else None,
        )
        apply_session = fake_session_initialization(client, company, job_seeker, {})

        next_url = reverse("job_seekers_views:check_job_seeker_info", kwargs={"session_uuid": apply_session.name})
        response = client.get(next_url)
        if handled_by_proxy:
            assertNotContains(response, job_seeker.jobseeker_profile.birthdate.isoformat())
            assert "birthdate" not in response.context["form"].fields
        else:
            assertRedirects(
                response,
                reverse("apply:step_check_prev_applications", kwargs={"session_uuid": apply_session.name}),
                fetch_redirect_response=False,
            )

        post_data = {
            "phone": "",
            "birthdate": datetime.date(1978, 11, 20),  # inconsistent birthdate with nir
            "pole_emploi_id": "3454471C",
        }
        response = client.post(next_url, data=post_data)
        job_seeker.jobseeker_profile.refresh_from_db()
        # birthdate is unchanged
        assert job_seeker.jobseeker_profile.birthdate == datetime.date(1990, 12, 1)
        if handled_by_proxy:
            # but pole_emploi_id is updated
            assert job_seeker.jobseeker_profile.pole_emploi_id == "3454471C"
            assertRedirects(
                response,
                reverse("apply:step_check_prev_applications", kwargs={"session_uuid": apply_session.name}),
                fetch_redirect_response=False,
            )
        else:
            # and pole_emploi_id is unchanged
            assert job_seeker.jobseeker_profile.pole_emploi_id == ""
            assertContains(
                response,
                "Votre utilisateur n'est pas autorisé à modifier les informations de ce candidat",
                status_code=403,
                html=True,
            )

    @pytest.mark.parametrize("handled_by_proxy", [True, False])
    def test_check_info_as_unauthorized_prescriber_for_job_seeker_with_pole_emploi_id(self, client, handled_by_proxy):
        company = CompanyFactory(with_membership=True)
        prescriber = PrescriberFactory()
        client.force_login(prescriber)
        job_seeker = JobSeekerFactory(
            jobseeker_profile__birthdate=None,  # Make sure the view is accessible
            jobseeker_profile__pole_emploi_id="1234567C",
            jobseeker_profile__nir="",  # Make sure birthdate change is not blocked by NIR consistency check
            created_by=prescriber,
            last_login=timezone.now() if not handled_by_proxy else None,
        )
        apply_session = fake_session_initialization(client, company, job_seeker, {})

        next_url = reverse("job_seekers_views:check_job_seeker_info", kwargs={"session_uuid": apply_session.name})
        response = client.get(next_url)
        if handled_by_proxy:
            assertNotContains(response, job_seeker.jobseeker_profile.pole_emploi_id)
            assert "pole_emploi_id" not in response.context["form"].fields
        else:
            assertRedirects(
                response,
                reverse("apply:step_check_prev_applications", kwargs={"session_uuid": apply_session.name}),
                fetch_redirect_response=False,
            )

        post_data = {
            "birthdate": datetime.date(1978, 11, 20),
            "pole_emploi_id": "3454471C",
        }
        response = client.post(next_url, data=post_data)
        job_seeker.jobseeker_profile.refresh_from_db()
        # pole_emploi_id is unchanged
        assert job_seeker.jobseeker_profile.pole_emploi_id == "1234567C"
        if handled_by_proxy:
            # birthdate is updated
            assert job_seeker.jobseeker_profile.birthdate == datetime.date(1978, 11, 20)
            assertRedirects(
                response,
                reverse("apply:step_check_prev_applications", kwargs={"session_uuid": apply_session.name}),
                fetch_redirect_response=False,
            )
        else:
            # birthdate is unchanged
            assert job_seeker.jobseeker_profile.birthdate is None
            assertContains(
                response,
                "Votre utilisateur n'est pas autorisé à modifier les informations de ce candidat",
                status_code=403,
                html=True,
            )

    @pytest.mark.parametrize("is_authorized", [True, False])
    @pytest.mark.parametrize("with_phone", [True, False])
    def test_check_info_as_prescriber_for_job_seeker_with_phone(self, client, is_authorized, with_phone):
        company = CompanyFactory(with_membership=True)
        prescriber = PrescriberMembershipFactory(organization__authorized=is_authorized).user
        client.force_login(prescriber)
        job_seeker = JobSeekerFactory(
            phone="0987654321" if with_phone else "",
            jobseeker_profile__birthdate=datetime.date(1990, 12, 1),
            jobseeker_profile__pole_emploi_id="",  # Make sure the view is accessible
        )
        apply_session = fake_session_initialization(client, company, job_seeker, {})

        next_url = reverse("job_seekers_views:check_job_seeker_info", kwargs={"session_uuid": apply_session.name})
        response = client.get(next_url)
        if is_authorized:
            if with_phone:
                assertNotContains(response, job_seeker.phone)
                assert "phone" not in response.context["form"].fields
            else:
                assert "phone" in response.context["form"].fields
        else:
            assertRedirects(
                response,
                reverse("apply:step_check_prev_applications", kwargs={"session_uuid": apply_session.name}),
                fetch_redirect_response=False,
            )

        post_data = {
            "phone": "0123456789",
            "lack_of_pole_emploi_id_reason": LackOfPoleEmploiId.REASON_NOT_REGISTERED.value,
        }
        response = client.post(next_url, data=post_data)
        job_seeker.refresh_from_db()
        if is_authorized:
            assert (
                job_seeker.jobseeker_profile.lack_of_pole_emploi_id_reason
                == LackOfPoleEmploiId.REASON_NOT_REGISTERED.value
            )
            # Prescribers can provide a phone only if the job seeker has none
            if with_phone:
                # phone is unchanged
                assert job_seeker.phone == "0987654321"
            else:
                # phone is updated
                assert job_seeker.phone == "0123456789"
            assertRedirects(
                response,
                reverse("apply:step_check_prev_applications", kwargs={"session_uuid": apply_session.name}),
                fetch_redirect_response=False,
            )
        else:
            # lack_of_pole_emploi_id_reason is unchanged
            assert job_seeker.jobseeker_profile.lack_of_pole_emploi_id_reason == ""
            assertContains(
                response,
                "Votre utilisateur n'est pas autorisé à modifier les informations de ce candidat",
                status_code=403,
                html=True,
            )


class TestApplyAsPrescriberNirExceptions:
    """
    The following normal use cases are tested in tests above:
        - job seeker creation,
        - job seeker found with a unique NIR.
    But, for historical reasons, our database is not perfectly clean.
    Some job seekers share the same NIR as the historical unique key was the e-mail address.
    Or the NIR is not found because their account was created before
    we added this possibility.
    """

    def create_test_data(self):
        company = CompanyFactory(romes=("N1101", "N1105"), with_membership=True, with_jobs=True)
        # Only authorized prescribers can add a NIR.
        # See User.can_add_nir
        prescriber_organization = PrescriberOrganizationFactory(authorized=True, with_membership=True)
        user = prescriber_organization.members.first()
        return company, user

    def test_one_account_no_nir(self, client):
        """
        No account with this NIR is found.
        A search by email is proposed.
        An account is found for this email.
        This NIR account is empty.
        An update is expected.
        """
        job_seeker = JobSeekerFactory(jobseeker_profile__nir="", jobseeker_profile__with_pole_emploi_id=True)
        # Create an approval to bypass the eligibility diagnosis step.
        ApprovalFactory(user=job_seeker)
        company, user = self.create_test_data()
        reset_url_company = reverse("companies_views:card", kwargs={"company_pk": company.pk})
        client.force_login(user)

        # Follow all redirections…
        response = client.get(
            reverse("apply:start", kwargs={"company_pk": company.pk}), {"back_url": reset_url_company}, follow=True
        )

        # …until a job seeker has to be determined.
        assert response.status_code == 200
        last_url = response.redirect_chain[-1][0]
        job_seeker_session_name = get_session_name(client.session, JobSeekerSessionKinds.GET_OR_CREATE)
        apply_session_name = get_session_name(client.session, APPLY_SESSION_KIND)
        assert last_url == reverse(
            "job_seekers_views:check_nir_for_sender", kwargs={"session_uuid": job_seeker_session_name}
        )

        # Enter a non-existing NIR.
        # ----------------------------------------------------------------------
        nir = "141068078200557"
        post_data = {"nir": nir, "confirm": 1}
        response = client.post(last_url, data=post_data)
        next_url = reverse(
            "job_seekers_views:search_by_email_for_sender",
            kwargs={"session_uuid": job_seeker_session_name},
        )
        expected_job_seeker_session = {
            "config": {
                "tunnel": "sender",
                "from_url": reverse("companies_views:card", kwargs={"company_pk": company.pk}),
            },
            "apply": {
                "company_pk": company.pk,
                "session_uuid": apply_session_name,
            },
            "profile": {
                "nir": nir,
            },
        }

        assertRedirects(response, next_url)
        assert client.session[job_seeker_session_name] == expected_job_seeker_session
        assertRedirects(response, next_url)

        # Create a job seeker with this NIR right after the check. Sorry.
        # ----------------------------------------------------------------------
        other_job_seeker = JobSeekerFactory(jobseeker_profile__nir=nir)

        # Enter an existing email.
        # ----------------------------------------------------------------------
        post_data = {"email": job_seeker.email, "confirm": "1"}
        response = client.post(next_url, data=post_data)
        assert response.status_code == 200
        assert (
            "Le<b> numéro de sécurité sociale</b> renseigné (141068078200557) "
            "est déjà utilisé par un autre candidat sur la Plateforme." in str(list(response.context["messages"])[0])
        )

        # Remove that extra job seeker and proceed with "normal" flow
        # ----------------------------------------------------------------------
        other_job_seeker.delete()

        response = client.post(next_url, data=post_data)
        assertRedirects(
            response,
            reverse(
                "job_seekers_views:check_job_seeker_info",
                kwargs={"session_uuid": apply_session_name},
                query={"job_seeker_public_id": job_seeker.public_id},
            ),
            target_status_code=302,
        )

        response = client.post(next_url, data=post_data, follow=True)
        assert response.status_code == 200
        assert 0 == len(list(response.context["messages"]))

        # Make sure the job seeker NIR is now filled in.
        # ----------------------------------------------------------------------
        job_seeker.jobseeker_profile.refresh_from_db()
        assert job_seeker.jobseeker_profile.nir == nir

    def test_one_account_lack_of_nir_reason(self, client):
        job_seeker = JobSeekerFactory(
            jobseeker_profile__nir="",
            jobseeker_profile__lack_of_nir_reason=LackOfNIRReason.NO_NIR,
            jobseeker_profile__with_pole_emploi_id=True,
        )
        # Create an approval to bypass the eligibility diagnosis step.
        ApprovalFactory(user=job_seeker)
        siae, user = self.create_test_data()
        reset_url_company = reverse("companies_views:card", kwargs={"company_pk": siae.pk})
        client.force_login(user)

        # Follow all redirections…
        response = client.get(
            reverse("apply:start", kwargs={"company_pk": siae.pk}), {"back_url": reset_url_company}, follow=True
        )
        job_seeker_session_name = get_session_name(client.session, JobSeekerSessionKinds.GET_OR_CREATE)
        apply_session_name = get_session_name(client.session, APPLY_SESSION_KIND)

        # …until a job seeker has to be determined.
        assert response.status_code == 200
        last_url = response.redirect_chain[-1][0]
        assert last_url == reverse(
            "job_seekers_views:check_nir_for_sender", kwargs={"session_uuid": job_seeker_session_name}
        )

        # Enter a non-existing NIR.
        # ----------------------------------------------------------------------
        nir = "141068078200557"
        post_data = {"nir": nir, "confirm": 1}
        response = client.post(last_url, data=post_data)
        next_url = reverse(
            "job_seekers_views:search_by_email_for_sender",
            kwargs={"session_uuid": job_seeker_session_name},
        )
        expected_job_seeker_session = {
            "config": {
                "tunnel": "sender",
                "from_url": reverse("companies_views:card", kwargs={"company_pk": siae.pk}),
            },
            "apply": {
                "company_pk": siae.pk,
                "session_uuid": apply_session_name,
            },
            "profile": {
                "nir": nir,
            },
        }
        assertRedirects(response, next_url)
        assert client.session[job_seeker_session_name] == expected_job_seeker_session
        assertRedirects(response, next_url)

        # Enter an existing email.
        # ----------------------------------------------------------------------
        post_data = {"email": job_seeker.email, "confirm": "1"}
        response = client.post(next_url, data=post_data)
        assertRedirects(
            response,
            reverse(
                "job_seekers_views:check_job_seeker_info",
                kwargs={"session_uuid": apply_session_name},
                query={"job_seeker_public_id": job_seeker.public_id},
            ),
            target_status_code=302,
        )

        response = client.post(next_url, data=post_data, follow=True)
        assert response.status_code == 200
        assert 0 == len(list(response.context["messages"]))

        # Make sure the job seeker NIR is now filled in.
        # ----------------------------------------------------------------------
        job_seeker.jobseeker_profile.refresh_from_db()
        assert job_seeker.jobseeker_profile.nir == nir
        assert job_seeker.jobseeker_profile.lack_of_nir_reason == ""


class TestApplyAsCompany:
    @pytest.fixture(autouse=True)
    def setup_method(self, settings, mocker):
        [self.city] = create_test_cities(["67"], num_per_department=1)
        settings.API_GEOPF_BASE_URL = "http://ban-api"
        mocker.patch(
            "itou.utils.apis.geocoding.get_geocoding_data",
            side_effect=mock_get_geocoding_data_by_ban_api_resolved,
        )

    def test_perms_for_company(self, client):
        """A company can postulate only for itself."""
        company_1 = CompanyFactory(with_membership=True)
        company_2 = CompanyFactory(with_membership=True)

        user = company_1.members.first()
        client.force_login(user)

        response = client.get(reverse("apply:start", kwargs={"company_pk": company_2.pk}), follow=True)
        job_seeker_session_name = get_session_name(client.session, JobSeekerSessionKinds.GET_OR_CREATE)
        assertRedirects(
            response,
            expected_url=reverse(
                "job_seekers_views:check_nir_for_sender", kwargs={"session_uuid": job_seeker_session_name}
            ),
        )
        assert client.session[job_seeker_session_name].get("apply").get("company_pk") == company_2.pk

    def test_apply_as_siae_with_suspension_sanction(self, client):
        company = CompanyFactory(romes=("N1101", "N1105"), with_membership=True, with_jobs=True)
        Sanctions.objects.create(
            evaluated_siae=EvaluatedSiaeFactory(siae=company),
            suspension_dates=InclusiveDateRange(timezone.localdate() - relativedelta(days=1)),
        )

        user = company.members.first()
        client.force_login(user)

        response = client.get(reverse("apply:start", kwargs={"company_pk": company.pk}))
        assertContains(
            response,
            "suite aux mesures prises dans le cadre du contrôle a posteriori",
            status_code=403,
        )

    def _test_apply_as_company(self, client, user, company, dummy_job_seeker, pdf_file):
        # Autoprescription: send to dashboard, otherwise send to other company card
        reset_url = (
            reverse("dashboard:index")
            if company in user.company_set.all()
            else reverse("companies_views:card", kwargs={"company_pk": company.pk})
        )

        existing_job_seeker = JobSeekerFactory()

        # Entry point.
        # ----------------------------------------------------------------------

        response = client.get(reverse("apply:start", kwargs={"company_pk": company.pk}), {"back_url": reset_url})

        apply_session_name = get_session_name(client.session, APPLY_SESSION_KIND)
        params = {
            "tunnel": "sender",
            "apply_session_uuid": apply_session_name,
            "company": company.pk,
            "from_url": reset_url,
        }
        next_url = reverse("job_seekers_views:get_or_create_start", query=params)
        assertRedirects(response, next_url, target_status_code=302, fetch_redirect_response=False)

        response = client.get(next_url)
        job_seeker_session_name = get_session_name(client.session, JobSeekerSessionKinds.GET_OR_CREATE)
        next_url = reverse("job_seekers_views:check_nir_for_sender", kwargs={"session_uuid": job_seeker_session_name})
        assertRedirects(response, next_url)

        # Step determine the job seeker with a NIR. First try: NIR is found
        # ----------------------------------------------------------------------

        response = client.get(next_url)
        assertContains(response, LINK_RESET_MARKUP % reset_url)

        response = client.post(next_url, data={"nir": existing_job_seeker.jobseeker_profile.nir, "preview": 1})
        assert_contains_apply_nir_modal(response, existing_job_seeker)

        # Step determine the job seeker with a NIR. Second try: NIR is not found
        # ----------------------------------------------------------------------

        response = client.post(next_url, data={"nir": dummy_job_seeker.jobseeker_profile.nir, "confirm": 1})

        next_url = reverse(
            "job_seekers_views:search_by_email_for_sender",
            kwargs={"session_uuid": job_seeker_session_name},
        )
        expected_job_seeker_session = {
            "config": {"tunnel": "sender", "from_url": reset_url},
            "apply": {
                "company_pk": company.pk,
                "session_uuid": apply_session_name,
            },
            "profile": {
                "nir": dummy_job_seeker.jobseeker_profile.nir,
            },
        }
        assertRedirects(response, next_url)
        assert client.session[job_seeker_session_name] == expected_job_seeker_session

        # Step get job seeker e-mail. First try: email is found
        # ----------------------------------------------------------------------

        response = client.get(next_url)
        assertContains(response, CONFIRM_RESET_MARKUP % reset_url)

        response = client.post(
            next_url,
            data={"email": existing_job_seeker.email, "preview": 1},
        )
        assert_contains_apply_email_modal(response, existing_job_seeker)

        # Step get job seeker e-mail. Second try: email is not found
        # ----------------------------------------------------------------------

        response = client.post(next_url, data={"email": dummy_job_seeker.email, "confirm": "1"})

        expected_job_seeker_session |= {
            "user": {
                "email": dummy_job_seeker.email,
            },
        }
        assert client.session[job_seeker_session_name] == expected_job_seeker_session

        next_url = reverse(
            "job_seekers_views:create_job_seeker_step_1_for_sender",
            kwargs={"session_uuid": job_seeker_session_name},
        )
        assertRedirects(response, next_url)

        # Step create a job seeker.
        # ----------------------------------------------------------------------

        response = client.get(next_url)
        # The NIR is prefilled
        assertContains(response, dummy_job_seeker.jobseeker_profile.nir)
        # Check that the back url is correct
        assertContains(
            response,
            reverse(
                "job_seekers_views:search_by_email_for_sender",
                kwargs={"session_uuid": job_seeker_session_name},
            ),
        )
        assertContains(response, CONFIRM_RESET_MARKUP % reset_url)

        geispolsheim = create_city_geispolsheim()
        birthdate = dummy_job_seeker.jobseeker_profile.birthdate

        # Let's check for consistency between the NIR, the birthdate and the title.
        # ----------------------------------------------------------------------

        post_data = {
            "title": "M",  # inconsistent title
            "first_name": dummy_job_seeker.first_name,
            "last_name": dummy_job_seeker.last_name,
            "birthdate": birthdate,
            "lack_of_nir": False,
            "lack_of_nir_reason": "",
        }
        response = client.post(next_url, data=post_data)
        assertContains(response, JobSeekerProfile.ERROR_JOBSEEKER_INCONSISTENT_NIR_TITLE % "")

        post_data = {
            "title": "MME",
            "first_name": dummy_job_seeker.first_name,
            "last_name": dummy_job_seeker.last_name,
            "birthdate": datetime.date(1978, 11, 20),  # inconsistent birthdate
            "lack_of_nir": False,
            "lack_of_nir_reason": "",
        }
        response = client.post(next_url, data=post_data)
        assertContains(response, JobSeekerProfile.ERROR_JOBSEEKER_INCONSISTENT_NIR_BIRTHDATE % "")

        # Resume to valid data and proceed with "normal" flow.
        # ----------------------------------------------------------------------

        post_data = {
            "title": dummy_job_seeker.title,
            "first_name": dummy_job_seeker.first_name,
            "last_name": dummy_job_seeker.last_name,
            "birthdate": birthdate,
            "lack_of_nir": False,
            "lack_of_nir_reason": "",
            "birth_place": Commune.objects.by_insee_code_and_period(geispolsheim.code_insee, birthdate).id,
            "birth_country": Country.FRANCE_ID,
        }
        response = client.post(next_url, data=post_data)
        expected_job_seeker_session["profile"]["birthdate"] = post_data.pop("birthdate")
        expected_job_seeker_session["profile"]["lack_of_nir_reason"] = post_data.pop("lack_of_nir_reason")
        expected_job_seeker_session["profile"]["birth_place"] = post_data.pop("birth_place")
        expected_job_seeker_session["profile"]["birth_country"] = post_data.pop("birth_country")
        expected_job_seeker_session["user"] |= post_data
        assert client.session[job_seeker_session_name] == expected_job_seeker_session

        next_url = reverse(
            "job_seekers_views:create_job_seeker_step_2_for_sender",
            kwargs={"session_uuid": job_seeker_session_name},
        )
        assertRedirects(response, next_url)

        response = client.get(next_url)
        assertContains(response, CONFIRM_RESET_MARKUP % reset_url)

        post_data = {
            "ban_api_resolved_address": dummy_job_seeker.geocoding_address,
            "address_line_1": dummy_job_seeker.address_line_1,
            "post_code": self.city.post_codes[0],
            "insee_code": self.city.code_insee,
            "city": self.city.name,
            "phone": dummy_job_seeker.phone,
            "fill_mode": "ban_api",
        }

        response = client.post(next_url, data=post_data)
        expected_job_seeker_session["user"] |= post_data | {"address_line_2": "", "address_for_autocomplete": None}
        assert client.session[job_seeker_session_name] == expected_job_seeker_session

        next_url = reverse(
            "job_seekers_views:create_job_seeker_step_3_for_sender",
            kwargs={"session_uuid": job_seeker_session_name},
        )
        assertRedirects(response, next_url)

        response = client.get(next_url)
        assertContains(response, CONFIRM_RESET_MARKUP % reset_url)

        post_data = {
            "education_level": dummy_job_seeker.jobseeker_profile.education_level,
        }
        response = client.post(next_url, data=post_data)
        expected_job_seeker_session["profile"] |= post_data | {
            "pole_emploi_id": "",
            "lack_of_pole_emploi_id_reason": LackOfPoleEmploiId.REASON_NOT_REGISTERED,
            "resourceless": False,
            "rqth_employee": False,
            "oeth_employee": False,
            "pole_emploi": False,
            "pole_emploi_id_forgotten": "",
            "pole_emploi_since": "",
            "unemployed": False,
            "unemployed_since": "",
            "rsa_allocation": False,
            "has_rsa_allocation": RSAAllocation.NO.value,
            "rsa_allocation_since": "",
            "ass_allocation": False,
            "ass_allocation_since": "",
            "aah_allocation": False,
            "aah_allocation_since": "",
            "ase_exit": False,
            "isolated_parent": False,
            "housing_issue": False,
            "refugee": False,
            "detention_exit_or_ppsmj": False,
            "low_level_in_french": False,
            "mobility_issue": False,
        }
        assert client.session[job_seeker_session_name] == expected_job_seeker_session

        next_url = reverse(
            "job_seekers_views:create_job_seeker_step_end_for_sender",
            kwargs={"session_uuid": job_seeker_session_name},
        )
        assertRedirects(response, next_url)

        response = client.get(next_url)
        assertContains(response, "Créer le compte candidat")

        response = client.post(next_url)

        assert job_seeker_session_name not in client.session
        new_job_seeker = User.objects.get(email=dummy_job_seeker.email)

        next_url = reverse(
            "apply:application_jobs",
            kwargs={"session_uuid": apply_session_name},
            query={"job_seeker_public_id": new_job_seeker.public_id},
        )
        assertRedirects(response, next_url)

        # Check GPS group
        # ----------------------------------------------------------------------
        membership = FollowUpGroupMembership.objects.filter(
            follow_up_group__beneficiary=new_job_seeker, member=user
        ).get()
        membership.delete()  # delete it to check it is created again when applying

        # Check JobSeekerAssignment
        # ----------------------------------------------------------------------
        assignment = JobSeekerAssignment.objects.filter(
            job_seeker=new_job_seeker,
            professional=user,
            company=user.company_set.first(),
            last_action_kind=ActionKind.CREATE,
        ).get()
        assignment.delete()  # delete it to check it is created again when applying

        # Step application's jobs.
        # ----------------------------------------------------------------------

        response = client.get(next_url)
        assertContains(response, LINK_RESET_MARKUP % reset_url)

        selected_job = company.job_description_through.first()
        response = client.post(next_url, data={"selected_jobs": [selected_job.pk]})

        assert client.session[apply_session_name] == {
            "selected_jobs": [selected_job.pk],
            "reset_url": reset_url,
            "company_pk": company.pk,
            "job_seeker_public_id": str(new_job_seeker.public_id),
        }

        next_url = reverse("apply:application_resume", kwargs={"session_uuid": apply_session_name})
        assertRedirects(response, next_url)

        # Step application's resume (skip eligibility step as the user is not an authorzed prescriber)
        # ----------------------------------------------------------------------
        response = client.get(next_url)
        assertContains(response, "Enregistrer" if user in company.members.all() else "Postuler")
        assertContains(response, CONFIRM_RESET_MARKUP % reset_url)

        with mock.patch(
            "itou.files.models.uuid.uuid4",
            return_value=uuid.UUID("11111111-1111-1111-1111-111111111111"),
        ):
            response = client.post(
                next_url,
                data={
                    "message": "Lorem ipsum dolor sit amet, consectetur adipiscing elit.",
                    "resume": pdf_file,
                },
            )

        job_application = JobApplication.objects.get(sender=user, to_company=company)
        assert job_application.job_seeker == new_job_seeker
        assert job_application.sender_kind == SenderKind.EMPLOYER
        assert job_application.sender_company == user.company_set.first()
        assert job_application.sender_prescriber_organization is None
        assert job_application.state == JobApplicationState.NEW
        assert job_application.message == "Lorem ipsum dolor sit amet, consectetur adipiscing elit."
        assert job_application.selected_jobs.get() == selected_job
        assert job_application.resume.key == "resume/11111111-1111-1111-1111-111111111111.pdf"
        assert default_storage_ls_files() == [job_application.resume.key]

        assert apply_session_name not in client.session

        next_url = reverse("apply:application_end", kwargs={"application_pk": job_application.pk})
        assertRedirects(response, next_url)

        # Step application's end.
        # ----------------------------------------------------------------------
        response = client.get(next_url)
        assert response.status_code == 200

        # Check GPS group again
        # ----------------------------------------------------------------------
        assert FollowUpGroupMembership.objects.filter(
            follow_up_group__beneficiary=new_job_seeker, member=user
        ).exists()

        # Check JobSeekerAssignment
        # ----------------------------------------------------------------------
        assignment = JobSeekerAssignment.objects.filter(
            job_seeker=new_job_seeker,
            professional=user,
            company=user.company_set.first(),
            last_action_kind=ActionKind.APPLY,
        ).get()
        assignment.delete()  # delete it to check it is created again when applying

    @pytest.mark.usefixtures("temporary_bucket")
    def test_apply_as_employer(self, client, pdf_file):
        company = CompanyFactory(romes=("N1101", "N1105"), with_membership=True, with_jobs=True)
        employer = company.members.first()
        client.force_login(employer)

        dummy_job_seeker = JobSeekerFactory.build(
            jobseeker_profile__with_hexa_address=True,
            jobseeker_profile__with_education_level=True,
            with_ban_geoloc_address=True,
            jobseeker_profile__nir="278122978200555",
            jobseeker_profile__birthdate=datetime.date(1978, 12, 20),
            title="MME",
        )
        self._test_apply_as_company(client, employer, company, dummy_job_seeker, pdf_file)

    @pytest.mark.usefixtures("temporary_bucket")
    def test_apply_as_another_employer(self, client, pdf_file):
        company = CompanyFactory(with_membership=True, with_jobs=True, romes=("N1101", "N1105"))
        employer = EmployerFactory(membership=True)
        client.force_login(employer)

        dummy_job_seeker = JobSeekerFactory.build(
            jobseeker_profile__with_hexa_address=True,
            jobseeker_profile__with_education_level=True,
            with_ban_geoloc_address=True,
            jobseeker_profile__nir="278122978200555",
            jobseeker_profile__birthdate=datetime.date(1978, 12, 20),
            title="MME",
        )
        self._test_apply_as_company(client, employer, company, dummy_job_seeker, pdf_file)

    def test_check_info_as_employer_for_job_seeker_with_incomplete_info(self, client):
        company = CompanyFactory(with_membership=True, with_jobs=True, romes=("N1101", "N1105"))
        employer = EmployerFactory(membership=True)
        client.force_login(employer)
        dummy_job_seeker = JobSeekerFactory(
            jobseeker_profile__with_hexa_address=True,
            jobseeker_profile__with_education_level=True,
            with_ban_geoloc_address=True,
            jobseeker_profile__nir="278122978200555",
            jobseeker_profile__birthdate=None,
            title="MME",
        )
        apply_session = fake_session_initialization(client, company, dummy_job_seeker, {})

        next_url = reverse("job_seekers_views:check_job_seeker_info", kwargs={"session_uuid": apply_session.name})

        post_data = {
            "phone": "",
            "birthdate": datetime.date(1978, 11, 20),  # inconsistent birthdate
            "pole_emploi_id": "3454471C",
        }
        response = client.post(next_url, data=post_data)
        assertContains(
            response,
            (
                "Une erreur a été détectée. "
                "La date de naissance renseignée ne correspond pas au numéro de sécurité "
                "sociale 278122978200555 enregistré."
            ),
        )

    def test_cannot_create_job_seeker_with_pole_emploi_email(self, client):
        # It's unlikely to happen
        membership = CompanyMembershipFactory()
        company = membership.company
        user = membership.user
        client.force_login(user)

        # Init session
        start_url = reverse("apply:start", kwargs={"company_pk": company.pk})
        client.get(start_url, follow=True)
        job_seeker_session_name = get_session_name(client.session, JobSeekerSessionKinds.GET_OR_CREATE)
        nir_url = reverse("job_seekers_views:check_nir_for_sender", kwargs={"session_uuid": job_seeker_session_name})
        response = client.get(nir_url)
        assert response.status_code == 200

        response = client.post(nir_url, data={"nir": JobSeekerProfileFactory.build().nir, "confirm": 1})

        email_url = reverse(
            "job_seekers_views:search_by_email_for_sender",
            kwargs={"session_uuid": job_seeker_session_name},
        )
        assertRedirects(response, email_url)

        # Step get job seeker e-mail.
        # ----------------------------------------------------------------------

        response = client.get(email_url)
        assert response.status_code == 200

        response = client.post(email_url, data={"email": "toto@pole-emploi.fr", "confirm": "1"})
        assertContains(response, "Vous ne pouvez pas utiliser un e-mail Pôle emploi pour un candidat.")

        response = client.post(email_url, data={"email": "titi@francetravail.fr", "confirm": "1"})
        assertContains(response, "Vous ne pouvez pas utiliser un e-mail France Travail pour un candidat.")


class TestApplyAsOther:
    ROUTES = [
        "apply:start",
        "apply:start_hire",
    ]

    def test_labor_inspectors_are_not_allowed_to_submit_application(self, client, subtests):
        company = CompanyFactory()
        institution = InstitutionFactory(with_membership=True)
        client.force_login(institution.members.first())

        for route in self.ROUTES:
            with subtests.test(route=route):
                response = client.get(reverse(route, kwargs={"company_pk": company.pk}), follow=True)
                assert response.status_code == 403

    def test_itou_staff_are_not_allowed_to_submit_application(self, client, subtests):
        company = CompanyFactory()
        user = ItouStaffFactory()
        client.force_login(user)

        for route in self.ROUTES:
            with subtests.test(route=route):
                response = client.get(reverse(route, kwargs={"company_pk": company.pk}), follow=True)
                assert response.status_code == 403


class TestApplicationView:
    DIAGORIENTE_JOB_SEEKER_TITLE = "Vous n’avez pas de CV ?"
    DIAGORIENTE_JOB_SEEKER_DESCRIPTION = "Créez-en un grâce à notre partenaire Diagoriente."
    DIAGORIENTE_PRESCRIBER_TITLE = "Ce candidat n’a pas encore de CV ?"
    DIAGORIENTE_PRESCRIBER_DESCRIPTION = (
        "Accompagnez-le dans la création de son CV grâce à notre partenaire Diagoriente."
    )
    DIAGORIENTE_URL = "https://diagoriente.beta.gouv.fr/services/plateforme"

    spontaneous_application_field = "spontaneous_application"
    spontaneous_application_label = "Candidature spontanée"

    def test_application_jobs_use_previously_selected_jobs(self, client):
        company = CompanyFactory(subject_to_iae_rules=True, with_membership=True, with_jobs=True)

        client.force_login(company.members.first())
        selected_job = company.job_description_through.first()
        job_seeker = JobSeekerFactory()
        apply_session = fake_session_initialization(client, company, job_seeker, {"selected_jobs": [selected_job.pk]})

        response = client.get(reverse("apply:application_jobs", kwargs={"session_uuid": apply_session.name}))
        assertContains(response, self.spontaneous_application_label)
        assert response.context["form"].initial["selected_jobs"] == [selected_job.pk]
        assert self.spontaneous_application_field in response.context["form"].fields

    def test_application_jobs_spontaneous_applications_disabled(self, client):
        company = CompanyFactory(with_membership=True, with_jobs=True, spontaneous_applications_open_since=None)

        client.force_login(company.members.first())
        job_seeker = JobSeekerFactory()
        apply_session = fake_session_initialization(client, company, job_seeker, {})

        response = client.get(reverse("apply:application_jobs", kwargs={"session_uuid": apply_session.name}))
        assertNotContains(response, self.spontaneous_application_label)
        assert self.spontaneous_application_field not in response.context["form"].fields

    def test_application_jobs_none_available(self, client, snapshot):
        # No jobs available and spontaneous applications closed.
        company = CompanyFactory(with_membership=True, spontaneous_applications_open_since=None)
        client.force_login(company.members.first())
        job_seeker = JobSeekerFactory()
        apply_session = fake_session_initialization(client, company, job_seeker, {})

        response = client.get(reverse("apply:application_jobs", kwargs={"session_uuid": apply_session.name}))
        assert (
            pretty_indented(
                parse_response_to_soup(
                    response,
                    ".c-form > form",
                    replace_in_attr=[("href", f"/company/{company.pk}/card", "/company/[Pk of Company]/card")],
                )
            )
            == snapshot
        )

    def test_application_start_with_invalid_job_description_id(self, client):
        company = CompanyFactory(subject_to_iae_rules=True, with_membership=True, with_jobs=True)
        client.force_login(company.members.get())
        response = client.get(
            reverse("apply:start", kwargs={"company_pk": company.pk}), {"job_description_id": "invalid"}, follow=True
        )
        job_seeker_session_name = get_session_name(client.session, JobSeekerSessionKinds.GET_OR_CREATE)
        apply_session_name = get_session_name(client.session, APPLY_SESSION_KIND)
        assertRedirects(
            response,
            reverse("job_seekers_views:check_nir_for_sender", kwargs={"session_uuid": job_seeker_session_name}),
        )
        assert client.session[apply_session_name].get("selected_jobs") is None

    def test_access_without_session(self, client):
        prescriber = PrescriberOrganizationFactory(authorized=True, with_membership=True).members.first()
        client.force_login(prescriber)
        response = client.get(reverse("apply:application_iae_eligibility", kwargs={"session_uuid": uuid.uuid4()}))
        assert response.status_code == 404

    def test_application_resume_hidden_fields(self, client):
        company = CompanyFactory(with_membership=True, with_jobs=True)
        job_seeker = JobSeekerFactory()

        client.force_login(company.members.first())
        apply_session = fake_session_initialization(
            client, company, job_seeker, {"selected_jobs": company.job_description_through.all()}
        )

        response = client.get(reverse("apply:application_resume", kwargs={"session_uuid": apply_session.name}))
        assertContains(response, 'name="resume"')

    def test_application_resume_diagoriente_shown_as_job_seeker(self, client):
        company = CompanyFactory(with_membership=True, with_jobs=True)
        job_seeker = JobSeekerFactory()
        client.force_login(job_seeker)
        apply_session = fake_session_initialization(client, company, job_seeker, {"selected_jobs": []})

        response = client.get(reverse("apply:application_resume", kwargs={"session_uuid": apply_session.name}))
        assertContains(response, self.DIAGORIENTE_JOB_SEEKER_TITLE)
        assertContains(response, self.DIAGORIENTE_JOB_SEEKER_DESCRIPTION)
        assertNotContains(response, self.DIAGORIENTE_PRESCRIBER_TITLE)
        assertNotContains(response, self.DIAGORIENTE_PRESCRIBER_DESCRIPTION)
        assertContains(response, f"{self.DIAGORIENTE_URL}?utm_source=emploi-inclusion-candidat")

    def test_application_resume_diagoriente_not_shown_as_company(self, client):
        company = CompanyFactory(with_membership=True, with_jobs=True)
        job_seeker = JobSeekerFactory()
        client.force_login(company.members.first())
        apply_session = fake_session_initialization(client, company, job_seeker, {"selected_jobs": []})

        response = client.get(reverse("apply:application_resume", kwargs={"session_uuid": apply_session.name}))
        assertNotContains(response, self.DIAGORIENTE_JOB_SEEKER_TITLE)
        assertNotContains(response, self.DIAGORIENTE_JOB_SEEKER_DESCRIPTION)
        assertNotContains(response, self.DIAGORIENTE_PRESCRIBER_TITLE)
        assertNotContains(response, self.DIAGORIENTE_PRESCRIBER_DESCRIPTION)
        assertNotContains(response, self.DIAGORIENTE_URL)

    def test_application_resume_diagoriente_shown_as_prescriber(self, client):
        company = CompanyFactory(with_membership=True, with_jobs=True)
        prescriber = PrescriberOrganizationFactory(with_membership=True).members.first()
        job_seeker = JobSeekerFactory()
        client.force_login(prescriber)
        apply_session = fake_session_initialization(client, company, job_seeker, {"selected_jobs": []})

        response = client.get(reverse("apply:application_resume", kwargs={"session_uuid": apply_session.name}))
        assertNotContains(response, self.DIAGORIENTE_JOB_SEEKER_TITLE)
        assertNotContains(response, self.DIAGORIENTE_JOB_SEEKER_DESCRIPTION)
        assertContains(response, self.DIAGORIENTE_PRESCRIBER_TITLE)
        assertContains(response, self.DIAGORIENTE_PRESCRIBER_DESCRIPTION)
        assertContains(response, f"{self.DIAGORIENTE_URL}?utm_source=emploi-inclusion-prescripteur")

    def test_application_eligibility_is_bypassed_for_company_not_subject_to_eligibility_rules(self, client):
        company = CompanyFactory(not_subject_to_iae_rules=True, with_membership=True)
        job_seeker = JobSeekerFactory()

        client.force_login(company.members.first())
        apply_session = fake_session_initialization(client, company, job_seeker, {})

        response = client.get(
            reverse("apply:application_iae_eligibility", kwargs={"session_uuid": apply_session.name})
        )
        assertRedirects(
            response,
            reverse("apply:application_resume", kwargs={"session_uuid": apply_session.name}),
            fetch_redirect_response=False,
        )

    def test_application_eligibility_is_bypassed_for_unauthorized_prescriber(self, client):
        company = CompanyFactory(not_subject_to_iae_rules=True, with_membership=True)
        prescriber = PrescriberOrganizationFactory(with_membership=True).members.first()
        job_seeker = JobSeekerFactory()

        client.force_login(prescriber)
        apply_session = fake_session_initialization(client, company, job_seeker, {})

        response = client.get(
            reverse("apply:application_iae_eligibility", kwargs={"session_uuid": apply_session.name})
        )
        assertRedirects(
            response,
            reverse("apply:application_resume", kwargs={"session_uuid": apply_session.name}),
            fetch_redirect_response=False,
        )

    def test_application_eligibility_is_bypassed_when_the_job_seeker_already_has_an_approval(self, client):
        company = CompanyFactory(not_subject_to_iae_rules=True, with_membership=True)
        eligibility_diagnosis = IAEEligibilityDiagnosisFactory(from_prescriber=True)

        client.force_login(company.members.first())
        apply_session = fake_session_initialization(client, company, eligibility_diagnosis.job_seeker, {})

        response = client.get(
            reverse("apply:application_iae_eligibility", kwargs={"session_uuid": apply_session.name})
        )
        assertRedirects(
            response,
            reverse("apply:application_resume", kwargs={"session_uuid": apply_session.name}),
            fetch_redirect_response=False,
        )

    def test_application_eligibility_update_diagnosis_only_if_not_shrouded(self, client):
        company = CompanyFactory(subject_to_iae_rules=True, with_membership=True)
        prescriber = PrescriberOrganizationFactory(authorized=True, with_membership=True).members.first()
        eligibility_diagnosis = IAEEligibilityDiagnosisFactory(from_prescriber=True)

        client.force_login(prescriber)
        apply_session = fake_session_initialization(client, company, eligibility_diagnosis.job_seeker, {})

        # if "shrouded" is present then we don't update the eligibility diagnosis
        response = client.post(
            reverse("apply:application_iae_eligibility", kwargs={"session_uuid": apply_session.name}),
            {"level_1_1": True, "shrouded": "whatever"},
        )
        assertRedirects(
            response,
            reverse("apply:application_resume", kwargs={"session_uuid": apply_session.name}),
            fetch_redirect_response=False,
        )
        assert [eligibility_diagnosis] == list(
            EligibilityDiagnosis.objects.for_job_seeker_and_siae(job_seeker=eligibility_diagnosis.job_seeker)
        )

        # If "shrouded" is NOT present then we update the eligibility diagnosis
        response = client.post(
            reverse("apply:application_iae_eligibility", kwargs={"session_uuid": apply_session.name}),
            {"level_1_1": True},
        )
        assertRedirects(
            response,
            reverse("apply:application_resume", kwargs={"session_uuid": apply_session.name}),
            fetch_redirect_response=False,
        )
        new_eligibility_diagnosis = (
            EligibilityDiagnosis.objects.for_job_seeker_and_siae(job_seeker=eligibility_diagnosis.job_seeker)
            .order_by()
            .last()
        )
        assert new_eligibility_diagnosis != eligibility_diagnosis
        assert new_eligibility_diagnosis.author == prescriber

    def test_application_iae_eligibility_prefilled(self, client):
        PREFILLED_TEMPLATE = "eligibility/includes/iae/criteria_filled_from_job_seeker.html"
        company = CompanyFactory(subject_to_iae_rules=True, with_membership=True)
        job_seeker = JobSeekerFactory(last_checked_at=timezone.now() - datetime.timedelta(hours=25))
        prescriber = PrescriberOrganizationFactory(authorized=True, with_membership=True).members.first()

        client.force_login(prescriber)
        apply_session = fake_session_initialization(client, company, job_seeker, {})

        response = client.get(
            reverse("apply:application_iae_eligibility", kwargs={"session_uuid": apply_session.name})
        )
        assertTemplateNotUsed(response, PREFILLED_TEMPLATE)

        job_seeker.jobseeker_profile.low_level_in_french = True
        job_seeker.jobseeker_profile.ass_allocation_since = AllocationDuration.FROM_12_TO_23_MONTHS
        job_seeker.jobseeker_profile.save(update_fields=["low_level_in_french", "ass_allocation_since"])
        job_seeker.last_checked_at = timezone.now()
        job_seeker.save(update_fields=["last_checked_at"])

        response = client.get(
            reverse("apply:application_iae_eligibility", kwargs={"session_uuid": apply_session.name})
        )
        assertTemplateUsed(response, PREFILLED_TEMPLATE)
        prefilled_criteria = [c.kind for c in response.context["form"].initial["administrative_criteria"]]
        assert AdministrativeCriteriaKind.ASS in prefilled_criteria
        assert AdministrativeCriteriaKind.FLE in prefilled_criteria
        assert response.context["form"].initial["level_1_2"] is True  # ASS criterion
        assert response.context["form"].initial["level_2_17"] is True  # FLE / low_level_in_french criterion


class TestApplicationEndView:
    def test_update_job_seeker(self, client):
        job_application = JobApplicationFactory(sent_by_prescriber_alone=True, job_seeker__with_mocked_address=True)
        job_seeker = job_application.job_seeker
        # Ensure sender cannot update job seeker infos
        assert job_seeker.address_line_2 == ""
        url = reverse("apply:application_end", kwargs={"application_pk": job_application.pk})
        client.force_login(job_application.sender)
        response = client.post(
            url,
            data={
                "address_line_1": job_seeker.address_line_1,
                "address_line_2": "something new",
                "post_code": job_seeker.post_code,
                "city": job_seeker.city,
                "phone": job_seeker.phone,
            },
        )
        assert response.status_code == 403
        job_seeker.refresh_from_db()
        assert job_seeker.address_line_2 == ""

    def test_wo_phone_number_as_job_seeker(self, client):
        application = JobApplicationFactory(sent_by_job_seeker=True, job_seeker__phone="")
        expected_html = (
            '<p class="text-warning fst-italic">L’ajout du numéro de téléphone permet à l’employeur de vous '
            "contacter plus facilement.</p>"
        )
        client.force_login(application.job_seeker)
        response = client.get(reverse("apply:application_end", kwargs={"application_pk": application.pk}))
        assertContains(response, expected_html, html=True)

    def test_wo_phone_number_as_employer(self, client):
        application = JobApplicationFactory(sent_by_another_employer=True, job_seeker__phone="")
        expected_html = (
            '<p class="text-warning fst-italic">L’ajout du numéro de téléphone facilitera '
            "la prise de contact avec le candidat.</p>"
        )
        client.force_login(application.sender)
        response = client.get(reverse("apply:application_end", kwargs={"application_pk": application.pk}))
        assertContains(response, expected_html, html=True)

    def test_wo_phone_number_as_prescriber(self, client):
        application = JobApplicationFactory(sent_by_authorized_prescriber=True, job_seeker__phone="")
        expected_html = (
            '<p class="text-warning fst-italic">L’ajout du numéro de téléphone facilitera '
            "la prise de contact avec le candidat.</p>"
        )
        client.force_login(application.sender)
        response = client.get(reverse("apply:application_end", kwargs={"application_pk": application.pk}))
        assertContains(response, expected_html, html=True)

    def test_not_sender(self, client):
        application = JobApplicationFactory(sent_by_prescriber_alone=True)
        client.force_login(application.job_seeker)  # not the sender
        response = client.get(reverse("apply:application_end", kwargs={"application_pk": application.pk}))
        assert response.status_code == 404


class TestLastCheckedAtView:
    @pytest.fixture(autouse=True)
    def setup_method(self):
        self.company = CompanyFactory(subject_to_iae_rules=True, with_membership=True)
        self.job_seeker = JobSeekerFactory()

    def _check_last_checked_at(self, client, user, sees_warning, sees_verify_link):
        client.force_login(user)
        apply_session = fake_session_initialization(client, self.company, self.job_seeker, {"selected_jobs": []})

        url = reverse("apply:application_jobs", kwargs={"session_uuid": apply_session.name})
        response = client.get(url)
        assert response.status_code == 200

        params = {
            "job_seeker_public_id": self.job_seeker.public_id,
            "from_url": url,
        }
        update_url = reverse("job_seekers_views:update_job_seeker_start", query=params)
        link_check = assertContains if sees_verify_link else assertNotContains
        link_check(response, f'<a class="btn-link ms-3" href="{update_url}">Vérifier le profil</a>', html=True)
        # Check last_checked_at is shown
        assertContains(response, "Dernière actualisation du profil : ")
        assertNotContains(response, "Merci de vérifier la validité des informations")

        self.job_seeker.last_checked_at -= datetime.timedelta(days=500)
        self.job_seeker.save(update_fields=["last_checked_at"])
        response = client.get(url)
        warning_check = assertContains if sees_warning else assertNotContains
        warning_check(response, "Merci de vérifier la validité des informations")
        link_check(response, f'<a class="btn-link ms-3" href="{update_url}">Vérifier le profil</a>', html=True)

    def test_company_employee(self, client):
        self._check_last_checked_at(client, self.company.members.first(), sees_warning=True, sees_verify_link=True)

    def test_job_seeker(self, client):
        self._check_last_checked_at(client, self.job_seeker, sees_warning=False, sees_verify_link=False)

    def test_authorized_prescriber(self, client):
        authorized_prescriber = PrescriberOrganizationFactory(authorized=True, with_membership=True).members.first()
        self._check_last_checked_at(client, authorized_prescriber, sees_warning=True, sees_verify_link=True)

    def test_unauthorized_prescriber(self, client):
        prescriber = PrescriberOrganizationFactory(authorized=False, with_membership=True).members.first()
        self._check_last_checked_at(client, prescriber, sees_warning=True, sees_verify_link=False)

    def test_unauthorized_prescriber_that_created_the_job_seeker(self, client):
        prescriber = PrescriberOrganizationFactory(authorized=False, with_membership=True).members.first()
        self.job_seeker.created_by = prescriber
        self.job_seeker.save(update_fields=["created_by"])
        self._check_last_checked_at(client, prescriber, sees_warning=True, sees_verify_link=True)


class UpdateJobSeekerTestMixin:
    @pytest.fixture(autouse=True)
    def setup_method(self, settings, mocker, client):
        self.company = CompanyFactory(subject_to_iae_rules=True, with_membership=True)
        self.job_seeker = JobSeekerFactory(
            with_ban_geoloc_address=True,
            jobseeker_profile__nir="178122978200508",
            jobseeker_profile__birthdate=datetime.date(1978, 12, 20),
            title="M",
        )
        self.apply_session = fake_session_initialization(client, self.company, None, {})
        from_url = reverse(self.FINAL_REDIRECT_VIEW_NAME, kwargs={"session_uuid": self.apply_session.name})
        self.config = {
            "config": {"from_url": from_url},
            "job_seeker_pk": self.job_seeker.pk,
        }

        [self.city] = create_test_cities(["67"], num_per_department=1)

        self.INFO_MODIFIABLE_PAR_CANDIDAT_UNIQUEMENT = "Informations modifiables par le candidat uniquement"
        self.job_seeker_session_key = f"job_seeker-{self.job_seeker.public_id}"

        settings.API_GEOPF_BASE_URL = "http://ban-api"
        mocker.patch(
            "itou.utils.apis.geocoding.get_geocoding_data",
            side_effect=mock_get_first_geocoding_data,
        )

        params = {
            "job_seeker_public_id": self.job_seeker.public_id,
            "from_url": from_url,
        }
        self.start_url = reverse("job_seekers_views:update_job_seeker_start", query=params)

    def get_job_seeker_session_key(self, client):
        return get_session_name(client.session, JobSeekerSessionKinds.UPDATE)

    def get_step_url(self, step, client):
        viewname = f"job_seekers_views:update_job_seeker_step_{step}"
        return reverse(viewname, kwargs={"session_uuid": self.get_job_seeker_session_key(client)})

    def _check_nothing_permitted(self, client, user):
        client.force_login(user)

        response = client.get(self.start_url)
        assert response.status_code == 403

    def _check_that_last_step_doesnt_crash_with_direct_access(self, client, user):
        client.force_login(user)
        client.get(self.start_url)  # Setup job_seeker_session
        client.get(self.get_step_url("end", client))  # Use partial job_seeker_session

    def _check_everything_allowed(self, client, snapshot, user, extra_post_data_1=None):
        client.force_login(user)

        # START
        with assertSnapshotQueries(snapshot(name="queries - start")):
            response = client.get(self.start_url)
        assert client.session[self.get_job_seeker_session_key(client)] == self.config
        assertRedirects(response, self.get_step_url("1", client))

        # STEP 1
        with assertSnapshotQueries(snapshot(name="queries - step 1")):
            response = client.get(self.get_step_url("1", client))
        assertContains(response, self.job_seeker.first_name)
        assertNotContains(response, self.INFO_MODIFIABLE_PAR_CANDIDAT_UNIQUEMENT)

        # Let's check for consistency between the NIR, the birthdate and the title.
        # (but do not check when there is no NIR)
        # ----------------------------------------------------------------------

        if self.job_seeker.jobseeker_profile.nir != "":
            post_data = {
                "title": "MME",  # Inconsistent title
                "first_name": self.job_seeker.first_name,
                "last_name": self.job_seeker.last_name,
                "birthdate": self.job_seeker.jobseeker_profile.birthdate,
                "lack_of_nir": False,
                "lack_of_nir_reason": "",
            }
            response = client.post(self.get_step_url("1", client), data=post_data)
            assertContains(response, JobSeekerProfile.ERROR_JOBSEEKER_INCONSISTENT_NIR_TITLE % "")

            post_data = {
                "title": "M",
                "first_name": self.job_seeker.first_name,
                "last_name": self.job_seeker.last_name,
                "birthdate": datetime.date(1978, 11, 20),  # Inconsistent birthdate
                "lack_of_nir": False,
                "lack_of_nir_reason": "",
            }
            response = client.post(self.get_step_url("1", client), data=post_data)
            assertContains(response, JobSeekerProfile.ERROR_JOBSEEKER_INCONSISTENT_NIR_BIRTHDATE % "")

        # Resume to valid data and proceed with "normal" flow.
        # ----------------------------------------------------------------------

        NEW_FIRST_NAME = "New first name"
        PROCESS_TITLE = "Modification du compte candidat"

        post_data = {
            "title": "M",
            "first_name": NEW_FIRST_NAME,
            "last_name": "New last name",
            "birthdate": self.job_seeker.jobseeker_profile.birthdate,
            "lack_of_nir": False,
            "lack_of_nir_reason": "",
        }
        if extra_post_data_1 is not None:
            post_data.update(extra_post_data_1)
        response = client.post(self.get_step_url("1", client), data=post_data)
        assertRedirects(response, self.get_step_url("2", client), fetch_redirect_response=False)

        # Data is stored in the session but user is untouched
        # (nir value is retrieved from the job_seeker and stored in the session)
        lack_of_nir_reason = post_data.pop("lack_of_nir_reason")
        nir = post_data.pop("nir", None)
        birthdate = post_data.pop("birthdate", None)
        birth_place = post_data.pop("birth_place", None)
        birth_country = post_data.pop("birth_country", None)
        expected_job_seeker_session = {
            "user": post_data,
            "profile": {
                "birth_place": birth_place or self.job_seeker.jobseeker_profile.birth_place,
                "birth_country": birth_country or self.job_seeker.jobseeker_profile.birth_country,
                "birthdate": birthdate or self.job_seeker.jobseeker_profile.birthdate,
                "nir": nir or self.job_seeker.jobseeker_profile.nir,
                "lack_of_nir_reason": lack_of_nir_reason,
            },
        } | self.config
        assert client.session[self.get_job_seeker_session_key(client)] == expected_job_seeker_session
        self.job_seeker.refresh_from_db()
        assert self.job_seeker.first_name != NEW_FIRST_NAME

        # If you go back to step 1, new data is shown
        response = client.get(self.get_step_url("1", client))
        assertContains(response, PROCESS_TITLE, html=True)
        assertContains(response, NEW_FIRST_NAME)

        # STEP 2
        with assertSnapshotQueries(snapshot(name="queries - step 2")):
            response = client.get(self.get_step_url("2", client))
        assertContains(response, PROCESS_TITLE, html=True)
        assertContains(response, self.job_seeker.phone)
        assertNotContains(response, self.INFO_MODIFIABLE_PAR_CANDIDAT_UNIQUEMENT)

        NEW_ADDRESS_LINE = "382 ROUTE DE JOLLIVET"

        fields = [NEW_ADDRESS_LINE, f"{self.city.post_codes[0]} {self.city}"]
        new_geocoding_address = ", ".join([field for field in fields if field])

        post_data = {
            "ban_api_resolved_address": new_geocoding_address,
            "address_line_1": NEW_ADDRESS_LINE,
            "post_code": self.city.post_codes[0],
            "insee_code": self.city.code_insee,
            "city": self.city.name,
            "phone": self.job_seeker.phone,
            "fill_mode": "ban_api",
        }

        response = client.post(self.get_step_url("2", client), data=post_data)
        assertRedirects(response, self.get_step_url("3", client), fetch_redirect_response=False)

        # Data is stored in the session but user is untouched
        expected_job_seeker_session["user"] |= post_data | {"address_line_2": "", "address_for_autocomplete": None}
        assert client.session[self.get_job_seeker_session_key(client)] == expected_job_seeker_session
        self.job_seeker.refresh_from_db()
        assert self.job_seeker.address_line_1 != NEW_ADDRESS_LINE

        # If you go back to step 2, new data is shown
        response = client.get(self.get_step_url("2", client))
        assertContains(response, NEW_ADDRESS_LINE)

        # STEP 3
        with assertSnapshotQueries(snapshot(name="queries - step 3")):
            response = client.get(self.get_step_url("3", client))
        assertContains(response, PROCESS_TITLE, html=True)
        assertContains(response, "Niveau de formation")

        post_data = {
            "education_level": EducationLevel.BAC_LEVEL.value,
        }
        response = client.post(self.get_step_url("3", client), data=post_data)
        assertRedirects(response, self.get_step_url("end", client), fetch_redirect_response=False)

        # Data is stored in the session but user & profiles are untouched
        expected_job_seeker_session["profile"] |= post_data | {
            "pole_emploi_id": "",
            "lack_of_pole_emploi_id_reason": LackOfPoleEmploiId.REASON_NOT_REGISTERED,
            "resourceless": False,
            "rqth_employee": False,
            "oeth_employee": False,
            "pole_emploi": False,
            "pole_emploi_id_forgotten": "",
            "pole_emploi_since": "",
            "unemployed": False,
            "unemployed_since": "",
            "rsa_allocation": False,
            "has_rsa_allocation": RSAAllocation.NO.value,
            "rsa_allocation_since": "",
            "ass_allocation": False,
            "ass_allocation_since": "",
            "aah_allocation": False,
            "aah_allocation_since": "",
            "ase_exit": False,
            "isolated_parent": False,
            "housing_issue": False,
            "refugee": False,
            "detention_exit_or_ppsmj": False,
            "low_level_in_french": False,
            "mobility_issue": False,
        }
        assert client.session[self.get_job_seeker_session_key(client)] == expected_job_seeker_session
        self.job_seeker.refresh_from_db()

        # If you go back to step 3, new data is shown
        response = client.get(self.get_step_url("3", client))
        assertContains(response, '<option value="40" selected="">Formation de niveau BAC</option>', html=True)

        # Step END
        response = client.get(self.get_step_url("end", client))
        assertContains(response, PROCESS_TITLE, html=True)
        assertContains(response, NEW_FIRST_NAME.title())  # User.get_full_name() changes the firstname display
        assertContains(response, NEW_ADDRESS_LINE)
        assertContains(response, "Formation de niveau BAC")
        assertContains(response, "Valider les informations")

        previous_last_checked_at = self.job_seeker.last_checked_at

        response = client.post(self.get_step_url("end", client))
        assertRedirects(
            response,
            reverse(self.FINAL_REDIRECT_VIEW_NAME, kwargs={"session_uuid": self.apply_session.name}),
            fetch_redirect_response=False,
        )
        assert client.session.get(self.get_job_seeker_session_key(client)) is None

        self.job_seeker.refresh_from_db()
        assert self.job_seeker.has_jobseeker_profile is True
        assert self.job_seeker.first_name == NEW_FIRST_NAME
        assert self.job_seeker.address_line_1 == NEW_ADDRESS_LINE
        self.job_seeker.jobseeker_profile.refresh_from_db()
        assert self.job_seeker.jobseeker_profile.education_level == EducationLevel.BAC_LEVEL

        assert self.job_seeker.last_checked_at != previous_last_checked_at

        # Check JobSeekerAssignment: no assignment is created when a job seeker is updated
        # ----------------------------------------------------------------------
        assert not JobSeekerAssignment.objects.exists()

    def _check_only_administrative_allowed(self, client, user):
        client.force_login(user)

        # START
        response = client.get(self.start_url)
        expected_job_seeker_session = self.config
        assert client.session[self.get_job_seeker_session_key(client)] == expected_job_seeker_session
        assertRedirects(response, self.get_step_url("1", client))

        # STEP 1
        response = client.get(self.get_step_url("1", client))
        assertContains(response, self.job_seeker.first_name)
        assertContains(response, self.INFO_MODIFIABLE_PAR_CANDIDAT_UNIQUEMENT)

        response = client.post(self.get_step_url("1", client))
        assertRedirects(response, self.get_step_url("2", client), fetch_redirect_response=False)
        expected_job_seeker_session |= {"user": {}}
        assert client.session[self.get_job_seeker_session_key(client)] == expected_job_seeker_session

        # STEP 2
        response = client.get(self.get_step_url("2", client))
        assertContains(response, self.job_seeker.phone)
        assertContains(response, self.INFO_MODIFIABLE_PAR_CANDIDAT_UNIQUEMENT)

        response = client.post(self.get_step_url("2", client))
        assertRedirects(response, self.get_step_url("3", client), fetch_redirect_response=False)

        # Data is stored in the session but user is untouched
        assert client.session[self.get_job_seeker_session_key(client)] == expected_job_seeker_session

        # STEP 3
        response = client.get(self.get_step_url("3", client))
        assertContains(response, "Niveau de formation")

        post_data = {
            "education_level": EducationLevel.BAC_LEVEL.value,
        }
        response = client.post(self.get_step_url("3", client), data=post_data)
        assertRedirects(response, self.get_step_url("end", client), fetch_redirect_response=False)

        # Data is stored in the session but user & profiles are untouched
        expected_job_seeker_session["profile"] = post_data | {
            "pole_emploi_id": "",
            "lack_of_pole_emploi_id_reason": LackOfPoleEmploiId.REASON_NOT_REGISTERED,
            "resourceless": False,
            "rqth_employee": False,
            "oeth_employee": False,
            "pole_emploi": False,
            "pole_emploi_id_forgotten": "",
            "pole_emploi_since": "",
            "unemployed": False,
            "unemployed_since": "",
            "rsa_allocation": False,
            "has_rsa_allocation": RSAAllocation.NO.value,
            "rsa_allocation_since": "",
            "ass_allocation": False,
            "ass_allocation_since": "",
            "aah_allocation": False,
            "aah_allocation_since": "",
            "ase_exit": False,
            "isolated_parent": False,
            "housing_issue": False,
            "refugee": False,
            "detention_exit_or_ppsmj": False,
            "low_level_in_french": False,
            "mobility_issue": False,
        }
        assert client.session[self.get_job_seeker_session_key(client)] == expected_job_seeker_session
        self.job_seeker.refresh_from_db()

        # If you go back to step 3, new data is shown
        response = client.get(self.get_step_url("3", client))
        assertContains(response, '<option value="40" selected="">Formation de niveau BAC</option>', html=True)

        # Step END
        response = client.get(self.get_step_url("end", client))
        assertContains(response, "Formation de niveau BAC")

        previous_last_checked_at = self.job_seeker.last_checked_at

        response = client.post(self.get_step_url("end", client))
        assertRedirects(
            response,
            reverse(self.FINAL_REDIRECT_VIEW_NAME, kwargs={"session_uuid": self.apply_session.name}),
            fetch_redirect_response=False,
        )
        assert client.session.get(self.get_job_seeker_session_key(client)) is None

        self.job_seeker.refresh_from_db()
        assert self.job_seeker.has_jobseeker_profile is True
        assert self.job_seeker.jobseeker_profile.education_level == EducationLevel.BAC_LEVEL
        assert self.job_seeker.last_checked_at != previous_last_checked_at

        # Check JobSeekerAssignment: no assignment is created when a job seeker is updated
        # ----------------------------------------------------------------------
        assert not JobSeekerAssignment.objects.exists()


class TestUpdateJobSeeker(UpdateJobSeekerTestMixin):
    FINAL_REDIRECT_VIEW_NAME = "apply:application_jobs"

    def test_as_job_seeker(self, client):
        self._check_nothing_permitted(client, self.job_seeker)

    def test_as_unauthorized_prescriber(self, client):
        prescriber = PrescriberOrganizationFactory(authorized=False, with_membership=True).members.first()
        self._check_nothing_permitted(client, prescriber)

    def test_as_unauthorized_prescriber_that_created_proxied_job_seeker(self, client, snapshot):
        prescriber = PrescriberOrganizationFactory(authorized=False, with_membership=True).members.first()
        self.job_seeker.created_by = prescriber
        self.job_seeker.last_login = None
        self.job_seeker.save(update_fields=["created_by", "last_login"])

        geispolsheim = create_city_geispolsheim()
        birthdate = self.job_seeker.jobseeker_profile.birthdate

        self._check_everything_allowed(
            client,
            snapshot,
            prescriber,
            extra_post_data_1={
                "birth_place": Commune.objects.by_insee_code_and_period(geispolsheim.code_insee, birthdate).id,
                "birth_country": Country.FRANCE_ID,
            },
        )

    def test_as_unauthorized_prescriber_that_created_the_non_proxied_job_seeker(self, client):
        prescriber = PrescriberOrganizationFactory(authorized=False, with_membership=True).members.first()
        self.job_seeker.created_by = prescriber
        # Make sure the job seeker does manage its own account
        self.job_seeker.last_login = timezone.now() - relativedelta(months=1)
        self.job_seeker.save(update_fields=["created_by", "last_login"])
        self._check_nothing_permitted(client, prescriber)

    def test_as_authorized_prescriber_with_proxied_job_seeker(self, client, snapshot):
        # Make sure the job seeker does not manage its own account
        self.job_seeker.created_by = PrescriberFactory()
        self.job_seeker.last_login = None
        self.job_seeker.save(update_fields=["created_by", "last_login"])
        authorized_prescriber = PrescriberOrganizationFactory(authorized=True, with_membership=True).members.first()

        geispolsheim = create_city_geispolsheim()
        birthdate = self.job_seeker.jobseeker_profile.birthdate

        self._check_everything_allowed(
            client,
            snapshot,
            authorized_prescriber,
            extra_post_data_1={
                "birth_place": Commune.objects.by_insee_code_and_period(geispolsheim.code_insee, birthdate).id,
                "birth_country": Country.FRANCE_ID,
            },
        )

    def test_as_authorized_prescriber_with_non_proxied_job_seeker(self, client):
        # Make sure the job seeker does manage its own account
        self.job_seeker.last_login = timezone.now() - relativedelta(months=1)
        self.job_seeker.save(update_fields=["last_login"])
        authorized_prescriber = PrescriberOrganizationFactory(authorized=True, with_membership=True).members.first()
        self._check_only_administrative_allowed(client, authorized_prescriber)

    def test_as_company_with_proxied_job_seeker(self, client, snapshot):
        # Make sure the job seeker does not manage its own account
        self.job_seeker.created_by = EmployerFactory()
        self.job_seeker.last_login = None
        self.job_seeker.save(update_fields=["created_by", "last_login"])

        geispolsheim = create_city_geispolsheim()
        birthdate = self.job_seeker.jobseeker_profile.birthdate

        self._check_everything_allowed(
            client,
            snapshot,
            self.company.members.first(),
            extra_post_data_1={
                "birth_place": Commune.objects.by_insee_code_and_period(geispolsheim.code_insee, birthdate).id,
                "birth_country": Country.FRANCE_ID,
            },
        )

    def test_as_company_with_non_proxied_job_seeker(self, client):
        # Make sure the job seeker does manage its own account
        self.job_seeker.last_login = timezone.now() - relativedelta(months=1)
        self.job_seeker.save(update_fields=["last_login"])
        self._check_only_administrative_allowed(client, self.company.members.first())

    def test_as_company_with_non_proxied_job_seeker_with_place_infos(self, client):
        # Make sure the job seeker does manage its own account
        self.job_seeker.last_login = timezone.now() - relativedelta(months=1)
        self.job_seeker.save(update_fields=["last_login"])

        # Set birth place infos
        geispolsheim = create_city_geispolsheim()
        birthdate = self.job_seeker.jobseeker_profile.birthdate
        geispolsheim_commune = Commune.objects.by_insee_code_and_period(geispolsheim.code_insee, birthdate)
        self.job_seeker.jobseeker_profile.birth_place = geispolsheim_commune
        self.job_seeker.jobseeker_profile.birth_country_id = Country.FRANCE_ID
        self.job_seeker.jobseeker_profile.save(update_fields=["birth_place", "birth_country"])
        self._check_only_administrative_allowed(client, self.company.members.first())

        # Check that birth place infos are still there
        assert self.job_seeker.jobseeker_profile.birth_place == geispolsheim_commune
        assert self.job_seeker.jobseeker_profile.birth_country_id == Country.FRANCE_ID

    def test_with_invalid_job_seeker_session(self, client):
        client.force_login(self.company.members.first())
        invalid_session_name = uuid.uuid4()
        kwargs = {"session_uuid": invalid_session_name}
        for url in [
            reverse("job_seekers_views:update_job_seeker_step_1", kwargs=kwargs),
            reverse("job_seekers_views:update_job_seeker_step_2", kwargs=kwargs),
            reverse("job_seekers_views:update_job_seeker_step_3", kwargs=kwargs),
            reverse("job_seekers_views:update_job_seeker_step_end", kwargs=kwargs),
        ]:
            response = client.get(url)
            assert response.status_code == 404

    def test_with_job_seeker_without_nir(self, client, snapshot):
        # Make sure the job seeker does not manage its own account (and has no nir)
        self.job_seeker.jobseeker_profile.nir = ""
        self.job_seeker.jobseeker_profile.lack_of_nir_reason = ""
        self.job_seeker.jobseeker_profile.save(update_fields=["nir", "lack_of_nir_reason"])

        self.job_seeker.created_by = EmployerFactory()
        self.job_seeker.last_login = None
        self.job_seeker.save(update_fields=["created_by", "last_login"])

        geispolsheim = create_city_geispolsheim()
        birthdate = self.job_seeker.jobseeker_profile.birthdate

        self._check_everything_allowed(
            client,
            snapshot,
            self.company.members.first(),
            extra_post_data_1={
                "nir": "",
                "lack_of_nir": True,
                "lack_of_nir_reason": LackOfNIRReason.NO_NIR.value,
                "birth_place": Commune.objects.by_insee_code_and_period(geispolsheim.code_insee, birthdate).id,
                "birth_country": Country.FRANCE_ID,
            },
        )
        # Check that we could update its NIR infos
        assert self.job_seeker.jobseeker_profile.lack_of_nir_reason == LackOfNIRReason.NO_NIR

    def test_as_company_that_last_step_doesnt_crash_with_direct_access(self, client):
        # Make sure the job seeker does not manage its own account
        self.job_seeker.created_by = EmployerFactory()
        self.job_seeker.last_login = None
        self.job_seeker.save(update_fields=["created_by", "last_login"])
        self._check_that_last_step_doesnt_crash_with_direct_access(client, self.company.members.first())


class TestUpdateJobSeekerStep3View:
    def test_job_seeker_with_profile_has_check_boxes_ticked_in_step3(self, client):
        company = CompanyFactory(subject_to_iae_rules=True, with_membership=True)
        job_seeker = JobSeekerFactory(jobseeker_profile__ass_allocation_since=AllocationDuration.FROM_6_TO_11_MONTHS)

        client.force_login(company.members.first())
        apply_session = fake_session_initialization(client, company, job_seeker, {"selected_jobs": []})

        # START to setup jobseeker session
        params = {
            "job_seeker_public_id": job_seeker.public_id,
            "from_url": reverse("apply:application_jobs", kwargs={"session_uuid": apply_session.name}),
        }
        url = reverse("job_seekers_views:update_job_seeker_start", query=params)
        response = client.get(url)
        assert response.status_code == 302

        # Go straight to STEP 3
        job_seeker_session_name = get_session_name(client.session, JobSeekerSessionKinds.UPDATE)
        response = client.get(
            reverse(
                "job_seekers_views:update_job_seeker_step_3",
                kwargs={"session_uuid": job_seeker_session_name},
            )
        )
        assertContains(
            response,
            '<input type="checkbox" name="ass_allocation" class="form-check-input" id="id_ass_allocation" checked="">',
            html=True,
        )


def test_detect_existing_job_seeker(client):
    company = CompanyFactory(romes=("N1101", "N1105"), with_membership=True, with_jobs=True)
    reset_url_company = reverse("companies_views:card", kwargs={"company_pk": company.pk})

    prescriber_organization = PrescriberOrganizationFactory(authorized=True, with_membership=True)
    user = prescriber_organization.members.first()
    client.force_login(user)

    job_seeker = JobSeekerFactory(
        jobseeker_profile__nir="",
        jobseeker_profile__birthdate=datetime.date(1997, 1, 1),
        title="M",
        first_name="Jérémy",
        email="jeremy@example.com",
    )

    # Entry point.
    # ----------------------------------------------------------------------

    response = client.get(reverse("apply:start", kwargs={"company_pk": company.pk}), {"back_url": reset_url_company})
    apply_session_name = get_session_name(client.session, APPLY_SESSION_KIND)

    params = {
        "tunnel": "sender",
        "apply_session_uuid": apply_session_name,
        "company": company.pk,
        "from_url": reverse("companies_views:card", kwargs={"company_pk": company.pk}),
    }
    next_url = reverse("job_seekers_views:get_or_create_start", query=params)
    assertRedirects(response, next_url, target_status_code=302, fetch_redirect_response=False)

    # Step determine the job seeker with a NIR.
    # ----------------------------------------------------------------------

    response = client.get(next_url)
    job_seeker_session_name = get_session_name(client.session, JobSeekerSessionKinds.GET_OR_CREATE)
    next_url = reverse("job_seekers_views:check_nir_for_sender", kwargs={"session_uuid": job_seeker_session_name})

    response = client.get(next_url)
    assert response.status_code == 200

    NEW_NIR = "197013625838386"
    response = client.post(next_url, data={"nir": NEW_NIR, "confirm": 1})
    next_url = reverse(
        "job_seekers_views:search_by_email_for_sender",
        kwargs={"session_uuid": job_seeker_session_name},
    )
    expected_job_seeker_session = {
        "config": {
            "tunnel": "sender",
            "from_url": reverse("companies_views:card", kwargs={"company_pk": company.pk}),
        },
        "apply": {
            "company_pk": company.pk,
            "session_uuid": apply_session_name,
        },
        "profile": {
            "nir": NEW_NIR,
        },
    }
    assertRedirects(response, next_url)
    assert client.session[job_seeker_session_name] == expected_job_seeker_session

    # Step get job seeker e-mail.
    # ----------------------------------------------------------------------

    response = client.get(next_url)
    assert response.status_code == 200

    response = client.post(next_url, data={"email": "wrong-email@example.com", "confirm": "1"})

    expected_job_seeker_session |= {
        "user": {
            "email": "wrong-email@example.com",
        },
    }
    assert client.session[job_seeker_session_name] == expected_job_seeker_session

    next_url = reverse(
        "job_seekers_views:create_job_seeker_step_1_for_sender",
        kwargs={"session_uuid": job_seeker_session_name},
    )
    assertRedirects(response, next_url)

    # Step to create a job seeker.
    # ----------------------------------------------------------------------

    response = client.get(next_url)
    # Make sure the specified NIR is properly filled
    assertContains(response, NEW_NIR)

    geispolsheim = create_city_geispolsheim()
    birthdate = job_seeker.jobseeker_profile.birthdate

    post_data = {
        "title": job_seeker.title,
        "first_name": "JEREMY",  # Try without the accent and in uppercase
        "last_name": job_seeker.last_name,
        "birthdate": birthdate,
        "lack_of_nir_reason": "",
        "lack_of_nir": False,
        "birth_place": Commune.objects.by_insee_code_and_period(geispolsheim.code_insee, birthdate).id,
        "birth_country": Country.FRANCE_ID,
    }
    response = client.post(next_url, data=post_data)
    assertContains(
        response,
        (
            "D'après les informations renseignées, il semblerait que ce candidat soit "
            "déjà rattaché à un autre email : j*****@e******.c**."
        ),
        html=True,
    )
    assertContains(
        response,
        '<button name="confirm" value="1" class="btn btn-sm btn-outline-primary">'
        "Poursuivre la création du compte</button>",
        html=True,
    )
    check_email_url = reverse(
        "job_seekers_views:search_by_email_for_sender",
        kwargs={"session_uuid": job_seeker_session_name},
    )
    assertContains(
        response,
        f"""<a href="{check_email_url}" class="btn btn-sm btn-primary">Modifier l'email du candidat</a>""",
        html=True,
    )
    # Use the modal button to send confirmation
    response = client.post(next_url, data=post_data | {"confirm": 1})

    # session data is updated and we are correctly redirected to step 2
    expected_job_seeker_session["profile"] |= {
        "lack_of_nir_reason": post_data.pop("lack_of_nir_reason", ""),
        "birthdate": post_data.pop("birthdate"),
        "birth_country": post_data.pop("birth_country"),
        "birth_place": post_data.pop("birth_place"),
    }
    expected_job_seeker_session["user"] |= post_data
    assert client.session[job_seeker_session_name] == expected_job_seeker_session

    next_url = reverse(
        "job_seekers_views:create_job_seeker_step_2_for_sender",
        kwargs={"session_uuid": job_seeker_session_name},
    )
    assertRedirects(response, next_url)

    # If we chose to cancel & go back, we should find our old wrong email in the page
    response = client.get(check_email_url)
    assertContains(response, "wrong-email@example.com")


class TestApplicationGEIQEligibilityView:
    DIAG_VALIDITY_TXT = "Date de fin de validité du diagnostic"
    UPDATE_ELIGIBILITY = "Mettre à jour l’éligibilité"
    CONFIRMED_ELIGIBILITY = "Éligibilité GEIQ confirmée"
    UNCONFIRMED_ELIGIBILITY = "Éligibilité GEIQ non confirmée"

    @pytest.fixture(autouse=True)
    def setup_method(self):
        self.geiq = CompanyFactory(with_membership=True, with_jobs=True, kind=CompanyKind.GEIQ)
        self.prescriber_org = PrescriberOrganizationFactory(authorized=True, with_membership=True)
        self.orienter = PrescriberFactory()
        self.job_seeker_with_geiq_diagnosis = GEIQEligibilityDiagnosisFactory(from_prescriber=True).job_seeker
        self.company = CompanyFactory(with_membership=True, kind=CompanyKind.EI)

    def test_bypass_geiq_eligibility_diagnosis_form_for_orienter(self, client):
        # When creating a job application, should bypass GEIQ eligibility form step:
        # - if user is an authorized prescriber
        # - if user structure is not a GEIQ : should not be possible, form asserts it and crashes
        job_seeker = JobSeekerFactory()

        # Redirect orienter
        client.force_login(self.orienter)
        apply_session = fake_session_initialization(
            client, self.geiq, job_seeker, {"selected_jobs": self.geiq.job_description_through.all()}
        )
        response = client.get(
            reverse("apply:application_geiq_eligibility", kwargs={"session_uuid": apply_session.name})
        )

        # Must redirect to resume
        assertRedirects(
            response,
            reverse("apply:application_resume", kwargs={"session_uuid": apply_session.name}),
            fetch_redirect_response=False,
        )
        assertTemplateNotUsed(response, "apply/includes/geiq/geiq_administrative_criteria_form.html")

    def test_bypass_geiq_diagnosis_for_staff_members(self, client):
        job_seeker = JobSeekerFactory()
        client.force_login(self.geiq.members.first())
        apply_session = fake_session_initialization(
            client, self.geiq, job_seeker, {"selected_jobs": self.geiq.job_description_through.all()}
        )
        response = client.get(
            reverse("apply:application_geiq_eligibility", kwargs={"session_uuid": apply_session.name})
        )

        # Must redirect to resume
        assertRedirects(
            response,
            reverse("apply:application_resume", kwargs={"session_uuid": apply_session.name}),
            fetch_redirect_response=False,
        )
        assertTemplateNotUsed(response, "apply/includes/geiq/geiq_administrative_criteria_form.html")

    def test_bypass_geiq_diagnosis_for_job_seeker(self, client):
        # A job seeker must not have access to GEIQ eligibility form
        job_seeker = JobSeekerFactory()
        client.force_login(job_seeker)
        apply_session = fake_session_initialization(
            client, self.geiq, job_seeker, {"selected_jobs": self.geiq.job_description_through.all()}
        )
        response = client.get(
            reverse("apply:application_geiq_eligibility", kwargs={"session_uuid": apply_session.name})
        )

        # Must redirect to resume
        assertRedirects(
            response,
            reverse("apply:application_resume", kwargs={"session_uuid": apply_session.name}),
            fetch_redirect_response=False,
        )
        assertTemplateNotUsed(response, "apply/includes/geiq/geiq_administrative_criteria_form.html")

    def test_sanity_check_geiq_diagnosis_for_non_geiq(self, client):
        job_seeker = JobSeekerFactory()
        # See comment im previous test:
        # assert we're not somewhere we don't belong to (non-GEIQ)
        client.force_login(self.company.members.first())
        apply_session = fake_session_initialization(
            client, self.company, job_seeker, {"selected_jobs": self.geiq.job_description_through.all()}
        )

        response = client.get(
            reverse("apply:application_geiq_eligibility", kwargs={"session_uuid": apply_session.name})
        )
        assert response.status_code == 404

    def test_access_as_authorized_prescriber(self, client):
        job_seeker = JobSeekerFactory()
        client.force_login(self.prescriber_org.members.first())
        apply_session = fake_session_initialization(
            client, self.geiq, job_seeker, {"selected_jobs": self.geiq.job_description_through.all()}
        )

        geiq_eligibility_url = reverse(
            "apply:application_geiq_eligibility", kwargs={"session_uuid": apply_session.name}
        )
        response = client.get(geiq_eligibility_url)

        assert response.status_code == 200
        assertTemplateUsed(response, "apply/includes/geiq/geiq_administrative_criteria_form.html")

        # Check back_url in next step
        response = client.get(
            reverse("apply:application_resume", kwargs={"session_uuid": apply_session.name}),
        )
        assertContains(response, geiq_eligibility_url)

    def test_authorized_prescriber_can_see_other_authorized_prescriber_eligibility_diagnosis(self, client):
        job_seeker = JobSeekerFactory()
        GEIQEligibilityDiagnosisFactory(from_prescriber=True, job_seeker=job_seeker)

        client.force_login(self.prescriber_org.members.get())
        apply_session = fake_session_initialization(
            client, self.geiq, job_seeker, {"selected_jobs": self.geiq.job_description_through.all()}
        )
        response = client.get(
            reverse("apply:application_geiq_eligibility", kwargs={"session_uuid": apply_session.name})
        )
        assertContains(response, self.CONFIRMED_ELIGIBILITY)
        assertContains(response, self.DIAG_VALIDITY_TXT)
        assertContains(response, self.UPDATE_ELIGIBILITY)

    def test_authorized_prescriber_do_not_see_company_eligibility_diagnosis(self, client):
        job_seeker = JobSeekerFactory()
        GEIQEligibilityDiagnosisFactory(from_employer=True, author_geiq=self.geiq, job_seeker=job_seeker)
        prescriber = self.prescriber_org.members.get()

        client.force_login(prescriber)
        apply_session = fake_session_initialization(
            client, self.geiq, job_seeker, {"selected_jobs": self.geiq.job_description_through.all()}
        )
        url = reverse("apply:application_geiq_eligibility", kwargs={"session_uuid": apply_session.name})
        response = client.get(url)
        assertContains(response, self.UNCONFIRMED_ELIGIBILITY)
        assertNotContains(response, self.DIAG_VALIDITY_TXT)
        assertNotContains(response, self.UPDATE_ELIGIBILITY)

        response = client.post(url, {"not": "empty"})
        assertRedirects(
            response,
            reverse("apply:application_resume", kwargs={"session_uuid": apply_session.name}),
        )
        prescriber_diag, _company_diag = GEIQEligibilityDiagnosis.objects.filter(job_seeker=job_seeker).order_by(
            "-created_at"
        )
        assert prescriber_diag.author_kind == AuthorKind.PRESCRIBER
        assert prescriber_diag.author == prescriber
        assert prescriber_diag.author_prescriber_organization == self.prescriber_org
        assert prescriber_diag.job_seeker == job_seeker
        assert prescriber_diag.author_geiq is None

    def test_access_without_session(self, client):
        client.force_login(self.prescriber_org.members.first())
        response = client.get(
            reverse("apply:application_geiq_eligibility", kwargs={"session_uuid": str(uuid.uuid4())})
        )
        assert response.status_code == 404

    def test_geiq_eligibility_badge(self, client):
        client.force_login(self.prescriber_org.members.first())

        # Badge OK if job seeker has a valid eligibility diagnosis
        apply_session = fake_session_initialization(
            client,
            self.geiq,
            self.job_seeker_with_geiq_diagnosis,
            {"selected_jobs": self.geiq.job_description_through.all()},
        )
        response = client.get(
            reverse("apply:application_geiq_eligibility", kwargs={"session_uuid": apply_session.name}),
            follow=True,
        )

        assertContains(response, self.CONFIRMED_ELIGIBILITY)
        assertTemplateUsed(response, "apply/includes/geiq/geiq_administrative_criteria_form.html")
        assertContains(response, self.DIAG_VALIDITY_TXT)

        # Badge KO if job seeker has no diagnosis
        job_seeker_without_diagnosis = JobSeekerFactory()
        apply_session = fake_session_initialization(
            client, self.geiq, job_seeker_without_diagnosis, {"selected_jobs": self.geiq.job_description_through.all()}
        )
        response = client.get(
            reverse("apply:application_geiq_eligibility", kwargs={"session_uuid": apply_session.name}),
            follow=True,
        )
        assertContains(response, self.UNCONFIRMED_ELIGIBILITY)
        assertTemplateUsed(response, "apply/includes/geiq/geiq_administrative_criteria_form.html")

        # Badge KO if job seeker has an expired diagnosis
        job_seeker_with_expired_diagnosis = JobSeekerFactory()
        diagnosis = GEIQEligibilityDiagnosisFactory(
            from_prescriber=True, expired=True, job_seeker=job_seeker_with_expired_diagnosis
        )
        assert not diagnosis.is_valid
        apply_session = fake_session_initialization(
            client,
            self.geiq,
            job_seeker_with_expired_diagnosis,
            {"selected_jobs": self.geiq.job_description_through.all()},
        )
        response = client.get(
            reverse("apply:application_geiq_eligibility", kwargs={"session_uuid": apply_session.name}),
            follow=True,
        )
        assertContains(response, self.UNCONFIRMED_ELIGIBILITY)
        assertTemplateUsed(response, "apply/includes/geiq/geiq_administrative_criteria_form.html")

        # Badge is KO if job seeker has a valid diagnosis without allowance
        diagnosis = GEIQEligibilityDiagnosisFactory(from_employer=True)
        assert diagnosis.allowance_amount == 0

        client.force_login(self.prescriber_org.members.first())
        apply_session = fake_session_initialization(
            client,
            diagnosis.author_geiq,
            job_seeker_without_diagnosis,
            {"selected_jobs": self.geiq.job_description_through.all()},
        )
        response = client.get(
            reverse("apply:application_geiq_eligibility", kwargs={"session_uuid": apply_session.name}),
            follow=True,
        )
        assertContains(response, "Éligibilité GEIQ non confirmée")
        assertTemplateUsed(response, "apply/includes/geiq/geiq_administrative_criteria_form.html")

    def test_geiq_diagnosis_form_validation(self, client, subtests):
        client.force_login(self.prescriber_org.members.first())
        apply_session = fake_session_initialization(
            client,
            self.geiq,
            self.job_seeker_with_geiq_diagnosis,
            {"selected_jobs": self.geiq.job_description_through.all()},
        )

        response = client.post(
            reverse("apply:application_geiq_eligibility", kwargs={"session_uuid": apply_session.name}),
            data={"jeune_26_ans": True},
        )

        assertRedirects(
            response,
            reverse("apply:application_resume", kwargs={"session_uuid": apply_session.name}),
            fetch_redirect_response=False,
        )

        # Age coherence
        test_data = [
            {"senior_50_ans": True, "jeune_26_ans": True},
            {"de_45_ans_et_plus": True, "jeune_26_ans": True},
            {"senior_50_ans": True, "sortant_ase": True},
            {"de_45_ans_et_plus": True, "sortant_ase": True},
        ]

        for post_data in test_data:
            with subtests.test(post_data):
                response = client.post(
                    reverse("apply:application_geiq_eligibility", kwargs={"session_uuid": apply_session.name}),
                    data=post_data,
                    follow=True,
                )
                assertTemplateUsed(response, "apply/includes/geiq/geiq_administrative_criteria_form.html")
                assertContains(response, "Incohérence dans les critères")

        # TODO: more coherence tests asked to business ...


class TestCheckPreviousApplicationsView:
    @pytest.fixture(autouse=True)
    def setup_method(self):
        self.company = CompanyFactory(subject_to_iae_rules=True, with_membership=True, for_snapshot=True)
        self.job_seeker = JobSeekerFactory()

    def _login_and_setup_session(self, client, user):
        client.force_login(user)
        self.apply_session = fake_session_initialization(
            client,
            self.company,
            self.job_seeker,
            {
                "selected_jobs": [],
                "reset_url": reverse("companies_views:card", kwargs={"company_pk": self.company.pk}),
            },
        )

    @property
    def check_infos_url(self):
        return reverse("job_seekers_views:check_job_seeker_info", kwargs={"session_uuid": self.apply_session.name})

    @property
    def check_prev_applications_url(self):
        return reverse("apply:step_check_prev_applications", kwargs={"session_uuid": self.apply_session.name})

    @property
    def application_jobs_url(self):
        return reverse("apply:application_jobs", kwargs={"session_uuid": self.apply_session.name})

    def test_no_previous_as_job_seeker(self, client):
        self._login_and_setup_session(client, self.job_seeker)
        response = client.get(self.check_prev_applications_url)
        assertRedirects(response, self.application_jobs_url)

        response = client.get(self.application_jobs_url)
        company_card_url = reverse("companies_views:card", kwargs={"company_pk": self.company.pk})

        # Reset URL is correct
        assertContains(response, LINK_RESET_MARKUP % company_card_url, count=1)

    @freeze_time("2025-09-08 11:39")
    def test_with_previous_as_job_seeker(self, client, snapshot):
        self._login_and_setup_session(client, self.job_seeker)

        # Create a very recent application
        job_application = JobApplicationFactory(
            sent_by_prescriber_alone=True, job_seeker=self.job_seeker, to_company=self.company
        )
        response = client.get(self.check_prev_applications_url)
        assert pretty_indented(
            parse_response_to_soup(
                response,
                ".c-form",
                replace_in_attr=[
                    ("href", f"/company/{job_application.to_company.pk}/card", "/company/[PK of Company]/card"),
                ],
            )
        ) == snapshot(name="blocked")

        # Don't allow to skip to another step
        response = client.get(self.application_jobs_url)
        assertContains(
            response, "Vous avez déjà postulé chez cet employeur durant les dernières 24 heures.", status_code=403
        )
        response = client.get(self.application_jobs_url)
        assert response.status_code == 404

        # Make it less recent to avoid the 403
        job_application.created_at = timezone.now() - datetime.timedelta(days=2)
        job_application.save(update_fields=("created_at", "updated_at"))
        self._login_and_setup_session(client, self.job_seeker)
        response = client.get(self.check_prev_applications_url)
        assert pretty_indented(
            parse_response_to_soup(
                response,
                ".c-form",
                replace_in_attr=[
                    ("href", f"/company/{job_application.to_company.pk}/card", "/company/[PK of Company]/card"),
                ],
            )
        ) == snapshot(name="allowed")
        response = client.post(self.check_prev_applications_url, data={"force_new_application": "force"})
        assertRedirects(response, self.application_jobs_url)

        # Reset URL is correct
        response = client.get(self.application_jobs_url)
        company_card_url = reverse("companies_views:card", kwargs={"company_pk": self.company.pk})
        assertContains(response, LINK_RESET_MARKUP % company_card_url, count=1)

    def test_no_previous_as_authorized_prescriber(self, client):
        authorized_prescriber = PrescriberOrganizationFactory(authorized=True, with_membership=True).members.first()
        self._login_and_setup_session(client, authorized_prescriber)
        response = client.get(self.check_prev_applications_url)
        assertRedirects(response, self.application_jobs_url)

        # Reset URL is correct
        response = client.get(self.application_jobs_url)
        company_card_url = reverse("companies_views:card", kwargs={"company_pk": self.company.pk})
        assertContains(response, LINK_RESET_MARKUP % company_card_url, count=1)

    @freeze_time("2025-09-08 11:39")
    def test_with_previous_as_prescriber(self, client, snapshot):
        prescriber = PrescriberFactory()
        self._login_and_setup_session(client, prescriber)

        # Create a very recent application
        job_application = JobApplicationFactory(
            sent_by_prescriber_alone=True, job_seeker=self.job_seeker, to_company=self.company
        )
        response = client.get(self.check_prev_applications_url)
        assert pretty_indented(
            parse_response_to_soup(
                response,
                ".c-form",
                replace_in_attr=[
                    ("href", f"/company/{job_application.to_company.pk}/card", "/company/[PK of Company]/card"),
                ],
            )
        ) == snapshot(name="blocked")

        # Don't allow to skip to another step
        response = client.get(self.application_jobs_url)
        assertContains(
            response, "Ce candidat a déjà postulé chez cet employeur durant les dernières 24 heures.", status_code=403
        )
        response = client.get(self.application_jobs_url)
        assert response.status_code == 404

        # Make it less recent to avoid the 403
        job_application.created_at = timezone.now() - datetime.timedelta(days=2)
        job_application.save(update_fields=("created_at", "updated_at"))
        self._login_and_setup_session(client, prescriber)
        response = client.get(self.check_prev_applications_url)
        assert pretty_indented(
            parse_response_to_soup(
                response,
                ".c-form",
                replace_in_attr=[
                    ("href", f"/company/{job_application.to_company.pk}/card", "/company/[PK of Company]/card"),
                ],
            )
        ) == snapshot(name="allowed")
        response = client.post(self.check_prev_applications_url, data={"force_new_application": "force"})
        assertRedirects(response, self.application_jobs_url)

        # Reset URL is correct
        response = client.get(self.application_jobs_url)
        company_card_url = reverse("companies_views:card", kwargs={"company_pk": self.company.pk})
        assertContains(response, LINK_RESET_MARKUP % company_card_url, count=1)

    @freeze_time("2025-09-08 11:39")
    def test_with_previous_as_authorized_prescriber(self, client, snapshot):
        authorized_prescriber = PrescriberOrganizationFactory(authorized=True, with_membership=True).members.first()
        self._login_and_setup_session(client, authorized_prescriber)

        # Create a very recent application
        job_application = JobApplicationFactory(
            sent_by_prescriber_alone=True,
            job_seeker=self.job_seeker,
            to_company=self.company,
            with_iae_eligibility_diagnosis=True,
        )
        response = client.get(self.check_prev_applications_url)
        assert pretty_indented(
            parse_response_to_soup(
                response,
                ".c-form",
                replace_in_attr=[
                    ("href", str(self.job_seeker.public_id), "[Public ID of JobSeeker]"),
                    ("href", f"/company/{job_application.to_company.pk}/card", "/company/[PK of Company]/card"),
                    (
                        "href",
                        f"%2Fcompany%2F{job_application.to_company.pk}%2Fcard",
                        "%2Fcompany%2F[PK of Company]%2Fcard",
                    ),
                ],
            )
        ) == snapshot(name="blocked")

        # Don't allow to skip to another step
        response = client.get(self.application_jobs_url)
        assertContains(
            response, "Ce candidat a déjà postulé chez cet employeur durant les dernières 24 heures.", status_code=403
        )
        response = client.get(self.application_jobs_url)
        assert response.status_code == 404

        # Make it less recent to avoid the 403
        job_application.created_at = timezone.now() - datetime.timedelta(days=2)
        job_application.save(update_fields=("created_at", "updated_at"))
        self._login_and_setup_session(client, authorized_prescriber)
        response = client.get(self.check_prev_applications_url)
        assert pretty_indented(
            parse_response_to_soup(
                response,
                ".c-form",
                replace_in_attr=[
                    ("href", str(self.job_seeker.public_id), "[Public ID of JobSeeker]"),
                    ("href", f"/company/{job_application.to_company.pk}/card", "/company/[PK of Company]/card"),
                    (
                        "href",
                        f"%2Fcompany%2F{job_application.to_company.pk}%2Fcard",
                        "%2Fcompany%2F[PK of Company]%2Fcard",
                    ),
                ],
            )
        ) == snapshot(name="allowed update diagnosis")

        # Remove previous eligibility diagnosis to change the button label
        eligibility_diagnosis = job_application.eligibility_diagnosis
        job_application.eligibility_diagnosis = None
        job_application.save()
        eligibility_diagnosis.delete()
        response = client.get(self.check_prev_applications_url)
        assert pretty_indented(
            parse_response_to_soup(
                response,
                ".c-form",
                replace_in_attr=[
                    ("href", str(self.job_seeker.public_id), "[Public ID of JobSeeker]"),
                    ("href", f"/company/{job_application.to_company.pk}/card", "/company/[PK of Company]/card"),
                    (
                        "href",
                        f"%2Fcompany%2F{job_application.to_company.pk}%2Fcard",
                        "%2Fcompany%2F[PK of Company]%2Fcard",
                    ),
                ],
            )
        ) == snapshot(name="allowed validate diagnosis")

        response = client.post(self.check_prev_applications_url, data={"force_new_application": "force"})
        assertRedirects(response, self.application_jobs_url)

        # Reset URL is correct
        response = client.get(self.application_jobs_url)
        company_card_url = reverse("companies_views:card", kwargs={"company_pk": self.company.pk})
        assertContains(response, LINK_RESET_MARKUP % company_card_url, count=1)

    def test_no_previous_as_employer(self, client):
        self._login_and_setup_session(client, self.company.members.first())

        response = client.get(self.check_prev_applications_url)
        assertRedirects(response, self.application_jobs_url)

        response = client.get(self.application_jobs_url)
        assertNotContains(response, BACK_BUTTON_ARIA_LABEL)

    def test_with_previous_as_employer(self, client):
        JobApplicationFactory(sent_by_prescriber_alone=True, job_seeker=self.job_seeker, to_company=self.company)
        self._login_and_setup_session(client, self.company.members.first())

        response = client.get(self.check_prev_applications_url)
        assertContains(response, "Ce candidat a déjà postulé pour cette entreprise")
        response = client.post(self.check_prev_applications_url, data={"force_new_application": "force"})
        assertRedirects(response, self.application_jobs_url)

        response = client.get(self.application_jobs_url)
        assertNotContains(response, BACK_BUTTON_ARIA_LABEL)

    def test_no_previous_as_another_employer(self, client):
        another_company = CompanyFactory(with_membership=True)
        self._login_and_setup_session(client, another_company.members.first())

        response = client.get(self.check_prev_applications_url)
        assertRedirects(response, self.application_jobs_url)

        # Reset URL is correct
        response = client.get(self.application_jobs_url)
        company_card_url = reverse("companies_views:card", kwargs={"company_pk": self.company.pk})
        assertContains(response, LINK_RESET_MARKUP % company_card_url, count=1)

    @freeze_time("2025-09-08 11:39")
    def test_with_previous_as_another_employer(self, client, snapshot):
        employer = EmployerFactory(membership=True)
        self._login_and_setup_session(client, employer)

        # Create a very recent application
        job_application = JobApplicationFactory(
            sent_by_another_employer=True,
            sender=employer,
            job_seeker=self.job_seeker,
            to_company=self.company,
        )
        response = client.get(self.check_prev_applications_url)
        assert pretty_indented(
            parse_response_to_soup(
                response,
                ".c-form",
                replace_in_attr=[
                    ("href", f"/company/{job_application.to_company.pk}/card", "/company/[PK of Company]/card"),
                ],
            )
        ) == snapshot(name="blocked")

        # Don't allow to skip to another step
        response = client.get(self.application_jobs_url)
        assertContains(
            response, "Ce candidat a déjà postulé chez cet employeur durant les dernières 24 heures.", status_code=403
        )
        response = client.get(self.application_jobs_url)
        assert response.status_code == 404

        # Make it less recent to avoid the 403
        job_application.created_at = timezone.now() - datetime.timedelta(days=2)
        job_application.save(update_fields=("created_at", "updated_at"))
        self._login_and_setup_session(client, employer)
        response = client.get(self.check_prev_applications_url)
        assert pretty_indented(
            parse_response_to_soup(
                response,
                ".c-form",
                replace_in_attr=[
                    ("href", f"/company/{job_application.to_company.pk}/card", "/company/[PK of Company]/card"),
                ],
            )
        ) == snapshot(name="allowed")
        response = client.post(self.check_prev_applications_url, data={"force_new_application": "force"})
        assertRedirects(response, self.application_jobs_url)

        # Reset URL is correct
        response = client.get(self.application_jobs_url)
        company_card_url = reverse("companies_views:card", kwargs={"company_pk": self.company.pk})
        assertContains(response, LINK_RESET_MARKUP % company_card_url, count=1)
