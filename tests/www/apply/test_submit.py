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
from pytest_django.asserts import assertContains, assertRedirects

from itou.asp.models import AllocationDuration, EducationLevel, RSAAllocation
from itou.companies.enums import CompanyKind, ContractType
from itou.eligibility.models import (
    AdministrativeCriteria,
    EligibilityDiagnosis,
    GEIQAdministrativeCriteria,
    GEIQEligibilityDiagnosis,
)
from itou.job_applications.enums import QualificationLevel, QualificationType, SenderKind
from itou.job_applications.models import JobApplication
from itou.siae_evaluations.models import Sanctions
from itou.users.enums import LackOfNIRReason, LackOfPoleEmploiId
from itou.users.models import User
from itou.utils.models import InclusiveDateRange
from itou.utils.session import SessionNamespace
from itou.utils.urls import add_url_params
from itou.utils.widgets import DuetDatePickerWidget
from tests.approvals.factories import PoleEmploiApprovalFactory
from tests.cities.factories import create_city_in_zrr, create_test_cities
from tests.companies.factories import CompanyFactory, CompanyWithMembershipAndJobsFactory
from tests.eligibility.factories import EligibilityDiagnosisFactory, GEIQEligibilityDiagnosisFactory
from tests.geo.factories import ZRRFactory
from tests.institutions.factories import InstitutionWithMembershipFactory
from tests.job_applications.factories import JobApplicationFactory
from tests.prescribers.factories import PrescriberOrganizationWithMembershipFactory
from tests.siae_evaluations.factories import EvaluatedSiaeFactory
from tests.users.factories import (
    EmployerFactory,
    ItouStaffFactory,
    JobSeekerFactory,
    JobSeekerProfileWithHexaAddressFactory,
    JobSeekerWithAddressFactory,
    PrescriberFactory,
)
from tests.users.test_models import user_with_approval_in_waiting_period
from tests.utils.test import TestCase, assertMessages


class ApplyTest(TestCase):
    def test_company_with_no_members(self):
        company = CompanyFactory()
        user = JobSeekerFactory()
        self.client.force_login(user)
        url = reverse("apply:start", kwargs={"company_pk": company.pk})
        response = self.client.get(url)
        assert response.status_code == 403
        assertContains(
            response,
            '<p class="mb-0">'
            "Cet employeur n&#x27;est pas inscrit, vous ne pouvez pas déposer de candidatures en ligne."
            "</p>",
            status_code=403,
            count=1,
        )

    def test_anonymous_access(self):
        company = CompanyFactory(with_jobs=True, with_membership=True)
        for viewname in (
            "apply:start",
            "apply:pending_authorization_for_sender",
            "apply:check_nir_for_sender",
            "apply:check_nir_for_job_seeker",
        ):
            url = reverse(viewname, kwargs={"company_pk": company.pk})
            response = self.client.get(url)
            self.assertRedirects(response, reverse("account_login") + f"?next={url}")

        job_seeker = JobSeekerFactory()
        for viewname in (
            "apply:step_check_job_seeker_info",
            "apply:step_check_prev_applications",
            "apply:application_jobs",
            "apply:application_eligibility",
            "apply:application_geiq_eligibility",
            "apply:application_resume",
        ):
            url = reverse(viewname, kwargs={"company_pk": company.pk, "job_seeker_pk": job_seeker.pk})
            response = self.client.get(url)
            self.assertRedirects(response, reverse("account_login") + f"?next={url}")

    def test_we_raise_a_permission_denied_on_missing_session(self):
        user = JobSeekerFactory()
        company = CompanyFactory(with_jobs=True)

        self.client.force_login(user)
        response = self.client.get(
            reverse(
                "apply:search_by_email_for_sender",
                kwargs={"company_pk": company.pk, "session_uuid": str(uuid.uuid4())},
            )
        )
        assert response.status_code == 403
        assert response.context["exception"] == "A session namespace doesn't exist."

    def test_we_raise_a_permission_denied_on_missing_temporary_session_for_create_job_seeker(self):
        routes = {
            "apply:create_job_seeker_step_1_for_sender",
            "apply:create_job_seeker_step_2_for_sender",
            "apply:create_job_seeker_step_3_for_sender",
            "apply:create_job_seeker_step_end_for_sender",
        }
        user = JobSeekerFactory()
        company = CompanyFactory(with_jobs=True)

        self.client.force_login(user)
        for route in routes:
            with self.subTest(route=route):
                response = self.client.get(
                    reverse(route, kwargs={"company_pk": company.pk, "session_uuid": uuid.uuid4()})
                )
                assert response.status_code == 403
                assert response.context["exception"] == "A session namespace doesn't exist."

    def test_404_when_trying_to_apply_for_a_prescriber(self):
        company = CompanyFactory(with_jobs=True)
        prescriber = PrescriberFactory()
        self.client.force_login(prescriber)
        for viewname in (
            "apply:step_check_job_seeker_info",
            "apply:step_check_prev_applications",
            "apply:application_jobs",
            "apply:application_eligibility",
            "apply:application_geiq_eligibility",
            "apply:application_resume",
        ):
            url = reverse(viewname, kwargs={"company_pk": company.pk, "job_seeker_pk": prescriber.pk})
            response = self.client.get(url)
            assert response.status_code == 404

    def test_resume_is_optional(self):
        company = CompanyFactory(with_jobs=True, with_membership=True)
        job_seeker = JobSeekerFactory()
        self.client.force_login(job_seeker)
        response = self.client.post(
            reverse("apply:application_resume", kwargs={"company_pk": company.pk, "job_seeker_pk": job_seeker.pk}),
            {"message": "Hire me?"},
        )
        job_application = JobApplication.objects.get()
        self.assertRedirects(
            response,
            reverse("apply:application_end", kwargs={"company_pk": company.pk, "application_pk": job_application.pk}),
        )


class HireTest(TestCase):
    def test_anonymous_access(self):
        company = CompanyFactory(with_jobs=True, with_membership=True)
        url = reverse("apply:check_nir_for_hire", kwargs={"company_pk": company.pk})
        response = self.client.get(url)
        self.assertRedirects(response, reverse("account_login") + f"?next={url}")

        job_seeker = JobSeekerFactory()
        for viewname in (
            "apply:check_job_seeker_info_for_hire",
            "apply:check_prev_applications_for_hire",
            "apply:eligibility_for_hire",
            "apply:geiq_eligibility_for_hire",
            "apply:geiq_eligibility_criteria_for_hire",
            "apply:hire_confirmation",
        ):
            url = reverse(viewname, kwargs={"company_pk": company.pk, "job_seeker_pk": job_seeker.pk})
            response = self.client.get(url)
            self.assertRedirects(response, reverse("account_login") + f"?next={url}")

    def test_we_raise_a_permission_denied_on_missing_session(self):
        user = JobSeekerFactory()
        company = CompanyFactory(with_jobs=True)

        self.client.force_login(user)
        response = self.client.get(
            reverse(
                "apply:search_by_email_for_hire", kwargs={"company_pk": company.pk, "session_uuid": str(uuid.uuid4())}
            )
        )
        assert response.status_code == 403
        assert response.context["exception"] == "A session namespace doesn't exist."

    def test_we_raise_a_permission_denied_on_missing_temporary_session_for_create_job_seeker(self):
        routes = {
            "apply:create_job_seeker_step_1_for_hire",
            "apply:create_job_seeker_step_2_for_hire",
            "apply:create_job_seeker_step_3_for_hire",
            "apply:create_job_seeker_step_end_for_hire",
        }
        user = JobSeekerFactory()
        company = CompanyFactory(with_jobs=True)

        self.client.force_login(user)
        for route in routes:
            with self.subTest(route=route):
                response = self.client.get(
                    reverse(route, kwargs={"company_pk": company.pk, "session_uuid": uuid.uuid4()})
                )
                assert response.status_code == 403
                assert response.context["exception"] == "A session namespace doesn't exist."

    def test_403_when_trying_to_update_a_prescriber(self):
        company = CompanyFactory(with_jobs=True, with_membership=True)
        prescriber = PrescriberFactory()
        self.client.force_login(company.members.first())
        for viewname in (
            "apply:update_job_seeker_step_1_for_hire",
            "apply:update_job_seeker_step_2_for_hire",
            "apply:update_job_seeker_step_3_for_hire",
            "apply:update_job_seeker_step_end_for_hire",
        ):
            url = reverse(viewname, kwargs={"company_pk": company.pk, "job_seeker_pk": prescriber.pk})
            response = self.client.get(url)
            assert response.status_code == 403

    def test_404_when_trying_to_hire_a_prescriber(self):
        company = CompanyFactory(with_jobs=True, with_membership=True)
        prescriber = PrescriberFactory()
        self.client.force_login(company.members.first())
        for viewname in (
            "apply:check_job_seeker_info_for_hire",
            "apply:check_prev_applications_for_hire",
            "apply:eligibility_for_hire",
            "apply:geiq_eligibility_for_hire",
            "apply:geiq_eligibility_criteria_for_hire",
            "apply:hire_confirmation",
        ):
            url = reverse(viewname, kwargs={"company_pk": company.pk, "job_seeker_pk": prescriber.pk})
            response = self.client.get(url)
            assert response.status_code == 404

    def test_403_when_trying_to_hire_a_jobseeker_with_invalid_approval(self):
        company = CompanyFactory(with_membership=True)
        job_seeker = user_with_approval_in_waiting_period()
        self.client.force_login(company.members.first())
        for viewname in (
            "apply:check_job_seeker_info_for_hire",
            "apply:check_prev_applications_for_hire",
            "apply:eligibility_for_hire",
            "apply:hire_confirmation",
        ):
            url = reverse(viewname, kwargs={"company_pk": company.pk, "job_seeker_pk": job_seeker.pk})
            response = self.client.get(url)
            self.assertContains(
                response, "Le candidat a terminé un parcours il y a moins de deux ans", status_code=403
            )


def test_check_nir_job_seeker_with_lack_of_nir_reason(client):
    """Apply as jobseeker."""

    company = CompanyWithMembershipAndJobsFactory(romes=("N1101", "N1105"))

    user = JobSeekerFactory(birthdate=None, nir="", lack_of_nir_reason=LackOfNIRReason.TEMPORARY_NUMBER)
    client.force_login(user)

    # Entry point.
    # ----------------------------------------------------------------------

    response = client.get(reverse("apply:start", kwargs={"company_pk": company.pk}))
    assert response.status_code == 302

    session_data = client.session[f"job_application-{company.pk}"]
    assert session_data == {
        "selected_jobs": [],
    }

    next_url = reverse("apply:check_nir_for_job_seeker", kwargs={"company_pk": company.pk})
    assert response.url == next_url

    # Step check job seeker NIR.
    # ----------------------------------------------------------------------

    response = client.get(next_url)
    assert response.status_code == 200

    nir = "141068078200557"
    post_data = {"nir": nir, "confirm": 1}

    response = client.post(next_url, data=post_data)
    assert response.status_code == 302

    user.refresh_from_db()
    assert user.nir == nir
    assert user.lack_of_nir_reason == ""


