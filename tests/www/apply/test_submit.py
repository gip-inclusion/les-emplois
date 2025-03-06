import datetime
import io
import uuid
from unittest import mock

import pytest
from dateutil.relativedelta import relativedelta
from django.conf import settings
from django.contrib import messages
from django.core.files.storage import storages
from django.urls import resolve, reverse
from django.utils import timezone
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

from itou.asp.models import AllocationDuration, Commune, Country, EducationLevel, RSAAllocation
from itou.companies.enums import CompanyKind, ContractType
from itou.eligibility.enums import CERTIFIABLE_ADMINISTRATIVE_CRITERIA_KINDS, AuthorKind
from itou.eligibility.models import (
    AdministrativeCriteria,
    EligibilityDiagnosis,
    GEIQAdministrativeCriteria,
    GEIQEligibilityDiagnosis,
)
from itou.gps.models import FollowUpGroup, FollowUpGroupMembership
from itou.job_applications.enums import JobApplicationState, QualificationLevel, QualificationType, SenderKind
from itou.job_applications.models import JobApplication
from itou.siae_evaluations.models import Sanctions
from itou.users.enums import LackOfNIRReason, LackOfPoleEmploiId
from itou.users.models import JobSeekerProfile, User
from itou.utils.mocks.address_format import mock_get_first_geocoding_data, mock_get_geocoding_data_by_ban_api_resolved
from itou.utils.models import InclusiveDateRange
from itou.utils.session import SessionNamespace
from itou.utils.templatetags.format_filters import format_nir
from itou.utils.templatetags.str_filters import mask_unless
from itou.utils.urls import add_url_params
from itou.utils.widgets import DuetDatePickerWidget
from itou.www.job_seekers_views.enums import JobSeekerSessionKinds
from tests.approvals.factories import ApprovalFactory, PoleEmploiApprovalFactory
from tests.cities.factories import create_city_geispolsheim, create_city_in_zrr, create_test_cities
from tests.companies.factories import CompanyFactory, CompanyMembershipFactory, CompanyWithMembershipAndJobsFactory
from tests.eligibility.factories import GEIQEligibilityDiagnosisFactory, IAEEligibilityDiagnosisFactory
from tests.geo.factories import ZRRFactory
from tests.gps.test import mock_advisor_list
from tests.institutions.factories import InstitutionWithMembershipFactory
from tests.job_applications.factories import JobApplicationFactory
from tests.prescribers.factories import (
    PrescriberOrganizationWithMembershipFactory,
    PrescriberPoleEmploiWithMembershipFactory,
)
from tests.siae_evaluations.factories import EvaluatedSiaeFactory
from tests.users.factories import (
    EmployerFactory,
    ItouStaffFactory,
    JobSeekerFactory,
    JobSeekerProfileFactory,
    PrescriberFactory,
)
from tests.users.test_models import user_with_approval_in_waiting_period
from tests.utils.test import KNOWN_SESSION_KEYS, assertSnapshotQueries


BACK_BUTTON_ARIA_LABEL = "Retourner à l’étape précédente"
LINK_RESET_MARKUP = (
    '<a href="%s" class="btn btn-link btn-ico ps-lg-0 w-100 w-lg-auto"'
    ' aria-label="Annuler la saisie de ce formulaire">'
)
CONFIRM_RESET_MARKUP = '<a href="%s" class="btn btn-sm btn-danger">Confirmer l\'annulation</a>'