@pytest.mark.usefixtures("unittest_compatibility")
class ApplyAsJobSeekerTest(TestCase):
    @property
    def default_session_data(self):
        return {
            "selected_jobs": [],
        }

    def test_apply_as_job_seeker_with_suspension_sanction(self):
        company = CompanyWithMembershipAndJobsFactory(romes=("N1101", "N1105"))
        Sanctions.objects.create(
            evaluated_siae=EvaluatedSiaeFactory(siae=company),
            suspension_dates=InclusiveDateRange(timezone.localdate() - relativedelta(days=1)),
        )

        user = JobSeekerFactory(birthdate=None, nir="")
        self.client.force_login(user)

        response = self.client.get(reverse("apply:start", kwargs={"company_pk": company.pk}))
        # The suspension does not prevent access to the process
        self.assertRedirects(
            response, expected_url=reverse("apply:check_nir_for_job_seeker", kwargs={"company_pk": company.pk})
        )

    def test_apply_as_jobseeker(self):
        """Apply as jobseeker."""

        company = CompanyWithMembershipAndJobsFactory(romes=("N1101", "N1105"))

        user = JobSeekerFactory(birthdate=None, nir="")
        self.client.force_login(user)

        # Entry point.
        # ----------------------------------------------------------------------

        response = self.client.get(reverse("apply:start", kwargs={"company_pk": company.pk}))
        assert response.status_code == 302

        session_data = self.client.session[f"job_application-{company.pk}"]
        assert session_data == self.default_session_data

        next_url = reverse("apply:check_nir_for_job_seeker", kwargs={"company_pk": company.pk})
        assert response.url == next_url

        # Step check job seeker NIR.
        # ----------------------------------------------------------------------

        response = self.client.get(next_url)
        assert response.status_code == 200

        nir = "141068078200557"
        post_data = {"nir": nir, "confirm": 1}

        response = self.client.post(next_url, data=post_data)
        assert response.status_code == 302

        user = User.objects.get(pk=user.pk)
        assert user.nir == nir

        session_data = self.client.session[f"job_application-{company.pk}"]
        assert session_data == self.default_session_data

        next_url = reverse(
            "apply:step_check_job_seeker_info", kwargs={"company_pk": company.pk, "job_seeker_pk": user.pk}
        )
        assert response.url == next_url

        # Step check job seeker info.
        # ----------------------------------------------------------------------

        response = self.client.get(next_url)
        assert response.status_code == 200

        post_data = {"birthdate": "20/12/1978", "phone": "0610203040", "pole_emploi_id": "1234567A"}

        response = self.client.post(next_url, data=post_data)
        assert response.status_code == 302

        user = User.objects.get(pk=user.pk)
        assert user.birthdate.strftime("%d/%m/%Y") == post_data["birthdate"]
        assert user.phone == post_data["phone"]

        assert user.pole_emploi_id == post_data["pole_emploi_id"]

        next_url = reverse(
            "apply:step_check_prev_applications", kwargs={"company_pk": company.pk, "job_seeker_pk": user.pk}
        )
        assert response.url == next_url

        # Step check previous job applications.
        # ----------------------------------------------------------------------

        response = self.client.get(next_url)
        assert response.status_code == 302

        next_url = reverse("apply:application_jobs", kwargs={"company_pk": company.pk, "job_seeker_pk": user.pk})
        assert response.url == next_url

        # Step application's jobs.
        # ----------------------------------------------------------------------

        response = self.client.get(next_url)
        # Check back_url is present
        self.assertContains(
            response,
            reverse("apply:step_check_job_seeker_info", kwargs={"company_pk": company.pk, "job_seeker_pk": user.pk}),
        )

        response = self.client.post(next_url, data={"selected_jobs": [company.job_description_through.first().pk]})
        assert response.status_code == 302

        assert self.client.session[f"job_application-{company.pk}"] == self.default_session_data | {
            "selected_jobs": [company.job_description_through.first().pk],
        }

        next_url = reverse(
            "apply:application_eligibility", kwargs={"company_pk": company.pk, "job_seeker_pk": user.pk}
        )
        assert response.url == next_url

        # Step application's eligibility.
        # ----------------------------------------------------------------------
        response = self.client.get(next_url)
        assert response.status_code == 302

        next_url = reverse("apply:application_resume", kwargs={"company_pk": company.pk, "job_seeker_pk": user.pk})
        assert response.url == next_url

        # Step application's resume.
        # ----------------------------------------------------------------------
        response = self.client.get(next_url)
        self.assertContains(response, "Envoyer la candidature")

        with mock.patch(
            "itou.www.apply.views.submit_views.uuid.uuid4",
            return_value=uuid.UUID("11111111-1111-1111-1111-111111111111"),
        ):
            response = self.client.post(
                next_url,
                data={
                    "selected_jobs": [company.job_description_through.first().pk],
                    "message": "Lorem ipsum dolor sit amet, consectetur adipiscing elit.",
                    "resume": self.pdf_file,
                },
            )
        assert response.status_code == 302

        job_application = JobApplication.objects.get(sender=user, to_company=company)
        assert job_application.job_seeker == user
        assert job_application.sender_kind == SenderKind.JOB_SEEKER
        assert job_application.sender_company is None
        assert job_application.sender_prescriber_organization is None
        assert job_application.state == job_application.state.workflow.STATE_NEW
        assert job_application.message == "Lorem ipsum dolor sit amet, consectetur adipiscing elit."
        assert list(job_application.selected_jobs.all()) == [company.job_description_through.first()]
        assert job_application.resume_link == (
            f"{settings.AWS_S3_ENDPOINT_URL}tests/{storages['public'].location}"
            "/resume/11111111-1111-1111-1111-111111111111.pdf"
        )

        assert f"job_application-{company.pk}" not in self.client.session

        next_url = reverse(
            "apply:application_end", kwargs={"company_pk": company.pk, "application_pk": job_application.pk}
        )
        assert response.url == next_url

        # Step application's end.
        # ----------------------------------------------------------------------
        response = self.client.get(next_url)
        # 1 in desktop header
        # + 1 in mobile header
        # + 1 in the page content
        self.assertContains(response, reverse("dashboard:edit_user_info"), count=3)

    def test_apply_as_job_seeker_temporary_nir(self):
        """
        Full path is tested above. See test_apply_as_job_seeker.
        """
        company = CompanyWithMembershipAndJobsFactory(romes=("N1101", "N1105"))

        user = JobSeekerFactory(nir="")
        self.client.force_login(user)

        # Entry point.
        # ----------------------------------------------------------------------

        response = self.client.get(reverse("apply:start", kwargs={"company_pk": company.pk}), follow=True)
        assert response.status_code == 200

        # Follow all redirections until NIR.
        # ----------------------------------------------------------------------
        next_url = reverse("apply:check_nir_for_job_seeker", kwargs={"company_pk": company.pk})

        response = self.client.post(next_url, data={"nir": "123456789KLOIU"})
        assert response.status_code == 200
        assert not response.context["form"].is_valid()

        # Temporary number should be skipped.
        response = self.client.post(next_url, data={"nir": "123456789KLOIU", "skip": 1}, follow=True)
        assert response.status_code == 200
        assert response.redirect_chain[-1][0] == reverse(
            "apply:application_jobs", kwargs={"company_pk": company.pk, "job_seeker_pk": user.pk}
        )

        user.refresh_from_db()
        assert not user.nir

    def test_apply_as_job_seeker_on_sender_tunnel(self):
        company = CompanyFactory()
        user = JobSeekerFactory()
        self.client.force_login(user)

        self.client.get(reverse("apply:start", kwargs={"company_pk": company.pk}))  # Init the session
        response = self.client.get(reverse("apply:check_nir_for_sender", kwargs={"company_pk": company.pk}))
        self.assertRedirects(
            response, reverse("apply:start", kwargs={"company_pk": company.pk}), fetch_redirect_response=False
        )

    def test_apply_as_job_seeker_resume_not_pdf(self):
        company = CompanyWithMembershipAndJobsFactory(romes=("N1101"))
        user = JobSeekerFactory()
        self.client.force_login(user)
        with io.BytesIO(b"Plain text") as text_file:
            text_file.name = "cv.txt"
            response = self.client.post(
                reverse(
                    "apply:application_resume",
                    kwargs={
                        "company_pk": company.pk,
                        "job_seeker_pk": user.pk,
                    },
                ),
                data={
                    "selected_jobs": [company.job_description_through.first().pk],
                    "message": "Lorem ipsum dolor sit amet.",
                    "resume": text_file,
                },
            )
        self.assertContains(
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

    def test_apply_as_job_seeker_resume_not_pdf_disguised_as_pdf(self):
        company = CompanyWithMembershipAndJobsFactory(romes=("N1101"))
        user = JobSeekerFactory()
        self.client.force_login(user)
        with io.BytesIO(b"Plain text") as text_file:
            text_file.name = "cv.pdf"
            response = self.client.post(
                reverse(
                    "apply:application_resume",
                    kwargs={
                        "company_pk": company.pk,
                        "job_seeker_pk": user.pk,
                    },
                ),
                data={
                    "selected_jobs": [company.job_description_through.first().pk],
                    "message": "Lorem ipsum dolor sit amet.",
                    "resume": text_file,
                },
            )
        self.assertContains(
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

    def test_apply_as_job_seeker_resume_too_large(self):
        company = CompanyWithMembershipAndJobsFactory(romes=("N1101"))
        user = JobSeekerFactory()
        self.client.force_login(user)
        with io.BytesIO(b"A" * (5 * 1024 * 1024 + 1)) as text_file:
            text_file.name = "cv.pdf"
            response = self.client.post(
                reverse(
                    "apply:application_resume",
                    kwargs={
                        "company_pk": company.pk,
                        "job_seeker_pk": user.pk,
                    },
                ),
                data={
                    "selected_jobs": [company.job_description_through.first().pk],
                    "message": "Lorem ipsum dolor sit amet.",
                    "resume": text_file,
                },
            )
        self.assertContains(
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


@pytest.mark.usefixtures("unittest_compatibility")
class ApplyAsAuthorizedPrescriberTest(TestCase):
    def setUp(self):
        super().setUp()
        [self.city] = create_test_cities(["67"], num_per_department=1)

    @property
    def default_session_data(self):
        return {
            "selected_jobs": [],
        }

    def test_apply_as_prescriber_with_pending_authorization(self):
        """Apply as prescriber that has pending authorization."""

        company = CompanyWithMembershipAndJobsFactory(romes=("N1101", "N1105"))

        prescriber_organization = PrescriberOrganizationWithMembershipFactory(with_pending_authorization=True)
        user = prescriber_organization.members.first()
        self.client.force_login(user)

        dummy_job_seeker = JobSeekerWithAddressFactory.build()
        dummy_job_seeker.jobseeker_profile = JobSeekerProfileWithHexaAddressFactory.build()

        # Entry point.
        # ----------------------------------------------------------------------

        response = self.client.get(reverse("apply:start", kwargs={"company_pk": company.pk}))
        assert response.status_code == 302

        session = self.client.session
        session_data = session[f"job_application-{company.pk}"]
        assert session_data == self.default_session_data

        next_url = reverse("apply:pending_authorization_for_sender", kwargs={"company_pk": company.pk})
        assert response.url == next_url

        # Step show warning message about pending authorization.
        # ----------------------------------------------------------------------

        response = self.client.get(next_url)

        next_url = reverse("apply:check_nir_for_sender", kwargs={"company_pk": company.pk})
        self.assertContains(response, "Status de prescripteur habilité non vérifié")
        self.assertContains(response, next_url)

        # Step determine the job seeker with a NIR.
        # ----------------------------------------------------------------------

        response = self.client.get(next_url)
        assert response.status_code == 200

        response = self.client.post(next_url, data={"nir": dummy_job_seeker.nir, "confirm": 1})
        assert self.client.session[f"job_application-{company.pk}"] == self.default_session_data
        assert response.status_code == 302

        job_seeker_session_name = str(resolve(response.url).kwargs["session_uuid"])
        next_url = reverse(
            "apply:search_by_email_for_sender",
            kwargs={"company_pk": company.pk, "session_uuid": job_seeker_session_name},
        )
        assert response.url == next_url
        assert self.client.session[job_seeker_session_name] == {"user": {"nir": dummy_job_seeker.nir}}

        # Step get job seeker e-mail.
        # ----------------------------------------------------------------------

        response = self.client.get(next_url)
        assert response.status_code == 200

        response = self.client.post(next_url, data={"email": dummy_job_seeker.email, "confirm": "1"})
        assert response.status_code == 302
        job_seeker_session_name = str(resolve(response.url).kwargs["session_uuid"])

        expected_job_seeker_session = {
            "user": {
                "email": dummy_job_seeker.email,
                "nir": dummy_job_seeker.nir,
            }
        }
        assert self.client.session[job_seeker_session_name] == expected_job_seeker_session

        next_url = reverse(
            "apply:create_job_seeker_step_1_for_sender",
            kwargs={"company_pk": company.pk, "session_uuid": job_seeker_session_name},
        )
        assert response.url == next_url

        # Step create a job seeker.
        # ----------------------------------------------------------------------

        response = self.client.get(next_url)
        # The NIR is prefilled
        self.assertContains(response, dummy_job_seeker.nir)
        # The back_url is correct
        self.assertContains(
            response,
            reverse(
                "apply:search_by_email_for_sender",
                kwargs={"company_pk": company.pk, "session_uuid": job_seeker_session_name},
            ),
        )

        post_data = {
            "title": dummy_job_seeker.title,
            "first_name": dummy_job_seeker.first_name,
            "last_name": dummy_job_seeker.last_name,
            "birthdate": dummy_job_seeker.birthdate,
            "lack_of_nir": False,
            "lack_of_nir_reason": "",
        }
        response = self.client.post(next_url, data=post_data)
        assert response.status_code == 302
        expected_job_seeker_session["user"] |= post_data
        assert self.client.session[job_seeker_session_name] == expected_job_seeker_session

        next_url = reverse(
            "apply:create_job_seeker_step_2_for_sender",
            kwargs={"company_pk": company.pk, "session_uuid": job_seeker_session_name},
        )
        assert response.url == next_url

        response = self.client.get(next_url)
        assert response.status_code == 200

        post_data = {
            "address_line_1": dummy_job_seeker.address_line_1,
            "post_code": self.city.post_codes[0],
            "city_slug": self.city.slug,
            "city": self.city.name,
            "phone": dummy_job_seeker.phone,
        }
        response = self.client.post(next_url, data=post_data)
        assert response.status_code == 302
        expected_job_seeker_session["user"] |= post_data | {"department": "67", "address_line_2": ""}
        assert self.client.session[job_seeker_session_name] == expected_job_seeker_session

        next_url = reverse(
            "apply:create_job_seeker_step_3_for_sender",
            kwargs={"company_pk": company.pk, "session_uuid": job_seeker_session_name},
        )
        assert response.url == next_url

        response = self.client.get(next_url)
        assert response.status_code == 200

        post_data = {
            "education_level": dummy_job_seeker.jobseeker_profile.education_level,
        }
        response = self.client.post(next_url, data=post_data)
        assert response.status_code == 302
        expected_job_seeker_session["profile"] = post_data | {
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
        expected_job_seeker_session["user"] |= {
            "pole_emploi_id": "",
            "lack_of_pole_emploi_id_reason": LackOfPoleEmploiId.REASON_NOT_REGISTERED,
        }
        assert self.client.session[job_seeker_session_name] == expected_job_seeker_session

        next_url = reverse(
            "apply:create_job_seeker_step_end_for_sender",
            kwargs={"company_pk": company.pk, "session_uuid": job_seeker_session_name},
        )
        assert response.url == next_url

        response = self.client.get(next_url)
        self.assertContains(response, "Créer le compte candidat")

        response = self.client.post(next_url)
        assert response.status_code == 302

        assert job_seeker_session_name not in self.client.session
        new_job_seeker = User.objects.get(email=dummy_job_seeker.email)
        assert self.client.session[f"job_application-{company.pk}"] == self.default_session_data

        next_url = reverse(
            "apply:application_jobs", kwargs={"company_pk": company.pk, "job_seeker_pk": new_job_seeker.pk}
        )
        assert response.url == next_url

        # Step application's jobs.
        # ----------------------------------------------------------------------

        response = self.client.get(next_url)
        assert response.status_code == 200

        response = self.client.post(next_url, data={"selected_jobs": [company.job_description_through.first().pk]})
        assert response.status_code == 302

        assert self.client.session[f"job_application-{company.pk}"] == self.default_session_data | {
            "selected_jobs": [company.job_description_through.first().pk],
        }

        next_url = reverse(
            "apply:application_eligibility", kwargs={"company_pk": company.pk, "job_seeker_pk": new_job_seeker.pk}
        )
        assert response.url == next_url

        # Step application's eligibility.
        # ----------------------------------------------------------------------
        response = self.client.get(next_url)
        assert response.status_code == 302

        next_url = reverse(
            "apply:application_resume", kwargs={"company_pk": company.pk, "job_seeker_pk": new_job_seeker.pk}
        )
        assert response.url == next_url

        # Step application's resume.
        # ----------------------------------------------------------------------
        response = self.client.get(next_url)

        with mock.patch(
            "itou.www.apply.views.submit_views.uuid.uuid4",
            return_value=uuid.UUID("11111111-1111-1111-1111-111111111111"),
        ):
            response = self.client.post(
                next_url,
                data={
                    "selected_jobs": [
                        company.job_description_through.first().pk,
                        company.job_description_through.last().pk,
                    ],
                    "message": "Lorem ipsum dolor sit amet, consectetur adipiscing elit.",
                    "resume": self.pdf_file,
                },
            )
        assert response.status_code == 302

        job_application = JobApplication.objects.get(sender=user, to_company=company)
        assert job_application.job_seeker == new_job_seeker
        assert job_application.sender_kind == SenderKind.PRESCRIBER
        assert job_application.sender_company is None
        assert job_application.sender_prescriber_organization == prescriber_organization
        assert job_application.state == job_application.state.workflow.STATE_NEW
        assert job_application.message == "Lorem ipsum dolor sit amet, consectetur adipiscing elit."
        assert list(job_application.selected_jobs.all()) == [
            company.job_description_through.first(),
            company.job_description_through.last(),
        ]
        assert (
            job_application.resume_link == f"{settings.AWS_S3_ENDPOINT_URL}"
            f"tests/{storages['public'].location}/resume/11111111-1111-1111-1111-111111111111.pdf"
        )

        assert f"job_application-{company.pk}" not in self.client.session

        next_url = reverse(
            "apply:application_end", kwargs={"company_pk": company.pk, "application_pk": job_application.pk}
        )
        assert response.url == next_url

        # Step application's end.
        # ----------------------------------------------------------------------
        response = self.client.get(next_url)
        assert response.status_code == 200

    def test_apply_as_authorized_prescriber(self):
        company = CompanyWithMembershipAndJobsFactory(romes=("N1101", "N1105"))

        # test ZRR / QPV template loading
        city = create_city_in_zrr()
        ZRRFactory(insee_code=city.code_insee)

        prescriber_organization = PrescriberOrganizationWithMembershipFactory(authorized=True)
        user = prescriber_organization.members.first()
        self.client.force_login(user)

        dummy_job_seeker = JobSeekerWithAddressFactory.build()
        dummy_job_seeker.jobseeker_profile = JobSeekerProfileWithHexaAddressFactory.build()

        # Entry point.
        # ----------------------------------------------------------------------

        response = self.client.get(reverse("apply:start", kwargs={"company_pk": company.pk}))
        assert response.status_code == 302

        session_data = self.client.session[f"job_application-{company.pk}"]
        assert session_data == self.default_session_data

        next_url = reverse("apply:check_nir_for_sender", kwargs={"company_pk": company.pk})
        assert response.url == next_url

        # Step determine the job seeker with a NIR.
        # ----------------------------------------------------------------------

        response = self.client.get(next_url)
        assert response.status_code == 200

        response = self.client.post(next_url, data={"nir": dummy_job_seeker.nir, "confirm": 1})
        assert response.status_code == 302
        assert self.client.session[f"job_application-{company.pk}"] == self.default_session_data

        session_uuid = str(resolve(response.url).kwargs["session_uuid"])
        next_url = reverse(
            "apply:search_by_email_for_sender", kwargs={"company_pk": company.pk, "session_uuid": session_uuid}
        )
        assert response.url == next_url

        # Step get job seeker e-mail.
        # ----------------------------------------------------------------------

        response = self.client.get(next_url)
        assert response.status_code == 200

        response = self.client.post(next_url, data={"email": dummy_job_seeker.email, "confirm": "1"})
        assert response.status_code == 302
        job_seeker_session_name = str(resolve(response.url).kwargs["session_uuid"])

        expected_job_seeker_session = {
            "user": {
                "email": dummy_job_seeker.email,
                "nir": dummy_job_seeker.nir,
            }
        }
        assert self.client.session[job_seeker_session_name] == expected_job_seeker_session

        next_url = reverse(
            "apply:create_job_seeker_step_1_for_sender",
            kwargs={"company_pk": company.pk, "session_uuid": job_seeker_session_name},
        )
        assert response.url == next_url

        # Step create a job seeker.
        # ----------------------------------------------------------------------

        response = self.client.get(next_url)
        # Check that the back url is correct
        self.assertContains(
            response,
            reverse(
                "apply:search_by_email_for_sender",
                kwargs={"company_pk": company.pk, "session_uuid": job_seeker_session_name},
            ),
        )

        post_data = {
            "title": dummy_job_seeker.title,
            "first_name": dummy_job_seeker.first_name,
            "last_name": dummy_job_seeker.last_name,
            "birthdate": dummy_job_seeker.birthdate,
            "nir": dummy_job_seeker.nir,
            "lack_of_nir": False,
            "lack_of_nir_reason": "",
        }
        response = self.client.post(next_url, data=post_data)
        assert response.status_code == 302
        expected_job_seeker_session["user"] |= post_data
        assert self.client.session[job_seeker_session_name] == expected_job_seeker_session

        next_url = reverse(
            "apply:create_job_seeker_step_2_for_sender",
            kwargs={"company_pk": company.pk, "session_uuid": job_seeker_session_name},
        )
        assert response.url == next_url

        response = self.client.get(next_url)
        assert response.status_code == 200

        post_data = {
            "address_line_1": dummy_job_seeker.address_line_1,
            "post_code": city.post_codes[0],
            "city_slug": city.slug,
            "city": city.name,
            "phone": dummy_job_seeker.phone,
        }
        response = self.client.post(next_url, data=post_data)
        assert response.status_code == 302
        expected_job_seeker_session["user"] |= post_data | {"department": "12", "address_line_2": ""}
        assert self.client.session[job_seeker_session_name] == expected_job_seeker_session

        next_url = reverse(
            "apply:create_job_seeker_step_3_for_sender",
            kwargs={"company_pk": company.pk, "session_uuid": job_seeker_session_name},
        )
        assert response.url == next_url

        response = self.client.get(next_url)
        assert response.status_code == 200

        post_data = {
            "education_level": dummy_job_seeker.jobseeker_profile.education_level,
        }
        response = self.client.post(next_url, data=post_data)
        assert response.status_code == 302
        expected_job_seeker_session["profile"] = post_data | {
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
        expected_job_seeker_session["user"] |= {
            "pole_emploi_id": "",
            "lack_of_pole_emploi_id_reason": LackOfPoleEmploiId.REASON_NOT_REGISTERED,
        }
        assert self.client.session[job_seeker_session_name] == expected_job_seeker_session

        next_url = reverse(
            "apply:create_job_seeker_step_end_for_sender",
            kwargs={"company_pk": company.pk, "session_uuid": job_seeker_session_name},
        )
        assert response.url == next_url

        response = self.client.get(next_url)
        self.assertContains(response, "Créer le compte candidat")

        response = self.client.post(next_url)
        assert response.status_code == 302

        assert job_seeker_session_name not in self.client.session
        new_job_seeker = User.objects.get(email=dummy_job_seeker.email)
        assert self.client.session[f"job_application-{company.pk}"] == self.default_session_data

        next_url = reverse(
            "apply:application_jobs", kwargs={"company_pk": company.pk, "job_seeker_pk": new_job_seeker.pk}
        )
        assert response.url == next_url

        # Step application's jobs.
        # ----------------------------------------------------------------------

        response = self.client.get(next_url)
        assert response.status_code == 200

        response = self.client.post(next_url, data={"selected_jobs": [company.job_description_through.first().pk]})
        assert response.status_code == 302

        assert self.client.session[f"job_application-{company.pk}"] == self.default_session_data | {
            "selected_jobs": [company.job_description_through.first().pk],
        }

        next_url = reverse(
            "apply:application_eligibility", kwargs={"company_pk": company.pk, "job_seeker_pk": new_job_seeker.pk}
        )
        assert response.url == next_url

        # Step application's eligibility.
        # ----------------------------------------------------------------------
        response = self.client.get(next_url)
        assert response.status_code == 200
        assert not EligibilityDiagnosis.objects.has_considered_valid(new_job_seeker, for_siae=company)
        self.assertTemplateUsed(response, "apply/includes/known_criteria.html", count=1)

        response = self.client.post(next_url, {"level_1_1": True})
        assert response.status_code == 302
        assert EligibilityDiagnosis.objects.has_considered_valid(new_job_seeker, for_siae=company)

        next_url = reverse(
            "apply:application_resume", kwargs={"company_pk": company.pk, "job_seeker_pk": new_job_seeker.pk}
        )
        assert response.url == next_url

        # Step application's resume.
        # ----------------------------------------------------------------------
        response = self.client.get(next_url)

        with mock.patch(
            "itou.www.apply.views.submit_views.uuid.uuid4",
            return_value=uuid.UUID("11111111-1111-1111-1111-111111111111"),
        ):
            response = self.client.post(
                next_url,
                data={
                    "selected_jobs": [
                        company.job_description_through.first().pk,
                        company.job_description_through.last().pk,
                    ],
                    "message": "Lorem ipsum dolor sit amet, consectetur adipiscing elit.",
                    "resume": self.pdf_file,
                },
            )
        assert response.status_code == 302

        job_application = JobApplication.objects.get(sender=user, to_company=company)
        assert job_application.job_seeker == new_job_seeker
        assert job_application.sender_kind == SenderKind.PRESCRIBER
        assert job_application.sender_company is None
        assert job_application.sender_prescriber_organization == prescriber_organization
        assert job_application.state == job_application.state.workflow.STATE_NEW
        assert job_application.message == "Lorem ipsum dolor sit amet, consectetur adipiscing elit."
        assert list(job_application.selected_jobs.all()) == [
            company.job_description_through.first(),
            company.job_description_through.last(),
        ]
        assert job_application.resume_link == (
            f"{settings.AWS_S3_ENDPOINT_URL}tests/{storages['public'].location}"
            "/resume/11111111-1111-1111-1111-111111111111.pdf"
        )

        assert f"job_application-{company.pk}" not in self.client.session

        next_url = reverse(
            "apply:application_end", kwargs={"company_pk": company.pk, "application_pk": job_application.pk}
        )
        assert response.url == next_url

        # Step application's end.
        # ----------------------------------------------------------------------
        response = self.client.get(next_url)
        assert response.status_code == 200


@pytest.mark.usefixtures("unittest_compatibility")
class ApplyAsPrescriberTest(TestCase):
    def setUp(self):
        super().setUp()
        cities = create_test_cities(["67"], num_per_department=10)
        self.city = cities[0]

    @property
    def default_session_data(self):
        return {
            "selected_jobs": [],
        }

    def test_apply_as_prescriber_with_suspension_sanction(self):
        company = CompanyWithMembershipAndJobsFactory(romes=("N1101", "N1105"))
        Sanctions.objects.create(
            evaluated_siae=EvaluatedSiaeFactory(siae=company),
            suspension_dates=InclusiveDateRange(timezone.localdate() - relativedelta(days=1)),
        )

        user = PrescriberFactory()
        self.client.force_login(user)

        response = self.client.get(reverse("apply:start", kwargs={"company_pk": company.pk}))
        # The suspension does not prevent the access to the process
        self.assertRedirects(
            response, expected_url=reverse("apply:check_nir_for_sender", kwargs={"company_pk": company.pk})
        )

    def test_apply_as_prescriber(self):
        company = CompanyWithMembershipAndJobsFactory(romes=("N1101", "N1105"))

        user = PrescriberFactory()
        self.client.force_login(user)

        dummy_job_seeker = JobSeekerWithAddressFactory.build()
        dummy_job_seeker.jobseeker_profile = JobSeekerProfileWithHexaAddressFactory.build()

        # Entry point.
        # ----------------------------------------------------------------------

        response = self.client.get(reverse("apply:start", kwargs={"company_pk": company.pk}))
        assert response.status_code == 302

        session_data = self.client.session[f"job_application-{company.pk}"]
        assert session_data == self.default_session_data

        next_url = reverse("apply:check_nir_for_sender", kwargs={"company_pk": company.pk})
        assert response.url == next_url

        # Step determine the job seeker with a NIR.
        # ----------------------------------------------------------------------

        response = self.client.get(next_url)
        assert response.status_code == 200

        response = self.client.post(next_url, data={"nir": dummy_job_seeker.nir, "confirm": 1})
        assert self.client.session[f"job_application-{company.pk}"] == self.default_session_data
        assert response.status_code == 302

        job_seeker_session_name = str(resolve(response.url).kwargs["session_uuid"])
        next_url = reverse(
            "apply:search_by_email_for_sender",
            kwargs={"company_pk": company.pk, "session_uuid": job_seeker_session_name},
        )
        assert response.url == next_url
        assert self.client.session[job_seeker_session_name] == {"user": {"nir": dummy_job_seeker.nir}}

        # Step get job seeker e-mail.
        # ----------------------------------------------------------------------

        response = self.client.get(next_url)
        assert response.status_code == 200

        response = self.client.post(next_url, data={"email": dummy_job_seeker.email, "confirm": "1"})
        assert response.status_code == 302
        job_seeker_session_name = str(resolve(response.url).kwargs["session_uuid"])

        expected_job_seeker_session = {
            "user": {
                "email": dummy_job_seeker.email,
                "nir": dummy_job_seeker.nir,
            }
        }
        assert self.client.session[job_seeker_session_name] == expected_job_seeker_session

        next_url = reverse(
            "apply:create_job_seeker_step_1_for_sender",
            kwargs={"company_pk": company.pk, "session_uuid": job_seeker_session_name},
        )
        assert response.url == next_url

        # Step create a job seeker.
        # ----------------------------------------------------------------------

        response = self.client.get(next_url)
        # The NIR is prefilled
        self.assertContains(response, dummy_job_seeker.nir)
        # Check that the back url is correct
        self.assertContains(
            response,
            reverse(
                "apply:search_by_email_for_sender",
                kwargs={"company_pk": company.pk, "session_uuid": job_seeker_session_name},
            ),
        )

        post_data = {
            "title": dummy_job_seeker.title,
            "first_name": dummy_job_seeker.first_name,
            "last_name": dummy_job_seeker.last_name,
            "birthdate": dummy_job_seeker.birthdate,
            "lack_of_nir": False,
            "lack_of_nir_reason": "",
        }
        response = self.client.post(next_url, data=post_data)
        assert response.status_code == 302
        expected_job_seeker_session["user"] |= post_data
        assert self.client.session[job_seeker_session_name] == expected_job_seeker_session

        next_url = reverse(
            "apply:create_job_seeker_step_2_for_sender",
            kwargs={"company_pk": company.pk, "session_uuid": job_seeker_session_name},
        )
        assert response.url == next_url

        response = self.client.get(next_url)
        assert response.status_code == 200

        post_data = {
            "address_line_1": dummy_job_seeker.address_line_1,
            "post_code": self.city.post_codes[0],
            "city_slug": self.city.slug,
            "city": self.city.name,
            "phone": dummy_job_seeker.phone,
        }
        response = self.client.post(next_url, data=post_data)
        assert response.status_code == 302
        expected_job_seeker_session["user"] |= post_data | {"department": "67", "address_line_2": ""}
        assert self.client.session[job_seeker_session_name] == expected_job_seeker_session

        next_url = reverse(
            "apply:create_job_seeker_step_3_for_sender",
            kwargs={"company_pk": company.pk, "session_uuid": job_seeker_session_name},
        )
        assert response.url == next_url

        response = self.client.get(next_url)
        assert response.status_code == 200

        post_data = {
            "education_level": dummy_job_seeker.jobseeker_profile.education_level,
        }
        response = self.client.post(next_url, data=post_data)
        assert response.status_code == 302
        expected_job_seeker_session["profile"] = post_data | {
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
        expected_job_seeker_session["user"] |= {
            "pole_emploi_id": "",
            "lack_of_pole_emploi_id_reason": LackOfPoleEmploiId.REASON_NOT_REGISTERED,
        }
        assert self.client.session[job_seeker_session_name] == expected_job_seeker_session

        next_url = reverse(
            "apply:create_job_seeker_step_end_for_sender",
            kwargs={"company_pk": company.pk, "session_uuid": job_seeker_session_name},
        )
        assert response.url == next_url

        response = self.client.get(next_url)
        self.assertContains(response, "Créer le compte candidat")

        # Let's add another job seeker with exactly the same NIR, in the middle of the process.
        # ----------------------------------------------------------------------
        other_job_seeker = JobSeekerFactory(nir=dummy_job_seeker.nir)

        response = self.client.post(next_url)
        assertMessages(
            response, [(messages.ERROR, "Ce numéro de sécurité sociale est déjà associé à un autre utilisateur.")]
        )
        self.assertRedirects(response, reverse("dashboard:index"))

        # Remove that extra job seeker and proceed with "normal" flow
        # ----------------------------------------------------------------------
        other_job_seeker.delete()

        response = self.client.post(next_url)
        assert response.status_code == 302

        assert job_seeker_session_name not in self.client.session
        new_job_seeker = User.objects.get(email=dummy_job_seeker.email)
        assert self.client.session[f"job_application-{company.pk}"] == self.default_session_data

        next_url = reverse(
            "apply:application_jobs", kwargs={"company_pk": company.pk, "job_seeker_pk": new_job_seeker.pk}
        )
        assert response.url == next_url

        # Step application's jobs.
        # ----------------------------------------------------------------------

        response = self.client.get(next_url)
        assert response.status_code == 200

        response = self.client.post(next_url, data={"selected_jobs": [company.job_description_through.first().pk]})
        assert response.status_code == 302

        assert self.client.session[f"job_application-{company.pk}"] == self.default_session_data | {
            "selected_jobs": [company.job_description_through.first().pk],
        }

        next_url = reverse(
            "apply:application_eligibility", kwargs={"company_pk": company.pk, "job_seeker_pk": new_job_seeker.pk}
        )
        assert response.url == next_url

        # Step application's eligibility.
        # ----------------------------------------------------------------------
        response = self.client.get(next_url)
        assert response.status_code == 302

        next_url = reverse(
            "apply:application_resume", kwargs={"company_pk": company.pk, "job_seeker_pk": new_job_seeker.pk}
        )
        assert response.url == next_url

        # Step application's resume.
        # ----------------------------------------------------------------------
        response = self.client.get(next_url)

        with mock.patch(
            "itou.www.apply.views.submit_views.uuid.uuid4",
            return_value=uuid.UUID("11111111-1111-1111-1111-111111111111"),
        ):
            response = self.client.post(
                next_url,
                data={
                    "selected_jobs": [
                        company.job_description_through.first().pk,
                        company.job_description_through.last().pk,
                    ],
                    "message": "Lorem ipsum dolor sit amet, consectetur adipiscing elit.",
                    "resume": self.pdf_file,
                },
            )
        assert response.status_code == 302

        job_application = JobApplication.objects.get(sender=user, to_company=company)
        assert job_application.job_seeker == new_job_seeker
        assert job_application.sender_kind == SenderKind.PRESCRIBER
        assert job_application.sender_company is None
        assert job_application.sender_prescriber_organization is None
        assert job_application.state == job_application.state.workflow.STATE_NEW
        assert job_application.message == "Lorem ipsum dolor sit amet, consectetur adipiscing elit."
        assert list(job_application.selected_jobs.all()) == [
            company.job_description_through.first(),
            company.job_description_through.last(),
        ]
        assert job_application.resume_link == (
            f"{settings.AWS_S3_ENDPOINT_URL}tests/{storages['public'].location}"
            "/resume/11111111-1111-1111-1111-111111111111.pdf"
        )

        assert f"job_application-{company.pk}" not in self.client.session

        next_url = reverse(
            "apply:application_end", kwargs={"company_pk": company.pk, "application_pk": job_application.pk}
        )
        assert response.url == next_url

        # Step application's end.
        # ----------------------------------------------------------------------
        response = self.client.get(next_url)
        assert response.status_code == 200

    def test_apply_as_prescriber_on_job_seeker_tunnel(self):
        company = CompanyFactory()
        user = PrescriberFactory()
        self.client.force_login(user)

        self.client.get(reverse("apply:start", kwargs={"company_pk": company.pk}))  # Use that view to init the session
        response = self.client.get(reverse("apply:check_nir_for_job_seeker", kwargs={"company_pk": company.pk}))
        self.assertRedirects(
            response, reverse("apply:start", kwargs={"company_pk": company.pk}), fetch_redirect_response=False
        )


class ApplyAsPrescriberNirExceptionsTest(TestCase):
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

    def test_one_account_no_nir(self):
        """
        No account with this NIR is found.
        A search by email is proposed.
        An account is found for this email.
        This NIR account is empty.
        An update is expected.
        """
        job_seeker = JobSeekerFactory(nir="")
        # Create an approval to bypass the eligibility diagnosis step.
        PoleEmploiApprovalFactory(birthdate=job_seeker.birthdate, pole_emploi_id=job_seeker.pole_emploi_id)
        company, user = self.create_test_data()
        self.client.force_login(user)

        # Follow all redirections…
        response = self.client.get(reverse("apply:start", kwargs={"company_pk": company.pk}), follow=True)

        # …until a job seeker has to be determined.
        assert response.status_code == 200
        last_url = response.redirect_chain[-1][0]
        assert last_url == reverse("apply:check_nir_for_sender", kwargs={"company_pk": company.pk})

        # Enter a non-existing NIR.
        # ----------------------------------------------------------------------
        nir = "141068078200557"
        post_data = {"nir": nir, "confirm": 1}
        response = self.client.post(last_url, data=post_data)
        job_seeker_session_name = str(resolve(response.url).kwargs["session_uuid"])
        next_url = reverse(
            "apply:search_by_email_for_sender",
            kwargs={"company_pk": company.pk, "session_uuid": job_seeker_session_name},
        )
        assert response.url == next_url
        assert self.client.session[job_seeker_session_name] == {"user": {"nir": nir}}
        self.assertRedirects(response, next_url)

        # Create a job seeker with this NIR right after the check. Sorry.
        # ----------------------------------------------------------------------
        other_job_seeker = JobSeekerFactory(nir=nir)

        # Enter an existing email.
        # ----------------------------------------------------------------------
        post_data = {"email": job_seeker.email, "confirm": "1"}
        response = self.client.post(next_url, data=post_data)
        assert response.status_code == 200
        assert (
            "Le<b> numéro de sécurité sociale</b> renseigné (141068078200557) "
            "est déjà utilisé par un autre candidat sur la Plateforme." in str(list(response.context["messages"])[0])
        )

        # Remove that extra job seeker and proceed with "normal" flow
        # ----------------------------------------------------------------------
        other_job_seeker.delete()

        response = self.client.post(next_url, data=post_data)
        self.assertRedirects(
            response,
            reverse(
                "apply:step_check_job_seeker_info", kwargs={"company_pk": company.pk, "job_seeker_pk": job_seeker.pk}
            ),
            target_status_code=302,
        )

        response = self.client.post(next_url, data=post_data, follow=True)
        assert response.status_code == 200
        assert 0 == len(list(response.context["messages"]))

        # Make sure the job seeker NIR is now filled in.
        # ----------------------------------------------------------------------
        job_seeker.refresh_from_db()
        assert job_seeker.nir == nir

    def test_one_account_lack_of_nir_reason(self):
        job_seeker = JobSeekerFactory(nir="", lack_of_nir_reason=LackOfNIRReason.TEMPORARY_NUMBER)
        # Create an approval to bypass the eligibility diagnosis step.
        PoleEmploiApprovalFactory(birthdate=job_seeker.birthdate, pole_emploi_id=job_seeker.pole_emploi_id)
        siae, user = self.create_test_data()
        self.client.force_login(user)

        # Follow all redirections…
        response = self.client.get(reverse("apply:start", kwargs={"company_pk": siae.pk}), follow=True)

        # …until a job seeker has to be determined.
        assert response.status_code == 200
        last_url = response.redirect_chain[-1][0]
        assert last_url == reverse("apply:check_nir_for_sender", kwargs={"company_pk": siae.pk})

        # Enter a non-existing NIR.
        # ----------------------------------------------------------------------
        nir = "141068078200557"
        post_data = {"nir": nir, "confirm": 1}
        response = self.client.post(last_url, data=post_data)
        job_seeker_session_name = str(resolve(response.url).kwargs["session_uuid"])
        next_url = reverse(
            "apply:search_by_email_for_sender", kwargs={"company_pk": siae.pk, "session_uuid": job_seeker_session_name}
        )
        assert response.url == next_url
        assert self.client.session[job_seeker_session_name] == {"user": {"nir": nir}}
        self.assertRedirects(response, next_url)

        # Enter an existing email.
        # ----------------------------------------------------------------------
        post_data = {"email": job_seeker.email, "confirm": "1"}
        response = self.client.post(next_url, data=post_data)
        self.assertRedirects(
            response,
            reverse(
                "apply:step_check_job_seeker_info", kwargs={"company_pk": siae.pk, "job_seeker_pk": job_seeker.pk}
            ),
            target_status_code=302,
        )

        response = self.client.post(next_url, data=post_data, follow=True)
        assert response.status_code == 200
        assert 0 == len(list(response.context["messages"]))

        # Make sure the job seeker NIR is now filled in.
        # ----------------------------------------------------------------------
        job_seeker.refresh_from_db()
        assert job_seeker.nir == nir
        assert job_seeker.lack_of_nir_reason == ""


@pytest.mark.usefixtures("unittest_compatibility")
class ApplyAsCompanyTest(TestCase):
    def setUp(self):
        super().setUp()
        [self.city] = create_test_cities(["67"], num_per_department=1)

    @property
    def default_session_data(self):
        return {
            "selected_jobs": [],
        }

    def test_perms_for_company(self):
        """A company can postulate only for itself."""
        company_1 = CompanyFactory(with_membership=True)
        company_2 = CompanyFactory(with_membership=True)

        user = company_1.members.first()
        self.client.force_login(user)

        response = self.client.get(reverse("apply:start", kwargs={"company_pk": company_2.pk}))
        assert response.status_code == 403

    def test_apply_as_siae_with_suspension_sanction(self):
        company = CompanyWithMembershipAndJobsFactory(romes=("N1101", "N1105"))
        Sanctions.objects.create(
            evaluated_siae=EvaluatedSiaeFactory(siae=company),
            suspension_dates=InclusiveDateRange(timezone.localdate() - relativedelta(days=1)),
        )

        user = company.members.first()
        self.client.force_login(user)

        response = self.client.get(reverse("apply:start", kwargs={"company_pk": company.pk}))
        self.assertContains(
            response,
            "suite aux mesures prises dans le cadre du contrôle a posteriori",
            status_code=403,
        )

    def test_apply_as_company(self):
        """Apply as company."""

        company = CompanyWithMembershipAndJobsFactory(romes=("N1101", "N1105"))

        user = company.members.first()
        self.client.force_login(user)

        dummy_job_seeker = JobSeekerWithAddressFactory.build()
        dummy_job_seeker.jobseeker_profile = JobSeekerProfileWithHexaAddressFactory.build()

        # Entry point.
        # ----------------------------------------------------------------------

        response = self.client.get(reverse("apply:start", kwargs={"company_pk": company.pk}))
        assert response.status_code == 302

        session_data = self.client.session[f"job_application-{company.pk}"]
        assert session_data == self.default_session_data

        next_url = reverse("apply:check_nir_for_sender", kwargs={"company_pk": company.pk})
        assert response.url == next_url

        # Step determine the job seeker with a NIR.
        # ----------------------------------------------------------------------

        response = self.client.get(next_url)
        assert response.status_code == 200

        response = self.client.post(next_url, data={"nir": dummy_job_seeker.nir, "confirm": 1})
        assert self.client.session[f"job_application-{company.pk}"] == self.default_session_data
        assert response.status_code == 302

        job_seeker_session_name = str(resolve(response.url).kwargs["session_uuid"])
        next_url = reverse(
            "apply:search_by_email_for_sender",
            kwargs={"company_pk": company.pk, "session_uuid": job_seeker_session_name},
        )
        assert response.url == next_url
        assert self.client.session[job_seeker_session_name] == {"user": {"nir": dummy_job_seeker.nir}}

        # Step get job seeker e-mail.
        # ----------------------------------------------------------------------

        response = self.client.get(next_url)
        assert response.status_code == 200

        response = self.client.post(next_url, data={"email": dummy_job_seeker.email, "confirm": "1"})
        assert response.status_code == 302

        expected_job_seeker_session = {
            "user": {
                "email": dummy_job_seeker.email,
                "nir": dummy_job_seeker.nir,
            }
        }
        assert self.client.session[job_seeker_session_name] == expected_job_seeker_session

        next_url = reverse(
            "apply:create_job_seeker_step_1_for_sender",
            kwargs={"company_pk": company.pk, "session_uuid": job_seeker_session_name},
        )
        assert response.url == next_url

        # Step create a job seeker.
        # ----------------------------------------------------------------------

        response = self.client.get(next_url)
        # The NIR is prefilled
        self.assertContains(response, dummy_job_seeker.nir)
        # Check that the back url is correct
        self.assertContains(
            response,
            reverse(
                "apply:search_by_email_for_sender",
                kwargs={"company_pk": company.pk, "session_uuid": job_seeker_session_name},
            ),
        )

        post_data = {
            "title": dummy_job_seeker.title,
            "first_name": dummy_job_seeker.first_name,
            "last_name": dummy_job_seeker.last_name,
            "birthdate": dummy_job_seeker.birthdate,
            "lack_of_nir": False,
            "lack_of_nir_reason": "",
        }
        response = self.client.post(next_url, data=post_data)
        assert response.status_code == 302
        expected_job_seeker_session["user"] |= post_data
        assert self.client.session[job_seeker_session_name] == expected_job_seeker_session

        next_url = reverse(
            "apply:create_job_seeker_step_2_for_sender",
            kwargs={"company_pk": company.pk, "session_uuid": job_seeker_session_name},
        )
        assert response.url == next_url

        response = self.client.get(next_url)
        assert response.status_code == 200

        post_data = {
            "address_line_1": dummy_job_seeker.address_line_1,
            "post_code": self.city.post_codes[0],
            "city_slug": self.city.slug,
            "city": self.city.name,
            "phone": dummy_job_seeker.phone,
        }
        response = self.client.post(next_url, data=post_data)
        assert response.status_code == 302
        expected_job_seeker_session["user"] |= post_data | {"department": "67", "address_line_2": ""}
        assert self.client.session[job_seeker_session_name] == expected_job_seeker_session

        next_url = reverse(
            "apply:create_job_seeker_step_3_for_sender",
            kwargs={"company_pk": company.pk, "session_uuid": job_seeker_session_name},
        )
        assert response.url == next_url

        response = self.client.get(next_url)
        assert response.status_code == 200

        post_data = {
            "education_level": dummy_job_seeker.jobseeker_profile.education_level,
        }
        response = self.client.post(next_url, data=post_data)
        assert response.status_code == 302
        expected_job_seeker_session["profile"] = post_data | {
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
        expected_job_seeker_session["user"] |= {
            "pole_emploi_id": "",
            "lack_of_pole_emploi_id_reason": LackOfPoleEmploiId.REASON_NOT_REGISTERED,
        }
        assert self.client.session[job_seeker_session_name] == expected_job_seeker_session

        next_url = reverse(
            "apply:create_job_seeker_step_end_for_sender",
            kwargs={"company_pk": company.pk, "session_uuid": job_seeker_session_name},
        )
        assert response.url == next_url

        response = self.client.get(next_url)
        self.assertContains(response, "Créer le compte candidat")

        response = self.client.post(next_url)
        assert response.status_code == 302

        assert job_seeker_session_name not in self.client.session
        new_job_seeker = User.objects.get(email=dummy_job_seeker.email)
        assert self.client.session[f"job_application-{company.pk}"] == self.default_session_data

        next_url = reverse(
            "apply:application_jobs", kwargs={"company_pk": company.pk, "job_seeker_pk": new_job_seeker.pk}
        )
        assert response.url == next_url

        # Step application's jobs.
        # ----------------------------------------------------------------------

        response = self.client.get(next_url)
        assert response.status_code == 200

        response = self.client.post(next_url, data={"selected_jobs": [company.job_description_through.first().pk]})
        assert response.status_code == 302

        assert self.client.session[f"job_application-{company.pk}"] == self.default_session_data | {
            "selected_jobs": [company.job_description_through.first().pk],
        }

        next_url = reverse(
            "apply:application_eligibility", kwargs={"company_pk": company.pk, "job_seeker_pk": new_job_seeker.pk}
        )
        assert response.url == next_url

        # Step application's eligibility.
        # ----------------------------------------------------------------------
        response = self.client.get(next_url)
        assert response.status_code == 302

        next_url = reverse(
            "apply:application_resume", kwargs={"company_pk": company.pk, "job_seeker_pk": new_job_seeker.pk}
        )
        assert response.url == next_url

        # Step application's resume.
        # ----------------------------------------------------------------------
        response = self.client.get(next_url)
        self.assertContains(response, "Enregistrer")

        with mock.patch(
            "itou.www.apply.views.submit_views.uuid.uuid4",
            return_value=uuid.UUID("11111111-1111-1111-1111-111111111111"),
        ):
            response = self.client.post(
                next_url,
                data={
                    "selected_jobs": [
                        company.job_description_through.first().pk,
                        company.job_description_through.last().pk,
                    ],
                    "message": "Lorem ipsum dolor sit amet, consectetur adipiscing elit.",
                    "resume": self.pdf_file,
                },
            )
        assert response.status_code == 302

        job_application = JobApplication.objects.get(sender=user, to_company=company)
        assert job_application.job_seeker == new_job_seeker
        assert job_application.sender_kind == SenderKind.EMPLOYER
        assert job_application.sender_company == company
        assert job_application.sender_prescriber_organization is None
        assert job_application.state == job_application.state.workflow.STATE_NEW
        assert job_application.message == "Lorem ipsum dolor sit amet, consectetur adipiscing elit."
        assert list(job_application.selected_jobs.all()) == [
            company.job_description_through.first(),
            company.job_description_through.last(),
        ]
        assert job_application.resume_link == (
            f"{settings.AWS_S3_ENDPOINT_URL}tests/{storages['public'].location}"
            "/resume/11111111-1111-1111-1111-111111111111.pdf"
        )

        assert f"job_application-{company.pk}" not in self.client.session

        next_url = reverse(
            "apply:application_end", kwargs={"company_pk": company.pk, "application_pk": job_application.pk}
        )
        assert response.url == next_url

        # Step application's end.
        # ----------------------------------------------------------------------
        response = self.client.get(next_url)
        assert response.status_code == 200


class DirectHireFullProcessTest(TestCase):
    def setUp(self):
        super().setUp()
        [self.city] = create_test_cities(["67"], num_per_department=1)

    def test_perms_for_company(self):
        """A company can hire only for itself."""
        company_1 = CompanyFactory(with_membership=True)
        company_2 = CompanyFactory(with_membership=True)

        user = company_1.members.first()
        self.client.force_login(user)

        response = self.client.get(reverse("apply:check_nir_for_hire", kwargs={"company_pk": company_2.pk}))
        assert response.status_code == 403

    def test_hire_as_siae_with_suspension_sanction(self):
        company = CompanyWithMembershipAndJobsFactory(romes=("N1101", "N1105"))
        Sanctions.objects.create(
            evaluated_siae=EvaluatedSiaeFactory(siae=company),
            suspension_dates=InclusiveDateRange(timezone.localdate() - relativedelta(days=1)),
        )

        user = company.members.first()
        self.client.force_login(user)

        response = self.client.get(
            reverse(
                "apply:eligibility_for_hire", kwargs={"company_pk": company.pk, "job_seeker_pk": JobSeekerFactory().pk}
            )
        )
        self.assertContains(
            response,
            "suite aux mesures prises dans le cadre du contrôle a posteriori",
            status_code=403,
        )

    def test_hire_as_company(self):
        """Apply as company (and create new job seeker)"""

        company = CompanyWithMembershipAndJobsFactory(romes=("N1101", "N1105"))

        user = company.members.first()
        self.client.force_login(user)

        dummy_job_seeker = JobSeekerWithAddressFactory.build()
        dummy_job_seeker.jobseeker_profile = JobSeekerProfileWithHexaAddressFactory.build()

        # Step determine the job seeker with a NIR.
        # ----------------------------------------------------------------------

        check_nir_url = reverse("apply:check_nir_for_hire", kwargs={"company_pk": company.pk})
        response = self.client.get(check_nir_url)
        assert response.status_code == 200

        response = self.client.post(check_nir_url, data={"nir": dummy_job_seeker.nir, "preview": 1})
        assert response.status_code == 302

        job_seeker_session_name = str(resolve(response.url).kwargs["session_uuid"])
        next_url = reverse(
            "apply:search_by_email_for_hire",
            kwargs={"company_pk": company.pk, "session_uuid": job_seeker_session_name},
        )
        assert response.url == next_url

        # Step get job seeker e-mail.
        # ----------------------------------------------------------------------

        response = self.client.get(next_url)
        assert response.status_code == 200

        response = self.client.post(next_url, data={"email": dummy_job_seeker.email, "confirm": "1"})
        assert response.status_code == 302

        expected_job_seeker_session = {
            "user": {
                "email": dummy_job_seeker.email,
                "nir": dummy_job_seeker.nir,
            }
        }
        assert self.client.session[job_seeker_session_name] == expected_job_seeker_session

        next_url = reverse(
            "apply:create_job_seeker_step_1_for_hire",
            kwargs={"company_pk": company.pk, "session_uuid": job_seeker_session_name},
        )
        assert response.url == next_url

        # Step create a job seeker.
        # ----------------------------------------------------------------------

        response = self.client.get(next_url)
        # The NIR is prefilled
        self.assertContains(response, dummy_job_seeker.nir)
        # Check that the back url is correct
        self.assertContains(
            response,
            reverse(
                "apply:search_by_email_for_hire",
                kwargs={"company_pk": company.pk, "session_uuid": job_seeker_session_name},
            ),
        )

        post_data = {
            "title": dummy_job_seeker.title,
            "first_name": dummy_job_seeker.first_name,
            "last_name": dummy_job_seeker.last_name,
            "birthdate": dummy_job_seeker.birthdate,
            "lack_of_nir": False,
            "lack_of_nir_reason": "",
        }
        response = self.client.post(next_url, data=post_data)
        assert response.status_code == 302
        expected_job_seeker_session["user"] |= post_data
        assert self.client.session[job_seeker_session_name] == expected_job_seeker_session

        next_url = reverse(
            "apply:create_job_seeker_step_2_for_hire",
            kwargs={"company_pk": company.pk, "session_uuid": job_seeker_session_name},
        )
        assert response.url == next_url

        response = self.client.get(next_url)
        assert response.status_code == 200

        post_data = {
            "address_line_1": dummy_job_seeker.address_line_1,
            "post_code": self.city.post_codes[0],
            "city_slug": self.city.slug,
            "city": self.city.name,
            "phone": dummy_job_seeker.phone,
        }
        response = self.client.post(next_url, data=post_data)
        assert response.status_code == 302
        expected_job_seeker_session["user"] |= post_data | {"department": "67", "address_line_2": ""}
        assert self.client.session[job_seeker_session_name] == expected_job_seeker_session

        next_url = reverse(
            "apply:create_job_seeker_step_3_for_hire",
            kwargs={"company_pk": company.pk, "session_uuid": job_seeker_session_name},
        )
        assert response.url == next_url

        response = self.client.get(next_url)
        assert response.status_code == 200

        post_data = {
            "education_level": dummy_job_seeker.jobseeker_profile.education_level,
        }
        response = self.client.post(next_url, data=post_data)
        assert response.status_code == 302
        expected_job_seeker_session["profile"] = post_data | {
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
        expected_job_seeker_session["user"] |= {
            "pole_emploi_id": "",
            "lack_of_pole_emploi_id_reason": LackOfPoleEmploiId.REASON_NOT_REGISTERED,
        }
        assert self.client.session[job_seeker_session_name] == expected_job_seeker_session

        next_url = reverse(
            "apply:create_job_seeker_step_end_for_hire",
            kwargs={"company_pk": company.pk, "session_uuid": job_seeker_session_name},
        )
        assert response.url == next_url

        response = self.client.get(next_url)
        assert response.status_code == 200

        response = self.client.post(next_url)
        assert response.status_code == 302

        assert job_seeker_session_name not in self.client.session
        new_job_seeker = User.objects.get(email=dummy_job_seeker.email)

        next_url = reverse(
            "apply:eligibility_for_hire", kwargs={"company_pk": company.pk, "job_seeker_pk": new_job_seeker.pk}
        )
        assert response.url == next_url

        # Step eligibility diagnosis
        # ----------------------------------------------------------------------

        response = self.client.get(next_url)
        self.assertTemplateUsed("approvals/includes/card.html")

        criterion1 = AdministrativeCriteria.objects.level1().get(pk=1)
        criterion2 = AdministrativeCriteria.objects.level2().get(pk=5)
        criterion3 = AdministrativeCriteria.objects.level2().get(pk=15)
        response = self.client.post(
            next_url,
            data={
                # Administrative criteria level 1.
                f"{criterion1.key}": "on",
                # Administrative criteria level 2.
                f"{criterion2.key}": "on",
                f"{criterion3.key}": "on",
            },
        )
        assert response.status_code == 302

        next_url = reverse(
            "apply:hire_confirmation", kwargs={"company_pk": company.pk, "job_seeker_pk": new_job_seeker.pk}
        )
        assert response.url == next_url

        # Hire confirmation
        # ----------------------------------------------------------------------
        response = self.client.get(next_url)
        self.assertTemplateUsed("approvals/includes/card.html")
        self.assertContains(response, "Valider l’embauche")

        hiring_start_at = timezone.localdate()
        post_data = {
            "hiring_start_at": hiring_start_at.strftime(DuetDatePickerWidget.INPUT_DATE_FORMAT),
            "hiring_end_at": "",
            "pole_emploi_id": new_job_seeker.pole_emploi_id,
            "lack_of_pole_emploi_id_reason": new_job_seeker.lack_of_pole_emploi_id_reason,
            "answer": "",
            "address_line_1": new_job_seeker.address_line_1,
            "post_code": new_job_seeker.post_code,
            "city": self.city.name,
            "city_slug": self.city.slug,
        }
        response = self.client.post(
            next_url,
            data=post_data,
            headers={"hx-request": "true"},
        )
        assert response.status_code == 200
        assert (
            response.headers.get("HX-Trigger") == '{"modalControl": {"id": "js-confirmation-modal", "action": "show"}}'
        )
        post_data = post_data | {"confirmed": "True"}
        response = self.client.post(next_url, headers={"hx-request": "true"}, data=post_data)

        job_application = JobApplication.objects.get(sender=user, to_company=company)
        next_url = reverse("approvals:detail", kwargs={"pk": job_application.approval.pk})
        self.assertRedirects(response, next_url, status_code=200, fetch_redirect_response=False)

        assert job_application.job_seeker == new_job_seeker
        assert job_application.sender_kind == SenderKind.EMPLOYER
        assert job_application.sender_company == company
        assert job_application.sender_prescriber_organization is None
        assert job_application.state == job_application.state.workflow.STATE_ACCEPTED
        assert job_application.message == ""
        assert list(job_application.selected_jobs.all()) == []
        assert job_application.resume_link == ""

        # Get application detail
        # ----------------------------------------------------------------------
        response = self.client.get(next_url)
        assert response.status_code == 200

    @pytest.mark.ignore_template_errors
    def test_hire_as_geiq(self):
        """Apply as GEIQ with pre-existing job seeker without previous application"""
        company = CompanyWithMembershipAndJobsFactory(romes=("N1101", "N1105"), kind=CompanyKind.GEIQ)
        job_seeker = JobSeekerFactory()

        user = company.members.first()
        self.client.force_login(user)

        # Step determine the job seeker with a NIR.
        # ----------------------------------------------------------------------

        check_nir_url = reverse("apply:check_nir_for_hire", kwargs={"company_pk": company.pk})
        response = self.client.get(check_nir_url)
        assert response.status_code == 200

        response = self.client.post(check_nir_url, data={"nir": job_seeker.nir, "confirm": 1})
        check_infos_url = reverse(
            "apply:check_job_seeker_info_for_hire", kwargs={"company_pk": company.pk, "job_seeker_pk": job_seeker.pk}
        )
        self.assertRedirects(response, check_infos_url, fetch_redirect_response=False)

        # Step check job seeker infos
        # ----------------------------------------------------------------------

        response = self.client.get(check_infos_url)
        self.assertTemplateNotUsed("approvals/includes/card.html")

        prev_applicaitons_url = reverse(
            "apply:check_prev_applications_for_hire", kwargs={"company_pk": company.pk, "job_seeker_pk": job_seeker.pk}
        )
        self.assertContains(response, prev_applicaitons_url)
        self.assertContains(response, "Éligibilité GEIQ non confirmée")

        # Step check previous applications
        # ----------------------------------------------------------------------

        response = self.client.get(prev_applicaitons_url)
        self.assertTemplateNotUsed("approvals/includes/card.html")
        geiq_eligibility_url = reverse(
            "apply:geiq_eligibility_for_hire", kwargs={"company_pk": company.pk, "job_seeker_pk": job_seeker.pk}
        )
        self.assertRedirects(response, geiq_eligibility_url, fetch_redirect_response=False)

        # Step GEIQ eligibility
        # ----------------------------------------------------------------------
        geiq_criteria_url = reverse(
            "apply:geiq_eligibility_criteria_for_hire",
            kwargs={"company_pk": company.pk, "job_seeker_pk": job_seeker.pk},
        )
        confirmation_url = reverse(
            "apply:hire_confirmation", kwargs={"company_pk": company.pk, "job_seeker_pk": job_seeker.pk}
        )

        response = self.client.get(geiq_eligibility_url)
        self.assertTemplateNotUsed("approvals/includes/card.html")
        response = self.client.post(
            geiq_eligibility_url,
            data={"choice": "True"},
            headers={"hx-request": "true"},
        )
        self.assertRedirects(
            response,
            add_url_params(geiq_criteria_url, {"back_url": check_infos_url, "next_url": confirmation_url}),
            fetch_redirect_response=False,
        )
        htmx_response = self.client.get(geiq_criteria_url, headers={"hx-request": "true"})
        assert htmx_response.status_code == 200

        response = self.client.post(
            add_url_params(geiq_criteria_url, {"back_url": check_infos_url, "next_url": confirmation_url}),
            data={
                "jeune_26_ans": "on",
                "jeune_de_moins_de_26_ans_sans_qualification": "on",
                "proof_of_eligibility": "on",
            },
        )
        self.assertRedirects(response, confirmation_url)

        # Hire confirmation
        # ----------------------------------------------------------------------
        response = self.client.get(confirmation_url)
        self.assertTemplateNotUsed("approvals/includes/card.html")
        self.assertContains(response, "Valider l’embauche")

        hiring_start_at = timezone.localdate()
        post_data = {
            "hiring_start_at": hiring_start_at.strftime(DuetDatePickerWidget.INPUT_DATE_FORMAT),
            "hiring_end_at": "",
            "pole_emploi_id": job_seeker.pole_emploi_id,
            "lack_of_pole_emploi_id_reason": job_seeker.lack_of_pole_emploi_id_reason,
            "answer": "",
            "address_line_1": job_seeker.address_line_1,
            "post_code": job_seeker.post_code,
            "city": self.city.name,
            "city_slug": self.city.slug,
            "prehiring_guidance_days": 3,
            "nb_hours_per_week": 4,
            "planned_training_hours": 5,
            "contract_type": ContractType.APPRENTICESHIP,
            "qualification_type": QualificationType.STATE_DIPLOMA,
            "qualification_level": QualificationLevel.LEVEL_4,
            "hired_job": company.job_description_through.first().pk,
        }
        response = self.client.post(
            confirmation_url,
            data=post_data,
            headers={"hx-request": "true"},
        )
        assert response.status_code == 200
        assert (
            response.headers.get("HX-Trigger") == '{"modalControl": {"id": "js-confirmation-modal", "action": "show"}}'
        )
        post_data = post_data | {"confirmed": "True"}
        response = self.client.post(confirmation_url, headers={"hx-request": "true"}, data=post_data)

        job_application = JobApplication.objects.get(sender=user, to_company=company)
        next_url = reverse("apply:details_for_company", kwargs={"job_application_id": job_application.pk})
        self.assertRedirects(response, next_url, status_code=200, fetch_redirect_response=False)

        assert job_application.job_seeker == job_seeker
        assert job_application.sender_kind == SenderKind.EMPLOYER
        assert job_application.sender_company == company
        assert job_application.sender_prescriber_organization is None
        assert job_application.state == job_application.state.workflow.STATE_ACCEPTED
        assert job_application.message == ""
        assert list(job_application.selected_jobs.all()) == []
        assert job_application.resume_link == ""
        assert job_application.qualification_type == QualificationType.STATE_DIPLOMA
        assert job_application.qualification_level == QualificationLevel.LEVEL_4

        # Get application detail
        # ----------------------------------------------------------------------
        response = self.client.get(next_url)
        assert response.status_code == 200


class ApplyAsOtherTest(TestCase):
    ROUTES = [
        "apply:start",
        "apply:check_nir_for_job_seeker",
        "apply:check_nir_for_sender",
    ]

    def test_labor_inspectors_are_not_allowed_to_submit_application(self):
        company = CompanyFactory()
        institution = InstitutionWithMembershipFactory()

        self.client.force_login(institution.members.first())

        for route in self.ROUTES:
            with self.subTest(route=route):
                response = self.client.get(reverse(route, kwargs={"company_pk": company.pk}), follow=True)
                assert response.status_code == 403

    def test_itou_staff_are_not_allowed_to_submit_application(self):
        company = CompanyFactory()
        user = ItouStaffFactory()
        self.client.force_login(user)

        for route in self.ROUTES:
            with self.subTest(route=route):
                response = self.client.get(reverse(route, kwargs={"company_pk": company.pk}), follow=True)
                assert response.status_code == 403


class ApplicationViewTest(TestCase):
    def test_application_jobs_use_previously_selected_jobs(self):
        company = CompanyFactory(subject_to_eligibility=True, with_membership=True, with_jobs=True)

        self.client.force_login(company.members.first())
        job_seeker = JobSeekerFactory()
        apply_session = SessionNamespace(self.client.session, f"job_application-{company.pk}")
        apply_session.init(
            {
                "selected_jobs": company.job_description_through.all(),
            }
        )
        apply_session.save()

        response = self.client.get(
            reverse("apply:application_jobs", kwargs={"company_pk": company.pk, "job_seeker_pk": job_seeker.pk})
        )
        assert response.status_code == 200
        assert response.context["form"].initial["selected_jobs"] == [
            jd.pk for jd in company.job_description_through.all()
        ]

    def test_application_resume_hidden_fields(self):
        company = CompanyFactory(with_membership=True, with_jobs=True)
        job_seeker = JobSeekerFactory()

        self.client.force_login(company.members.first())
        apply_session = SessionNamespace(self.client.session, f"job_application-{company.pk}")
        apply_session.init(
            {
                "selected_jobs": company.job_description_through.all(),
            }
        )
        apply_session.save()

        response = self.client.get(
            reverse("apply:application_resume", kwargs={"company_pk": company.pk, "job_seeker_pk": job_seeker.pk})
        )
        self.assertContains(response, 'name="selected_jobs"')
        self.assertContains(response, 'name="resume"')

    def test_application_eligibility_is_bypassed_for_company_not_subject_to_eligibility_rules(self):
        company = CompanyFactory(not_subject_to_eligibility=True, with_membership=True)
        job_seeker = JobSeekerFactory()

        self.client.force_login(company.members.first())
        apply_session = SessionNamespace(self.client.session, f"job_application-{company.pk}")
        apply_session.init({})  # We still need a session, even if empty
        apply_session.save()

        response = self.client.get(
            reverse("apply:application_eligibility", kwargs={"company_pk": company.pk, "job_seeker_pk": job_seeker.pk})
        )
        self.assertRedirects(
            response,
            reverse("apply:application_resume", kwargs={"company_pk": company.pk, "job_seeker_pk": job_seeker.pk}),
            fetch_redirect_response=False,
        )

    def test_application_eligibility_is_bypassed_for_unauthorized_prescriber(self):
        company = CompanyFactory(not_subject_to_eligibility=True, with_membership=True)
        prescriber = PrescriberOrganizationWithMembershipFactory().members.first()
        job_seeker = JobSeekerFactory()

        self.client.force_login(prescriber)
        apply_session = SessionNamespace(self.client.session, f"job_application-{company.pk}")
        apply_session.init({})  # We still need a session, even if empty
        apply_session.save()

        response = self.client.get(
            reverse("apply:application_eligibility", kwargs={"company_pk": company.pk, "job_seeker_pk": job_seeker.pk})
        )
        self.assertRedirects(
            response,
            reverse("apply:application_resume", kwargs={"company_pk": company.pk, "job_seeker_pk": job_seeker.pk}),
            fetch_redirect_response=False,
        )

    def test_application_eligibility_is_bypassed_when_the_job_seeker_already_has_an_approval(self):
        company = CompanyFactory(not_subject_to_eligibility=True, with_membership=True)
        eligibility_diagnosis = EligibilityDiagnosisFactory()

        self.client.force_login(company.members.first())
        apply_session = SessionNamespace(self.client.session, f"job_application-{company.pk}")
        apply_session.init({})  # We still need a session, even if empty
        apply_session.save()

        response = self.client.get(
            reverse(
                "apply:application_eligibility",
                kwargs={"company_pk": company.pk, "job_seeker_pk": eligibility_diagnosis.job_seeker.pk},
            )
        )
        self.assertRedirects(
            response,
            reverse(
                "apply:application_resume",
                kwargs={"company_pk": company.pk, "job_seeker_pk": eligibility_diagnosis.job_seeker.pk},
            ),
            fetch_redirect_response=False,
        )

    def test_application_eligibility_update_diagnosis_only_if_not_shrouded(self):
        company = CompanyFactory(subject_to_eligibility=True, with_membership=True)
        prescriber = PrescriberOrganizationWithMembershipFactory(authorized=True).members.first()
        eligibility_diagnosis = EligibilityDiagnosisFactory()

        self.client.force_login(prescriber)
        apply_session = SessionNamespace(self.client.session, f"job_application-{company.pk}")
        apply_session.init({})  # We still need a session, even if empty
        apply_session.save()

        # if "shrouded" is present then we don't update the eligibility diagnosis
        response = self.client.post(
            reverse(
                "apply:application_eligibility",
                kwargs={"company_pk": company.pk, "job_seeker_pk": eligibility_diagnosis.job_seeker.pk},
            ),
            {"level_1_1": True, "shrouded": "whatever"},
        )
        self.assertRedirects(
            response,
            reverse(
                "apply:application_resume",
                kwargs={"company_pk": company.pk, "job_seeker_pk": eligibility_diagnosis.job_seeker.pk},
            ),
            fetch_redirect_response=False,
        )
        assert [eligibility_diagnosis] == list(
            EligibilityDiagnosis.objects.for_job_seeker(eligibility_diagnosis.job_seeker)
        )

        # If "shrouded" is NOT present then we update the eligibility diagnosis
        response = self.client.post(
            reverse(
                "apply:application_eligibility",
                kwargs={"company_pk": company.pk, "job_seeker_pk": eligibility_diagnosis.job_seeker.pk},
            ),
            {"level_1_1": True},
        )
        self.assertRedirects(
            response,
            reverse(
                "apply:application_resume",
                kwargs={"company_pk": company.pk, "job_seeker_pk": eligibility_diagnosis.job_seeker.pk},
            ),
            fetch_redirect_response=False,
        )
        new_eligibility_diagnosis = (
            EligibilityDiagnosis.objects.for_job_seeker(eligibility_diagnosis.job_seeker).order_by().last()
        )
        assert new_eligibility_diagnosis != eligibility_diagnosis
        assert new_eligibility_diagnosis.author == prescriber


def test_application_end_update_job_seeker(client):
    job_application = JobApplicationFactory(job_seeker_with_address=True)
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
            "city_slug": job_seeker.city_slug,
            "city": job_seeker.city,
            "phone": job_seeker.phone,
        },
    )
    assert response.status_code == 403
    job_seeker.refresh_from_db()
    assert job_seeker.address_line_2 == ""


class LastCheckedAtViewTest(TestCase):
    @classmethod
    def setUpTestData(cls):
        cls.company = CompanyFactory(subject_to_eligibility=True, with_membership=True)
        cls.job_seeker = JobSeekerFactory()

    def _check_last_checked_at(self, user, sees_warning, sees_verify_link):
        self.client.force_login(user)
        apply_session = SessionNamespace(self.client.session, f"job_application-{self.company.pk}")
        apply_session.init(
            {
                "selected_jobs": [],
            }
        )
        apply_session.save()

        url = reverse(
            "apply:application_jobs", kwargs={"company_pk": self.company.pk, "job_seeker_pk": self.job_seeker.pk}
        )
        response = self.client.get(url)
        assert response.status_code == 200

        # Check the presence of the verify link
        update_url = reverse(
            "apply:update_job_seeker_step_1",
            kwargs={"company_pk": self.company.pk, "job_seeker_pk": self.job_seeker.pk},
        )
        link_check = self.assertContains if sees_verify_link else self.assertNotContains
        link_check(response, f'<a class="btn btn-link" href="{update_url}">Vérifier le profil</a>', html=True)
        # Check last_checked_at is shown
        self.assertContains(response, "Dernière actualisation du profil : ")
        self.assertNotContains(response, "Merci de vérifier la validité des informations")

        self.job_seeker.last_checked_at -= datetime.timedelta(days=500)
        self.job_seeker.save(update_fields=["last_checked_at"])
        response = self.client.get(url)
        warning_check = self.assertContains if sees_warning else self.assertNotContains
        warning_check(response, "Merci de vérifier la validité des informations")
        link_check(response, f'<a class="btn btn-link" href="{update_url}">Vérifier le profil</a>', html=True)

    def test_company_employee(self):
        self._check_last_checked_at(self.company.members.first(), sees_warning=True, sees_verify_link=True)

    def test_job_seeker(self):
        self._check_last_checked_at(self.job_seeker, sees_warning=False, sees_verify_link=False)

    def test_authorized_prescriber(self):
        authorized_prescriber = PrescriberOrganizationWithMembershipFactory(authorized=True).members.first()
        self._check_last_checked_at(authorized_prescriber, sees_warning=True, sees_verify_link=True)

    def test_unauthorized_prescriber(self):
        prescriber = PrescriberOrganizationWithMembershipFactory(authorized=False).members.first()
        self._check_last_checked_at(prescriber, sees_warning=True, sees_verify_link=False)

    def test_unauthorized_prescriber_that_created_the_job_seeker(self):
        prescriber = PrescriberOrganizationWithMembershipFactory(authorized=False).members.first()
        self.job_seeker.created_by = prescriber
        self.job_seeker.save(update_fields=["created_by"])
        self._check_last_checked_at(prescriber, sees_warning=True, sees_verify_link=True)


class UpdateJobSeekerBaseTestCase(TestCase):
    @classmethod
    def setUpTestData(cls):
        cls.company = CompanyFactory(subject_to_eligibility=True, with_membership=True)
        cls.job_seeker = JobSeekerFactory()
        cls.step_1_url = reverse(
            cls.STEP_1_VIEW_NAME, kwargs={"company_pk": cls.company.pk, "job_seeker_pk": cls.job_seeker.pk}
        )
        cls.step_2_url = reverse(
            cls.STEP_2_VIEW_NAME, kwargs={"company_pk": cls.company.pk, "job_seeker_pk": cls.job_seeker.pk}
        )
        cls.step_3_url = reverse(
            cls.STEP_3_VIEW_NAME, kwargs={"company_pk": cls.company.pk, "job_seeker_pk": cls.job_seeker.pk}
        )
        cls.step_end_url = reverse(
            cls.STEP_END_VIEW_NAME, kwargs={"company_pk": cls.company.pk, "job_seeker_pk": cls.job_seeker.pk}
        )
        [cls.city] = create_test_cities(["67"], num_per_department=1)

        cls.INFO_MODIFIABLE_PAR_CANDIDAT_UNIQUEMENT = "Informations modifiables par le candidat uniquement"
        cls.job_seeker_session_key = f"job_seeker-{cls.job_seeker.pk}"

    def _check_nothing_permitted(self, user):
        self.client.force_login(user)
        for url in [
            self.step_1_url,
            self.step_2_url,
            self.step_3_url,
            self.step_end_url,
        ]:
            response = self.client.get(url)
            assert response.status_code == 403

    def _check_that_last_step_doesnt_crash_with_direct_access(self, user):
        self.client.force_login(user)
        self.client.get(self.step_1_url)  # Setup job_seeker_session
        self.client.get(self.step_end_url)  # Use partial job_seeker_session

    def _check_everything_allowed(self, user, extra_post_data_1=None):
        self.client.force_login(user)

        # STEP 1
        response = self.client.get(self.step_1_url)
        self.assertContains(response, self.job_seeker.first_name)
        self.assertNotContains(response, self.INFO_MODIFIABLE_PAR_CANDIDAT_UNIQUEMENT)

        NEW_FIRST_NAME = "New first name"
        PROCESS_TITLE = "Modification du compte candidat"

        post_data = {
            "title": "M",
            "first_name": NEW_FIRST_NAME,
            "last_name": "New last name",
            "birthdate": self.job_seeker.birthdate,
            "lack_of_nir": False,
            "lack_of_nir_reason": "",
        }
        if extra_post_data_1 is not None:
            post_data.update(extra_post_data_1)
        response = self.client.post(self.step_1_url, data=post_data)
        assertRedirects(response, self.step_2_url, fetch_redirect_response=False)

        # Data is stored in the session but user is untouched
        # (nir value is retrieved from the job_seeker and stored in the session)
        expected_job_seeker_session = {"user": post_data | {"nir": self.job_seeker.nir}}
        assert self.client.session[self.job_seeker_session_key] == expected_job_seeker_session
        self.job_seeker.refresh_from_db()
        assert self.job_seeker.first_name != NEW_FIRST_NAME

        # If you go back to step 1, new data is shown
        response = self.client.get(self.step_1_url)
        self.assertContains(response, PROCESS_TITLE, html=True)
        self.assertContains(response, NEW_FIRST_NAME)

        # STEP 2
        response = self.client.get(self.step_2_url)
        self.assertContains(response, PROCESS_TITLE, html=True)
        self.assertContains(response, self.job_seeker.phone)
        self.assertNotContains(response, self.INFO_MODIFIABLE_PAR_CANDIDAT_UNIQUEMENT)

        NEW_ADDRESS_LINE = "123 de la jolie rue"

        post_data = {
            "address_line_1": NEW_ADDRESS_LINE,
            "post_code": self.city.post_codes[0],
            "city_slug": self.city.slug,
            "city": self.city.name,
            "phone": self.job_seeker.phone,
        }
        response = self.client.post(self.step_2_url, data=post_data)
        assertRedirects(response, self.step_3_url, fetch_redirect_response=False)

        # Data is stored in the session but user is untouched
        expected_job_seeker_session["user"] |= post_data | {"department": "67", "address_line_2": ""}
        assert self.client.session[self.job_seeker_session_key] == expected_job_seeker_session
        self.job_seeker.refresh_from_db()
        assert self.job_seeker.address_line_1 != NEW_ADDRESS_LINE

        # If you go back to step 2, new data is shown
        response = self.client.get(self.step_2_url)
        self.assertContains(response, NEW_ADDRESS_LINE)

        # STEP 3
        response = self.client.get(self.step_3_url)
        self.assertContains(response, PROCESS_TITLE, html=True)
        self.assertContains(response, "Niveau de formation")

        post_data = {
            "education_level": EducationLevel.BAC_LEVEL.value,
        }
        response = self.client.post(self.step_3_url, data=post_data)
        assertRedirects(response, self.step_end_url, fetch_redirect_response=False)

        # Data is stored in the session but user & profiles are untouched
        expected_job_seeker_session["profile"] = post_data | {
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
        expected_job_seeker_session["user"] |= {
            "pole_emploi_id": "",
            "lack_of_pole_emploi_id_reason": LackOfPoleEmploiId.REASON_NOT_REGISTERED,
        }
        assert self.client.session[self.job_seeker_session_key] == expected_job_seeker_session
        self.job_seeker.refresh_from_db()

        # If you go back to step 3, new data is shown
        response = self.client.get(self.step_3_url)
        self.assertContains(response, '<option value="40" selected="">Formation de niveau BAC</option>', html=True)

        # Step END
        response = self.client.get(self.step_end_url)
        self.assertContains(response, PROCESS_TITLE, html=True)
        self.assertContains(response, NEW_FIRST_NAME.title())  # User.get_full_name() changes the firstname display
        self.assertContains(response, NEW_ADDRESS_LINE)
        self.assertContains(response, "Formation de niveau BAC")
        self.assertContains(response, "Valider les informations")

        previous_last_checked_at = self.job_seeker.last_checked_at

        response = self.client.post(self.step_end_url)
        assertRedirects(
            response,
            reverse(
                self.FINAL_REDIRECT_VIEW_NAME,
                kwargs={"company_pk": self.company.pk, "job_seeker_pk": self.job_seeker.pk},
            ),
            fetch_redirect_response=False,
        )
        assert self.client.session.get(self.job_seeker_session_key) is None

        self.job_seeker.refresh_from_db()
        assert self.job_seeker.has_jobseeker_profile is True
        assert self.job_seeker.first_name == NEW_FIRST_NAME
        assert self.job_seeker.address_line_1 == NEW_ADDRESS_LINE
        assert self.job_seeker.jobseeker_profile.education_level == EducationLevel.BAC_LEVEL

        assert self.job_seeker.last_checked_at != previous_last_checked_at

    def _check_only_administrative_allowed(self, user):
        self.client.force_login(user)

        # STEP 1
        response = self.client.get(self.step_1_url)
        self.assertContains(response, self.job_seeker.first_name)
        self.assertContains(response, self.INFO_MODIFIABLE_PAR_CANDIDAT_UNIQUEMENT)

        response = self.client.post(self.step_1_url)
        assertRedirects(response, self.step_2_url, fetch_redirect_response=False)

        # Session is created
        expected_job_seeker_session = {"user": {}}
        assert self.client.session[self.job_seeker_session_key] == expected_job_seeker_session

        # STEP 2
        response = self.client.get(self.step_2_url)
        self.assertContains(response, self.job_seeker.phone)
        self.assertContains(response, self.INFO_MODIFIABLE_PAR_CANDIDAT_UNIQUEMENT)

        response = self.client.post(self.step_2_url)
        assertRedirects(response, self.step_3_url, fetch_redirect_response=False)

        # Data is stored in the session but user is untouched
        assert self.client.session[self.job_seeker_session_key] == expected_job_seeker_session

        # STEP 3
        response = self.client.get(self.step_3_url)
        self.assertContains(response, "Niveau de formation")

        post_data = {
            "education_level": EducationLevel.BAC_LEVEL.value,
        }
        response = self.client.post(self.step_3_url, data=post_data)
        assertRedirects(response, self.step_end_url, fetch_redirect_response=False)

        # Data is stored in the session but user & profiles are untouched
        expected_job_seeker_session["profile"] = post_data | {
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
        expected_job_seeker_session["user"] |= {
            "pole_emploi_id": "",
            "lack_of_pole_emploi_id_reason": LackOfPoleEmploiId.REASON_NOT_REGISTERED,
        }
        assert self.client.session[self.job_seeker_session_key] == expected_job_seeker_session
        self.job_seeker.refresh_from_db()

        # If you go back to step 3, new data is shown
        response = self.client.get(self.step_3_url)
        self.assertContains(response, '<option value="40" selected="">Formation de niveau BAC</option>', html=True)

        # Step END
        response = self.client.get(self.step_end_url)
        self.assertContains(response, "Formation de niveau BAC")

        previous_last_checked_at = self.job_seeker.last_checked_at

        response = self.client.post(self.step_end_url)
        assertRedirects(
            response,
            reverse(
                self.FINAL_REDIRECT_VIEW_NAME,
                kwargs={"company_pk": self.company.pk, "job_seeker_pk": self.job_seeker.pk},
            ),
            fetch_redirect_response=False,
        )
        assert self.client.session.get(self.job_seeker_session_key) is None

        self.job_seeker.refresh_from_db()
        assert self.job_seeker.has_jobseeker_profile is True
        assert self.job_seeker.jobseeker_profile.education_level == EducationLevel.BAC_LEVEL
        assert self.job_seeker.last_checked_at != previous_last_checked_at


class UpdateJobSeekerTestCase(UpdateJobSeekerBaseTestCase):
    STEP_1_VIEW_NAME = "apply:update_job_seeker_step_1"
    STEP_2_VIEW_NAME = "apply:update_job_seeker_step_2"
    STEP_3_VIEW_NAME = "apply:update_job_seeker_step_3"
    STEP_END_VIEW_NAME = "apply:update_job_seeker_step_end"
    FINAL_REDIRECT_VIEW_NAME = "apply:application_jobs"

    def test_anonymous_step_1(self):
        response = self.client.get(self.step_1_url)
        self.assertRedirects(response, reverse("account_login") + f"?next={self.step_1_url}")

    def test_anonymous_step_2(self):
        response = self.client.get(self.step_2_url)
        assert response.status_code == 403

    def test_anonymous_step_3(self):
        response = self.client.get(self.step_3_url)
        assert response.status_code == 403

    def test_anonymous_step_end(self):
        response = self.client.get(self.step_end_url)
        assert response.status_code == 403

    def test_as_job_seeker(self):
        self._check_nothing_permitted(self.job_seeker)

    def test_as_unauthorized_prescriber(self):
        prescriber = PrescriberOrganizationWithMembershipFactory(authorized=False).members.first()
        self._check_nothing_permitted(prescriber)

    def test_as_unauthorized_prescriber_that_created_proxied_job_seeker(self):
        prescriber = PrescriberOrganizationWithMembershipFactory(authorized=False).members.first()
        self.job_seeker.created_by = prescriber
        self.job_seeker.last_login = None
        self.job_seeker.save(update_fields=["created_by", "last_login"])
        self._check_everything_allowed(prescriber)

    def test_as_unauthorized_prescriber_that_created_the_non_proxied_job_seeker(self):
        prescriber = PrescriberOrganizationWithMembershipFactory(authorized=False).members.first()
        self.job_seeker.created_by = prescriber
        # Make sure the job seeker does manage its own account
        self.job_seeker.last_login = timezone.now() - relativedelta(months=1)
        self.job_seeker.save(update_fields=["created_by", "last_login"])
        self._check_nothing_permitted(prescriber)

    def test_as_authorized_prescriber_with_proxied_job_seeker(self):
        # Make sure the job seeker does not manage its own account
        self.job_seeker.created_by = PrescriberFactory()
        self.job_seeker.last_login = None
        self.job_seeker.save(update_fields=["created_by", "last_login"])
        authorized_prescriber = PrescriberOrganizationWithMembershipFactory(authorized=True).members.first()
        self._check_everything_allowed(authorized_prescriber)

    def test_as_authorized_prescriber_with_non_proxied_job_seeker(self):
        # Make sure the job seeker does manage its own account
        self.job_seeker.last_login = timezone.now() - relativedelta(months=1)
        self.job_seeker.save(update_fields=["last_login"])
        authorized_prescriber = PrescriberOrganizationWithMembershipFactory(authorized=True).members.first()
        self._check_only_administrative_allowed(authorized_prescriber)

    def test_as_company_with_proxied_job_seeker(self):
        # Make sure the job seeker does not manage its own account
        self.job_seeker.created_by = EmployerFactory()
        self.job_seeker.last_login = None
        self.job_seeker.save(update_fields=["created_by", "last_login"])
        self._check_everything_allowed(self.company.members.first())

    def test_as_company_with_non_proxied_job_seeker(self):
        # Make sure the job seeker does manage its own account
        self.job_seeker.last_login = timezone.now() - relativedelta(months=1)
        self.job_seeker.save(update_fields=["last_login"])
        self._check_only_administrative_allowed(self.company.members.first())

    def test_without_job_seeker_session(self):
        self.client.force_login(self.company.members.first())
        for url in [
            self.step_2_url,
            self.step_3_url,
            self.step_end_url,
        ]:
            response = self.client.get(url)
            assert response.status_code == 403

    def test_with_job_seeker_without_nir(self):
        # Make sure the job seeker does not manage its own account (and has no nir)
        self.job_seeker.nir = ""
        self.job_seeker.lack_of_nir_reason = ""
        self.job_seeker.created_by = EmployerFactory()
        self.job_seeker.last_login = None
        self.job_seeker.save(update_fields=["created_by", "last_login", "nir", "lack_of_nir_reason"])
        self._check_everything_allowed(
            self.company.members.first(),
            extra_post_data_1={"nir": "", "lack_of_nir": True, "lack_of_nir_reason": LackOfNIRReason.TEMPORARY_NUMBER},
        )
        # Check that we could update its NIR infos
        assert self.job_seeker.lack_of_nir_reason == LackOfNIRReason.TEMPORARY_NUMBER

    def test_as_company_that_last_step_doesnt_crash_with_direct_access(self):
        # Make sure the job seeker does not manage its own account
        self.job_seeker.created_by = EmployerFactory()
        self.job_seeker.last_login = None
        self.job_seeker.save(update_fields=["created_by", "last_login"])
        self._check_that_last_step_doesnt_crash_with_direct_access(self.company.members.first())


class UpdateJobSeekerForHireTestCase(UpdateJobSeekerBaseTestCase):
    STEP_1_VIEW_NAME = "apply:update_job_seeker_step_1_for_hire"
    STEP_2_VIEW_NAME = "apply:update_job_seeker_step_2_for_hire"
    STEP_3_VIEW_NAME = "apply:update_job_seeker_step_3_for_hire"
    STEP_END_VIEW_NAME = "apply:update_job_seeker_step_end_for_hire"
    FINAL_REDIRECT_VIEW_NAME = "apply:check_job_seeker_info_for_hire"

    def test_anonymous_step_1(self):
        response = self.client.get(self.step_1_url)
        self.assertRedirects(response, reverse("account_login") + f"?next={self.step_1_url}")

    def test_anonymous_step_2(self):
        response = self.client.get(self.step_2_url)
        assert response.status_code == 403

    def test_anonymous_step_3(self):
        response = self.client.get(self.step_3_url)
        assert response.status_code == 403

    def test_anonymous_step_end(self):
        response = self.client.get(self.step_end_url)
        assert response.status_code == 403

    def test_as_job_seeker(self):
        self._check_nothing_permitted(self.job_seeker)

    def test_as_unauthorized_prescriber(self):
        prescriber = PrescriberOrganizationWithMembershipFactory(authorized=False).members.first()
        self._check_nothing_permitted(prescriber)

    def test_as_unauthorized_prescriber_that_created_proxied_job_seeker(self):
        prescriber = PrescriberOrganizationWithMembershipFactory(authorized=False).members.first()
        self.job_seeker.created_by = prescriber
        self.job_seeker.last_login = None
        self.job_seeker.save(update_fields=["created_by", "last_login"])
        self._check_nothing_permitted(prescriber)

    def test_as_unauthorized_prescriber_that_created_the_non_proxied_job_seeker(self):
        prescriber = PrescriberOrganizationWithMembershipFactory(authorized=False).members.first()
        self.job_seeker.created_by = prescriber
        # Make sure the job seeker does manage its own account
        self.job_seeker.last_login = timezone.now() - relativedelta(months=1)
        self.job_seeker.save(update_fields=["created_by", "last_login"])
        self._check_nothing_permitted(prescriber)

    def test_as_authorized_prescriber_with_proxied_job_seeker(self):
        # Make sure the job seeker does not manage its own account
        self.job_seeker.created_by = PrescriberFactory()
        self.job_seeker.last_login = None
        self.job_seeker.save(update_fields=["created_by", "last_login"])
        authorized_prescriber = PrescriberOrganizationWithMembershipFactory(authorized=True).members.first()
        self._check_nothing_permitted(authorized_prescriber)

    def test_as_authorized_prescriber_with_non_proxied_job_seeker(self):
        # Make sure the job seeker does manage its own account
        self.job_seeker.last_login = timezone.now() - relativedelta(months=1)
        self.job_seeker.save(update_fields=["last_login"])
        authorized_prescriber = PrescriberOrganizationWithMembershipFactory(authorized=True).members.first()
        self._check_nothing_permitted(authorized_prescriber)

    def test_as_company_with_proxied_job_seeker(self):
        # Make sure the job seeker does not manage its own account
        self.job_seeker.created_by = EmployerFactory()
        self.job_seeker.last_login = None
        self.job_seeker.save(update_fields=["created_by", "last_login"])
        self._check_everything_allowed(self.company.members.first())

    def test_as_company_with_non_proxied_job_seeker(self):
        # Make sure the job seeker does manage its own account
        self.job_seeker.last_login = timezone.now() - relativedelta(months=1)
        self.job_seeker.save(update_fields=["last_login"])
        self._check_only_administrative_allowed(self.company.members.first())

    def test_without_job_seeker_session(self):
        self.client.force_login(self.company.members.first())
        for url in [
            self.step_2_url,
            self.step_3_url,
            self.step_end_url,
        ]:
            response = self.client.get(url)
            assert response.status_code == 403

    def test_with_job_seeker_without_nir(self):
        # Make sure the job seeker does not manage its own account (and has no nir)
        self.job_seeker.nir = ""
        self.job_seeker.lack_of_nir_reason = ""
        self.job_seeker.created_by = EmployerFactory()
        self.job_seeker.last_login = None
        self.job_seeker.save(update_fields=["created_by", "last_login", "nir", "lack_of_nir_reason"])
        self._check_everything_allowed(
            self.company.members.first(),
            extra_post_data_1={"nir": "", "lack_of_nir": True, "lack_of_nir_reason": LackOfNIRReason.TEMPORARY_NUMBER},
        )
        # Check that we could update its NIR infos
        assert self.job_seeker.lack_of_nir_reason == LackOfNIRReason.TEMPORARY_NUMBER

    def test_as_company_that_last_step_doesnt_crash_with_direct_access(self):
        # Make sure the job seeker does not manage its own account
        self.job_seeker.created_by = EmployerFactory()
        self.job_seeker.last_login = None
        self.job_seeker.save(update_fields=["created_by", "last_login"])
        self._check_that_last_step_doesnt_crash_with_direct_access(self.company.members.first())


class UpdateJobSeekerStep3ViewTestCase(TestCase):
    def test_job_seeker_with_profile_has_check_boxes_ticked_in_step3(self):
        company = CompanyFactory(subject_to_eligibility=True, with_membership=True)
        job_seeker = JobSeekerFactory(jobseeker_profile__ass_allocation_since=AllocationDuration.FROM_6_TO_11_MONTHS)

        self.client.force_login(company.members.first())
        apply_session = SessionNamespace(self.client.session, f"job_application-{company.pk}")
        apply_session.init(
            {
                "selected_jobs": [],
            }
        )
        apply_session.save()

        # STEP 1 to setup jobseeker session
        response = self.client.get(
            reverse(
                "apply:update_job_seeker_step_1", kwargs={"company_pk": company.pk, "job_seeker_pk": job_seeker.pk}
            )
        )
        assert response.status_code == 200

        # Go straight to STEP 3
        response = self.client.get(
            reverse(
                "apply:update_job_seeker_step_3", kwargs={"company_pk": company.pk, "job_seeker_pk": job_seeker.pk}
            )
        )
        self.assertContains(
            response,
            '<input type="checkbox" name="ass_allocation" class="form-check-input" id="id_ass_allocation" checked="">',
            html=True,
        )


def test_detect_existing_job_seeker(client):
    company = CompanyWithMembershipAndJobsFactory(romes=("N1101", "N1105"))

    prescriber_organization = PrescriberOrganizationWithMembershipFactory(authorized=True)
    user = prescriber_organization.members.first()
    client.force_login(user)

    job_seeker = JobSeekerWithAddressFactory(nir="", first_name="Jérémy", email="jeremy@example.com")

    default_session_data = {
        "selected_jobs": [],
    }

    # Entry point.
    # ----------------------------------------------------------------------

    response = client.get(reverse("apply:start", kwargs={"company_pk": company.pk}))
    assert response.status_code == 302

    session_data = client.session[f"job_application-{company.pk}"]
    assert session_data == default_session_data

    next_url = reverse("apply:check_nir_for_sender", kwargs={"company_pk": company.pk})
    assert response.url == next_url

    # Step determine the job seeker with a NIR.
    # ----------------------------------------------------------------------

    response = client.get(next_url)
    assert response.status_code == 200

    NEW_NIR = "197013625838386"
    response = client.post(next_url, data={"nir": NEW_NIR, "confirm": 1})
    assert client.session[f"job_application-{company.pk}"] == default_session_data
    assert response.status_code == 302
    job_seeker_session_name = str(resolve(response.url).kwargs["session_uuid"])
    next_url = reverse(
        "apply:search_by_email_for_sender", kwargs={"company_pk": company.pk, "session_uuid": job_seeker_session_name}
    )
    assert response.url == next_url
    assert client.session[job_seeker_session_name] == {"user": {"nir": NEW_NIR}}

    # Step get job seeker e-mail.
    # ----------------------------------------------------------------------

    response = client.get(next_url)
    assert response.status_code == 200

    response = client.post(next_url, data={"email": "wrong-email@example.com", "confirm": "1"})
    assert response.status_code == 302

    expected_job_seeker_session = {
        "user": {
            "email": "wrong-email@example.com",
            "nir": NEW_NIR,
        }
    }
    assert client.session[job_seeker_session_name] == expected_job_seeker_session

    next_url = reverse(
        "apply:create_job_seeker_step_1_for_sender",
        kwargs={"company_pk": company.pk, "session_uuid": job_seeker_session_name},
    )
    assert response.url == next_url

    # Step to create a job seeker.
    # ----------------------------------------------------------------------

    response = client.get(next_url)
    # Make sure the specified NIR is properly filled
    assertContains(response, NEW_NIR)

    post_data = {
        "title": job_seeker.title,
        "first_name": "JEREMY",  # Try without the accent and in uppercase
        "last_name": job_seeker.last_name,
        "birthdate": job_seeker.birthdate,
        "lack_of_nir_reason": "",
        "lack_of_nir": False,
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
        "apply:search_by_email_for_sender", kwargs={"company_pk": company.pk, "session_uuid": job_seeker_session_name}
    )
    assertContains(
        response,
        f"""<a href="{ check_email_url }" class="btn btn-sm btn-primary">Modifier l'email du candidat</a>""",
        html=True,
    )
    # Use the modal button to send confirmation
    response = client.post(next_url, data=post_data | {"confirm": 1})

    # session data is updated and we are correctly redirected to step 2
    expected_job_seeker_session["user"] |= post_data
    assert client.session[job_seeker_session_name] == expected_job_seeker_session

    next_url = reverse(
        "apply:create_job_seeker_step_2_for_sender",
        kwargs={"company_pk": company.pk, "session_uuid": job_seeker_session_name},
    )
    assert response.url == next_url

    # If we chose to cancel & go back, we should find our old wrong email in the page
    response = client.get(check_email_url)
    assertContains(response, "wrong-email@example.com")


class ApplicationGEIQEligibilityViewTest(TestCase):
    @classmethod
    def setUpTestData(cls):
        cls.geiq = CompanyFactory(with_membership=True, with_jobs=True, kind=CompanyKind.GEIQ)
        cls.prescriber_org = PrescriberOrganizationWithMembershipFactory(authorized=True)
        cls.orienter = PrescriberFactory()
        cls.job_seeker_with_geiq_diagnosis = GEIQEligibilityDiagnosisFactory(with_prescriber=True).job_seeker
        cls.company = CompanyFactory(with_membership=True, kind=CompanyKind.EI)

    def _setup_session(self, company_pk=None):
        apply_session = SessionNamespace(self.client.session, f"job_application-{company_pk or self.geiq.pk}")
        apply_session.init(
            {
                "selected_jobs": self.geiq.job_description_through.all(),
            }
        )
        apply_session.save()

    def test_bypass_geiq_eligibility_diagnosis_form_for_orienter(self):
        # When creating a job application, should bypass GEIQ eligibility form step:
        # - if user is an authorized prescriber
        # - if user structure is not a GEIQ : should not be possible, form asserts it and crashes
        job_seeker = JobSeekerFactory()

        # Redirect orienter
        self.client.force_login(self.orienter)
        self._setup_session()
        response = self.client.get(
            reverse(
                "apply:application_geiq_eligibility",
                kwargs={"company_pk": self.geiq.pk, "job_seeker_pk": job_seeker.pk},
            )
        )

        # Must redirect to resume
        assertRedirects(
            response,
            reverse("apply:application_resume", kwargs={"company_pk": self.geiq.pk, "job_seeker_pk": job_seeker.pk}),
            fetch_redirect_response=False,
        )
        self.assertTemplateNotUsed(response, "apply/includes/geiq/geiq_administrative_criteria_form.html")

    def test_bypass_geiq_diagnosis_for_staff_members(self):
        job_seeker = JobSeekerFactory()
        self.client.force_login(self.geiq.members.first())
        self._setup_session()
        response = self.client.get(
            reverse(
                "apply:application_geiq_eligibility",
                kwargs={"company_pk": self.geiq.pk, "job_seeker_pk": job_seeker.pk},
            )
        )

        # Must redirect to resume
        assertRedirects(
            response,
            reverse("apply:application_resume", kwargs={"company_pk": self.geiq.pk, "job_seeker_pk": job_seeker.pk}),
            fetch_redirect_response=False,
        )
        self.assertTemplateNotUsed(response, "apply/includes/geiq/geiq_administrative_criteria_form.html")

    def test_bypass_geiq_diagnosis_for_job_seeker(self):
        # A job seeker must not have access to GEIQ eligibility form
        job_seeker = JobSeekerFactory()
        self.client.force_login(job_seeker)
        self._setup_session()
        response = self.client.get(
            reverse(
                "apply:application_geiq_eligibility",
                kwargs={"company_pk": self.geiq.pk, "job_seeker_pk": job_seeker.pk},
            )
        )

        # Must redirect to resume
        assertRedirects(
            response,
            reverse("apply:application_resume", kwargs={"company_pk": self.geiq.pk, "job_seeker_pk": job_seeker.pk}),
            fetch_redirect_response=False,
        )
        self.assertTemplateNotUsed(response, "apply/includes/geiq/geiq_administrative_criteria_form.html")

    @pytest.mark.ignore_template_errors
    def test_sanity_check_geiq_diagnosis_for_non_geiq(self):
        job_seeker = JobSeekerFactory()
        # See comment im previous test:
        # assert we're not somewhere we don't belong to (non-GEIQ)
        self.client.force_login(self.company.members.first())
        self._setup_session(company_pk=self.company.pk)

        with self.assertRaisesRegex(ValueError, "This form is only for GEIQ"):
            self.client.get(
                reverse(
                    "apply:application_geiq_eligibility",
                    kwargs={"company_pk": self.company.pk, "job_seeker_pk": job_seeker.pk},
                )
            )

    def test_access_as_authorized_prescriber(self):
        job_seeker = JobSeekerFactory()
        self.client.force_login(self.prescriber_org.members.first())
        self._setup_session()

        geiq_eligibility_url = reverse(
            "apply:application_geiq_eligibility", kwargs={"company_pk": self.geiq.pk, "job_seeker_pk": job_seeker.pk}
        )
        response = self.client.get(geiq_eligibility_url)

        assert response.status_code == 200
        self.assertTemplateUsed(response, "apply/includes/geiq/geiq_administrative_criteria_form.html")

        # Check back_url in next step
        response = self.client.get(
            reverse(
                "apply:application_resume",
                kwargs={"company_pk": self.geiq.pk, "job_seeker_pk": job_seeker.pk},
            ),
        )
        self.assertContains(response, geiq_eligibility_url)

    def test_geiq_eligibility_badge(self):
        self.client.force_login(self.prescriber_org.members.first())

        # Badge OK if job seeker has a valid eligibility diagnosis
        self._setup_session()
        response = self.client.get(
            reverse(
                "apply:application_geiq_eligibility",
                kwargs={"company_pk": self.geiq.pk, "job_seeker_pk": self.job_seeker_with_geiq_diagnosis.pk},
            ),
            follow=True,
        )

        self.assertContains(response, "Éligibilité GEIQ confirmée")
        self.assertTemplateUsed(response, "apply/includes/geiq/geiq_administrative_criteria_form.html")

        # Badge KO if job seeker has no diagnosis
        job_seeker_without_diagnosis = JobSeekerFactory()
        self._setup_session()
        response = self.client.get(
            reverse(
                "apply:application_geiq_eligibility",
                kwargs={"company_pk": self.geiq.pk, "job_seeker_pk": job_seeker_without_diagnosis.pk},
            ),
            follow=True,
        )

        self.assertContains(response, "Éligibilité GEIQ non confirmée")
        self.assertTemplateUsed(response, "apply/includes/geiq/geiq_administrative_criteria_form.html")

        # Badge is KO if job seeker has a valid diagnosis without allowance
        diagnosis = GEIQEligibilityDiagnosisFactory(with_geiq=True)
        assert diagnosis.allowance_amount == 0
        assert not diagnosis.eligibility_confirmed

        self.client.force_login(self.prescriber_org.members.first())
        self._setup_session(diagnosis.author_geiq.pk)
        response = self.client.get(
            reverse(
                "apply:application_geiq_eligibility",
                kwargs={"company_pk": diagnosis.author_geiq.pk, "job_seeker_pk": job_seeker_without_diagnosis.pk},
            ),
            follow=True,
        )
        self.assertContains(response, "Éligibilité GEIQ non confirmée")
        self.assertTemplateUsed(response, "apply/includes/geiq/geiq_administrative_criteria_form.html")

    def test_geiq_diagnosis_form_validation(self):
        self.client.force_login(self.prescriber_org.members.first())
        self._setup_session()

        response = self.client.post(
            reverse(
                "apply:application_geiq_eligibility",
                kwargs={"company_pk": self.geiq.pk, "job_seeker_pk": self.job_seeker_with_geiq_diagnosis.pk},
            ),
            data={"jeune_26_ans": True},
        )

        assertRedirects(
            response,
            reverse(
                "apply:application_resume",
                kwargs={"company_pk": self.geiq.pk, "job_seeker_pk": self.job_seeker_with_geiq_diagnosis.pk},
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
            with self.subTest(post_data):
                response = self.client.post(
                    reverse(
                        "apply:application_geiq_eligibility",
                        kwargs={"company_pk": self.geiq.pk, "job_seeker_pk": self.job_seeker_with_geiq_diagnosis.pk},
                    ),
                    data=post_data,
                    follow=True,
                )
                self.assertTemplateUsed(response, "apply/includes/geiq/geiq_administrative_criteria_form.html")
                self.assertContains(response, "Incohérence dans les critères")

        # TODO: more coherence tests asked to business ...


class CheckPreviousApplicationsViewTestCase(TestCase):
    @classmethod
    def setUpTestData(cls):
        cls.company = CompanyFactory(subject_to_eligibility=True, with_membership=True)
        cls.job_seeker = JobSeekerFactory()
        cls.check_infos_url = reverse(
            "apply:step_check_job_seeker_info",
            kwargs={"company_pk": cls.company.pk, "job_seeker_pk": cls.job_seeker.pk},
        )
        cls.check_prev_applications_url = reverse(
            "apply:step_check_prev_applications",
            kwargs={"company_pk": cls.company.pk, "job_seeker_pk": cls.job_seeker.pk},
        )
        cls.application_jobs_url = reverse(
            "apply:application_jobs", kwargs={"company_pk": cls.company.pk, "job_seeker_pk": cls.job_seeker.pk}
        )

    def _login_and_setup_session(self, user):
        self.client.force_login(user)
        apply_session = SessionNamespace(self.client.session, f"job_application-{self.company.pk}")
        apply_session.init(
            {
                "selected_jobs": [],
            }
        )
        apply_session.save()

    def test_no_previous_as_job_seeker(self):
        self._login_and_setup_session(self.job_seeker)
        response = self.client.get(self.check_prev_applications_url)
        self.assertRedirects(response, self.application_jobs_url)

        response = self.client.get(self.application_jobs_url)
        self.assertContains(response, self.check_infos_url)
        self.assertNotContains(response, self.check_prev_applications_url)

    def test_with_previous_as_job_seeker(self):
        self._login_and_setup_session(self.job_seeker)

        # Create a very recent application
        job_application = JobApplicationFactory(job_seeker=self.job_seeker, to_company=self.company)
        response = self.client.get(self.check_prev_applications_url)
        self.assertContains(
            response, "Vous avez déjà postulé chez cet employeur durant les dernières 24 heures.", status_code=403
        )

        # Make it less recent to avoid the 403
        job_application.created_at = timezone.now() - datetime.timedelta(days=2)
        job_application.save(update_fields=("created_at",))
        response = self.client.get(self.check_prev_applications_url)
        self.assertContains(response, "Vous avez déjà postulé chez cet employeur le")
        response = self.client.post(self.check_prev_applications_url, data={"force_new_application": "force"})
        self.assertRedirects(response, self.application_jobs_url)

        # Check that the back URL is correct
        response = self.client.get(self.application_jobs_url)
        self.assertNotContains(response, self.check_infos_url)
        self.assertContains(response, self.check_prev_applications_url)

    def test_no_previous_as_authorized_prescriber(self):
        authorized_prescriber = PrescriberOrganizationWithMembershipFactory(authorized=True).members.first()
        self._login_and_setup_session(authorized_prescriber)
        response = self.client.get(self.check_prev_applications_url)
        self.assertRedirects(response, self.application_jobs_url)

        response = self.client.get(self.application_jobs_url)
        self.assertContains(response, self.check_infos_url)
        self.assertNotContains(response, self.check_prev_applications_url)

    def test_with_previous_as_authorized_prescriber(self):
        authorized_prescriber = PrescriberOrganizationWithMembershipFactory(authorized=True).members.first()
        self._login_and_setup_session(authorized_prescriber)

        # Create a very recent application
        job_application = JobApplicationFactory(job_seeker=self.job_seeker, to_company=self.company)
        response = self.client.get(self.check_prev_applications_url)
        self.assertContains(
            response, "Ce candidat a déjà postulé chez cet employeur durant les dernières 24 heures.", status_code=403
        )
        # Make it less recent to avoid the 403
        job_application.created_at = timezone.now() - datetime.timedelta(days=2)
        job_application.save(update_fields=("created_at",))
        response = self.client.get(self.check_prev_applications_url)
        self.assertContains(response, "Le candidat a déjà postulé chez cet employeur le")
        response = self.client.post(self.check_prev_applications_url, data={"force_new_application": "force"})
        self.assertRedirects(response, self.application_jobs_url)

        # Check that the back URL is correct
        response = self.client.get(self.application_jobs_url)
        self.assertNotContains(response, self.check_infos_url)
        self.assertContains(response, self.check_prev_applications_url)

    def test_no_previous_as_employer(self):
        self._login_and_setup_session(self.company.members.first())

        response = self.client.get(self.check_prev_applications_url)
        self.assertRedirects(response, self.application_jobs_url)

        response = self.client.get(self.application_jobs_url)
        self.assertContains(response, self.check_infos_url)
        self.assertNotContains(response, self.check_prev_applications_url)

    def test_with_previous_as_employer(self):
        JobApplicationFactory(job_seeker=self.job_seeker, to_company=self.company)
        self._login_and_setup_session(self.company.members.first())

        response = self.client.get(self.check_prev_applications_url)
        self.assertContains(response, "Le candidat a déjà postulé chez cet employeur le")
        response = self.client.post(self.check_prev_applications_url, data={"force_new_application": "force"})
        self.assertRedirects(response, self.application_jobs_url)

        # Check that the back URL is correct
        response = self.client.get(self.application_jobs_url)
        self.assertNotContains(response, self.check_infos_url)
        self.assertContains(response, self.check_prev_applications_url)


class FindJobSeekerForHireViewTestCase(TestCase):
    @classmethod
    def setUpTestData(cls):
        cls.company = CompanyFactory(with_membership=True)
        cls.check_nir_url = reverse("apply:check_nir_for_hire", kwargs={"company_pk": cls.company.pk})

    def test_job_seeker_found_with_nir(self):
        user = self.company.members.first()
        self.client.force_login(user)

        job_seeker = JobSeekerFactory(first_name="Sylvie", last_name="Martin")

        response = self.client.get(self.check_nir_url)
        self.assertContains(response, "Déclarer une embauche")

        response = self.client.post(self.check_nir_url, data={"nir": job_seeker.nir, "preview": 1})
        self.assertContains(response, "Sylvie MARTIN")
        # Confirmation modal is shown
        assert response.context["preview_mode"] is True

        response = self.client.post(self.check_nir_url, data={"nir": job_seeker.nir, "confirm": 1})
        self.assertRedirects(
            response,
            reverse(
                "apply:check_job_seeker_info_for_hire",
                kwargs={"company_pk": self.company.pk, "job_seeker_pk": job_seeker.pk},
            ),
        )

    def test_job_seeker_found_with_email(self):
        user = self.company.members.first()
        self.client.force_login(user)

        job_seeker = JobSeekerFactory(first_name="Sylvie", last_name="Martin")
        INVALID_NIR = "123456"

        response = self.client.get(self.check_nir_url)
        self.assertContains(response, "Déclarer une embauche")

        response = self.client.post(self.check_nir_url, data={"nir": INVALID_NIR, "preview": 1})
        self.assertContains(response, "Le numéro de sécurité sociale est trop court")
        response = self.client.post(self.check_nir_url, data={"nir": INVALID_NIR, "skip": 1})
        assert response.status_code == 302

        job_seeker_session_name = str(resolve(response.url).kwargs["session_uuid"])
        search_by_email_url = reverse(
            "apply:search_by_email_for_hire",
            kwargs={"company_pk": self.company.pk, "session_uuid": job_seeker_session_name},
        )
        assert response.url == search_by_email_url

        response = self.client.get(search_by_email_url)
        self.assertContains(response, "Déclarer une embauche")  # Check page title
        self.assertContains(response, self.check_nir_url)  # Check back button URL
        self.assertNotContains(response, INVALID_NIR)

        response = self.client.post(search_by_email_url, data={"email": job_seeker.email, "preview": 1})
        self.assertContains(response, "Sylvie MARTIN")
        # Confirmation modal is shown
        assert response.context["preview_mode"] is True

        response = self.client.post(search_by_email_url, data={"email": job_seeker.email, "confirm": 1})
        self.assertRedirects(
            response,
            reverse(
                "apply:check_job_seeker_info_for_hire",
                kwargs={"company_pk": self.company.pk, "job_seeker_pk": job_seeker.pk},
            ),
        )

    def test_no_job_seeker_redirect_to_create(self):
        user = self.company.members.first()
        self.client.force_login(user)

        dummy_job_seeker = JobSeekerWithAddressFactory.build()
        dummy_job_seeker.jobseeker_profile = JobSeekerProfileWithHexaAddressFactory.build()

        response = self.client.get(self.check_nir_url)
        self.assertContains(response, "Déclarer une embauche")

        response = self.client.post(self.check_nir_url, data={"nir": dummy_job_seeker.nir, "preview": 1})
        assert response.status_code == 302

        job_seeker_session_name = str(resolve(response.url).kwargs["session_uuid"])
        search_by_email_url = reverse(
            "apply:search_by_email_for_hire",
            kwargs={"company_pk": self.company.pk, "session_uuid": job_seeker_session_name},
        )
        assert response.url == search_by_email_url

        response = self.client.get(search_by_email_url)
        self.assertContains(response, "Déclarer une embauche")  # Check page title
        self.assertContains(response, self.check_nir_url)  # Check back button URL
        self.assertContains(response, dummy_job_seeker.nir)

        response = self.client.post(search_by_email_url, data={"email": dummy_job_seeker.email})
        self.assertRedirects(
            response,
            reverse(
                "apply:create_job_seeker_step_1_for_hire",
                kwargs={"company_pk": self.company.pk, "session_uuid": job_seeker_session_name},
            ),
        )

        expected_job_seeker_session = {
            "user": {
                "email": dummy_job_seeker.email,
                "nir": dummy_job_seeker.nir,
            }
        }
        assert self.client.session[job_seeker_session_name] == expected_job_seeker_session


class CheckJobSeekerInformationsForHireTestCase(TestCase):
    def test_company(self):
        company = CompanyFactory(subject_to_eligibility=True, with_membership=True)
        job_seeker = JobSeekerFactory(
            first_name="Son prénom",
            last_name="Son nom de famille",
            nir="",
            lack_of_nir_reason=LackOfNIRReason.TEMPORARY_NUMBER,
        )
        self.client.force_login(company.members.first())
        response = self.client.get(
            reverse(
                "apply:check_job_seeker_info_for_hire",
                kwargs={"company_pk": company.pk, "job_seeker_pk": job_seeker.pk},
            )
        )
        self.assertContains(
            response,
            '<h1>Informations personnelles de <span class="text-muted">Son Prénom Son Nom De Famille</span></h1>',
            html=True,
        )
        self.assertTemplateUsed("approvals/includes/card.html")
        self.assertContains(response, "Éligibilité IAE à valider")
        self.assertContains(
            response,
            reverse(
                "apply:update_job_seeker_step_1_for_hire",
                kwargs={"company_pk": company.pk, "job_seeker_pk": job_seeker.pk},
            ),
        )
        self.assertContains(
            response,
            reverse(
                "apply:check_prev_applications_for_hire",
                kwargs={"company_pk": company.pk, "job_seeker_pk": job_seeker.pk},
            ),
        )
        self.assertContains(response, reverse("dashboard:index"))

    def test_geiq(self):
        company = CompanyFactory(kind=CompanyKind.GEIQ, with_membership=True)
        job_seeker = JobSeekerFactory(
            first_name="Son prénom",
            last_name="Son nom de famille",
            nir="",
            lack_of_nir_reason=LackOfNIRReason.TEMPORARY_NUMBER,
        )
        self.client.force_login(company.members.first())
        response = self.client.get(
            reverse(
                "apply:check_job_seeker_info_for_hire",
                kwargs={"company_pk": company.pk, "job_seeker_pk": job_seeker.pk},
            )
        )
        self.assertContains(
            response,
            '<h1>Informations personnelles de <span class="text-muted">Son Prénom Son Nom De Famille</span></h1>',
            html=True,
        )
        self.assertTemplateNotUsed("approvals/includes/card.html")
        self.assertContains(
            response,
            reverse(
                "apply:update_job_seeker_step_1_for_hire",
                kwargs={"company_pk": company.pk, "job_seeker_pk": job_seeker.pk},
            ),
        )
        self.assertContains(
            response,
            reverse(
                "apply:check_prev_applications_for_hire",
                kwargs={"company_pk": company.pk, "job_seeker_pk": job_seeker.pk},
            ),
        )
        self.assertContains(response, reverse("dashboard:index"))


class CheckPreviousApplicationsForHireViewTestCase(TestCase):
    @classmethod
    def setUpTestData(cls):
        cls.job_seeker = JobSeekerFactory()

    def _reverse(self, view_name):
        return reverse(view_name, kwargs={"company_pk": self.company.pk, "job_seeker_pk": self.job_seeker.pk})

    def test_no_previous_as_employer(self):
        self.company = CompanyFactory(subject_to_eligibility=True, with_membership=True)
        self.client.force_login(self.company.members.first())

        response = self.client.get(self._reverse("apply:check_prev_applications_for_hire"))
        self.assertRedirects(response, self._reverse("apply:eligibility_for_hire"))

    def test_with_previous_as_employer(self):
        self.company = CompanyFactory(subject_to_eligibility=True, with_membership=True)
        JobApplicationFactory(job_seeker=self.job_seeker, to_company=self.company, eligibility_diagnosis=None)
        self.client.force_login(self.company.members.first())

        response = self.client.get(self._reverse("apply:check_prev_applications_for_hire"))
        self.assertTemplateUsed("approvals/includes/card.html")
        self.assertContains(response, "Le candidat a déjà postulé chez cet employeur le")
        response = self.client.post(
            self._reverse("apply:check_prev_applications_for_hire"), data={"force_new_application": "force"}
        )
        self.assertRedirects(response, self._reverse("apply:eligibility_for_hire"))

    def test_no_previous_as_geiq_staff(self):
        self.company = CompanyFactory(kind=CompanyKind.GEIQ, with_membership=True)
        self.client.force_login(self.company.members.first())

        response = self.client.get(self._reverse("apply:check_prev_applications_for_hire"))
        self.assertRedirects(response, self._reverse("apply:geiq_eligibility_for_hire"))

    def test_with_previous_as_geiq_staff(self):
        self.company = CompanyFactory(kind=CompanyKind.GEIQ, with_membership=True)
        JobApplicationFactory(job_seeker=self.job_seeker, to_company=self.company, eligibility_diagnosis=None)
        self.client.force_login(self.company.members.first())

        response = self.client.get(self._reverse("apply:check_prev_applications_for_hire"))
        self.assertContains(response, "Le candidat a déjà postulé chez cet employeur le")
        self.assertTemplateNotUsed("approvals/includes/card.html")
        response = self.client.post(
            self._reverse("apply:check_prev_applications_for_hire"), data={"force_new_application": "force"}
        )
        self.assertRedirects(response, self._reverse("apply:geiq_eligibility_for_hire"))


class EligibilityForHireTestCase(TestCase):
    @classmethod
    def setUpTestData(cls):
        cls.job_seeker = JobSeekerFactory(first_name="Ellie", last_name="Gibilitay")

    def _reverse(self, view_name):
        return reverse(view_name, kwargs={"company_pk": self.company.pk, "job_seeker_pk": self.job_seeker.pk})

    def test_not_subject_to_eligibility(self):
        self.company = CompanyFactory(not_subject_to_eligibility=True, with_membership=True)
        self.client.force_login(self.company.members.first())
        response = self.client.get(self._reverse("apply:eligibility_for_hire"))
        self.assertRedirects(response, self._reverse("apply:hire_confirmation"))

    def test_job_seeker_with_valid_diagnosis(self):
        self.company = CompanyFactory(subject_to_eligibility=True, with_membership=True)
        EligibilityDiagnosisFactory(job_seeker=self.job_seeker)
        self.client.force_login(self.company.members.first())
        response = self.client.get(self._reverse("apply:eligibility_for_hire"))
        self.assertRedirects(response, self._reverse("apply:hire_confirmation"))

    def test_job_seeker_without_valid_diagnosis(self):
        self.company = CompanyFactory(subject_to_eligibility=True, with_membership=True)
        assert not self.job_seeker.has_valid_diagnosis(for_siae=self.company)
        self.client.force_login(self.company.members.first())
        response = self.client.get(self._reverse("apply:eligibility_for_hire"))
        self.assertContains(response, "Déclarer l’embauche de Ellie GIBILITAY")
        self.assertContains(response, "Valider l'éligibilité IAE")
        self.assertContains(response, self._reverse("apply:check_job_seeker_info_for_hire"))  # cancel button

        criterion1 = AdministrativeCriteria.objects.level1().get(pk=1)
        criterion2 = AdministrativeCriteria.objects.level2().get(pk=5)
        criterion3 = AdministrativeCriteria.objects.level2().get(pk=15)
        response = self.client.post(
            self._reverse("apply:eligibility_for_hire"),
            data={
                # Administrative criteria level 1.
                f"{criterion1.key}": "on",
                # Administrative criteria level 2.
                f"{criterion2.key}": "on",
                f"{criterion3.key}": "on",
            },
        )
        self.assertRedirects(response, self._reverse("apply:hire_confirmation"))
        assert self.job_seeker.has_valid_diagnosis(for_siae=self.company)


class GEIQEligibilityForHireTestCase(TestCase):
    @classmethod
    def setUpTestData(cls):
        cls.job_seeker = JobSeekerFactory(first_name="Ellie", last_name="Gibilitay")

    def _reverse(self, view_name):
        return reverse(view_name, kwargs={"company_pk": self.company.pk, "job_seeker_pk": self.job_seeker.pk})

    def test_not_geiq(self):
        self.company = CompanyFactory(subject_to_eligibility=True, with_membership=True)
        self.client.force_login(self.company.members.first())
        response = self.client.get(self._reverse("apply:geiq_eligibility_for_hire"))
        assert response.status_code == 404

    def test_job_seeker_with_valid_diagnosis(self):
        diagnosis = GEIQEligibilityDiagnosisFactory(job_seeker=self.job_seeker, with_geiq=True)
        diagnosis.administrative_criteria.add(GEIQAdministrativeCriteria.objects.get(pk=19))
        self.company = diagnosis.author_geiq
        self.client.force_login(self.company.members.first())
        response = self.client.get(self._reverse("apply:eligibility_for_hire"))
        self.assertRedirects(response, self._reverse("apply:hire_confirmation"))

    @pytest.mark.ignore_template_errors
    def test_job_seeker_without_valid_diagnosis(self):
        self.company = CompanyFactory(kind=CompanyKind.GEIQ, with_membership=True)
        assert not GEIQEligibilityDiagnosis.objects.valid_diagnoses_for(self.job_seeker, self.company).exists()
        self.client.force_login(self.company.members.first())
        response = self.client.get(self._reverse("apply:geiq_eligibility_for_hire"))
        self.assertContains(response, "Déclarer l’embauche de Ellie GIBILITAY")
        self.assertContains(response, "Eligibilité GEIQ")
        self.assertContains(response, self._reverse("apply:check_job_seeker_info_for_hire"))  # cancel button

        response = self.client.post(
            self._reverse("apply:geiq_eligibility_for_hire"),
            data={"choice": "True"},
            headers={"hx-request": "true"},
        )
        criteria_url = add_url_params(
            self._reverse("apply:geiq_eligibility_criteria_for_hire"),
            {
                "back_url": self._reverse("apply:check_job_seeker_info_for_hire"),
                "next_url": self._reverse("apply:hire_confirmation"),
            },
        )
        self.assertRedirects(
            response,
            criteria_url,
            fetch_redirect_response=False,
        )
        htmx_response = self.client.get(criteria_url, headers={"hx-request": "true"})
        assert htmx_response.status_code == 200

        response = self.client.post(
            criteria_url,
            data={
                "jeune_26_ans": "on",
                "jeune_de_moins_de_26_ans_sans_qualification": "on",
                "proof_of_eligibility": "on",
            },
        )
        self.assertRedirects(response, self._reverse("apply:hire_confirmation"))
        assert GEIQEligibilityDiagnosis.objects.valid_diagnoses_for(self.job_seeker, self.company).exists()


class HireConfirmationTestCase(TestCase):
    @classmethod
    def setUpTestData(cls):
        cls.job_seeker = JobSeekerWithAddressFactory(first_name="Clara", last_name="Sion")
        [cls.city] = create_test_cities(["67"], num_per_department=1)

    def _reverse(self, view_name):
        return reverse(view_name, kwargs={"company_pk": self.company.pk, "job_seeker_pk": self.job_seeker.pk})

    def test_as_company(self):
        self.company = CompanyFactory(subject_to_eligibility=True, with_membership=True)
        EligibilityDiagnosisFactory(job_seeker=self.job_seeker)
        self.client.force_login(self.company.members.first())
        response = self.client.get(self._reverse("apply:hire_confirmation"))
        self.assertContains(response, "Déclarer l’embauche de Clara SION")
        self.assertContains(response, "Éligible à l’IAE")

        hiring_start_at = timezone.localdate()
        post_data = {
            "hiring_start_at": hiring_start_at.strftime(DuetDatePickerWidget.INPUT_DATE_FORMAT),
            "hiring_end_at": "",
            "pole_emploi_id": self.job_seeker.pole_emploi_id,
            "lack_of_pole_emploi_id_reason": self.job_seeker.lack_of_pole_emploi_id_reason,
            "answer": "",
            "address_line_1": self.job_seeker.address_line_1,
            "post_code": self.job_seeker.post_code,
            "city": self.city.name,
            "city_slug": self.city.slug,
        }
        response = self.client.post(
            self._reverse("apply:hire_confirmation"),
            data=post_data,
            headers={"hx-request": "true"},
        )
        assert response.status_code == 200
        assert (
            response.headers.get("HX-Trigger") == '{"modalControl": {"id": "js-confirmation-modal", "action": "show"}}'
        )
        post_data = post_data | {"confirmed": "True"}
        response = self.client.post(
            self._reverse("apply:hire_confirmation"), headers={"hx-request": "true"}, data=post_data
        )

        job_application = JobApplication.objects.get(sender=self.company.members.first(), to_company=self.company)
        next_url = reverse("approvals:detail", kwargs={"pk": job_application.approval.pk})
        self.assertRedirects(response, next_url, status_code=200)

        assert job_application.job_seeker == self.job_seeker
        assert job_application.sender_kind == SenderKind.EMPLOYER
        assert job_application.sender_company == self.company
        assert job_application.sender_prescriber_organization is None
        assert job_application.state == job_application.state.workflow.STATE_ACCEPTED
        assert job_application.message == ""
        assert list(job_application.selected_jobs.all()) == []
        assert job_application.resume_link == ""

    def test_as_geiq(self):
        diagnosis = GEIQEligibilityDiagnosisFactory(job_seeker=self.job_seeker, with_geiq=True)
        diagnosis.administrative_criteria.add(GEIQAdministrativeCriteria.objects.get(pk=19))
        self.company = diagnosis.author_geiq
        self.client.force_login(self.company.members.first())
        response = self.client.get(self._reverse("apply:hire_confirmation"))
        self.assertContains(response, "Déclarer l’embauche de Clara SION")
        self.assertContains(response, "Éligibilité GEIQ confirmée")

        hiring_start_at = timezone.localdate()
        post_data = {
            "hiring_start_at": hiring_start_at.strftime(DuetDatePickerWidget.INPUT_DATE_FORMAT),
            "hiring_end_at": "",
            "pole_emploi_id": self.job_seeker.pole_emploi_id,
            "lack_of_pole_emploi_id_reason": self.job_seeker.lack_of_pole_emploi_id_reason,
            "answer": "",
            "address_line_1": "1, Adress Line",
            "post_code": "Post code",
            "city": self.city.name,
            "city_slug": self.city.slug,
            # GEIQ specific fields
            "hired_job": self.company.job_description_through.first().pk,
            "prehiring_guidance_days": 3,
            "nb_hours_per_week": 4,
            "planned_training_hours": 5,
            "contract_type": ContractType.APPRENTICESHIP,
            "qualification_type": QualificationType.STATE_DIPLOMA,
            "qualification_level": QualificationLevel.LEVEL_4,
        }
        response = self.client.post(
            self._reverse("apply:hire_confirmation"),
            data=post_data,
            headers={"hx-request": "true"},
        )
        assert response.status_code == 200
        assert (
            response.headers.get("HX-Trigger") == '{"modalControl": {"id": "js-confirmation-modal", "action": "show"}}'
        )
        post_data = post_data | {"confirmed": "True"}
        response = self.client.post(
            self._reverse("apply:hire_confirmation"), headers={"hx-request": "true"}, data=post_data
        )

        job_application = JobApplication.objects.get(sender=self.company.members.first(), to_company=self.company)
        next_url = reverse("apply:details_for_company", kwargs={"job_application_id": job_application.pk})
        self.assertRedirects(response, next_url, status_code=200)

        assert job_application.job_seeker == self.job_seeker
        assert job_application.sender_kind == SenderKind.EMPLOYER
        assert job_application.sender_company == self.company
        assert job_application.sender_prescriber_organization is None
        assert job_application.state == job_application.state.workflow.STATE_ACCEPTED
        assert job_application.message == ""
        assert list(job_application.selected_jobs.all()) == []
        assert job_application.resume_link == ""


class NewHireProcessInfoTestCase(TestCase):
    GEIQ_APPLY_PROCESS_INFO = "Cet espace vous permet d’enregistrer une candidature à traiter plus tard"
    OTHER_APPLY_PROCESS_INFO = "Cet espace vous permet d’enregistrer une nouvelle candidature."

    GEIQ_DIRECT_HIRE_PROCESS_INFO = "Si vous souhaitez créer une candidature à traiter plus tard"
    OTHER_DIRECT_HIRE_PROCESS_INFO = "Pour la création d’une candidature, veuillez vous rendre sur"

    @classmethod
    def setUpTestData(cls):
        cls.company = CompanyFactory(subject_to_eligibility=True, with_membership=True)
        cls.geiq = CompanyFactory(kind=CompanyKind.GEIQ, with_membership=True)
        cls.job_seeker = JobSeekerFactory(nir="")

    def test_as_job_seeker(self):
        self.client.force_login(self.job_seeker)
        response = self.client.get(reverse("apply:check_nir_for_job_seeker", kwargs={"company_pk": self.company.pk}))
        self.assertNotContains(response, self.OTHER_APPLY_PROCESS_INFO)
        self.assertNotContains(response, self.OTHER_DIRECT_HIRE_PROCESS_INFO)
        response = self.client.get(reverse("apply:check_nir_for_job_seeker", kwargs={"company_pk": self.geiq.pk}))
        self.assertNotContains(response, self.GEIQ_APPLY_PROCESS_INFO)
        self.assertNotContains(response, self.GEIQ_DIRECT_HIRE_PROCESS_INFO)

    def test_as_prescriber(self):
        self.client.force_login(PrescriberFactory())
        response = self.client.get(reverse("apply:check_nir_for_sender", kwargs={"company_pk": self.company.pk}))
        self.assertNotContains(response, self.OTHER_APPLY_PROCESS_INFO)
        self.assertNotContains(response, self.OTHER_DIRECT_HIRE_PROCESS_INFO)
        response = self.client.get(reverse("apply:check_nir_for_sender", kwargs={"company_pk": self.geiq.pk}))
        self.assertNotContains(response, self.GEIQ_APPLY_PROCESS_INFO)
        self.assertNotContains(response, self.GEIQ_DIRECT_HIRE_PROCESS_INFO)

    def test_as_employer(self):
        self.client.force_login(self.company.members.first())
        response = self.client.get(reverse("apply:check_nir_for_sender", kwargs={"company_pk": self.company.pk}))
        self.assertContains(response, self.OTHER_APPLY_PROCESS_INFO)
        self.assertNotContains(response, self.OTHER_DIRECT_HIRE_PROCESS_INFO)
        response = self.client.get(reverse("apply:check_nir_for_hire", kwargs={"company_pk": self.company.pk}))
        self.assertNotContains(response, self.OTHER_APPLY_PROCESS_INFO)
        self.assertContains(response, self.OTHER_DIRECT_HIRE_PROCESS_INFO)

        self.client.force_login(self.geiq.members.first())
        response = self.client.get(reverse("apply:check_nir_for_sender", kwargs={"company_pk": self.geiq.pk}))
        self.assertContains(response, self.GEIQ_APPLY_PROCESS_INFO)
        self.assertNotContains(response, self.GEIQ_DIRECT_HIRE_PROCESS_INFO)
        response = self.client.get(reverse("apply:check_nir_for_hire", kwargs={"company_pk": self.geiq.pk}))
        self.assertNotContains(response, self.GEIQ_APPLY_PROCESS_INFO)
        self.assertContains(response, self.GEIQ_DIRECT_HIRE_PROCESS_INFO)