def assert_contains_apply_nir_modal(response, job_seeker, with_personal_information=True):
    assertContains(
        response,
        f"""
        <div class="modal-body">
            <p>
                Le numéro {format_nir(job_seeker.jobseeker_profile.nir)} est associé au compte de
                <b>{mask_unless(job_seeker.get_full_name(), with_personal_information)}</b>.
            </p>
            <p>
                Si cette candidature n'est pas pour
                <b>{mask_unless(job_seeker.get_full_name(), with_personal_information)}</b>,
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
                <b>{mask_unless(job_seeker.get_full_name(), with_personal_information)}</b>.
            </p>
            <p>
                L'identité du candidat est une information clé pour la structure.
                Si cette candidature n'est pas pour
                <b>{mask_unless(job_seeker.get_full_name(), with_personal_information)}</b>,
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
        for viewname in (
            "apply:start",
            "apply:start_hire",
            "apply:pending_authorization_for_sender",
        ):
            url = reverse(viewname, kwargs={"company_pk": company.pk})
            response = client.get(url)
            assertRedirects(response, reverse("account_login") + f"?next={url}")

        job_seeker = JobSeekerFactory()
        for viewname in (
            "job_seekers_views:check_job_seeker_info",
            "apply:step_check_prev_applications",
            "apply:application_jobs",
            "apply:application_eligibility",
            "apply:application_geiq_eligibility",
            "apply:application_resume",
        ):
            url = reverse(viewname, kwargs={"company_pk": company.pk, "job_seeker_public_id": job_seeker.public_id})
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
        for viewname in (
            "job_seekers_views:check_job_seeker_info",
            "apply:step_check_prev_applications",
            "apply:application_jobs",
            "apply:application_eligibility",
            "apply:application_geiq_eligibility",
            "apply:application_resume",
        ):
            url = reverse(viewname, kwargs={"company_pk": company.pk, "job_seeker_public_id": prescriber.public_id})
            response = client.get(url)
            assert response.status_code == 404

    def test_access_without_session(self, client):
        company = CompanyFactory(with_jobs=True, with_membership=True)
        job_seeker = JobSeekerFactory()
        client.force_login(job_seeker)
        response = client.post(
            reverse(
                "apply:application_resume",
                kwargs={"company_pk": company.pk, "job_seeker_public_id": job_seeker.public_id},
            ),
            {"message": "Hire me?"},
        )
        assert JobApplication.objects.exists() is False
        assertRedirects(
            response,
            reverse(
                "apply:application_jobs",
                kwargs={"company_pk": company.pk, "job_seeker_public_id": job_seeker.public_id},
            ),
        )

    def test_resume_is_optional(self, client):
        company = CompanyFactory(with_jobs=True, with_membership=True)
        job_seeker = JobSeekerFactory()
        client.force_login(job_seeker)
        session = client.session
        session[f"job_application-{company.pk}"] = {"selected_jobs": []}
        session.save()
        response = client.post(
            reverse(
                "apply:application_resume",
                kwargs={"company_pk": company.pk, "job_seeker_public_id": job_seeker.public_id},
            ),
            {"message": "Hire me?"},
        )
        job_application = JobApplication.objects.get()
        assertRedirects(
            response,
            reverse("apply:application_end", kwargs={"company_pk": company.pk, "application_pk": job_application.pk}),
        )


class TestHire:
    def test_anonymous_access(self, client):
        company = CompanyFactory(with_jobs=True, with_membership=True)

        url = reverse("apply:start_hire", kwargs={"company_pk": company.pk})
        response = client.get(url)
        assertRedirects(response, reverse("account_login") + f"?next={url}")

        job_seeker = JobSeekerFactory()
        for viewname in (
            "job_seekers_views:check_job_seeker_info_for_hire",
            "apply:check_prev_applications_for_hire",
            "apply:eligibility_for_hire",
            "apply:geiq_eligibility_for_hire",
            "apply:geiq_eligibility_criteria_for_hire",
            "apply:hire_confirmation",
        ):
            url = reverse(viewname, kwargs={"company_pk": company.pk, "job_seeker_public_id": job_seeker.public_id})
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
            "job_seekers_views:create_job_seeker_step_1_for_hire",
            "job_seekers_views:create_job_seeker_step_2_for_hire",
            "job_seekers_views:create_job_seeker_step_3_for_hire",
            "job_seekers_views:create_job_seeker_step_end_for_hire",
        }
        user = JobSeekerFactory()

        client.force_login(user)
        for route in routes:
            with subtests.test(route=route):
                response = client.get(reverse(route, kwargs={"session_uuid": uuid.uuid4()}))
                assert response.status_code == 404

    def test_404_when_trying_to_update_a_prescriber(self, client):
        company = CompanyFactory(with_jobs=True, with_membership=True)
        prescriber = PrescriberFactory()
        client.force_login(company.members.first())
        params = {
            "job_seeker": prescriber.public_id,
            "from_url": reverse("dashboard:index"),
        }
        url = add_url_params(reverse("job_seekers_views:update_job_seeker_start"), params)
        response = client.get(url)
        assert response.status_code == 404

    def test_404_when_trying_to_hire_a_prescriber(self, client):
        company = CompanyFactory(with_jobs=True, with_membership=True)
        prescriber = PrescriberFactory()
        client.force_login(company.members.first())
        for viewname in (
            "job_seekers_views:check_job_seeker_info_for_hire",
            "apply:check_prev_applications_for_hire",
            "apply:eligibility_for_hire",
            "apply:geiq_eligibility_for_hire",
            "apply:geiq_eligibility_criteria_for_hire",
            "apply:hire_confirmation",
        ):
            url = reverse(viewname, kwargs={"company_pk": company.pk, "job_seeker_public_id": prescriber.public_id})
            response = client.get(url)
            assert response.status_code == 404

    def test_403_when_trying_to_hire_a_jobseeker_with_invalid_approval(self, client):
        company = CompanyFactory(with_membership=True)
        job_seeker = user_with_approval_in_waiting_period()
        client.force_login(company.members.first())
        for viewname in (
            "job_seekers_views:check_job_seeker_info_for_hire",
            "apply:check_prev_applications_for_hire",
            "apply:eligibility_for_hire",
            "apply:hire_confirmation",
        ):
            url = reverse(viewname, kwargs={"company_pk": company.pk, "job_seeker_public_id": job_seeker.public_id})
            response = client.get(url)
            assertContains(response, "Le candidat a terminé un parcours il y a moins de deux ans", status_code=403)


def test_check_nir_job_seeker_with_lack_of_nir_reason(client):
    """Apply as jobseeker."""

    company = CompanyWithMembershipAndJobsFactory(romes=("N1101", "N1105"))

    user = JobSeekerFactory(
        jobseeker_profile__birthdate=None,
        jobseeker_profile__nir="",
        jobseeker_profile__lack_of_nir_reason=LackOfNIRReason.TEMPORARY_NUMBER,
    )
    client.force_login(user)

    # Entry point.
    # ----------------------------------------------------------------------

    response = client.get(reverse("apply:start", kwargs={"company_pk": company.pk}))

    [job_seeker_session_name] = [k for k in client.session.keys() if k not in KNOWN_SESSION_KEYS]
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
        company = CompanyWithMembershipAndJobsFactory(romes=("N1101", "N1105"))
        Sanctions.objects.create(
            evaluated_siae=EvaluatedSiaeFactory(siae=company),
            suspension_dates=InclusiveDateRange(timezone.localdate() - relativedelta(days=1)),
        )

        user = JobSeekerFactory(jobseeker_profile__birthdate=None, jobseeker_profile__nir="")
        client.force_login(user)

        response = client.get(reverse("apply:start", kwargs={"company_pk": company.pk}))
        [job_seeker_session_name] = [k for k in client.session.keys() if k not in KNOWN_SESSION_KEYS]
        # The suspension does not prevent access to the process
        assertRedirects(
            response,
            expected_url=reverse(
                "job_seekers_views:check_nir_for_job_seeker", kwargs={"session_uuid": job_seeker_session_name}
            ),
        )

    def test_apply_as_jobseeker(self, client, pdf_file):
        """Apply as jobseeker."""

        company = CompanyWithMembershipAndJobsFactory(romes=("N1101", "N1105"))
        reset_url_company = reverse("companies_views:card", kwargs={"siae_id": company.pk})

        user = JobSeekerFactory(jobseeker_profile__birthdate=None, jobseeker_profile__nir="")
        client.force_login(user)

        # Entry point.
        # ----------------------------------------------------------------------

        response = client.get(reverse("apply:start", kwargs={"company_pk": company.pk}))

        [job_seeker_session_name] = [k for k in client.session.keys() if k not in KNOWN_SESSION_KEYS]
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
            kwargs={"company_pk": company.pk, "job_seeker_public_id": user.public_id},
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

        next_url = reverse(
            "apply:step_check_prev_applications",
            kwargs={"company_pk": company.pk, "job_seeker_public_id": user.public_id},
        )
        assertRedirects(response, next_url, target_status_code=302, fetch_redirect_response=False)

        # Step check previous job applications.
        # ----------------------------------------------------------------------

        response = client.get(next_url)

        next_url = reverse(
            "apply:application_jobs", kwargs={"company_pk": company.pk, "job_seeker_public_id": user.public_id}
        )
        assertRedirects(response, next_url)

        # Step application's jobs.
        # ----------------------------------------------------------------------

        response = client.get(next_url)
        assertContains(response, LINK_RESET_MARKUP % reset_url_company)

        selected_job = company.job_description_through.first()
        reset_url_job_description = reverse(
            "companies_views:job_description_card", kwargs={"job_description_id": selected_job.pk}
        )
        response = client.post(next_url, data={"selected_jobs": [selected_job.pk]})

        assert client.session[f"job_application-{company.pk}"] == {"selected_jobs": [selected_job.pk]}

        next_url = reverse(
            "apply:application_eligibility", kwargs={"company_pk": company.pk, "job_seeker_public_id": user.public_id}
        )
        assertRedirects(response, next_url, target_status_code=302, fetch_redirect_response=False)

        # Step application's eligibility.
        # ----------------------------------------------------------------------
        response = client.get(next_url)

        next_url = reverse(
            "apply:application_resume", kwargs={"company_pk": company.pk, "job_seeker_public_id": user.public_id}
        )
        assertRedirects(response, next_url)

        # Step application's resume.
        # ----------------------------------------------------------------------
        response = client.get(next_url)
        assertContains(response, "Envoyer la candidature")
        assertContains(response, CONFIRM_RESET_MARKUP % reset_url_job_description)

        with mock.patch(
            "itou.www.apply.views.submit_views.uuid.uuid4",
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
        assert job_application.resume_link == (
            f"{settings.AWS_S3_ENDPOINT_URL}tests/{storages['public'].location}"
            "/resume/11111111-1111-1111-1111-111111111111.pdf"
        )

        assert f"job_application-{company.pk}" not in client.session

        next_url = reverse(
            "apply:application_end", kwargs={"company_pk": company.pk, "application_pk": job_application.pk}
        )
        assertRedirects(response, next_url)

        # Step application's end.
        # ----------------------------------------------------------------------
        response = client.get(next_url)
        # 1 in desktop header
        # + 1 in mobile header
        # + 1 in the page content
        assertContains(response, reverse("dashboard:edit_user_info"), count=3)

        # GPS : a job seeker must not follow himself
        assert not FollowUpGroup.objects.exists()

    def test_apply_as_job_seeker_temporary_nir(self, client):
        """
        Full path is tested above. See test_apply_as_job_seeker.
        """
        company = CompanyWithMembershipAndJobsFactory(romes=("N1101", "N1105"))

        user = JobSeekerFactory(jobseeker_profile__nir="", with_pole_emploi_id=True)
        client.force_login(user)

        # Entry point.
        # ----------------------------------------------------------------------

        response = client.get(reverse("apply:start", kwargs={"company_pk": company.pk}), follow=True)
        assert response.status_code == 200

        # Follow all redirections until NIR.
        # ----------------------------------------------------------------------
        [job_seeker_session_name] = [k for k in client.session.keys() if k not in KNOWN_SESSION_KEYS]
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
            kwargs={"company_pk": company.pk, "job_seeker_public_id": user.public_id},
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
        company = CompanyWithMembershipAndJobsFactory(romes=("N1101", "N1105"))
        job_description = company.job_description_through.first()
        reset_url_job_description = reverse(
            "companies_views:job_description_card", kwargs={"job_description_id": job_description.pk}
        )

        job_seeker = JobSeekerFactory(
            jobseeker_profile__nir="141068078200557",
            with_pole_emploi_id=True,
            jobseeker_profile__birthdate=datetime.date(1941, 6, 12),
        )
        client.force_login(job_seeker)

        # Follow the application process.
        response = client.get(
            reverse("apply:start", kwargs={"company_pk": company.pk}),
            {"job_description_id": job_description.pk},
        )
        [job_seeker_session_name] = [
            k for k in client.session.keys() if k not in KNOWN_SESSION_KEYS and not k.startswith("job_application")
        ]
        next_url = reverse(
            "job_seekers_views:check_nir_for_job_seeker", kwargs={"session_uuid": job_seeker_session_name}
        )
        assertRedirects(response, next_url, target_status_code=302, fetch_redirect_response=False)
        response = client.get(next_url)

        next_url = reverse(
            "job_seekers_views:check_job_seeker_info",
            kwargs={"company_pk": company.pk, "job_seeker_public_id": job_seeker.public_id},
        )
        assertRedirects(response, next_url, target_status_code=302, fetch_redirect_response=False)
        response = client.get(next_url)

        next_url = reverse(
            "apply:step_check_prev_applications",
            kwargs={"company_pk": company.pk, "job_seeker_public_id": job_seeker.public_id},
        )
        assertRedirects(response, next_url, target_status_code=302, fetch_redirect_response=False)
        response = client.get(next_url)

        next_url = reverse(
            "apply:application_jobs", kwargs={"company_pk": company.pk, "job_seeker_public_id": job_seeker.public_id}
        )
        assertRedirects(response, next_url)
        response = client.get(next_url)

        assertContains(response, LINK_RESET_MARKUP % reset_url_job_description)

    def test_apply_as_job_seeker_sent_emails(self, client, pdf_file, mailoutbox):
        company = CompanyWithMembershipAndJobsFactory(romes=("N1101"))
        employer = company.members.get()
        # Inactive user that should not receive an email
        CompanyMembershipFactory(company=company, user__is_active=False)
        user = JobSeekerFactory()
        client.force_login(user)
        session = client.session
        session[f"job_application-{company.pk}"] = {"selected_jobs": []}
        session.save()

        with mock.patch(
            "itou.www.apply.views.submit_views.uuid.uuid4",
            return_value=uuid.UUID("11111111-1111-1111-1111-111111111111"),
        ):
            response = client.post(
                reverse(
                    "apply:application_resume",
                    kwargs={"company_pk": company.pk, "job_seeker_public_id": user.public_id},
                ),
                data={
                    "message": "Lorem ipsum dolor sit amet, consectetur adipiscing elit.",
                    "resume": pdf_file,
                },
            )
        job_application = JobApplication.objects.get()
        assertRedirects(
            response,
            reverse("apply:application_end", kwargs={"company_pk": company.pk, "application_pk": job_application.pk}),
        )

        assert JobApplication.objects.filter(sender=user, to_company=company).exists()
        assert len(mailoutbox) == 2
        assert mailoutbox[0].to == [employer.email]
        assert mailoutbox[1].to == [user.email]

    def test_apply_as_job_seeker_resume_not_pdf(self, client):
        company = CompanyWithMembershipAndJobsFactory(romes=("N1101"))
        user = JobSeekerFactory()
        client.force_login(user)
        session = client.session
        session[f"job_application-{company.pk}"] = {"selected_jobs": []}
        session.save()
        client.session.save()
        with io.BytesIO(b"Plain text") as text_file:
            text_file.name = "cv.txt"
            response = client.post(
                reverse(
                    "apply:application_resume",
                    kwargs={
                        "company_pk": company.pk,
                        "job_seeker_public_id": user.public_id,
                    },
                ),
                data={
                    "message": "Lorem ipsum dolor sit amet.",
                    "resume": text_file,
                },
            )
        assertContains(
            response,
            """
            <div id="form_errors">
                <div class="alert alert-danger" role="alert">
                    L&#x27;extension de fichier « txt » n’est pas autorisée. Les extensions autorisées sont : pdf.
                </div>
            </div>
            """,
            html=True,
            count=1,
        )
        assert JobApplication.objects.exists() is False

    def test_apply_as_job_seeker_resume_not_pdf_disguised_as_pdf(self, client):
        company = CompanyWithMembershipAndJobsFactory(romes=("N1101"))
        user = JobSeekerFactory()
        client.force_login(user)
        session = client.session
        session[f"job_application-{company.pk}"] = {"selected_jobs": []}
        session.save()
        with io.BytesIO(b"Plain text") as text_file:
            text_file.name = "cv.pdf"
            response = client.post(
                reverse(
                    "apply:application_resume",
                    kwargs={
                        "company_pk": company.pk,
                        "job_seeker_public_id": user.public_id,
                    },
                ),
                data={
                    "message": "Lorem ipsum dolor sit amet.",
                    "resume": text_file,
                },
            )
        assertContains(
            response,
            """
            <div id="form_errors">
                <div class="alert alert-danger" role="alert">
                    Le fichier doit être un fichier PDF valide.
                </div>
            </div>
            """,
            html=True,
            count=1,
        )
        assert JobApplication.objects.exists() is False

    def test_apply_as_job_seeker_resume_too_large(self, client):
        company = CompanyWithMembershipAndJobsFactory(romes=("N1101"))
        user = JobSeekerFactory()
        client.force_login(user)
        session = client.session
        session[f"job_application-{company.pk}"] = {"selected_jobs": []}
        session.save()
        with io.BytesIO(b"A" * (5 * 1024 * 1024 + 1)) as text_file:
            text_file.name = "cv.pdf"
            response = client.post(
                reverse(
                    "apply:application_resume",
                    kwargs={
                        "company_pk": company.pk,
                        "job_seeker_public_id": user.public_id,
                    },
                ),
                data={
                    "message": "Lorem ipsum dolor sit amet.",
                    "resume": text_file,
                },
            )
        assertContains(
            response,
            """
            <div id="form_errors">
                <div class="alert alert-danger" role="alert">
                    Le fichier doit faire moins de 5,0 Mo.
                </div>
            </div>
            """,
            html=True,
            count=1,
        )
        assert JobApplication.objects.exists() is False

    def test_apply_end_view_wo_phone_number_as_job_seeker(self, client):
        application = JobApplicationFactory(
            sender_kind=SenderKind.JOB_SEEKER, sender_company=None, job_seeker__phone=""
        )
        expected_html = (
            '<p class="text-warning fst-italic">L’ajout du numéro de téléphone permet à l’employeur de vous '
            "contacter plus facilement.</p>"
        )
        client.force_login(application.job_seeker)
        response = client.get(
            reverse(
                "apply:application_end",
                kwargs={
                    "company_pk": application.to_company.pk,
                    "application_pk": application.pk,
                },
            )
        )
        assertContains(response, expected_html, html=True)

    def test_apply_end_view_wo_phone_number_as_employer(self, client):
        application = JobApplicationFactory(
            sender_kind=SenderKind.EMPLOYER, sender_company=CompanyFactory(), job_seeker__phone=""
        )
        expected_html = (
            '<p class="text-warning fst-italic">L’ajout du numéro de téléphone facilitera '
            "la prise de contact avec le candidat.</p>"
        )
        client.force_login(application.to_company.members.first())
        response = client.get(
            reverse(
                "apply:application_end",
                kwargs={
                    "company_pk": application.to_company.pk,
                    "application_pk": application.pk,
                },
            )
        )
        assertContains(response, expected_html, html=True)

    def test_apply_end_view_wo_phone_number_as_prescriber(self, client):
        application = JobApplicationFactory(
            sender_kind=SenderKind.PRESCRIBER,
            sender_prescriber_organization=PrescriberPoleEmploiWithMembershipFactory(),
            job_seeker__phone="",
        )
        expected_html = (
            '<p class="text-warning fst-italic">L’ajout du numéro de téléphone facilitera '
            "la prise de contact avec le candidat.</p>"
        )
        client.force_login(application.sender_prescriber_organization.members.first())
        response = client.get(
            reverse(
                "apply:application_end",
                kwargs={
                    "company_pk": application.to_company.pk,
                    "application_pk": application.pk,
                },
            )
        )
        assertContains(response, expected_html, html=True)


@pytest.mark.ignore_unknown_variable_template_error("job_seeker")
class TestApplyAsAuthorizedPrescriber:
    @pytest.fixture(autouse=True)
    def setup_method(self, settings, mocker):
        [self.city] = create_test_cities(["67"], num_per_department=1)
        settings.API_BAN_BASE_URL = "http://ban-api"
        mocker.patch(
            "itou.utils.apis.geocoding.get_geocoding_data",
            side_effect=mock_get_geocoding_data_by_ban_api_resolved,
        )

    def test_apply_as_prescriber_with_pending_authorization(self, client, pdf_file):
        """Apply as prescriber that has pending authorization."""

        company = CompanyWithMembershipAndJobsFactory(romes=("N1101", "N1105"))
        from_url = reverse("companies_views:card", kwargs={"siae_id": company.pk})

        prescriber_organization = PrescriberOrganizationWithMembershipFactory(with_pending_authorization=True)
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

        response = client.get(reverse("apply:start", kwargs={"company_pk": company.pk}))

        next_url = reverse(
            "apply:pending_authorization_for_sender",
            kwargs={"company_pk": company.pk},
        )
        assertRedirects(response, next_url)

        # Step show warning message about pending authorization.
        # ----------------------------------------------------------------------

        response = client.get(next_url)

        params = {
            "tunnel": "sender",
            "company": company.pk,
            "from_url": from_url,
        }
        next_url = add_url_params(reverse("job_seekers_views:get_or_create_start"), params)
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
        [job_seeker_session_name] = [k for k in client.session.keys() if k not in KNOWN_SESSION_KEYS]
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
                "session_kind": JobSeekerSessionKinds.GET_OR_CREATE,
            },
            "apply": {"company_pk": company.pk},
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
            "birth_country": Country.france_id,
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
        }
        assert client.session[job_seeker_session_name] == expected_job_seeker_session

        next_url = reverse(
            "job_seekers_views:create_job_seeker_step_end_for_sender",
            kwargs={"session_uuid": job_seeker_session_name},
        )
        assertRedirects(response, next_url)

        response = client.get(next_url)
        assertContains(response, "Créer le compte candidat")

        mock_advisor_list(dummy_job_seeker.jobseeker_profile.nir)
        response = client.post(next_url)

        assert job_seeker_session_name not in client.session
        new_job_seeker = User.objects.get(email=dummy_job_seeker.email)

        assert new_job_seeker.jobseeker_profile.advisor_information.name == "Jean BON"
        assert new_job_seeker.jobseeker_profile.advisor_information.email == "jean.bon@francetravail.fr"
        assert new_job_seeker.jobseeker_profile.created_by_prescriber_organization == prescriber_organization

        next_url = reverse(
            "apply:application_jobs",
            kwargs={"company_pk": company.pk, "job_seeker_public_id": new_job_seeker.public_id},
        )
        assertRedirects(response, next_url)

        # Step application's jobs.
        # ----------------------------------------------------------------------

        response = client.get(next_url)
        assert response.status_code == 200

        selected_job = company.job_description_through.first()
        response = client.post(next_url, data={"selected_jobs": [selected_job.pk]})

        assert client.session[f"job_application-{company.pk}"] == {"selected_jobs": [selected_job.pk]}

        next_url = reverse(
            "apply:application_eligibility",
            kwargs={"company_pk": company.pk, "job_seeker_public_id": new_job_seeker.public_id},
        )
        assertRedirects(response, next_url, target_status_code=302, fetch_redirect_response=False)

        # Step application's eligibility.
        # ----------------------------------------------------------------------
        response = client.get(next_url)

        next_url = reverse(
            "apply:application_resume",
            kwargs={"company_pk": company.pk, "job_seeker_public_id": new_job_seeker.public_id},
        )
        assertRedirects(response, next_url)

        # Step application's resume.
        # ----------------------------------------------------------------------
        response = client.get(next_url)
        assertContains(response, "Postuler")

        with mock.patch(
            "itou.www.apply.views.submit_views.uuid.uuid4",
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
        assert (
            job_application.resume_link == f"{settings.AWS_S3_ENDPOINT_URL}"
            f"tests/{storages['public'].location}/resume/11111111-1111-1111-1111-111111111111.pdf"
        )

        assert f"job_application-{company.pk}" not in client.session

        next_url = reverse(
            "apply:application_end", kwargs={"company_pk": company.pk, "application_pk": job_application.pk}
        )
        assertRedirects(response, next_url)

        # Step application's end.
        # ----------------------------------------------------------------------
        response = client.get(next_url)
        assert response.status_code == 200

    @freeze_time()
    def test_apply_as_authorized_prescriber(self, client, pdf_file):
        company = CompanyWithMembershipAndJobsFactory(romes=("N1101", "N1105"))
        reset_url_company = reverse("companies_views:card", kwargs={"siae_id": company.pk})

        # test ZRR / QPV template loading
        city = create_city_in_zrr()
        ZRRFactory(insee_code=city.code_insee)

        prescriber_organization = PrescriberOrganizationWithMembershipFactory(authorized=True)
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

        response = client.get(reverse("apply:start", kwargs={"company_pk": company.pk}))

        params = {
            "tunnel": "sender",
            "company": company.pk,
            "from_url": reset_url_company,
        }
        next_url = add_url_params(reverse("job_seekers_views:get_or_create_start"), params)
        assertRedirects(response, next_url, target_status_code=302, fetch_redirect_response=False)

        response = client.get(next_url)
        [job_seeker_session_name] = [k for k in client.session.keys() if k not in KNOWN_SESSION_KEYS]
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
                "session_kind": JobSeekerSessionKinds.GET_OR_CREATE,
            },
            "apply": {"company_pk": company.pk},
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
            "birth_country": Country.france_id,
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
            kwargs={"company_pk": company.pk, "job_seeker_public_id": new_job_seeker.public_id},
        )
        assertRedirects(response, next_url)

        # Step application's jobs.
        # ----------------------------------------------------------------------

        response = client.get(next_url)
        assertContains(response, LINK_RESET_MARKUP % reset_url_company)

        selected_job = company.job_description_through.first()
        reset_url_job_description = reverse(
            "companies_views:job_description_card", kwargs={"job_description_id": selected_job.pk}
        )
        response = client.post(next_url, data={"selected_jobs": [selected_job.pk]})

        assert client.session[f"job_application-{company.pk}"] == {"selected_jobs": [selected_job.pk]}

        next_url = reverse(
            "apply:application_eligibility",
            kwargs={"company_pk": company.pk, "job_seeker_public_id": new_job_seeker.public_id},
        )
        assertRedirects(response, next_url)

        # Step application's eligibility.
        # ----------------------------------------------------------------------

        # Simulate address in qpv. If the address is in qpv, the known_criteria template
        # should be used
        with mock.patch(
            "itou.common_apps.address.models.AddressMixin.address_in_qpv",
            return_value=True,
        ):
            response = client.get(next_url)
            assertContains(response, CONFIRM_RESET_MARKUP % reset_url_job_description)
            assert not EligibilityDiagnosis.objects.has_considered_valid(new_job_seeker, for_siae=company)
            assertTemplateUsed(response, "apply/includes/known_criteria.html", count=1)

        response = client.post(next_url, {"level_1_1": True})
        diag = EligibilityDiagnosis.objects.last_considered_valid(job_seeker=new_job_seeker, for_siae=company)
        assert diag.is_valid is True
        assert diag.expires_at == timezone.localdate() + relativedelta(months=6)

        next_url = reverse(
            "apply:application_resume",
            kwargs={"company_pk": company.pk, "job_seeker_public_id": new_job_seeker.public_id},
        )
        assertRedirects(response, next_url)

        # Step application's resume.
        # ----------------------------------------------------------------------
        response = client.get(next_url)
        assertContains(response, "Postuler")
        assertContains(response, CONFIRM_RESET_MARKUP % reset_url_job_description)

        with mock.patch(
            "itou.www.apply.views.submit_views.uuid.uuid4",
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
        assert job_application.resume_link == (
            f"{settings.AWS_S3_ENDPOINT_URL}tests/{storages['public'].location}"
            "/resume/11111111-1111-1111-1111-111111111111.pdf"
        )

        assert f"job_application-{company.pk}" not in client.session

        next_url = reverse(
            "apply:application_end", kwargs={"company_pk": company.pk, "application_pk": job_application.pk}
        )
        assertRedirects(response, next_url)

        # Step application's end.
        # ----------------------------------------------------------------------
        response = client.get(next_url)
        assert response.status_code == 200

        # Check GPS group
        # ----------------------------------------------------------------------
        group = FollowUpGroup.objects.get()
        assert group.beneficiary == new_job_seeker
        membership = FollowUpGroupMembership.objects.get(follow_up_group=group)
        assert membership.member == user
        assert membership.creator == user

    def test_cannot_create_job_seeker_with_pole_emploi_email(self, client):
        company = CompanyMembershipFactory().company

        prescriber_organization = PrescriberOrganizationWithMembershipFactory(authorized=True)
        user = prescriber_organization.members.first()
        client.force_login(user)

        # Init session
        start_url = reverse("apply:start", kwargs={"company_pk": company.pk})
        client.get(start_url, follow=True)
        [job_seeker_session_name] = [k for k in client.session.keys() if k not in KNOWN_SESSION_KEYS]
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
        company = CompanyFactory(name="Les petits pains", with_membership=True, subject_to_eligibility=True)
        job_seeker = JobSeekerFactory()
        IAEEligibilityDiagnosisFactory(from_employer=True, author_siae=company, job_seeker=job_seeker)
        prescriber_organization = PrescriberOrganizationWithMembershipFactory(authorized=True)
        prescriber = prescriber_organization.members.get()
        client.force_login(prescriber)
        apply_session = SessionNamespace(client.session, f"job_application-{company.pk}")
        apply_session.init({"selected_jobs": []})
        apply_session.save()
        response = client.get(
            reverse(
                "apply:application_eligibility",
                kwargs={
                    "company_pk": company.pk,
                    "job_seeker_public_id": str(job_seeker.public_id),
                },
            )
        )
        assert response.status_code == 200
        assert response.context["eligibility_diagnosis"] is None

    def test_apply_with_temporary_nir(self, client):
        company = CompanyWithMembershipAndJobsFactory(romes=["N1101"])
        prescriber_organization = PrescriberOrganizationWithMembershipFactory(authorized=True)
        user = prescriber_organization.members.get()
        client.force_login(user)

        response = client.get(reverse("apply:start", kwargs={"company_pk": company.pk}))

        params = {
            "tunnel": "sender",
            "company": company.pk,
            "from_url": reverse("companies_views:card", kwargs={"siae_id": company.pk}),
        }
        next_url = add_url_params(reverse("job_seekers_views:get_or_create_start"), params)
        assertRedirects(response, next_url, target_status_code=302, fetch_redirect_response=False)

        response = client.get(next_url)
        [job_seeker_session_name] = [k for k in client.session.keys() if k not in KNOWN_SESSION_KEYS]
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
        cities = create_test_cities(["67"], num_per_department=10)
        self.city = cities[0]
        settings.API_BAN_BASE_URL = "http://ban-api"
        mocker.patch(
            "itou.utils.apis.geocoding.get_geocoding_data",
            side_effect=mock_get_geocoding_data_by_ban_api_resolved,
        )

    def test_apply_as_prescriber_with_suspension_sanction(self, client):
        company = CompanyWithMembershipAndJobsFactory(romes=("N1101", "N1105"))
        Sanctions.objects.create(
            evaluated_siae=EvaluatedSiaeFactory(siae=company),
            suspension_dates=InclusiveDateRange(timezone.localdate() - relativedelta(days=1)),
        )

        user = PrescriberFactory()
        client.force_login(user)

        response = client.get(reverse("apply:start", kwargs={"company_pk": company.pk}), follow=True)
        [job_seeker_session_name] = [k for k in client.session.keys() if k not in KNOWN_SESSION_KEYS]

        # The suspension does not prevent the access to the process
        assertRedirects(
            response,
            expected_url=reverse(
                "job_seekers_views:check_nir_for_sender", kwargs={"session_uuid": job_seeker_session_name}
            ),
        )

    @pytest.mark.ignore_unknown_variable_template_error("job_seeker")
    def test_apply_as_prescriber(self, client, pdf_file):
        company = CompanyWithMembershipAndJobsFactory(romes=("N1101", "N1105"))
        reset_url_company = reverse("companies_views:card", kwargs={"siae_id": company.pk})

        user = PrescriberFactory()
        client.force_login(user)

        dummy_job_seeker = JobSeekerFactory.build(
            jobseeker_profile__with_hexa_address=True,
            jobseeker_profile__with_education_level=True,
            with_ban_geoloc_address=True,
            jobseeker_profile__nir="178122978200508",
            jobseeker_profile__birthdate=datetime.date(1978, 12, 20),
            title="M",
        )
        existing_job_seeker = JobSeekerFactory()

        # Entry point.
        # ----------------------------------------------------------------------

        response = client.get(reverse("apply:start", kwargs={"company_pk": company.pk}))
        params = {
            "tunnel": "sender",
            "company": company.pk,
            "from_url": reset_url_company,
        }
        next_url = add_url_params(reverse("job_seekers_views:get_or_create_start"), params)
        assertRedirects(response, next_url, target_status_code=302, fetch_redirect_response=False)

        response = client.get(next_url)
        [job_seeker_session_name] = [k for k in client.session.keys() if k not in KNOWN_SESSION_KEYS]
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
                "session_kind": JobSeekerSessionKinds.GET_OR_CREATE,
            },
            "apply": {"company_pk": company.pk},
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
            "birth_country": Country.france_id,
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
            kwargs={"company_pk": company.pk, "job_seeker_public_id": new_job_seeker.public_id},
        )
        assertRedirects(response, next_url)

        # Step application's jobs.
        # ----------------------------------------------------------------------

        response = client.get(next_url)
        assertContains(response, LINK_RESET_MARKUP % reset_url_company)

        selected_job = company.job_description_through.first()
        reset_url_job_description = reverse(
            "companies_views:job_description_card", kwargs={"job_description_id": selected_job.pk}
        )
        response = client.post(next_url, data={"selected_jobs": [selected_job.pk]})

        assert client.session[f"job_application-{company.pk}"] == {"selected_jobs": [selected_job.pk]}

        next_url = reverse(
            "apply:application_eligibility",
            kwargs={"company_pk": company.pk, "job_seeker_public_id": new_job_seeker.public_id},
        )
        assertRedirects(response, next_url, target_status_code=302, fetch_redirect_response=False)

        # Step application's eligibility.
        # ----------------------------------------------------------------------
        response = client.get(next_url)

        next_url = reverse(
            "apply:application_resume",
            kwargs={"company_pk": company.pk, "job_seeker_public_id": new_job_seeker.public_id},
        )
        assertRedirects(response, next_url)

        # Step application's resume.
        # ----------------------------------------------------------------------
        response = client.get(next_url)
        assertContains(response, "Postuler")
        assertContains(response, CONFIRM_RESET_MARKUP % reset_url_job_description)

        with mock.patch(
            "itou.www.apply.views.submit_views.uuid.uuid4",
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

        assert job_application.resume_link == (
            f"{settings.AWS_S3_ENDPOINT_URL}tests/{storages['public'].location}"
            "/resume/11111111-1111-1111-1111-111111111111.pdf"
        )

        assert f"job_application-{company.pk}" not in client.session

        next_url = reverse(
            "apply:application_end", kwargs={"company_pk": company.pk, "application_pk": job_application.pk}
        )
        assertRedirects(response, next_url)

        # Step application's end.
        # ----------------------------------------------------------------------
        response = client.get(next_url)
        assert response.status_code == 200

        # GPS : no following for not authorized prescribers
        # ----------------------------------------------------------------------
        assert not FollowUpGroup.objects.exists()

    def test_check_info_as_prescriber_for_job_seeker_with_incomplete_info(self, client):
        company = CompanyFactory(with_membership=True, with_jobs=True, romes=("N1101", "N1105"))
        user = PrescriberFactory()
        client.force_login(user)

        dummy_job_seeker = JobSeekerFactory(
            jobseeker_profile__with_hexa_address=True,
            jobseeker_profile__with_education_level=True,
            with_ban_geoloc_address=True,
            jobseeker_profile__nir="178122978200508",
            jobseeker_profile__birthdate=None,
            title="M",
        )

        next_url = reverse(
            "job_seekers_views:check_job_seeker_info",
            kwargs={"company_pk": company.pk, "job_seeker_public_id": dummy_job_seeker.public_id},
        )

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


@pytest.mark.ignore_unknown_variable_template_error("job_seeker")
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
        company = CompanyWithMembershipAndJobsFactory(romes=("N1101", "N1105"))
        # Only authorized prescribers can add a NIR.
        # See User.can_add_nir
        prescriber_organization = PrescriberOrganizationWithMembershipFactory(authorized=True)
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
        job_seeker = JobSeekerFactory(jobseeker_profile__nir="", with_pole_emploi_id=True)
        # Create an approval to bypass the eligibility diagnosis step.
        PoleEmploiApprovalFactory(
            birthdate=job_seeker.jobseeker_profile.birthdate,
            pole_emploi_id=job_seeker.jobseeker_profile.pole_emploi_id,
        )
        company, user = self.create_test_data()
        client.force_login(user)

        # Follow all redirections…
        response = client.get(reverse("apply:start", kwargs={"company_pk": company.pk}), follow=True)

        # …until a job seeker has to be determined.
        assert response.status_code == 200
        last_url = response.redirect_chain[-1][0]
        [job_seeker_session_name] = [k for k in client.session.keys() if k not in KNOWN_SESSION_KEYS]
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
                "from_url": reverse("companies_views:card", kwargs={"siae_id": company.pk}),
                "session_kind": JobSeekerSessionKinds.GET_OR_CREATE,
            },
            "apply": {"company_pk": company.pk},
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
                kwargs={"company_pk": company.pk, "job_seeker_public_id": job_seeker.public_id},
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
            jobseeker_profile__lack_of_nir_reason=LackOfNIRReason.TEMPORARY_NUMBER,
            with_pole_emploi_id=True,
        )
        # Create an approval to bypass the eligibility diagnosis step.
        PoleEmploiApprovalFactory(
            birthdate=job_seeker.jobseeker_profile.birthdate,
            pole_emploi_id=job_seeker.jobseeker_profile.pole_emploi_id,
        )
        siae, user = self.create_test_data()
        client.force_login(user)

        # Follow all redirections…
        response = client.get(reverse("apply:start", kwargs={"company_pk": siae.pk}), follow=True)
        [job_seeker_session_name] = [k for k in client.session.keys() if k not in KNOWN_SESSION_KEYS]

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
                "from_url": reverse("companies_views:card", kwargs={"siae_id": siae.pk}),
                "session_kind": JobSeekerSessionKinds.GET_OR_CREATE,
            },
            "apply": {"company_pk": siae.pk},
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
                kwargs={"company_pk": siae.pk, "job_seeker_public_id": job_seeker.public_id},
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
        settings.API_BAN_BASE_URL = "http://ban-api"
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
        [job_seeker_session_name] = [k for k in client.session.keys() if k not in KNOWN_SESSION_KEYS]
        assertRedirects(
            response,
            expected_url=reverse(
                "job_seekers_views:check_nir_for_sender", kwargs={"session_uuid": job_seeker_session_name}
            ),
        )
        assert client.session[job_seeker_session_name].get("apply").get("company_pk") == company_2.pk

    def test_apply_as_siae_with_suspension_sanction(self, client):
        company = CompanyWithMembershipAndJobsFactory(romes=("N1101", "N1105"))
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
            else reverse("companies_views:card", kwargs={"siae_id": company.pk})
        )

        existing_job_seeker = JobSeekerFactory()

        # Entry point.
        # ----------------------------------------------------------------------

        response = client.get(reverse("apply:start", kwargs={"company_pk": company.pk}))

        params = {
            "tunnel": "sender",
            "company": company.pk,
            "from_url": reset_url,
        }
        next_url = add_url_params(reverse("job_seekers_views:get_or_create_start"), params)
        assertRedirects(response, next_url, target_status_code=302, fetch_redirect_response=False)

        response = client.get(next_url)
        [job_seeker_session_name] = [k for k in client.session.keys() if k not in KNOWN_SESSION_KEYS]
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
            "config": {"tunnel": "sender", "from_url": reset_url, "session_kind": JobSeekerSessionKinds.GET_OR_CREATE},
            "apply": {"company_pk": company.pk},
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
            "birth_country": Country.france_id,
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
            kwargs={"company_pk": company.pk, "job_seeker_public_id": new_job_seeker.public_id},
        )
        assertRedirects(response, next_url)

        # Step application's jobs.
        # ----------------------------------------------------------------------

        response = client.get(next_url)
        assertContains(response, LINK_RESET_MARKUP % reset_url)

        selected_job = company.job_description_through.first()
        # Autoprescription: after job selection, reset button sends to dashboard,
        # otherwise sends to job description card
        reset_url = (
            reverse("dashboard:index")
            if company in user.company_set.all()
            else reverse("companies_views:job_description_card", kwargs={"job_description_id": selected_job.pk})
        )
        response = client.post(next_url, data={"selected_jobs": [selected_job.pk]})

        assert client.session[f"job_application-{company.pk}"] == {"selected_jobs": [selected_job.pk]}

        next_url = reverse(
            "apply:application_eligibility",
            kwargs={"company_pk": company.pk, "job_seeker_public_id": new_job_seeker.public_id},
        )
        assertRedirects(response, next_url, target_status_code=302, fetch_redirect_response=False)

        # Step application's eligibility.
        # ----------------------------------------------------------------------
        response = client.get(next_url)

        next_url = reverse(
            "apply:application_resume",
            kwargs={"company_pk": company.pk, "job_seeker_public_id": new_job_seeker.public_id},
        )
        assertRedirects(response, next_url)

        # Step application's resume.
        # ----------------------------------------------------------------------
        response = client.get(next_url)
        assertContains(response, "Enregistrer" if user in company.members.all() else "Postuler")
        assertContains(response, CONFIRM_RESET_MARKUP % reset_url)

        with mock.patch(
            "itou.www.apply.views.submit_views.uuid.uuid4",
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

        assert job_application.resume_link == (
            f"{settings.AWS_S3_ENDPOINT_URL}tests/{storages['public'].location}"
            "/resume/11111111-1111-1111-1111-111111111111.pdf"
        )

        assert f"job_application-{company.pk}" not in client.session

        next_url = reverse(
            "apply:application_end", kwargs={"company_pk": company.pk, "application_pk": job_application.pk}
        )
        assertRedirects(response, next_url)

        # Step application's end.
        # ----------------------------------------------------------------------
        response = client.get(next_url)
        assert response.status_code == 200

        # Check GPS group
        # ----------------------------------------------------------------------
        group = FollowUpGroup.objects.get()
        assert group.beneficiary == new_job_seeker
        membership = FollowUpGroupMembership.objects.get(follow_up_group=group)
        assert membership.member == user
        assert membership.creator == user

    @pytest.mark.ignore_unknown_variable_template_error("job_seeker")
    def test_apply_as_employer(self, client, pdf_file):
        company = CompanyWithMembershipAndJobsFactory(romes=("N1101", "N1105"))
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

    @pytest.mark.ignore_unknown_variable_template_error("job_seeker")
    def test_apply_as_another_employer(self, client, pdf_file):
        company = CompanyFactory(with_membership=True, with_jobs=True, romes=("N1101", "N1105"))
        employer = EmployerFactory(with_company=True)
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
        employer = EmployerFactory(with_company=True)
        client.force_login(employer)

        dummy_job_seeker = JobSeekerFactory(
            jobseeker_profile__with_hexa_address=True,
            jobseeker_profile__with_education_level=True,
            with_ban_geoloc_address=True,
            jobseeker_profile__nir="278122978200555",
            jobseeker_profile__birthdate=None,
            title="MME",
        )

        next_url = reverse(
            "job_seekers_views:check_job_seeker_info",
            kwargs={"company_pk": company.pk, "job_seeker_public_id": dummy_job_seeker.public_id},
        )

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

    @pytest.mark.ignore_unknown_variable_template_error("job_seeker")
    def test_cannot_create_job_seeker_with_pole_emploi_email(self, client):
        # It's unlikely to happen
        membership = CompanyMembershipFactory()
        company = membership.company
        user = membership.user
        client.force_login(user)

        # Init session
        start_url = reverse("apply:start", kwargs={"company_pk": company.pk})
        client.get(start_url, follow=True)
        [job_seeker_session_name] = [k for k in client.session.keys() if k not in KNOWN_SESSION_KEYS]
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


class TestDirectHireFullProcess:
    @pytest.fixture(autouse=True)
    def setup_method(self, settings, mocker):
        settings.API_BAN_BASE_URL = "http://ban-api"
        mocker.patch(
            "itou.utils.apis.geocoding.get_geocoding_data",
            side_effect=mock_get_geocoding_data_by_ban_api_resolved,
        )

    def test_perms_for_company(self, client):
        """A company can hire only for itself."""
        company_1 = CompanyFactory(with_membership=True)
        company_2 = CompanyFactory(with_membership=True)

        user = company_1.members.first()
        client.force_login(user)

        response = client.get(reverse("apply:start_hire", kwargs={"company_pk": company_2.pk}))
        assert response.status_code == 403

    def test_hire_as_siae_with_suspension_sanction(self, client):
        company = CompanyWithMembershipAndJobsFactory(romes=("N1101", "N1105"))
        Sanctions.objects.create(
            evaluated_siae=EvaluatedSiaeFactory(siae=company),
            suspension_dates=InclusiveDateRange(timezone.localdate() - relativedelta(days=1)),
        )

        user = company.members.first()
        client.force_login(user)

        response = client.get(
            reverse(
                "apply:eligibility_for_hire",
                kwargs={"company_pk": company.pk, "job_seeker_public_id": JobSeekerFactory().public_id},
            )
        )
        assertContains(
            response,
            "suite aux mesures prises dans le cadre du contrôle a posteriori",
            status_code=403,
        )

    @pytest.mark.ignore_unknown_variable_template_error("is_subject_to_eligibility_rules", "job_seeker")
    @freeze_time()
    def test_hire_as_company(self, client):
        """Apply as company (and create new job seeker)"""

        company = CompanyWithMembershipAndJobsFactory(romes=("N1101", "N1105"))
        reset_url_dashboard = reverse("dashboard:index")

        user = company.members.first()
        client.force_login(user)

        dummy_job_seeker = JobSeekerFactory.build(
            jobseeker_profile__with_hexa_address=True,
            jobseeker_profile__with_education_level=True,
            with_ban_geoloc_address=True,
            jobseeker_profile__nir="178122978200508",
            jobseeker_profile__birthdate=datetime.date(1978, 12, 20),
            title="M",
        )
        existing_job_seeker = JobSeekerFactory()

        geispolsheim = create_city_geispolsheim()

        # Init session
        response = client.get(reverse("apply:start_hire", kwargs={"company_pk": company.pk}), follow=True)
        [job_seeker_session_name] = [k for k in client.session.keys() if k not in KNOWN_SESSION_KEYS]
        check_nir_url = reverse(
            "job_seekers_views:check_nir_for_hire", kwargs={"session_uuid": job_seeker_session_name}
        )

        # Step determine the job seeker with a NIR. First try: NIR is found
        # ----------------------------------------------------------------------

        response = client.get(check_nir_url)
        assertContains(response, LINK_RESET_MARKUP % reset_url_dashboard)

        response = client.post(check_nir_url, data={"nir": existing_job_seeker.jobseeker_profile.nir, "preview": 1})
        assert_contains_apply_nir_modal(response, existing_job_seeker)

        # Step determine the job seeker with a NIR. Second try: NIR is not found
        # ----------------------------------------------------------------------

        response = client.post(check_nir_url, data={"nir": dummy_job_seeker.jobseeker_profile.nir, "preview": 1})

        next_url = reverse(
            "job_seekers_views:search_by_email_for_hire",
            kwargs={"session_uuid": job_seeker_session_name},
        )
        assertRedirects(response, next_url)

        # Step get job seeker e-mail. First try: email is found
        # ----------------------------------------------------------------------

        response = client.get(next_url)
        assertContains(response, CONFIRM_RESET_MARKUP % reset_url_dashboard)

        response = client.post(
            next_url,
            data={"email": existing_job_seeker.email, "preview": 1},
        )

        assert_contains_apply_email_modal(response, existing_job_seeker)

        # Step get job seeker e-mail. Second try: email is not found
        # ----------------------------------------------------------------------

        response = client.post(next_url, data={"email": dummy_job_seeker.email, "confirm": "1"})

        expected_job_seeker_session = {
            "config": {
                "tunnel": "hire",
                "from_url": reset_url_dashboard,
                "session_kind": JobSeekerSessionKinds.GET_OR_CREATE,
            },
            "apply": {"company_pk": company.pk},
            "profile": {
                "nir": dummy_job_seeker.jobseeker_profile.nir,
            },
            "user": {
                "email": dummy_job_seeker.email,
            },
        }
        assert client.session[job_seeker_session_name] == expected_job_seeker_session

        next_url = reverse(
            "job_seekers_views:create_job_seeker_step_1_for_hire",
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
                "job_seekers_views:search_by_email_for_hire",
                kwargs={"session_uuid": job_seeker_session_name},
            ),
        )
        assertContains(response, CONFIRM_RESET_MARKUP % reset_url_dashboard)

        birthdate = dummy_job_seeker.jobseeker_profile.birthdate

        # Let's check for consistency between the NIR, the birthdate and the title.
        # ----------------------------------------------------------------------

        post_data = {
            "title": "MME",  # inconsistent title
            "first_name": dummy_job_seeker.first_name,
            "last_name": dummy_job_seeker.last_name,
            "birthdate": birthdate,
            "birth_place": Commune.objects.by_insee_code_and_period("64483", birthdate).pk,
            "birth_country": Country.objects.get(code=Country.INSEE_CODE_FRANCE).pk,
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
        assertContains(response, JobSeekerProfile.ERROR_JOBSEEKER_INCONSISTENT_NIR_BIRTHDATE % "")

        # Resume to valid data and proceed with "normal" flow.
        # ----------------------------------------------------------------------

        birth_place_id = Commune.objects.by_insee_code_and_period(geispolsheim.code_insee, birthdate).id
        birth_country_id = Country.france_id
        post_data = {
            "title": dummy_job_seeker.title,
            "first_name": dummy_job_seeker.first_name,
            "last_name": dummy_job_seeker.last_name,
            "birthdate": birthdate,
            "lack_of_nir": False,
            "lack_of_nir_reason": "",
            "birth_place": birth_place_id,
            "birth_country": birth_country_id,
        }
        response = client.post(next_url, data=post_data)
        expected_job_seeker_session["profile"]["birthdate"] = post_data.pop("birthdate")
        expected_job_seeker_session["profile"]["lack_of_nir_reason"] = post_data.pop("lack_of_nir_reason")
        expected_job_seeker_session["profile"]["birth_place"] = post_data.pop("birth_place")
        expected_job_seeker_session["profile"]["birth_country"] = post_data.pop("birth_country")
        expected_job_seeker_session["user"] |= post_data
        assert client.session[job_seeker_session_name] == expected_job_seeker_session

        next_url = reverse(
            "job_seekers_views:create_job_seeker_step_2_for_hire",
            kwargs={"session_uuid": job_seeker_session_name},
        )
        assertRedirects(response, next_url)

        response = client.get(next_url)
        assertContains(response, CONFIRM_RESET_MARKUP % reset_url_dashboard)

        post_data = {
            "ban_api_resolved_address": dummy_job_seeker.geocoding_address,
            "address_line_1": dummy_job_seeker.address_line_1,
            "post_code": geispolsheim.post_codes[0],
            "insee_code": geispolsheim.code_insee,
            "city": geispolsheim.name,
            "phone": dummy_job_seeker.phone,
            "fill_mode": "ban_api",
        }

        response = client.post(next_url, data=post_data)

        expected_job_seeker_session["user"] |= post_data | {"address_line_2": "", "address_for_autocomplete": None}
        assert client.session[job_seeker_session_name] == expected_job_seeker_session

        next_url = reverse(
            "job_seekers_views:create_job_seeker_step_3_for_hire",
            kwargs={"session_uuid": job_seeker_session_name},
        )
        assertRedirects(response, next_url)

        response = client.get(next_url)
        assertContains(response, CONFIRM_RESET_MARKUP % reset_url_dashboard)

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
        }
        assert client.session[job_seeker_session_name] == expected_job_seeker_session

        next_url = reverse(
            "job_seekers_views:create_job_seeker_step_end_for_hire",
            kwargs={"session_uuid": job_seeker_session_name},
        )
        assertRedirects(response, next_url)

        response = client.get(next_url)
        assertContains(response, CONFIRM_RESET_MARKUP % reset_url_dashboard)

        response = client.post(next_url)

        assert job_seeker_session_name not in client.session
        new_job_seeker = User.objects.get(email=dummy_job_seeker.email)
        assert new_job_seeker.jobseeker_profile.nir

        next_url = reverse(
            "apply:eligibility_for_hire",
            kwargs={"company_pk": company.pk, "job_seeker_public_id": new_job_seeker.public_id},
        )
        assertRedirects(response, next_url)

        # Step eligibility diagnosis
        # ----------------------------------------------------------------------

        response = client.get(next_url)
        assertTemplateNotUsed(response, "approvals/includes/box.html")

        criterion1 = (
            AdministrativeCriteria.objects.level1().exclude(kind__in=CERTIFIABLE_ADMINISTRATIVE_CRITERIA_KINDS).first()
        )
        [criterion2, criterion3] = AdministrativeCriteria.objects.level2().exclude(
            kind__in=CERTIFIABLE_ADMINISTRATIVE_CRITERIA_KINDS
        )[:2]
        response = client.post(
            next_url,
            data={
                # Administrative criteria level 1.
                f"{criterion1.key}": "on",
                # Administrative criteria level 2.
                f"{criterion2.key}": "on",
                f"{criterion3.key}": "on",
            },
        )

        next_url = reverse(
            "apply:hire_confirmation",
            kwargs={"company_pk": company.pk, "job_seeker_public_id": new_job_seeker.public_id},
        )
        assertRedirects(response, next_url)
        diag = EligibilityDiagnosis.objects.last_considered_valid(job_seeker=new_job_seeker, for_siae=company)
        assert diag.expires_at == timezone.localdate() + EligibilityDiagnosis.EMPLOYER_DIAGNOSIS_VALIDITY_TIMEDELTA

        # Hire confirmation
        # ----------------------------------------------------------------------
        response = client.get(next_url)
        assertTemplateNotUsed(response, "approvals/includes/box.html")
        assertContains(response, "Valider l’embauche")
        check_infos_url = reverse(
            "job_seekers_views:check_job_seeker_info_for_hire",
            kwargs={"company_pk": company.pk, "job_seeker_public_id": new_job_seeker.public_id},
        )
        assertContains(response, LINK_RESET_MARKUP % check_infos_url)

        hiring_start_at = timezone.localdate()
        post_data = {
            "hiring_start_at": hiring_start_at.strftime(DuetDatePickerWidget.INPUT_DATE_FORMAT),
            "hiring_end_at": "",
            "pole_emploi_id": new_job_seeker.jobseeker_profile.pole_emploi_id,
            "lack_of_pole_emploi_id_reason": new_job_seeker.jobseeker_profile.lack_of_pole_emploi_id_reason,
            "answer": "",
            "ban_api_resolved_address": new_job_seeker.geocoding_address,
            "address_line_1": new_job_seeker.address_line_1,
            "post_code": geispolsheim.post_codes[0],
            "insee_code": geispolsheim.code_insee,
            "city": geispolsheim.name,
            "phone": new_job_seeker.phone,
            "fill_mode": "ban_api",
            # Select the first and only one option
            "address_for_autocomplete": "0",
            # BRSA criterion certification.
            "birthdate": birthdate,
            "birth_place": birth_place_id,
            "birth_country": birth_country_id,
        }
        response = client.post(
            next_url,
            data=post_data,
            headers={"hx-request": "true"},
        )
        assert response.status_code == 200
        assert (
            response.headers.get("HX-Trigger") == '{"modalControl": {"id": "js-confirmation-modal", "action": "show"}}'
        )
        post_data = post_data | {"confirmed": "True"}
        response = client.post(next_url, headers={"hx-request": "true"}, data=post_data)

        job_application = JobApplication.objects.get(sender=user, to_company=company)
        next_url = reverse("employees:detail", kwargs={"public_id": job_application.job_seeker.public_id})
        assertRedirects(response, next_url, status_code=200, fetch_redirect_response=False)

        assert job_application.job_seeker == new_job_seeker
        assert job_application.sender_kind == SenderKind.EMPLOYER
        assert job_application.sender_company == company
        assert job_application.sender_prescriber_organization is None
        assert job_application.state == JobApplicationState.ACCEPTED
        assert job_application.message == ""
        assert list(job_application.selected_jobs.all()) == []
        assert job_application.resume_link == ""

        # Get application detail
        # ----------------------------------------------------------------------
        response = client.get(next_url)
        assertTemplateUsed(response, "approvals/includes/box.html")
        assert response.status_code == 200

    @freeze_time()
    def test_hire_as_geiq(self, client):
        """Apply as GEIQ with pre-existing job seeker without previous application"""
        company = CompanyWithMembershipAndJobsFactory(romes=("N1101", "N1105"), kind=CompanyKind.GEIQ)
        reset_url_dashboard = reverse("dashboard:index")
        job_seeker = JobSeekerFactory()

        user = company.members.first()
        client.force_login(user)

        # Init session
        response = client.get(reverse("apply:start_hire", kwargs={"company_pk": company.pk}), follow=True)
        [job_seeker_session_name] = [k for k in client.session.keys() if k not in KNOWN_SESSION_KEYS]
        check_nir_url = reverse(
            "job_seekers_views:check_nir_for_hire", kwargs={"session_uuid": job_seeker_session_name}
        )

        # Step determine the job seeker with a NIR. First: show modal
        # ----------------------------------------------------------------------
        response = client.get(check_nir_url)
        assertContains(response, LINK_RESET_MARKUP % reset_url_dashboard)

        response = client.post(check_nir_url, data={"nir": job_seeker.jobseeker_profile.nir, "preview": 1})
        assert_contains_apply_nir_modal(response, job_seeker)

        # Step determine the job seeker with a NIR. Second: confirm
        # ----------------------------------------------------------------------

        response = client.post(check_nir_url, data={"nir": job_seeker.jobseeker_profile.nir, "confirm": 1})
        check_infos_url = reverse(
            "job_seekers_views:check_job_seeker_info_for_hire",
            kwargs={"company_pk": company.pk, "job_seeker_public_id": job_seeker.public_id},
        )
        assertRedirects(response, check_infos_url, fetch_redirect_response=False)

        # Step check job seeker infos
        # ----------------------------------------------------------------------

        response = client.get(check_infos_url)
        assertTemplateNotUsed(response, "approvals/includes/box.html")

        prev_applicaitons_url = reverse(
            "apply:check_prev_applications_for_hire",
            kwargs={"company_pk": company.pk, "job_seeker_public_id": job_seeker.public_id},
        )
        assertContains(response, prev_applicaitons_url)
        assertContains(response, "Éligibilité GEIQ non confirmée")
        assertContains(response, CONFIRM_RESET_MARKUP % reset_url_dashboard)

        # Step check previous applications
        # ----------------------------------------------------------------------

        response = client.get(prev_applicaitons_url)
        assertTemplateNotUsed(response, "approvals/includes/box.html")
        geiq_eligibility_url = reverse(
            "apply:geiq_eligibility_for_hire",
            kwargs={"company_pk": company.pk, "job_seeker_public_id": job_seeker.public_id},
        )
        assertRedirects(response, geiq_eligibility_url, fetch_redirect_response=False)

        # Step GEIQ eligibility
        # ----------------------------------------------------------------------
        geiq_criteria_url = reverse(
            "apply:geiq_eligibility_criteria_for_hire",
            kwargs={"company_pk": company.pk, "job_seeker_public_id": job_seeker.public_id},
        )
        confirmation_url = reverse(
            "apply:hire_confirmation", kwargs={"company_pk": company.pk, "job_seeker_public_id": job_seeker.public_id}
        )

        response = client.get(geiq_eligibility_url)
        assertTemplateNotUsed(response, "approvals/includes/box.html")
        response = client.post(
            geiq_eligibility_url,
            data={"choice": "True"},
            headers={"hx-request": "true"},
        )
        assertRedirects(
            response,
            add_url_params(geiq_criteria_url, {"back_url": check_infos_url, "next_url": confirmation_url}),
            fetch_redirect_response=False,
        )
        htmx_response = client.get(geiq_criteria_url, headers={"hx-request": "true"})
        assert htmx_response.status_code == 200

        response = client.post(
            add_url_params(geiq_criteria_url, {"back_url": check_infos_url, "next_url": confirmation_url}),
            data={
                "jeune_26_ans": "on",
                "jeune_de_moins_de_26_ans_sans_qualification": "on",
                "proof_of_eligibility": "on",
            },
        )
        assertRedirects(response, confirmation_url)
        diag = GEIQEligibilityDiagnosis.objects.get(job_seeker=job_seeker)
        assert diag.expires_at == timezone.localdate() + relativedelta(months=6)

        # Hire confirmation
        # ----------------------------------------------------------------------
        response = client.get(confirmation_url)
        assertTemplateNotUsed(response, "approvals/includes/box.html")
        assertContains(response, "Valider l’embauche")
        check_infos_url = reverse(
            "job_seekers_views:check_job_seeker_info_for_hire",
            kwargs={"company_pk": company.pk, "job_seeker_public_id": job_seeker.public_id},
        )
        assertContains(response, LINK_RESET_MARKUP % check_infos_url)

        hiring_start_at = timezone.localdate()
        post_data = {
            "hiring_start_at": hiring_start_at.strftime(DuetDatePickerWidget.INPUT_DATE_FORMAT),
            "hiring_end_at": "",
            "pole_emploi_id": job_seeker.jobseeker_profile.pole_emploi_id,
            "lack_of_pole_emploi_id_reason": job_seeker.jobseeker_profile.lack_of_pole_emploi_id_reason,
            "answer": "",
            "address_line_1": job_seeker.address_line_1,
            "post_code": job_seeker.post_code,
            "city": job_seeker.city,
            "prehiring_guidance_days": 3,
            "nb_hours_per_week": 4,
            "planned_training_hours": 5,
            "contract_type": ContractType.APPRENTICESHIP,
            "qualification_type": QualificationType.STATE_DIPLOMA,
            "qualification_level": QualificationLevel.LEVEL_4,
            "hired_job": company.job_description_through.first().pk,
        }
        response = client.post(
            confirmation_url,
            data=post_data,
            headers={"hx-request": "true"},
        )
        assert response.status_code == 200
        assert (
            response.headers.get("HX-Trigger") == '{"modalControl": {"id": "js-confirmation-modal", "action": "show"}}'
        )
        post_data = post_data | {"confirmed": "True"}
        response = client.post(confirmation_url, headers={"hx-request": "true"}, data=post_data)

        job_application = JobApplication.objects.get(sender=user, to_company=company)
        next_url = reverse("apply:details_for_company", kwargs={"job_application_id": job_application.pk})
        assertRedirects(response, next_url, status_code=200, fetch_redirect_response=False)

        assert job_application.job_seeker == job_seeker
        assert job_application.sender_kind == SenderKind.EMPLOYER
        assert job_application.sender_company == company
        assert job_application.sender_prescriber_organization is None
        assert job_application.state == JobApplicationState.ACCEPTED
        assert job_application.message == ""
        assert list(job_application.selected_jobs.all()) == []
        assert job_application.resume_link == ""
        assert job_application.qualification_type == QualificationType.STATE_DIPLOMA
        assert job_application.qualification_level == QualificationLevel.LEVEL_4

        # Get application detail
        # ----------------------------------------------------------------------
        response = client.get(next_url)
        assert response.status_code == 200


class TestApplyAsOther:
    ROUTES = [
        "apply:start",
        "apply:start_hire",
    ]

    def test_labor_inspectors_are_not_allowed_to_submit_application(self, client, subtests):
        company = CompanyFactory()
        institution = InstitutionWithMembershipFactory()

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

    @staticmethod
    def apply_session_key(company):
        return f"job_application-{company.pk}"

    def test_application_jobs_use_previously_selected_jobs(self, client):
        company = CompanyFactory(subject_to_eligibility=True, with_membership=True, with_jobs=True)

        client.force_login(company.members.first())
        selected_job = company.job_description_through.first()
        job_seeker = JobSeekerFactory()
        session = client.session
        session[self.apply_session_key(company)] = {"selected_jobs": [selected_job.pk]}
        session.save()

        response = client.get(
            reverse(
                "apply:application_jobs",
                kwargs={"company_pk": company.pk, "job_seeker_public_id": job_seeker.public_id},
            )
        )
        assertContains(response, self.spontaneous_application_label)
        assert response.context["form"].initial["selected_jobs"] == [selected_job.pk]
        assert self.spontaneous_application_field in response.context["form"].fields

    def test_application_jobs_spontaneous_applications_disabled(self, client):
        company = CompanyFactory(with_membership=True, with_jobs=True, spontaneous_applications_open_since=None)

        client.force_login(company.members.first())
        job_seeker = JobSeekerFactory()

        response = client.get(
            reverse(
                "apply:application_jobs",
                kwargs={"company_pk": company.pk, "job_seeker_public_id": job_seeker.public_id},
            )
        )
        assertNotContains(response, self.spontaneous_application_label)
        assert self.spontaneous_application_field not in response.context["form"].fields

    def test_application_start_with_invalid_job_description_id(self, client):
        company = CompanyFactory(subject_to_eligibility=True, with_membership=True, with_jobs=True)
        client.force_login(company.members.get())
        response = client.get(
            reverse("apply:start", kwargs={"company_pk": company.pk}), {"job_description_id": "invalid"}, follow=True
        )
        [job_seeker_session_name] = [k for k in client.session.keys() if k not in KNOWN_SESSION_KEYS]
        assertRedirects(
            response,
            reverse("job_seekers_views:check_nir_for_sender", kwargs={"session_uuid": job_seeker_session_name}),
        )
        assert self.apply_session_key(company) not in client.session

    def test_access_without_session(self, client):
        company = CompanyFactory(subject_to_eligibility=True, with_membership=True)
        job_seeker = JobSeekerFactory()
        prescriber = PrescriberOrganizationWithMembershipFactory(authorized=True).members.first()
        client.force_login(prescriber)
        response = client.get(
            reverse(
                "apply:application_eligibility",
                kwargs={"company_pk": company.pk, "job_seeker_public_id": job_seeker.public_id},
            )
        )
        assertRedirects(
            response,
            reverse(
                "apply:application_jobs",
                kwargs={"company_pk": company.pk, "job_seeker_public_id": job_seeker.public_id},
            ),
        )

    def test_application_resume_hidden_fields(self, client):
        company = CompanyFactory(with_membership=True, with_jobs=True)
        job_seeker = JobSeekerFactory()

        client.force_login(company.members.first())
        apply_session = SessionNamespace(client.session, f"job_application-{company.pk}")
        apply_session.init(
            {
                "selected_jobs": company.job_description_through.all(),
            }
        )
        apply_session.save()

        response = client.get(
            reverse(
                "apply:application_resume",
                kwargs={"company_pk": company.pk, "job_seeker_public_id": job_seeker.public_id},
            )
        )
        assertContains(response, 'name="resume"')

    def test_application_resume_diagoriente_shown_as_job_seeker(self, client):
        company = CompanyFactory(with_membership=True, with_jobs=True)
        job_seeker = JobSeekerFactory()
        client.force_login(job_seeker)
        session = client.session
        session[f"job_application-{company.pk}"] = {"selected_jobs": []}
        session.save()

        response = client.get(
            reverse(
                "apply:application_resume",
                kwargs={"company_pk": company.pk, "job_seeker_public_id": job_seeker.public_id},
            )
        )
        assertContains(response, self.DIAGORIENTE_JOB_SEEKER_TITLE)
        assertContains(response, self.DIAGORIENTE_JOB_SEEKER_DESCRIPTION)
        assertNotContains(response, self.DIAGORIENTE_PRESCRIBER_TITLE)
        assertNotContains(response, self.DIAGORIENTE_PRESCRIBER_DESCRIPTION)
        assertContains(response, f"{self.DIAGORIENTE_URL}?utm_source=emploi-inclusion-candidat")

    def test_application_resume_diagoriente_not_shown_as_company(self, client):
        company = CompanyFactory(with_membership=True, with_jobs=True)
        job_seeker = JobSeekerFactory()
        client.force_login(company.members.first())
        session = client.session
        session[f"job_application-{company.pk}"] = {"selected_jobs": []}
        session.save()

        response = client.get(
            reverse(
                "apply:application_resume",
                kwargs={"company_pk": company.pk, "job_seeker_public_id": job_seeker.public_id},
            )
        )
        assertNotContains(response, self.DIAGORIENTE_JOB_SEEKER_TITLE)
        assertNotContains(response, self.DIAGORIENTE_JOB_SEEKER_DESCRIPTION)
        assertNotContains(response, self.DIAGORIENTE_PRESCRIBER_TITLE)
        assertNotContains(response, self.DIAGORIENTE_PRESCRIBER_DESCRIPTION)
        assertNotContains(response, self.DIAGORIENTE_URL)

    def test_application_resume_diagoriente_shown_as_prescriber(self, client):
        company = CompanyFactory(with_membership=True, with_jobs=True)
        prescriber = PrescriberOrganizationWithMembershipFactory().members.first()
        job_seeker = JobSeekerFactory()
        client.force_login(prescriber)
        session = client.session
        session[f"job_application-{company.pk}"] = {"selected_jobs": []}
        session.save()

        response = client.get(
            reverse(
                "apply:application_resume",
                kwargs={"company_pk": company.pk, "job_seeker_public_id": job_seeker.public_id},
            )
        )
        assertNotContains(response, self.DIAGORIENTE_JOB_SEEKER_TITLE)
        assertNotContains(response, self.DIAGORIENTE_JOB_SEEKER_DESCRIPTION)
        assertContains(response, self.DIAGORIENTE_PRESCRIBER_TITLE)
        assertContains(response, self.DIAGORIENTE_PRESCRIBER_DESCRIPTION)
        assertContains(response, f"{self.DIAGORIENTE_URL}?utm_source=emploi-inclusion-prescripteur")

    def test_application_eligibility_is_bypassed_for_company_not_subject_to_eligibility_rules(self, client):
        company = CompanyFactory(not_subject_to_eligibility=True, with_membership=True)
        job_seeker = JobSeekerFactory()

        client.force_login(company.members.first())
        apply_session = SessionNamespace(client.session, f"job_application-{company.pk}")
        apply_session.init({})  # We still need a session, even if empty
        apply_session.save()

        response = client.get(
            reverse(
                "apply:application_eligibility",
                kwargs={"company_pk": company.pk, "job_seeker_public_id": job_seeker.public_id},
            )
        )
        assertRedirects(
            response,
            reverse(
                "apply:application_resume",
                kwargs={"company_pk": company.pk, "job_seeker_public_id": job_seeker.public_id},
            ),
            fetch_redirect_response=False,
        )

    def test_application_eligibility_is_bypassed_for_unauthorized_prescriber(self, client):
        company = CompanyFactory(not_subject_to_eligibility=True, with_membership=True)
        prescriber = PrescriberOrganizationWithMembershipFactory().members.first()
        job_seeker = JobSeekerFactory()

        client.force_login(prescriber)
        apply_session = SessionNamespace(client.session, f"job_application-{company.pk}")
        apply_session.init({})  # We still need a session, even if empty
        apply_session.save()

        response = client.get(
            reverse(
                "apply:application_eligibility",
                kwargs={"company_pk": company.pk, "job_seeker_public_id": job_seeker.public_id},
            )
        )
        assertRedirects(
            response,
            reverse(
                "apply:application_resume",
                kwargs={"company_pk": company.pk, "job_seeker_public_id": job_seeker.public_id},
            ),
            fetch_redirect_response=False,
        )

    def test_application_eligibility_is_bypassed_when_the_job_seeker_already_has_an_approval(self, client):
        company = CompanyFactory(not_subject_to_eligibility=True, with_membership=True)
        eligibility_diagnosis = IAEEligibilityDiagnosisFactory(from_prescriber=True)

        client.force_login(company.members.first())
        apply_session = SessionNamespace(client.session, f"job_application-{company.pk}")
        apply_session.init({})  # We still need a session, even if empty
        apply_session.save()

        response = client.get(
            reverse(
                "apply:application_eligibility",
                kwargs={"company_pk": company.pk, "job_seeker_public_id": eligibility_diagnosis.job_seeker.public_id},
            )
        )
        assertRedirects(
            response,
            reverse(
                "apply:application_resume",
                kwargs={"company_pk": company.pk, "job_seeker_public_id": eligibility_diagnosis.job_seeker.public_id},
            ),
            fetch_redirect_response=False,
        )

    def test_application_eligibility_update_diagnosis_only_if_not_shrouded(self, client):
        company = CompanyFactory(subject_to_eligibility=True, with_membership=True)
        prescriber = PrescriberOrganizationWithMembershipFactory(authorized=True).members.first()
        eligibility_diagnosis = IAEEligibilityDiagnosisFactory(from_prescriber=True)

        client.force_login(prescriber)
        apply_session = SessionNamespace(client.session, f"job_application-{company.pk}")
        apply_session.init({})  # We still need a session, even if empty
        apply_session.save()

        # if "shrouded" is present then we don't update the eligibility diagnosis
        response = client.post(
            reverse(
                "apply:application_eligibility",
                kwargs={"company_pk": company.pk, "job_seeker_public_id": eligibility_diagnosis.job_seeker.public_id},
            ),
            {"level_1_1": True, "shrouded": "whatever"},
        )
        assertRedirects(
            response,
            reverse(
                "apply:application_resume",
                kwargs={"company_pk": company.pk, "job_seeker_public_id": eligibility_diagnosis.job_seeker.public_id},
            ),
            fetch_redirect_response=False,
        )
        assert [eligibility_diagnosis] == list(
            EligibilityDiagnosis.objects.for_job_seeker_and_siae(job_seeker=eligibility_diagnosis.job_seeker)
        )

        # If "shrouded" is NOT present then we update the eligibility diagnosis
        response = client.post(
            reverse(
                "apply:application_eligibility",
                kwargs={"company_pk": company.pk, "job_seeker_public_id": eligibility_diagnosis.job_seeker.public_id},
            ),
            {"level_1_1": True},
        )
        assertRedirects(
            response,
            reverse(
                "apply:application_resume",
                kwargs={"company_pk": company.pk, "job_seeker_public_id": eligibility_diagnosis.job_seeker.public_id},
            ),
            fetch_redirect_response=False,
        )
        new_eligibility_diagnosis = (
            EligibilityDiagnosis.objects.for_job_seeker_and_siae(job_seeker=eligibility_diagnosis.job_seeker)
            .order_by()
            .last()
        )
        assert new_eligibility_diagnosis != eligibility_diagnosis
        assert new_eligibility_diagnosis.author == prescriber


def test_application_end_update_job_seeker(client):
    job_application = JobApplicationFactory(job_seeker__with_mocked_address=True)
    job_seeker = job_application.job_seeker
    # Ensure sender cannot update job seeker infos
    assert not job_seeker.can_edit_personal_information(job_application.sender)
    assert job_seeker.address_line_2 == ""
    url = reverse(
        "apply:application_end",
        kwargs={"company_pk": job_application.to_company.pk, "application_pk": job_application.pk},
    )
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


class TestLastCheckedAtView:
    @pytest.fixture(autouse=True)
    def setup_method(self):
        self.company = CompanyFactory(subject_to_eligibility=True, with_membership=True)
        self.job_seeker = JobSeekerFactory()

    def _check_last_checked_at(self, client, user, sees_warning, sees_verify_link):
        client.force_login(user)
        apply_session = SessionNamespace(client.session, f"job_application-{self.company.pk}")
        apply_session.init(
            {
                "selected_jobs": [],
            }
        )
        apply_session.save()

        url = reverse(
            "apply:application_jobs",
            kwargs={"company_pk": self.company.pk, "job_seeker_public_id": self.job_seeker.public_id},
        )
        response = client.get(url)
        assert response.status_code == 200

        params = {
            "job_seeker": self.job_seeker.public_id,
            "from_url": url,
        }
        update_url = add_url_params(reverse("job_seekers_views:update_job_seeker_start"), params)
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
        authorized_prescriber = PrescriberOrganizationWithMembershipFactory(authorized=True).members.first()
        self._check_last_checked_at(client, authorized_prescriber, sees_warning=True, sees_verify_link=True)

    def test_unauthorized_prescriber(self, client):
        prescriber = PrescriberOrganizationWithMembershipFactory(authorized=False).members.first()
        self._check_last_checked_at(client, prescriber, sees_warning=True, sees_verify_link=False)

    def test_unauthorized_prescriber_that_created_the_job_seeker(self, client):
        prescriber = PrescriberOrganizationWithMembershipFactory(authorized=False).members.first()
        self.job_seeker.created_by = prescriber
        self.job_seeker.save(update_fields=["created_by"])
        self._check_last_checked_at(client, prescriber, sees_warning=True, sees_verify_link=True)


class UpdateJobSeekerTestMixin:
    @pytest.fixture(autouse=True)
    def setup_method(self, settings, mocker):
        self.company = CompanyFactory(subject_to_eligibility=True, with_membership=True)
        self.job_seeker = JobSeekerFactory(
            with_ban_geoloc_address=True,
            jobseeker_profile__nir="178122978200508",
            jobseeker_profile__birthdate=datetime.date(1978, 12, 20),
            title="M",
        )
        from_url = reverse(
            self.FINAL_REDIRECT_VIEW_NAME,
            kwargs={"company_pk": self.company.pk, "job_seeker_public_id": self.job_seeker.public_id},
        )
        self.config = {
            "config": {"from_url": from_url, "session_kind": JobSeekerSessionKinds.UPDATE},
            "job_seeker_pk": self.job_seeker.pk,
        }

        [self.city] = create_test_cities(["67"], num_per_department=1)

        self.INFO_MODIFIABLE_PAR_CANDIDAT_UNIQUEMENT = "Informations modifiables par le candidat uniquement"
        self.job_seeker_session_key = f"job_seeker-{self.job_seeker.public_id}"

        settings.API_BAN_BASE_URL = "http://ban-api"
        mocker.patch(
            "itou.utils.apis.geocoding.get_geocoding_data",
            side_effect=mock_get_first_geocoding_data,
        )

        params = {
            "job_seeker": self.job_seeker.public_id,
            "from_url": from_url,
        }
        self.start_url = add_url_params(reverse("job_seekers_views:update_job_seeker_start"), params)

    def get_job_seeker_session_key(self, client):
        [job_seeker_session_key] = [
            k for k in client.session.keys() if k not in KNOWN_SESSION_KEYS and not k.startswith("job_application")
        ] or [None]
        return job_seeker_session_key

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
            reverse(
                self.FINAL_REDIRECT_VIEW_NAME,
                kwargs={"company_pk": self.company.pk, "job_seeker_public_id": self.job_seeker.public_id},
            ),
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
            reverse(
                self.FINAL_REDIRECT_VIEW_NAME,
                kwargs={"company_pk": self.company.pk, "job_seeker_public_id": self.job_seeker.public_id},
            ),
            fetch_redirect_response=False,
        )
        assert client.session.get(self.get_job_seeker_session_key(client)) is None

        self.job_seeker.refresh_from_db()
        assert self.job_seeker.has_jobseeker_profile is True
        assert self.job_seeker.jobseeker_profile.education_level == EducationLevel.BAC_LEVEL
        assert self.job_seeker.last_checked_at != previous_last_checked_at


class TestUpdateJobSeeker(UpdateJobSeekerTestMixin):
    FINAL_REDIRECT_VIEW_NAME = "apply:application_jobs"

    def test_as_job_seeker(self, client):
        self._check_nothing_permitted(client, self.job_seeker)

    def test_as_unauthorized_prescriber(self, client):
        prescriber = PrescriberOrganizationWithMembershipFactory(authorized=False).members.first()
        self._check_nothing_permitted(client, prescriber)

    def test_as_unauthorized_prescriber_that_created_proxied_job_seeker(self, client, snapshot):
        prescriber = PrescriberOrganizationWithMembershipFactory(authorized=False).members.first()
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
                "birth_country": Country.france_id,
            },
        )

    def test_as_unauthorized_prescriber_that_created_the_non_proxied_job_seeker(self, client):
        prescriber = PrescriberOrganizationWithMembershipFactory(authorized=False).members.first()
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
        authorized_prescriber = PrescriberOrganizationWithMembershipFactory(authorized=True).members.first()

        geispolsheim = create_city_geispolsheim()
        birthdate = self.job_seeker.jobseeker_profile.birthdate

        self._check_everything_allowed(
            client,
            snapshot,
            authorized_prescriber,
            extra_post_data_1={
                "birth_place": Commune.objects.by_insee_code_and_period(geispolsheim.code_insee, birthdate).id,
                "birth_country": Country.france_id,
            },
        )

    def test_as_authorized_prescriber_with_non_proxied_job_seeker(self, client):
        # Make sure the job seeker does manage its own account
        self.job_seeker.last_login = timezone.now() - relativedelta(months=1)
        self.job_seeker.save(update_fields=["last_login"])
        authorized_prescriber = PrescriberOrganizationWithMembershipFactory(authorized=True).members.first()
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
                "birth_country": Country.france_id,
            },
        )

    def test_as_company_with_non_proxied_job_seeker(self, client):
        # Make sure the job seeker does manage its own account
        self.job_seeker.last_login = timezone.now() - relativedelta(months=1)
        self.job_seeker.save(update_fields=["last_login"])
        self._check_only_administrative_allowed(client, self.company.members.first())

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
                "lack_of_nir_reason": LackOfNIRReason.TEMPORARY_NUMBER.value,
                "birth_place": Commune.objects.by_insee_code_and_period(geispolsheim.code_insee, birthdate).id,
                "birth_country": Country.france_id,
            },
        )
        # Check that we could update its NIR infos
        assert self.job_seeker.jobseeker_profile.lack_of_nir_reason == LackOfNIRReason.TEMPORARY_NUMBER

    def test_as_company_that_last_step_doesnt_crash_with_direct_access(self, client):
        # Make sure the job seeker does not manage its own account
        self.job_seeker.created_by = EmployerFactory()
        self.job_seeker.last_login = None
        self.job_seeker.save(update_fields=["created_by", "last_login"])
        self._check_that_last_step_doesnt_crash_with_direct_access(client, self.company.members.first())


class TestUpdateJobSeekerForHire(UpdateJobSeekerTestMixin):
    FINAL_REDIRECT_VIEW_NAME = "job_seekers_views:check_job_seeker_info_for_hire"

    def test_as_job_seeker(self, client):
        self._check_nothing_permitted(client, self.job_seeker)

    def test_as_unauthorized_prescriber(self, client):
        prescriber = PrescriberOrganizationWithMembershipFactory(authorized=False).members.first()
        self._check_nothing_permitted(client, prescriber)

    def test_as_unauthorized_prescriber_that_created_proxied_job_seeker(self, client, snapshot):
        prescriber = PrescriberOrganizationWithMembershipFactory(authorized=False).members.first()
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
                "birth_country": Country.france_id,
            },
        )

    def test_as_unauthorized_prescriber_that_created_the_non_proxied_job_seeker(self, client):
        prescriber = PrescriberOrganizationWithMembershipFactory(authorized=False).members.first()
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
        authorized_prescriber = PrescriberOrganizationWithMembershipFactory(authorized=True).members.first()

        geispolsheim = create_city_geispolsheim()
        birthdate = self.job_seeker.jobseeker_profile.birthdate

        self._check_everything_allowed(
            client,
            snapshot,
            authorized_prescriber,
            extra_post_data_1={
                "birth_place": Commune.objects.by_insee_code_and_period(geispolsheim.code_insee, birthdate).id,
                "birth_country": Country.france_id,
            },
        )

    def test_as_authorized_prescriber_with_non_proxied_job_seeker(self, client):
        # Make sure the job seeker does manage its own account
        self.job_seeker.last_login = timezone.now() - relativedelta(months=1)
        self.job_seeker.save(update_fields=["last_login"])
        authorized_prescriber = PrescriberOrganizationWithMembershipFactory(authorized=True).members.first()
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
                "birth_country": Country.france_id,
            },
        )

    def test_as_company_with_non_proxied_job_seeker(self, client):
        # Make sure the job seeker does manage its own account
        self.job_seeker.last_login = timezone.now() - relativedelta(months=1)
        self.job_seeker.save(update_fields=["last_login"])
        self._check_only_administrative_allowed(client, self.company.members.first())

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
                "lack_of_nir_reason": LackOfNIRReason.TEMPORARY_NUMBER.value,
                "birth_place": Commune.objects.by_insee_code_and_period(geispolsheim.code_insee, birthdate).id,
                "birth_country": Country.france_id,
            },
        )
        # Check that we could update its NIR infos
        assert self.job_seeker.jobseeker_profile.lack_of_nir_reason == LackOfNIRReason.TEMPORARY_NUMBER

    def test_as_company_that_last_step_doesnt_crash_with_direct_access(self, client):
        # Make sure the job seeker does not manage its own account
        self.job_seeker.created_by = EmployerFactory()
        self.job_seeker.last_login = None
        self.job_seeker.save(update_fields=["created_by", "last_login"])
        self._check_that_last_step_doesnt_crash_with_direct_access(client, self.company.members.first())


class TestUpdateJobSeekerStep3View:
    def test_job_seeker_with_profile_has_check_boxes_ticked_in_step3(self, client):
        company = CompanyFactory(subject_to_eligibility=True, with_membership=True)
        job_seeker = JobSeekerFactory(jobseeker_profile__ass_allocation_since=AllocationDuration.FROM_6_TO_11_MONTHS)

        client.force_login(company.members.first())
        apply_session = SessionNamespace(client.session, f"job_application-{company.pk}")
        apply_session.init(
            {
                "selected_jobs": [],
            }
        )
        apply_session.save()

        # START to setup jobseeker session
        params = {
            "job_seeker": job_seeker.public_id,
            "from_url": reverse(
                "apply:application_jobs",
                kwargs={"company_pk": company.pk, "job_seeker_public_id": job_seeker.public_id},
            ),
        }
        url = add_url_params(reverse("job_seekers_views:update_job_seeker_start"), params)
        response = client.get(url)
        assert response.status_code == 302

        # Go straight to STEP 3
        [job_seeker_session_name] = [
            k for k in client.session.keys() if k not in KNOWN_SESSION_KEYS and not k.startswith("job_application")
        ]
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


@pytest.mark.ignore_unknown_variable_template_error("job_seeker")
def test_detect_existing_job_seeker(client):
    company = CompanyWithMembershipAndJobsFactory(romes=("N1101", "N1105"))

    prescriber_organization = PrescriberOrganizationWithMembershipFactory(authorized=True)
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

    response = client.get(reverse("apply:start", kwargs={"company_pk": company.pk}))

    params = {
        "tunnel": "sender",
        "company": company.pk,
        "from_url": reverse("companies_views:card", kwargs={"siae_id": company.pk}),
    }
    next_url = add_url_params(reverse("job_seekers_views:get_or_create_start"), params)
    assertRedirects(response, next_url, target_status_code=302, fetch_redirect_response=False)

    # Step determine the job seeker with a NIR.
    # ----------------------------------------------------------------------

    response = client.get(next_url)
    [job_seeker_session_name] = [k for k in client.session.keys() if k not in KNOWN_SESSION_KEYS]
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
            "session_kind": JobSeekerSessionKinds.GET_OR_CREATE,
            "from_url": reverse("companies_views:card", kwargs={"siae_id": company.pk}),
        },
        "apply": {"company_pk": company.pk},
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
        "birth_country": Country.france_id,
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

    @pytest.fixture(autouse=True)
    def setup_method(self):
        self.geiq = CompanyFactory(with_membership=True, with_jobs=True, kind=CompanyKind.GEIQ)
        self.prescriber_org = PrescriberOrganizationWithMembershipFactory(authorized=True)
        self.orienter = PrescriberFactory()
        self.job_seeker_with_geiq_diagnosis = GEIQEligibilityDiagnosisFactory(from_prescriber=True).job_seeker
        self.company = CompanyFactory(with_membership=True, kind=CompanyKind.EI)

    def _setup_session(self, client, company_pk=None):
        apply_session = SessionNamespace(client.session, f"job_application-{company_pk or self.geiq.pk}")
        apply_session.init(
            {
                "selected_jobs": self.geiq.job_description_through.all(),
            }
        )
        apply_session.save()

    def test_bypass_geiq_eligibility_diagnosis_form_for_orienter(self, client):
        # When creating a job application, should bypass GEIQ eligibility form step:
        # - if user is an authorized prescriber
        # - if user structure is not a GEIQ : should not be possible, form asserts it and crashes
        job_seeker = JobSeekerFactory()

        # Redirect orienter
        client.force_login(self.orienter)
        self._setup_session(client)
        response = client.get(
            reverse(
                "apply:application_geiq_eligibility",
                kwargs={"company_pk": self.geiq.pk, "job_seeker_public_id": job_seeker.public_id},
            )
        )

        # Must redirect to resume
        assertRedirects(
            response,
            reverse(
                "apply:application_resume",
                kwargs={"company_pk": self.geiq.pk, "job_seeker_public_id": job_seeker.public_id},
            ),
            fetch_redirect_response=False,
        )
        assertTemplateNotUsed(response, "apply/includes/geiq/geiq_administrative_criteria_form.html")

    def test_bypass_geiq_diagnosis_for_staff_members(self, client):
        job_seeker = JobSeekerFactory()
        client.force_login(self.geiq.members.first())
        self._setup_session(client)
        response = client.get(
            reverse(
                "apply:application_geiq_eligibility",
                kwargs={"company_pk": self.geiq.pk, "job_seeker_public_id": job_seeker.public_id},
            )
        )

        # Must redirect to resume
        assertRedirects(
            response,
            reverse(
                "apply:application_resume",
                kwargs={"company_pk": self.geiq.pk, "job_seeker_public_id": job_seeker.public_id},
            ),
            fetch_redirect_response=False,
        )
        assertTemplateNotUsed(response, "apply/includes/geiq/geiq_administrative_criteria_form.html")

    def test_bypass_geiq_diagnosis_for_job_seeker(self, client):
        # A job seeker must not have access to GEIQ eligibility form
        job_seeker = JobSeekerFactory()
        client.force_login(job_seeker)
        self._setup_session(client)
        response = client.get(
            reverse(
                "apply:application_geiq_eligibility",
                kwargs={"company_pk": self.geiq.pk, "job_seeker_public_id": job_seeker.public_id},
            )
        )

        # Must redirect to resume
        assertRedirects(
            response,
            reverse(
                "apply:application_resume",
                kwargs={"company_pk": self.geiq.pk, "job_seeker_public_id": job_seeker.public_id},
            ),
            fetch_redirect_response=False,
        )
        assertTemplateNotUsed(response, "apply/includes/geiq/geiq_administrative_criteria_form.html")

    def test_sanity_check_geiq_diagnosis_for_non_geiq(self, client):
        job_seeker = JobSeekerFactory()
        # See comment im previous test:
        # assert we're not somewhere we don't belong to (non-GEIQ)
        client.force_login(self.company.members.first())
        self._setup_session(client, company_pk=self.company.pk)

        response = client.get(
            reverse(
                "apply:application_geiq_eligibility",
                kwargs={"company_pk": self.company.pk, "job_seeker_public_id": job_seeker.public_id},
            )
        )
        assert response.status_code == 404

    def test_access_as_authorized_prescriber(self, client):
        job_seeker = JobSeekerFactory()
        client.force_login(self.prescriber_org.members.first())
        self._setup_session(client)

        geiq_eligibility_url = reverse(
            "apply:application_geiq_eligibility",
            kwargs={"company_pk": self.geiq.pk, "job_seeker_public_id": job_seeker.public_id},
        )
        response = client.get(geiq_eligibility_url)

        assert response.status_code == 200
        assertTemplateUsed(response, "apply/includes/geiq/geiq_administrative_criteria_form.html")

        # Check back_url in next step
        response = client.get(
            reverse(
                "apply:application_resume",
                kwargs={"company_pk": self.geiq.pk, "job_seeker_public_id": job_seeker.public_id},
            ),
        )
        assertContains(response, geiq_eligibility_url)

    def test_authorized_prescriber_can_see_other_authorized_prescriber_eligibility_diagnosis(self, client):
        job_seeker = JobSeekerFactory()
        GEIQEligibilityDiagnosisFactory(from_prescriber=True, job_seeker=job_seeker)

        client.force_login(self.prescriber_org.members.get())
        self._setup_session(client)
        response = client.get(
            reverse(
                "apply:application_geiq_eligibility",
                kwargs={"company_pk": self.geiq.pk, "job_seeker_public_id": job_seeker.public_id},
            )
        )
        assertContains(response, "Éligibilité GEIQ confirmée")
        assertContains(response, self.DIAG_VALIDITY_TXT)
        assertContains(response, self.UPDATE_ELIGIBILITY)

    def test_authorized_prescriber_do_not_see_company_eligibility_diagnosis(self, client):
        job_seeker = JobSeekerFactory()
        GEIQEligibilityDiagnosisFactory(from_geiq=True, author_geiq=self.geiq, job_seeker=job_seeker)
        url = reverse(
            "apply:application_geiq_eligibility",
            kwargs={"company_pk": self.geiq.pk, "job_seeker_public_id": job_seeker.public_id},
        )
        prescriber = self.prescriber_org.members.get()

        client.force_login(prescriber)
        self._setup_session(client)
        response = client.get(url)
        assertContains(response, "Éligibilité GEIQ non confirmée")
        assertNotContains(response, self.DIAG_VALIDITY_TXT)
        assertNotContains(response, self.UPDATE_ELIGIBILITY)

        response = client.post(url, {"not": "empty"})
        assertRedirects(
            response,
            reverse(
                "apply:application_resume",
                kwargs={"company_pk": self.geiq.pk, "job_seeker_public_id": job_seeker.public_id},
            ),
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
        job_seeker = JobSeekerFactory()
        client.force_login(self.prescriber_org.members.first())
        response = client.get(
            reverse(
                "apply:application_geiq_eligibility",
                kwargs={"company_pk": self.geiq.pk, "job_seeker_public_id": job_seeker.public_id},
            )
        )
        assertRedirects(
            response,
            reverse(
                "apply:application_jobs",
                kwargs={"company_pk": self.geiq.pk, "job_seeker_public_id": job_seeker.public_id},
            ),
        )

    def test_geiq_eligibility_badge(self, client):
        client.force_login(self.prescriber_org.members.first())

        # Badge OK if job seeker has a valid eligibility diagnosis
        self._setup_session(client)
        response = client.get(
            reverse(
                "apply:application_geiq_eligibility",
                kwargs={
                    "company_pk": self.geiq.pk,
                    "job_seeker_public_id": self.job_seeker_with_geiq_diagnosis.public_id,
                },
            ),
            follow=True,
        )

        assertContains(response, "Éligibilité GEIQ confirmée")
        assertTemplateUsed(response, "apply/includes/geiq/geiq_administrative_criteria_form.html")
        assertContains(response, self.DIAG_VALIDITY_TXT)

        # Badge KO if job seeker has no diagnosis
        job_seeker_without_diagnosis = JobSeekerFactory()
        self._setup_session(client)
        response = client.get(
            reverse(
                "apply:application_geiq_eligibility",
                kwargs={"company_pk": self.geiq.pk, "job_seeker_public_id": job_seeker_without_diagnosis.public_id},
            ),
            follow=True,
        )

        assertContains(response, "Éligibilité GEIQ non confirmée")
        assertTemplateUsed(response, "apply/includes/geiq/geiq_administrative_criteria_form.html")

        # Badge is KO if job seeker has a valid diagnosis without allowance
        diagnosis = GEIQEligibilityDiagnosisFactory(from_geiq=True)
        assert diagnosis.allowance_amount == 0

        client.force_login(self.prescriber_org.members.first())
        self._setup_session(client, diagnosis.author_geiq.pk)
        response = client.get(
            reverse(
                "apply:application_geiq_eligibility",
                kwargs={
                    "company_pk": diagnosis.author_geiq.pk,
                    "job_seeker_public_id": job_seeker_without_diagnosis.public_id,
                },
            ),
            follow=True,
        )
        assertContains(response, "Éligibilité GEIQ non confirmée")
        assertTemplateUsed(response, "apply/includes/geiq/geiq_administrative_criteria_form.html")

    def test_geiq_diagnosis_form_validation(self, client, subtests):
        client.force_login(self.prescriber_org.members.first())
        self._setup_session(client)

        response = client.post(
            reverse(
                "apply:application_geiq_eligibility",
                kwargs={
                    "company_pk": self.geiq.pk,
                    "job_seeker_public_id": self.job_seeker_with_geiq_diagnosis.public_id,
                },
            ),
            data={"jeune_26_ans": True},
        )

        assertRedirects(
            response,
            reverse(
                "apply:application_resume",
                kwargs={
                    "company_pk": self.geiq.pk,
                    "job_seeker_public_id": self.job_seeker_with_geiq_diagnosis.public_id,
                },
            ),
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
                    reverse(
                        "apply:application_geiq_eligibility",
                        kwargs={
                            "company_pk": self.geiq.pk,
                            "job_seeker_public_id": self.job_seeker_with_geiq_diagnosis.public_id,
                        },
                    ),
                    data=post_data,
                    follow=True,
                )
                assertTemplateUsed(response, "apply/includes/geiq/geiq_administrative_criteria_form.html")
                assertContains(response, "Incohérence dans les critères")

        # TODO: more coherence tests asked to business ...


class TestCheckPreviousApplicationsView:
    @pytest.fixture(autouse=True)
    def setup_method(self):
        self.company = CompanyFactory(subject_to_eligibility=True, with_membership=True)
        self.job_seeker = JobSeekerFactory()
        self.check_infos_url = reverse(
            "job_seekers_views:check_job_seeker_info",
            kwargs={"company_pk": self.company.pk, "job_seeker_public_id": self.job_seeker.public_id},
        )
        self.check_prev_applications_url = reverse(
            "apply:step_check_prev_applications",
            kwargs={"company_pk": self.company.pk, "job_seeker_public_id": self.job_seeker.public_id},
        )
        self.application_jobs_url = reverse(
            "apply:application_jobs",
            kwargs={"company_pk": self.company.pk, "job_seeker_public_id": self.job_seeker.public_id},
        )

    def _login_and_setup_session(self, client, user):
        client.force_login(user)
        apply_session = SessionNamespace(client.session, f"job_application-{self.company.pk}")
        apply_session.init(
            {
                "selected_jobs": [],
            }
        )
        apply_session.save()

    def test_no_previous_as_job_seeker(self, client):
        self._login_and_setup_session(client, self.job_seeker)
        response = client.get(self.check_prev_applications_url)
        assertRedirects(response, self.application_jobs_url)

        response = client.get(self.application_jobs_url)
        company_card_url = reverse("companies_views:card", kwargs={"siae_id": self.company.pk})

        # Reset URL is correct
        assertContains(response, LINK_RESET_MARKUP % company_card_url, count=1)

    def test_with_previous_as_job_seeker(self, client):
        self._login_and_setup_session(client, self.job_seeker)

        # Create a very recent application
        job_application = JobApplicationFactory(job_seeker=self.job_seeker, to_company=self.company)
        response = client.get(self.check_prev_applications_url)
        assertContains(
            response, "Vous avez déjà postulé chez cet employeur durant les dernières 24 heures.", status_code=403
        )

        # Make it less recent to avoid the 403
        job_application.created_at = timezone.now() - datetime.timedelta(days=2)
        job_application.save(update_fields=("created_at",))
        response = client.get(self.check_prev_applications_url)
        assertContains(response, "Vous avez déjà postulé chez cet employeur le")
        response = client.post(self.check_prev_applications_url, data={"force_new_application": "force"})
        assertRedirects(response, self.application_jobs_url)

        # Reset URL is correct
        response = client.get(self.application_jobs_url)
        company_card_url = reverse("companies_views:card", kwargs={"siae_id": self.company.pk})
        assertContains(response, LINK_RESET_MARKUP % company_card_url, count=1)

    def test_no_previous_as_authorized_prescriber(self, client):
        authorized_prescriber = PrescriberOrganizationWithMembershipFactory(authorized=True).members.first()
        self._login_and_setup_session(client, authorized_prescriber)
        response = client.get(self.check_prev_applications_url)
        assertRedirects(response, self.application_jobs_url)

        # Reset URL is correct
        response = client.get(self.application_jobs_url)
        company_card_url = reverse("companies_views:card", kwargs={"siae_id": self.company.pk})
        assertContains(response, LINK_RESET_MARKUP % company_card_url, count=1)

    def test_with_previous_as_authorized_prescriber(self, client):
        authorized_prescriber = PrescriberOrganizationWithMembershipFactory(authorized=True).members.first()
        self._login_and_setup_session(client, authorized_prescriber)

        # Create a very recent application
        job_application = JobApplicationFactory(job_seeker=self.job_seeker, to_company=self.company)
        response = client.get(self.check_prev_applications_url)
        assertContains(
            response, "Ce candidat a déjà postulé chez cet employeur durant les dernières 24 heures.", status_code=403
        )
        # Make it less recent to avoid the 403
        job_application.created_at = timezone.now() - datetime.timedelta(days=2)
        job_application.save(update_fields=("created_at",))
        response = client.get(self.check_prev_applications_url)
        assertContains(response, "Le candidat a déjà postulé chez cet employeur le")
        response = client.post(self.check_prev_applications_url, data={"force_new_application": "force"})
        assertRedirects(response, self.application_jobs_url)

        # Reset URL is correct
        response = client.get(self.application_jobs_url)
        company_card_url = reverse("companies_views:card", kwargs={"siae_id": self.company.pk})
        assertContains(response, LINK_RESET_MARKUP % company_card_url, count=1)

    def test_no_previous_as_employer(self, client):
        self._login_and_setup_session(client, self.company.members.first())

        response = client.get(self.check_prev_applications_url)
        assertRedirects(response, self.application_jobs_url)

        response = client.get(self.application_jobs_url)
        assertNotContains(response, BACK_BUTTON_ARIA_LABEL)

    def test_with_previous_as_employer(self, client):
        JobApplicationFactory(job_seeker=self.job_seeker, to_company=self.company)
        self._login_and_setup_session(client, self.company.members.first())

        response = client.get(self.check_prev_applications_url)
        assertContains(response, "Le candidat a déjà postulé chez cet employeur le")
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
        company_card_url = reverse("companies_views:card", kwargs={"siae_id": self.company.pk})
        assertContains(response, LINK_RESET_MARKUP % company_card_url, count=1)

    def test_with_previous_as_another_employer(self, client):
        employer = EmployerFactory(with_company=True)
        self._login_and_setup_session(client, employer)

        # Create a very recent application
        job_application = JobApplicationFactory(
            sent_by_another_employer=True,
            sender=employer,
            job_seeker=self.job_seeker,
            to_company=self.company,
        )
        response = client.get(self.check_prev_applications_url)
        assertContains(
            response, "Ce candidat a déjà postulé chez cet employeur durant les dernières 24 heures.", status_code=403
        )
        # Make it less recent to avoid the 403
        job_application.created_at = timezone.now() - datetime.timedelta(days=2)
        job_application.save(update_fields=("created_at",))
        response = client.get(self.check_prev_applications_url)
        assertContains(response, "Le candidat a déjà postulé chez cet employeur le")
        response = client.post(self.check_prev_applications_url, data={"force_new_application": "force"})
        assertRedirects(response, self.application_jobs_url)

        # Reset URL is correct
        response = client.get(self.application_jobs_url)
        company_card_url = reverse("companies_views:card", kwargs={"siae_id": self.company.pk})
        assertContains(response, LINK_RESET_MARKUP % company_card_url, count=1)


@pytest.mark.ignore_unknown_variable_template_error("job_seeker")
class TestFindJobSeekerForHireView:
    @pytest.fixture(autouse=True)
    def setup_method(self):
        self.company = CompanyFactory(with_membership=True)

    def get_check_nir_url(self, client):
        # Init session
        start_url = reverse("apply:start_hire", kwargs={"company_pk": self.company.pk})
        client.get(start_url, follow=True)
        [job_seeker_session_name] = [k for k in client.session.keys() if k not in KNOWN_SESSION_KEYS]
        return reverse("job_seekers_views:check_nir_for_hire", kwargs={"session_uuid": job_seeker_session_name})

    def test_job_seeker_found_with_nir(self, client):
        user = self.company.members.first()
        client.force_login(user)

        job_seeker = JobSeekerFactory(first_name="Sylvie", last_name="Martin")

        check_nir_url = self.get_check_nir_url(client)
        response = client.get(check_nir_url)
        assertContains(response, "Déclarer une embauche")

        response = client.post(check_nir_url, data={"nir": job_seeker.jobseeker_profile.nir, "preview": 1})
        assertContains(response, "Sylvie MARTIN")
        # Confirmation modal is shown
        assert response.context["preview_mode"] is True

        response = client.post(check_nir_url, data={"nir": job_seeker.jobseeker_profile.nir, "confirm": 1})
        assertRedirects(
            response,
            reverse(
                "job_seekers_views:check_job_seeker_info_for_hire",
                kwargs={"company_pk": self.company.pk, "job_seeker_public_id": job_seeker.public_id},
            ),
        )

    def test_job_seeker_found_with_email(self, client):
        user = self.company.members.first()
        client.force_login(user)

        job_seeker = JobSeekerFactory(first_name="Sylvie", last_name="Martin")
        INVALID_NIR = "123456"

        check_nir_url = self.get_check_nir_url(client)
        response = client.get(check_nir_url)
        assertContains(response, "Déclarer une embauche")

        response = client.post(check_nir_url, data={"nir": INVALID_NIR, "preview": 1})
        assertContains(response, "Le numéro de sécurité sociale est trop court")
        [job_seeker_session_name] = [k for k in client.session.keys() if k not in KNOWN_SESSION_KEYS]
        search_by_email_url = reverse(
            "job_seekers_views:search_by_email_for_hire",
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

        response = client.get(search_by_email_url)
        assertContains(response, "Déclarer une embauche")  # Check page title
        assertContains(response, check_nir_url)  # Check back button URL
        assertNotContains(response, INVALID_NIR)

        response = client.post(search_by_email_url, data={"email": job_seeker.email, "preview": 1})
        assertContains(response, "Sylvie MARTIN")
        # Confirmation modal is shown
        assert response.context["preview_mode"] is True

        response = client.post(search_by_email_url, data={"email": job_seeker.email, "confirm": 1})
        assertRedirects(
            response,
            reverse(
                "job_seekers_views:check_job_seeker_info_for_hire",
                kwargs={"company_pk": self.company.pk, "job_seeker_public_id": job_seeker.public_id},
            ),
        )

    def test_no_job_seeker_redirect_to_create(self, client):
        user = self.company.members.first()
        client.force_login(user)

        dummy_job_seeker = JobSeekerFactory.build(
            with_address=True,
            jobseeker_profile__with_hexa_address=True,
        )

        check_nir_url = self.get_check_nir_url(client)
        response = client.get(check_nir_url)
        assertContains(response, "Déclarer une embauche")

        response = client.post(check_nir_url, data={"nir": dummy_job_seeker.jobseeker_profile.nir, "preview": 1})

        job_seeker_session_name = str(resolve(response.url).kwargs["session_uuid"])
        search_by_email_url = reverse(
            "job_seekers_views:search_by_email_for_hire",
            kwargs={"session_uuid": job_seeker_session_name},
        )
        assertRedirects(response, search_by_email_url)

        response = client.get(search_by_email_url)
        assertContains(response, "Déclarer une embauche")  # Check page title
        assertContains(response, check_nir_url)  # Check back button URL
        assertContains(response, dummy_job_seeker.jobseeker_profile.nir)

        response = client.post(search_by_email_url, data={"email": dummy_job_seeker.email})
        assertRedirects(
            response,
            reverse(
                "job_seekers_views:create_job_seeker_step_1_for_hire",
                kwargs={"session_uuid": job_seeker_session_name},
            ),
        )

        expected_job_seeker_session = {
            "config": {
                "tunnel": "hire",
                "from_url": reverse("dashboard:index"),  # Hire: reset_url = dashboard
                "session_kind": JobSeekerSessionKinds.GET_OR_CREATE,
            },
            "apply": {"company_pk": self.company.pk},
            "user": {
                "email": dummy_job_seeker.email,
            },
            "profile": {
                "nir": dummy_job_seeker.jobseeker_profile.nir,
            },
        }
        assert client.session[job_seeker_session_name] == expected_job_seeker_session


class TestCheckJobSeekerInformationsForHire:
    def test_company(self, client):
        company = CompanyFactory(subject_to_eligibility=True, with_membership=True)
        job_seeker = JobSeekerFactory(
            first_name="Son prénom",
            last_name="Son nom de famille",
            jobseeker_profile__nir="",
            jobseeker_profile__lack_of_nir_reason=LackOfNIRReason.TEMPORARY_NUMBER,
        )
        client.force_login(company.members.first())
        url_check_infos = reverse(
            "job_seekers_views:check_job_seeker_info_for_hire",
            kwargs={"company_pk": company.pk, "job_seeker_public_id": job_seeker.public_id},
        )
        response = client.get(url_check_infos)
        assertContains(
            response,
            """<h1 class="mb-1 mb-xl-0 me-xl-3 text-xl-nowrap">
            Informations personnelles de Son Prénom SON NOM DE FAMILLE</h1>""",
            html=True,
        )
        assertTemplateNotUsed(response, "approvals/includes/box.html")
        assertContains(response, "Éligibilité IAE à valider")
        params = {
            "job_seeker": job_seeker.public_id,
            "from_url": url_check_infos,
        }
        url_update = f"""
        <a class="btn btn-outline-primary float-end"
           href="{add_url_params(reverse("job_seekers_views:update_job_seeker_start"), params)}">Mettre à jour</a>
        """
        assertContains(response, url_update, html=True)
        assertContains(
            response,
            reverse(
                "apply:check_prev_applications_for_hire",
                kwargs={"company_pk": company.pk, "job_seeker_public_id": job_seeker.public_id},
            ),
        )

        assertContains(
            response,
            reverse("apply:start_hire", kwargs={"company_pk": company.pk}),
        )
        assertContains(response, reverse("dashboard:index"))

    def test_geiq(self, client):
        company = CompanyFactory(kind=CompanyKind.GEIQ, with_membership=True)
        job_seeker = JobSeekerFactory(
            first_name="Son prénom",
            last_name="Son nom de famille",
            jobseeker_profile__nir="",
            jobseeker_profile__lack_of_nir_reason=LackOfNIRReason.TEMPORARY_NUMBER,
        )
        client.force_login(company.members.first())
        url_check_infos = reverse(
            "job_seekers_views:check_job_seeker_info_for_hire",
            kwargs={"company_pk": company.pk, "job_seeker_public_id": job_seeker.public_id},
        )
        response = client.get(url_check_infos)
        assertContains(
            response,
            """<h1 class="mb-1 mb-xl-0 me-xl-3 text-xl-nowrap">
            Informations personnelles de Son Prénom SON NOM DE FAMILLE</h1>""",
            html=True,
        )
        assertTemplateNotUsed(response, "approvals/includes/box.html")
        params = {
            "job_seeker": job_seeker.public_id,
            "from_url": url_check_infos,
        }
        url_update = f"""
        <a class="btn btn-outline-primary float-end"
           href="{add_url_params(reverse("job_seekers_views:update_job_seeker_start"), params)}">Mettre à jour</a>
        """
        assertContains(response, url_update, html=True)
        assertContains(
            response,
            reverse(
                "apply:check_prev_applications_for_hire",
                kwargs={"company_pk": company.pk, "job_seeker_public_id": job_seeker.public_id},
            ),
        )
        assertContains(response, reverse("dashboard:index"))


@pytest.mark.ignore_unknown_variable_template_error("is_subject_to_eligibility_rules")
class TestCheckPreviousApplicationsForHireView:
    @pytest.fixture(autouse=True)
    def self(cls):
        cls.job_seeker = JobSeekerFactory()

    def _reverse(self, view_name):
        return reverse(
            view_name, kwargs={"company_pk": self.company.pk, "job_seeker_public_id": self.job_seeker.public_id}
        )

    def test_no_previous_as_employer(self, client):
        self.company = CompanyFactory(subject_to_eligibility=True, with_membership=True)
        client.force_login(self.company.members.first())

        response = client.get(self._reverse("apply:check_prev_applications_for_hire"))
        assertRedirects(response, self._reverse("apply:eligibility_for_hire"))

    def test_with_previous_as_employer(self, client):
        self.company = CompanyFactory(subject_to_eligibility=True, with_membership=True)
        JobApplicationFactory(job_seeker=self.job_seeker, to_company=self.company, eligibility_diagnosis=None)
        client.force_login(self.company.members.first())

        response = client.get(self._reverse("apply:check_prev_applications_for_hire"))
        assertTemplateNotUsed(response, "approvals/includes/box.html")
        assertContains(response, "Le candidat a déjà postulé chez cet employeur le")
        response = client.post(
            self._reverse("apply:check_prev_applications_for_hire"), data={"force_new_application": "force"}
        )
        assertRedirects(response, self._reverse("apply:eligibility_for_hire"))

    def test_no_previous_as_geiq_staff(self, client):
        self.company = CompanyFactory(kind=CompanyKind.GEIQ, with_membership=True)
        client.force_login(self.company.members.first())

        response = client.get(self._reverse("apply:check_prev_applications_for_hire"))
        assertRedirects(response, self._reverse("apply:geiq_eligibility_for_hire"))

    def test_with_previous_as_geiq_staff(self, client):
        self.company = CompanyFactory(kind=CompanyKind.GEIQ, with_membership=True)
        JobApplicationFactory(job_seeker=self.job_seeker, to_company=self.company, eligibility_diagnosis=None)
        client.force_login(self.company.members.first())

        response = client.get(self._reverse("apply:check_prev_applications_for_hire"))
        assertContains(response, "Le candidat a déjà postulé chez cet employeur le")
        assertTemplateNotUsed(response, "approvals/includes/box.html")
        response = client.post(
            self._reverse("apply:check_prev_applications_for_hire"), data={"force_new_application": "force"}
        )
        assertRedirects(response, self._reverse("apply:geiq_eligibility_for_hire"))


@pytest.mark.ignore_unknown_variable_template_error("is_subject_to_eligibility_rules")
class TestEligibilityForHire:
    @pytest.fixture(autouse=True)
    def setup_method(self):
        self.job_seeker = JobSeekerFactory(first_name="Ellie", last_name="Gibilitay")

    def _reverse(self, view_name):
        return reverse(
            view_name, kwargs={"company_pk": self.company.pk, "job_seeker_public_id": self.job_seeker.public_id}
        )

    def test_not_subject_to_eligibility(self, client):
        self.company = CompanyFactory(not_subject_to_eligibility=True, with_membership=True)
        client.force_login(self.company.members.first())
        response = client.get(self._reverse("apply:eligibility_for_hire"))
        assertRedirects(response, self._reverse("apply:hire_confirmation"))

    def test_job_seeker_with_valid_diagnosis(self, client):
        self.company = CompanyFactory(subject_to_eligibility=True, with_membership=True)
        IAEEligibilityDiagnosisFactory(from_prescriber=True, job_seeker=self.job_seeker)
        client.force_login(self.company.members.first())
        response = client.get(self._reverse("apply:eligibility_for_hire"))
        assertRedirects(response, self._reverse("apply:hire_confirmation"))

    def test_job_seeker_without_valid_diagnosis(self, client):
        self.company = CompanyFactory(subject_to_eligibility=True, with_membership=True)
        assert not self.job_seeker.has_valid_diagnosis(for_siae=self.company)
        client.force_login(self.company.members.first())
        response = client.get(self._reverse("apply:eligibility_for_hire"))
        assertContains(response, "Déclarer l’embauche de Ellie GIBILITAY")
        assertContains(response, "Valider l'éligibilité IAE")
        assertContains(response, self._reverse("job_seekers_views:check_job_seeker_info_for_hire"))  # cancel button

        criterion1 = AdministrativeCriteria.objects.level1().get(pk=1)
        criterion2 = AdministrativeCriteria.objects.level2().get(pk=5)
        criterion3 = AdministrativeCriteria.objects.level2().get(pk=15)
        response = client.post(
            self._reverse("apply:eligibility_for_hire"),
            data={
                # Administrative criteria level 1.
                f"{criterion1.key}": "on",
                # Administrative criteria level 2.
                f"{criterion2.key}": "on",
                f"{criterion3.key}": "on",
            },
        )
        assertRedirects(response, self._reverse("apply:hire_confirmation"))
        assert self.job_seeker.has_valid_diagnosis(for_siae=self.company)


class TestGEIQEligibilityForHire:
    @pytest.fixture(autouse=True)
    def setup_method(self):
        self.job_seeker = JobSeekerFactory(first_name="Ellie", last_name="Gibilitay")

    def _reverse(self, view_name):
        return reverse(
            view_name, kwargs={"company_pk": self.company.pk, "job_seeker_public_id": self.job_seeker.public_id}
        )

    def test_not_geiq(self, client):
        self.company = CompanyFactory(subject_to_eligibility=True, with_membership=True)
        client.force_login(self.company.members.first())
        response = client.get(self._reverse("apply:geiq_eligibility_for_hire"))
        assert response.status_code == 404

    def test_job_seeker_with_valid_diagnosis(self, client):
        diagnosis = GEIQEligibilityDiagnosisFactory(job_seeker=self.job_seeker, from_geiq=True)
        diagnosis.administrative_criteria.add(GEIQAdministrativeCriteria.objects.get(pk=19))
        self.company = diagnosis.author_geiq
        client.force_login(self.company.members.first())
        response = client.get(self._reverse("apply:eligibility_for_hire"))
        assertRedirects(response, self._reverse("apply:hire_confirmation"))

    def test_job_seeker_without_valid_diagnosis(self, client):
        self.company = CompanyFactory(kind=CompanyKind.GEIQ, with_membership=True)
        assert not GEIQEligibilityDiagnosis.objects.valid_diagnoses_for(self.job_seeker, self.company).exists()
        client.force_login(self.company.members.first())
        response = client.get(self._reverse("apply:geiq_eligibility_for_hire"))
        assertContains(response, "Déclarer l’embauche de Ellie GIBILITAY")
        assertContains(response, "Eligibilité GEIQ")
        assertContains(response, self._reverse("job_seekers_views:check_job_seeker_info_for_hire"))  # cancel button

        response = client.post(
            self._reverse("apply:geiq_eligibility_for_hire"),
            data={"choice": "True"},
            headers={"hx-request": "true"},
        )
        criteria_url = add_url_params(
            self._reverse("apply:geiq_eligibility_criteria_for_hire"),
            {
                "back_url": self._reverse("job_seekers_views:check_job_seeker_info_for_hire"),
                "next_url": self._reverse("apply:hire_confirmation"),
            },
        )
        assertRedirects(
            response,
            criteria_url,
            fetch_redirect_response=False,
        )
        htmx_response = client.get(criteria_url, headers={"hx-request": "true"})
        assert htmx_response.status_code == 200

        response = client.post(
            criteria_url,
            data={
                "jeune_26_ans": "on",
                "jeune_de_moins_de_26_ans_sans_qualification": "on",
                "proof_of_eligibility": "on",
            },
        )
        assertRedirects(response, self._reverse("apply:hire_confirmation"))
        assert GEIQEligibilityDiagnosis.objects.valid_diagnoses_for(self.job_seeker, self.company).exists()


class TestHireConfirmation:
    @pytest.fixture(autouse=True)
    def setup_method(self, settings, mocker):
        self.job_seeker = JobSeekerFactory(
            first_name="Clara",
            last_name="Sion",
            with_pole_emploi_id=True,
            with_ban_geoloc_address=True,
            born_in_france=True,
        )
        # This is the city matching with_ban_geoloc_address trait
        self.city = create_city_geispolsheim()

        settings.API_BAN_BASE_URL = "http://ban-api"
        mocker.patch(
            "itou.utils.apis.geocoding.get_geocoding_data",
            side_effect=mock_get_first_geocoding_data,
        )

    def _reverse(self, view_name):
        return reverse(
            view_name, kwargs={"company_pk": self.company.pk, "job_seeker_public_id": self.job_seeker.public_id}
        )

    def test_as_company(self, client, snapshot):
        self.company = CompanyFactory(subject_to_eligibility=True, with_membership=True)
        IAEEligibilityDiagnosisFactory(from_prescriber=True, job_seeker=self.job_seeker)
        client.force_login(self.company.members.first())

        with assertSnapshotQueries(snapshot(name="view queries")):
            response = client.get(self._reverse("apply:hire_confirmation"))
        assertContains(response, "Déclarer l’embauche de Clara SION")
        assertContains(response, "Éligible à l’IAE")

        hiring_start_at = timezone.localdate()
        post_data = {
            "hiring_start_at": hiring_start_at.strftime(DuetDatePickerWidget.INPUT_DATE_FORMAT),
            "hiring_end_at": "",
            "pole_emploi_id": self.job_seeker.jobseeker_profile.pole_emploi_id,
            "lack_of_pole_emploi_id_reason": self.job_seeker.jobseeker_profile.lack_of_pole_emploi_id_reason,
            "birthdate": self.job_seeker.jobseeker_profile.birthdate.isoformat(),
            "birth_place": self.job_seeker.jobseeker_profile.birth_place.pk,
            "birth_country": self.job_seeker.jobseeker_profile.birth_country.pk,
            "answer": "",
            "ban_api_resolved_address": self.job_seeker.geocoding_address,
            "address_line_1": self.job_seeker.address_line_1,
            "post_code": self.city.post_codes[0],
            "insee_code": self.city.code_insee,
            "city": self.city.name,
            "phone": self.job_seeker.phone,
            "fill_mode": "ban_api",
            "address_for_autocomplete": "0",
        }
        response = client.post(
            self._reverse("apply:hire_confirmation"),
            data=post_data,
            headers={"hx-request": "true"},
        )
        assert response.status_code == 200
        assert (
            response.headers.get("HX-Trigger") == '{"modalControl": {"id": "js-confirmation-modal", "action": "show"}}'
        )
        post_data = post_data | {"confirmed": "True"}
        response = client.post(
            self._reverse("apply:hire_confirmation"), headers={"hx-request": "true"}, data=post_data
        )

        job_application = JobApplication.objects.select_related("job_seeker").get(
            sender=self.company.members.first(), to_company=self.company
        )
        next_url = reverse("employees:detail", kwargs={"public_id": job_application.job_seeker.public_id})
        assertRedirects(response, next_url, status_code=200)

        assert job_application.job_seeker == self.job_seeker
        assert job_application.sender_kind == SenderKind.EMPLOYER
        assert job_application.sender_company == self.company
        assert job_application.sender_prescriber_organization is None
        assert job_application.state == JobApplicationState.ACCEPTED
        assert job_application.message == ""
        assert list(job_application.selected_jobs.all()) == []
        assert job_application.resume_link == ""

    def test_cannot_hire_start_date_after_approval_expires(self, client):
        self.company = CompanyFactory(subject_to_eligibility=True, with_membership=True)
        client.force_login(self.company.members.first())

        today = timezone.localdate()
        approval = ApprovalFactory(end_at=today + datetime.timedelta(days=1))
        self.job_seeker.approvals.add(approval)

        hiring_start_at = today + datetime.timedelta(days=2)
        post_data = {
            "hiring_start_at": hiring_start_at.strftime(DuetDatePickerWidget.INPUT_DATE_FORMAT),
            "hiring_end_at": "",
            "pole_emploi_id": self.job_seeker.jobseeker_profile.pole_emploi_id,
            "lack_of_pole_emploi_id_reason": self.job_seeker.jobseeker_profile.lack_of_pole_emploi_id_reason,
            "birthdate": self.job_seeker.jobseeker_profile.birthdate.isoformat(),
            "birth_place": self.job_seeker.jobseeker_profile.birth_place.pk,
            "birth_country": self.job_seeker.jobseeker_profile.birth_country.pk,
            "answer": "",
            "ban_api_resolved_address": self.job_seeker.geocoding_address,
            "address_line_1": self.job_seeker.address_line_1,
            "post_code": self.city.post_codes[0],
            "insee_code": self.city.code_insee,
            "city": self.city.name,
            "phone": self.job_seeker.phone,
            "fill_mode": "ban_api",
            "address_for_autocomplete": "0",
        }
        response = client.post(self._reverse("apply:hire_confirmation"), data=post_data)
        assert response.status_code == 200
        assertFormError(
            response.context["form_accept"],
            "hiring_start_at",
            JobApplication.ERROR_HIRES_AFTER_APPROVAL_EXPIRES,
        )

    def test_as_company_elibility_diagnosis_from_another_company(self, client, snapshot):
        eligibility_diagnosis = IAEEligibilityDiagnosisFactory(from_employer=True, job_seeker=self.job_seeker)
        ApprovalFactory(eligibility_diagnosis=eligibility_diagnosis, user=self.job_seeker)
        self.company = CompanyFactory(subject_to_eligibility=True, with_membership=True)
        client.force_login(self.company.members.get())

        response = client.get(self._reverse("apply:hire_confirmation"))
        assertContains(response, "Déclarer l’embauche de Clara SION")
        assertContains(response, "PASS IAE valide")

        hiring_start_at = timezone.localdate()
        post_data = {
            "hiring_start_at": hiring_start_at.strftime(DuetDatePickerWidget.INPUT_DATE_FORMAT),
            "hiring_end_at": "",
            "pole_emploi_id": self.job_seeker.jobseeker_profile.pole_emploi_id,
            "lack_of_pole_emploi_id_reason": self.job_seeker.jobseeker_profile.lack_of_pole_emploi_id_reason,
            "birthdate": self.job_seeker.jobseeker_profile.birthdate.isoformat(),
            "birth_place": self.job_seeker.jobseeker_profile.birth_place.pk,
            "birth_country": self.job_seeker.jobseeker_profile.birth_country.pk,
            "answer": "",
            "ban_api_resolved_address": self.job_seeker.geocoding_address,
            "address_line_1": self.job_seeker.address_line_1,
            "post_code": self.city.post_codes[0],
            "insee_code": self.city.code_insee,
            "city": self.city.name,
            "phone": self.job_seeker.phone,
            "fill_mode": "ban_api",
            "address_for_autocomplete": "0",
            "confirmed": "True",
        }
        response = client.post(
            self._reverse("apply:hire_confirmation"),
            data=post_data,
            headers={"hx-request": "true"},
        )

        job_application = JobApplication.objects.select_related("job_seeker").get(
            sender=self.company.members.first(), to_company=self.company
        )
        next_url = reverse("employees:detail", kwargs={"public_id": job_application.job_seeker.public_id})
        assertRedirects(response, next_url, status_code=200)

        assert job_application.job_seeker == self.job_seeker
        assert job_application.sender_kind == SenderKind.EMPLOYER
        assert job_application.sender_company == self.company
        assert job_application.sender_prescriber_organization is None
        assert job_application.state == JobApplicationState.ACCEPTED
        assert job_application.message == ""
        assert list(job_application.selected_jobs.all()) == []
        assert job_application.resume_link == ""

    def test_as_geiq(self, client):
        diagnosis = GEIQEligibilityDiagnosisFactory(job_seeker=self.job_seeker, from_geiq=True)
        diagnosis.administrative_criteria.add(GEIQAdministrativeCriteria.objects.get(pk=19))
        self.company = diagnosis.author_geiq
        client.force_login(self.company.members.first())
        response = client.get(self._reverse("apply:hire_confirmation"))
        assertContains(response, "Déclarer l’embauche de Clara SION")
        assertContains(response, "Éligibilité GEIQ confirmée")

        hiring_start_at = timezone.localdate()
        post_data = {
            "hiring_start_at": hiring_start_at.strftime(DuetDatePickerWidget.INPUT_DATE_FORMAT),
            "hiring_end_at": "",
            "pole_emploi_id": self.job_seeker.jobseeker_profile.pole_emploi_id,
            "lack_of_pole_emploi_id_reason": self.job_seeker.jobseeker_profile.lack_of_pole_emploi_id_reason,
            "answer": "",
            "address_line_1": "1, Adress Line",
            "post_code": "Post code",
            "city": self.city.name,
            # GEIQ specific fields
            "hired_job": self.company.job_description_through.first().pk,
            "prehiring_guidance_days": 3,
            "nb_hours_per_week": 4,
            "planned_training_hours": 5,
            "contract_type": ContractType.APPRENTICESHIP,
            "qualification_type": QualificationType.STATE_DIPLOMA,
            "qualification_level": QualificationLevel.LEVEL_4,
        }
        response = client.post(
            self._reverse("apply:hire_confirmation"),
            data=post_data,
            headers={"hx-request": "true"},
        )
        assert response.status_code == 200
        assert (
            response.headers.get("HX-Trigger") == '{"modalControl": {"id": "js-confirmation-modal", "action": "show"}}'
        )
        post_data = post_data | {"confirmed": "True"}
        response = client.post(
            self._reverse("apply:hire_confirmation"), headers={"hx-request": "true"}, data=post_data
        )

        job_application = JobApplication.objects.get(sender=self.company.members.first(), to_company=self.company)
        next_url = reverse("apply:details_for_company", kwargs={"job_application_id": job_application.pk})
        assertRedirects(response, next_url, status_code=200)

        assert job_application.job_seeker == self.job_seeker
        assert job_application.sender_kind == SenderKind.EMPLOYER
        assert job_application.sender_company == self.company
        assert job_application.sender_prescriber_organization is None
        assert job_application.state == JobApplicationState.ACCEPTED
        assert job_application.message == ""
        assert list(job_application.selected_jobs.all()) == []
        assert job_application.resume_link == ""


class TestNewHireProcessInfo:
    GEIQ_APPLY_PROCESS_INFO = "Cet espace vous permet d’enregistrer une candidature à traiter plus tard"
    OTHER_APPLY_PROCESS_INFO = "Cet espace vous permet d’enregistrer une nouvelle candidature."

    GEIQ_DIRECT_HIRE_PROCESS_INFO = "Si vous souhaitez créer une candidature à traiter plus tard"
    OTHER_DIRECT_HIRE_PROCESS_INFO = "Pour la création d’une candidature, veuillez vous rendre sur"

    @pytest.fixture(autouse=True)
    def setup_method(self):
        self.company = CompanyFactory(subject_to_eligibility=True, with_membership=True)
        self.geiq = CompanyFactory(kind=CompanyKind.GEIQ, with_membership=True)
        self.job_seeker = JobSeekerFactory(jobseeker_profile__nir="")

    def test_as_job_seeker(self, client):
        client.force_login(self.job_seeker)
        response = client.get(reverse("apply:start", kwargs={"company_pk": self.company.pk}), follow=True)
        assertNotContains(response, self.OTHER_APPLY_PROCESS_INFO)
        assertNotContains(response, self.OTHER_DIRECT_HIRE_PROCESS_INFO)
        response = client.get(reverse("apply:start", kwargs={"company_pk": self.geiq.pk}), follow=True)
        assertNotContains(response, self.GEIQ_APPLY_PROCESS_INFO)
        assertNotContains(response, self.GEIQ_DIRECT_HIRE_PROCESS_INFO)

    def test_as_prescriber(self, client):
        client.force_login(PrescriberFactory())
        response = client.get(reverse("apply:start", kwargs={"company_pk": self.company.pk}), follow=True)
        assertNotContains(response, self.OTHER_APPLY_PROCESS_INFO)
        assertNotContains(response, self.OTHER_DIRECT_HIRE_PROCESS_INFO)
        response = client.get(reverse("apply:start", kwargs={"company_pk": self.geiq.pk}), follow=True)
        assertNotContains(response, self.GEIQ_APPLY_PROCESS_INFO)
        assertNotContains(response, self.GEIQ_DIRECT_HIRE_PROCESS_INFO)

    def test_as_employer(self, client):
        client.force_login(self.company.members.first())

        # Init session
        response = client.get(reverse("apply:start_hire", kwargs={"company_pk": self.company.pk}), follow=True)
        [job_seeker_session_name] = [k for k in client.session.keys() if k not in KNOWN_SESSION_KEYS]
        response = client.get(
            reverse("job_seekers_views:check_nir_for_sender", kwargs={"session_uuid": job_seeker_session_name})
        )
        assertContains(response, self.OTHER_APPLY_PROCESS_INFO)
        assertNotContains(response, self.OTHER_DIRECT_HIRE_PROCESS_INFO)
        response = client.get(
            reverse("job_seekers_views:check_nir_for_hire", kwargs={"session_uuid": job_seeker_session_name})
        )
        assertNotContains(response, self.OTHER_APPLY_PROCESS_INFO)
        assertContains(response, self.OTHER_DIRECT_HIRE_PROCESS_INFO)

        client.force_login(self.geiq.members.first())

        # Init session
        response = client.get(reverse("apply:start_hire", kwargs={"company_pk": self.geiq.pk}), follow=True)
        [job_seeker_session_name_geiq] = [k for k in client.session.keys() if k not in KNOWN_SESSION_KEYS]
        response = client.get(
            reverse("job_seekers_views:check_nir_for_sender", kwargs={"session_uuid": job_seeker_session_name_geiq})
        )
        assertContains(response, self.GEIQ_APPLY_PROCESS_INFO)
        assertNotContains(response, self.GEIQ_DIRECT_HIRE_PROCESS_INFO)
        response = client.get(
            reverse("job_seekers_views:check_nir_for_hire", kwargs={"session_uuid": job_seeker_session_name_geiq})
        )
        assertNotContains(response, self.GEIQ_APPLY_PROCESS_INFO)
        assertContains(response, self.GEIQ_DIRECT_HIRE_PROCESS_INFO)
