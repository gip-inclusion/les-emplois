import datetime
import uuid
from unittest import mock

import faker
from dateutil.relativedelta import relativedelta
from django.contrib.messages import get_messages
from django.urls import resolve, reverse
from django.utils import timezone
from pytest_django.asserts import assertRedirects

from itou.approvals.factories import ApprovalFactory, PoleEmploiApprovalFactory
from itou.asp.models import AllocationDuration, EducationLevel, RSAAllocation
from itou.cities.factories import create_city_in_zrr, create_test_cities
from itou.cities.models import City
from itou.eligibility.factories import EligibilityDiagnosisFactory
from itou.eligibility.models import EligibilityDiagnosis
from itou.geo.factories import ZRRFactory
from itou.institutions.factories import InstitutionWithMembershipFactory
from itou.job_applications.enums import SenderKind
from itou.job_applications.models import JobApplication
from itou.prescribers.factories import PrescriberOrganizationWithMembershipFactory
from itou.siaes.factories import SiaeFactory, SiaeWithMembershipAndJobsFactory
from itou.users.factories import JobSeekerFactory, JobSeekerProfileFactory, PrescriberFactory, UserFactory
from itou.users.models import User
from itou.utils.session import SessionNamespace
from itou.utils.storage.s3 import S3Upload
from itou.utils.storage.testing import S3AccessingTestCase
from itou.utils.test import TestCase


fake = faker.Faker(locale="fr_FR")


class ApplyTest(TestCase):
    def test_we_raise_a_permission_denied_on_missing_session(self):
        routes = {
            "apply:check_nir_for_sender",
            "apply:check_email_for_sender",
            "apply:check_nir_for_job_seeker",
            "apply:step_check_job_seeker_info",
            "apply:step_check_prev_applications",
            "apply:application_jobs",
            "apply:application_eligibility",
            "apply:application_resume",
        }
        user = JobSeekerFactory()
        siae = SiaeFactory(with_jobs=True)

        self.client.force_login(user)
        for route in routes:
            with self.subTest(route=route):
                response = self.client.get(reverse(route, kwargs={"siae_pk": siae.pk}))
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
        siae = SiaeFactory(with_jobs=True)

        self.client.force_login(user)
        for route in routes:
            with self.subTest(route=route):
                response = self.client.get(reverse(route, kwargs={"siae_pk": siae.pk, "session_uuid": uuid.uuid4()}))
                assert response.status_code == 403
                assert response.context["exception"] == "A session namespace doesn't exist."

    def test_start_coalesce_back_url(self):
        siae = SiaeFactory(with_membership=True)
        self.client.force_login(siae.members.first())

        # Default / Fallback
        self.client.get(reverse("apply:start", kwargs={"siae_pk": siae.pk}))
        assert self.client.session[f"job_application-{siae.pk}"]["back_url"] == reverse(
            "siaes_views:card", kwargs={"siae_id": siae.pk}
        )

        # With a job description
        self.client.get(reverse("apply:start", kwargs={"siae_pk": siae.pk}), {"job_description_id": 42})
        assert self.client.session[f"job_application-{siae.pk}"]["back_url"] == reverse(
            "siaes_views:job_description_card", kwargs={"job_description_id": 42}
        )

        # With an already present back url
        self.client.get(reverse("apply:start", kwargs={"siae_pk": siae.pk}), {"back_url": "/"})
        assert self.client.session[f"job_application-{siae.pk}"]["back_url"] == "/"

        # With both
        self.client.get(
            reverse("apply:start", kwargs={"siae_pk": siae.pk}), {"job_description_id": 42, "back_url": "/"}
        )
        assert self.client.session[f"job_application-{siae.pk}"]["back_url"] == "/"


class ApplyAsJobSeekerTest(S3AccessingTestCase):
    @property
    def default_session_data(self):
        return {
            "back_url": "/",
            "job_seeker_pk": None,
            "nir": None,
            "selected_jobs": [],
        }

    def test_apply_as_jobseeker(self):
        """Apply as jobseeker."""

        siae = SiaeWithMembershipAndJobsFactory(romes=("N1101", "N1105"))

        user = JobSeekerFactory(birthdate=None, nir="")
        self.client.force_login(user)

        # Entry point.
        # ----------------------------------------------------------------------

        response = self.client.get(reverse("apply:start", kwargs={"siae_pk": siae.pk}), {"back_url": "/"})
        assert response.status_code == 302

        session_data = self.client.session[f"job_application-{siae.pk}"]
        expected_session_data = self.default_session_data | {
            "job_seeker_pk": user.pk,
        }
        assert session_data == expected_session_data

        next_url = reverse("apply:check_nir_for_job_seeker", kwargs={"siae_pk": siae.pk})
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

        session_data = self.client.session[f"job_application-{siae.pk}"]
        expected_session_data = self.default_session_data | {
            "job_seeker_pk": user.pk,
        }
        assert session_data == expected_session_data

        next_url = reverse("apply:step_check_job_seeker_info", kwargs={"siae_pk": siae.pk})
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

        next_url = reverse("apply:step_check_prev_applications", kwargs={"siae_pk": siae.pk})
        assert response.url == next_url

        # Step check previous job applications.
        # ----------------------------------------------------------------------

        response = self.client.get(next_url)
        assert response.status_code == 302

        next_url = reverse("apply:application_jobs", kwargs={"siae_pk": siae.pk})
        assert response.url == next_url

        # Step application's jobs.
        # ----------------------------------------------------------------------

        response = self.client.get(next_url)
        assert response.status_code == 200

        response = self.client.post(next_url, data={"selected_jobs": [siae.job_description_through.first().pk]})
        assert response.status_code == 302

        assert self.client.session[f"job_application-{siae.pk}"] == self.default_session_data | {
            "job_seeker_pk": user.pk,
            "selected_jobs": [siae.job_description_through.first().pk],
        }

        next_url = reverse("apply:application_eligibility", kwargs={"siae_pk": siae.pk})
        assert response.url == next_url

        # Step application's eligibility.
        # ----------------------------------------------------------------------
        response = self.client.get(next_url)
        assert response.status_code == 302

        next_url = reverse("apply:application_resume", kwargs={"siae_pk": siae.pk})
        assert response.url == next_url

        # Step application's resume.
        # ----------------------------------------------------------------------
        response = self.client.get(next_url)
        assert response.status_code == 200

        # Test fields mandatory to upload to S3
        s3_upload = S3Upload(kind="resume")
        # Don't test S3 form fields as it led to flaky tests, it's already done by the Boto library.
        self.assertContains(response, s3_upload.form_values["url"])
        # Config variables
        s3_upload.config.pop("upload_expiration")
        for value in s3_upload.config.values():
            self.assertContains(response, value)

        response = self.client.post(
            next_url,
            data={
                "selected_jobs": [siae.job_description_through.first().pk],
                "message": "Lorem ipsum dolor sit amet, consectetur adipiscing elit.",
                "resume_link": "https://server.com/rocky-balboa.pdf",
            },
        )
        assert response.status_code == 302

        job_application = JobApplication.objects.get(sender=user, to_siae=siae)
        assert job_application.job_seeker == user
        assert job_application.sender_kind == SenderKind.JOB_SEEKER
        assert job_application.sender_siae is None
        assert job_application.sender_prescriber_organization is None
        assert job_application.state == job_application.state.workflow.STATE_NEW
        assert job_application.message == "Lorem ipsum dolor sit amet, consectetur adipiscing elit."
        assert list(job_application.selected_jobs.all()) == [siae.job_description_through.first()]
        assert job_application.resume_link == "https://server.com/rocky-balboa.pdf"

        assert f"job_application-{siae.pk}" not in self.client.session

        next_url = reverse("apply:application_end", kwargs={"siae_pk": siae.pk, "application_pk": job_application.pk})
        assert response.url == next_url

        # Step application's end.
        # ----------------------------------------------------------------------
        response = self.client.get(next_url)
        assert response.status_code == 200
        # 1 in desktop header
        # + 1 in mobile header
        # + 1 in the page content
        self.assertContains(response, reverse("dashboard:edit_user_info"), count=3)

    def test_apply_as_job_seeker_temporary_nir(self):
        """
        Full path is tested above. See test_apply_as_job_seeker.
        """
        siae = SiaeWithMembershipAndJobsFactory(romes=("N1101", "N1105"))

        user = JobSeekerFactory(nir="")
        self.client.force_login(user)

        # Entry point.
        # ----------------------------------------------------------------------

        response = self.client.get(reverse("apply:start", kwargs={"siae_pk": siae.pk}), {"back_url": "/"}, follow=True)
        assert response.status_code == 200

        # Follow all redirections until NIR.
        # ----------------------------------------------------------------------
        next_url = reverse("apply:check_nir_for_job_seeker", kwargs={"siae_pk": siae.pk})

        response = self.client.post(next_url, data={"nir": "123456789KLOIU"})
        assert response.status_code == 200
        assert not response.context["form"].is_valid()

        # Temporary number should be skipped.
        response = self.client.post(next_url, data={"nir": "123456789KLOIU", "skip": 1}, follow=True)
        assert response.status_code == 200
        assert response.redirect_chain[-1][0] == reverse("apply:application_jobs", kwargs={"siae_pk": siae.pk})

        user.refresh_from_db()
        assert not user.nir

    def test_apply_as_jobseeker_to_siae_with_approval_in_waiting_period(self):
        """
        Apply as jobseeker to a SIAE (not a GEIQ) with an approval in waiting period.
        Waiting period cannot be bypassed.
        """
        now_date = timezone.localdate() - relativedelta(months=1)
        now = timezone.datetime(
            year=now_date.year, month=now_date.month, day=now_date.day, tzinfo=datetime.timezone.utc
        )

        with mock.patch("django.utils.timezone.now", side_effect=lambda: now):
            siae = SiaeWithMembershipAndJobsFactory(romes=("N1101", "N1105"))
            user = JobSeekerFactory()
            end_at = now_date - relativedelta(days=30)
            start_at = end_at - relativedelta(years=2)
            PoleEmploiApprovalFactory(
                pole_emploi_id=user.pole_emploi_id, birthdate=user.birthdate, start_at=start_at, end_at=end_at
            )
            self.client.force_login(user)

            # Follow all redirections…
            response = self.client.get(
                reverse("apply:start", kwargs={"siae_pk": siae.pk}), {"back_url": "/"}, follow=True
            )

            # …until the expected 403.
            assert response.status_code == 403
            assert "Vous avez terminé un parcours" in response.context["exception"]
            last_url = response.redirect_chain[-1][0]
            assert last_url == reverse("apply:step_check_job_seeker_info", kwargs={"siae_pk": siae.pk})

    def test_apply_as_job_seeker_on_sender_tunnel(self):
        siae = SiaeFactory()
        user = JobSeekerFactory()
        self.client.force_login(user)

        # Without a session namespace
        response = self.client.get(reverse("apply:check_nir_for_sender", kwargs={"siae_pk": siae.pk}))
        assert response.status_code == 403

        # With a session namespace
        self.client.get(reverse("apply:start", kwargs={"siae_pk": siae.pk}), {"back_url": "/"})  # Init the session
        response = self.client.get(reverse("apply:check_nir_for_sender", kwargs={"siae_pk": siae.pk}))
        assert response.status_code == 302
        assert response.url == reverse("apply:start", kwargs={"siae_pk": siae.pk})


class ApplyAsAuthorizedPrescriberTest(S3AccessingTestCase):
    def setUp(self):
        create_test_cities(["67"], num_per_department=1)
        self.city = City.objects.first()

    @property
    def default_session_data(self):
        return {
            "back_url": "/",
            "job_seeker_pk": None,
            "nir": None,
            "selected_jobs": [],
        }

    def test_apply_as_prescriber_with_pending_authorization(self):
        """Apply as prescriber that has pending authorization."""

        siae = SiaeWithMembershipAndJobsFactory(romes=("N1101", "N1105"))

        prescriber_organization = PrescriberOrganizationWithMembershipFactory(with_pending_authorization=True)
        user = prescriber_organization.members.first()
        self.client.force_login(user)

        dummy_job_seeker_profile = JobSeekerProfileFactory.build()

        # Entry point.
        # ----------------------------------------------------------------------

        response = self.client.get(reverse("apply:start", kwargs={"siae_pk": siae.pk}), {"back_url": "/"})
        assert response.status_code == 302

        session = self.client.session
        session_data = session[f"job_application-{siae.pk}"]
        assert session_data == self.default_session_data

        next_url = reverse("apply:pending_authorization_for_sender", kwargs={"siae_pk": siae.pk})
        assert response.url == next_url

        # Step show warning message about pending authorization.
        # ----------------------------------------------------------------------

        response = self.client.get(next_url)
        assert response.status_code == 200

        next_url = reverse("apply:check_nir_for_sender", kwargs={"siae_pk": siae.pk})
        self.assertContains(response, "Status de prescripteur habilité non vérifié")
        self.assertContains(response, next_url)

        # Step determine the job seeker with a NIR.
        # ----------------------------------------------------------------------

        response = self.client.get(next_url)
        assert response.status_code == 200

        response = self.client.post(next_url, data={"nir": dummy_job_seeker_profile.user.nir, "confirm": 1})
        assert response.status_code == 302
        session = self.client.session
        expected_session_data = self.default_session_data | {
            "nir": dummy_job_seeker_profile.user.nir,
        }
        assert self.client.session[f"job_application-{siae.pk}"] == expected_session_data

        next_url = reverse("apply:check_email_for_sender", kwargs={"siae_pk": siae.pk})
        assert response.url == next_url

        # Step get job seeker e-mail.
        # ----------------------------------------------------------------------

        response = self.client.get(next_url)
        assert response.status_code == 200

        response = self.client.post(next_url, data={"email": dummy_job_seeker_profile.user.email, "confirm": "1"})
        assert response.status_code == 302
        job_seeker_session_name = str(resolve(response.url).kwargs["session_uuid"])

        expected_job_seeker_session = {
            "user": {
                "email": dummy_job_seeker_profile.user.email,
                "nir": dummy_job_seeker_profile.user.nir,
            }
        }
        assert self.client.session[job_seeker_session_name] == expected_job_seeker_session

        next_url = reverse(
            "apply:create_job_seeker_step_1_for_sender",
            kwargs={"siae_pk": siae.pk, "session_uuid": job_seeker_session_name},
        )
        assert response.url == next_url

        # Step create a job seeker.
        # ----------------------------------------------------------------------

        response = self.client.get(next_url)
        assert response.status_code == 200

        post_data = {
            "title": dummy_job_seeker_profile.user.title,
            "first_name": dummy_job_seeker_profile.user.first_name,
            "last_name": dummy_job_seeker_profile.user.last_name,
            "birthdate": dummy_job_seeker_profile.user.birthdate,
        }
        response = self.client.post(next_url, data=post_data)
        assert response.status_code == 302
        expected_job_seeker_session["user"] |= post_data
        assert self.client.session[job_seeker_session_name] == expected_job_seeker_session

        next_url = reverse(
            "apply:create_job_seeker_step_2_for_sender",
            kwargs={"siae_pk": siae.pk, "session_uuid": job_seeker_session_name},
        )
        assert response.url == next_url

        response = self.client.get(next_url)
        assert response.status_code == 200

        post_data = {
            "address_line_1": dummy_job_seeker_profile.user.address_line_1,
            "post_code": self.city.post_codes[0],
            "city_slug": self.city.slug,
            "city": self.city.name,
            "phone": dummy_job_seeker_profile.user.phone,
        }
        response = self.client.post(next_url, data=post_data)
        assert response.status_code == 302
        expected_job_seeker_session["user"] |= post_data | {"department": "67", "address_line_2": ""}
        assert self.client.session[job_seeker_session_name] == expected_job_seeker_session

        next_url = reverse(
            "apply:create_job_seeker_step_3_for_sender",
            kwargs={"siae_pk": siae.pk, "session_uuid": job_seeker_session_name},
        )
        assert response.url == next_url

        response = self.client.get(next_url)
        assert response.status_code == 200

        post_data = {
            "education_level": dummy_job_seeker_profile.education_level,
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
            "lack_of_pole_emploi_id_reason": User.REASON_NOT_REGISTERED,
        }
        assert self.client.session[job_seeker_session_name] == expected_job_seeker_session

        next_url = reverse(
            "apply:create_job_seeker_step_end_for_sender",
            kwargs={"siae_pk": siae.pk, "session_uuid": job_seeker_session_name},
        )
        assert response.url == next_url

        response = self.client.get(next_url)
        assert response.status_code == 200

        response = self.client.post(next_url)
        assert response.status_code == 302

        assert job_seeker_session_name not in self.client.session
        new_job_seeker = User.objects.get(email=dummy_job_seeker_profile.user.email)
        expected_session_data = self.default_session_data | {
            "nir": dummy_job_seeker_profile.user.nir,
            "job_seeker_pk": new_job_seeker.pk,
        }
        assert self.client.session[f"job_application-{siae.pk}"] == expected_session_data

        next_url = reverse("apply:application_jobs", kwargs={"siae_pk": siae.pk})
        assert response.url == next_url

        # Step application's jobs.
        # ----------------------------------------------------------------------

        response = self.client.get(next_url)
        assert response.status_code == 200

        response = self.client.post(next_url, data={"selected_jobs": [siae.job_description_through.first().pk]})
        assert response.status_code == 302

        assert self.client.session[f"job_application-{siae.pk}"] == self.default_session_data | {
            "nir": dummy_job_seeker_profile.user.nir,
            "job_seeker_pk": new_job_seeker.pk,
            "selected_jobs": [siae.job_description_through.first().pk],
        }

        next_url = reverse("apply:application_eligibility", kwargs={"siae_pk": siae.pk})
        assert response.url == next_url

        # Step application's eligibility.
        # ----------------------------------------------------------------------
        response = self.client.get(next_url)
        assert response.status_code == 302

        next_url = reverse("apply:application_resume", kwargs={"siae_pk": siae.pk})
        assert response.url == next_url

        # Step application's resume.
        # ----------------------------------------------------------------------
        response = self.client.get(next_url)
        assert response.status_code == 200

        # Test fields mandatory to upload to S3
        s3_upload = S3Upload(kind="resume")
        # Don't test S3 form fields as it led to flaky tests, it's already done by the Boto library.
        self.assertContains(response, s3_upload.form_values["url"])
        # Config variables
        s3_upload.config.pop("upload_expiration")
        for value in s3_upload.config.values():
            self.assertContains(response, value)

        response = self.client.post(
            next_url,
            data={
                "selected_jobs": [siae.job_description_through.first().pk, siae.job_description_through.last().pk],
                "message": "Lorem ipsum dolor sit amet, consectetur adipiscing elit.",
                "resume_link": "https://server.com/rocky-balboa.pdf",
            },
        )
        assert response.status_code == 302

        job_application = JobApplication.objects.get(sender=user, to_siae=siae)
        assert job_application.job_seeker == new_job_seeker
        assert job_application.sender_kind == SenderKind.PRESCRIBER
        assert job_application.sender_siae is None
        assert job_application.sender_prescriber_organization == prescriber_organization
        assert job_application.state == job_application.state.workflow.STATE_NEW
        assert job_application.message == "Lorem ipsum dolor sit amet, consectetur adipiscing elit."
        assert list(job_application.selected_jobs.all()) == [
            siae.job_description_through.first(),
            siae.job_description_through.last(),
        ]
        assert job_application.resume_link == "https://server.com/rocky-balboa.pdf"

        assert f"job_application-{siae.pk}" not in self.client.session

        next_url = reverse("apply:application_end", kwargs={"siae_pk": siae.pk, "application_pk": job_application.pk})
        assert response.url == next_url

        # Step application's end.
        # ----------------------------------------------------------------------
        response = self.client.get(next_url)
        assert response.status_code == 200

    def test_apply_as_authorized_prescriber(self):
        """Apply as authorized prescriber."""

        siae = SiaeWithMembershipAndJobsFactory(romes=("N1101", "N1105"))

        # test ZRR / QPV template loading
        city = create_city_in_zrr()
        ZRRFactory(insee_code=city.code_insee)

        prescriber_organization = PrescriberOrganizationWithMembershipFactory(authorized=True)
        user = prescriber_organization.members.first()
        self.client.force_login(user)

        dummy_job_seeker_profile = JobSeekerProfileFactory.build()

        # Entry point.
        # ----------------------------------------------------------------------

        response = self.client.get(reverse("apply:start", kwargs={"siae_pk": siae.pk}), {"back_url": "/"})
        assert response.status_code == 302

        session_data = self.client.session[f"job_application-{siae.pk}"]
        assert session_data == self.default_session_data

        next_url = reverse("apply:check_nir_for_sender", kwargs={"siae_pk": siae.pk})
        assert response.url == next_url

        # Step determine the job seeker with a NIR.
        # ----------------------------------------------------------------------

        response = self.client.get(next_url)
        assert response.status_code == 200

        response = self.client.post(next_url, data={"nir": dummy_job_seeker_profile.user.nir, "confirm": 1})
        assert response.status_code == 302
        expected_session_data = self.default_session_data | {
            "nir": dummy_job_seeker_profile.user.nir,
        }
        assert self.client.session[f"job_application-{siae.pk}"] == expected_session_data

        next_url = reverse("apply:check_email_for_sender", kwargs={"siae_pk": siae.pk})
        assert response.url == next_url

        # Step get job seeker e-mail.
        # ----------------------------------------------------------------------

        response = self.client.get(next_url)
        assert response.status_code == 200

        response = self.client.post(next_url, data={"email": dummy_job_seeker_profile.user.email, "confirm": "1"})
        assert response.status_code == 302
        job_seeker_session_name = str(resolve(response.url).kwargs["session_uuid"])

        expected_job_seeker_session = {
            "user": {
                "email": dummy_job_seeker_profile.user.email,
                "nir": dummy_job_seeker_profile.user.nir,
            }
        }
        assert self.client.session[job_seeker_session_name] == expected_job_seeker_session

        next_url = reverse(
            "apply:create_job_seeker_step_1_for_sender",
            kwargs={"siae_pk": siae.pk, "session_uuid": job_seeker_session_name},
        )
        assert response.url == next_url

        # Step create a job seeker.
        # ----------------------------------------------------------------------

        response = self.client.get(next_url)
        assert response.status_code == 200

        post_data = {
            "title": dummy_job_seeker_profile.user.title,
            "first_name": dummy_job_seeker_profile.user.first_name,
            "last_name": dummy_job_seeker_profile.user.last_name,
            "birthdate": dummy_job_seeker_profile.user.birthdate,
        }
        response = self.client.post(next_url, data=post_data)
        assert response.status_code == 302
        expected_job_seeker_session["user"] |= post_data
        assert self.client.session[job_seeker_session_name] == expected_job_seeker_session

        next_url = reverse(
            "apply:create_job_seeker_step_2_for_sender",
            kwargs={"siae_pk": siae.pk, "session_uuid": job_seeker_session_name},
        )
        assert response.url == next_url

        response = self.client.get(next_url)
        assert response.status_code == 200

        post_data = {
            "address_line_1": dummy_job_seeker_profile.user.address_line_1,
            "post_code": city.post_codes[0],
            "city_slug": city.slug,
            "city": city.name,
            "phone": dummy_job_seeker_profile.user.phone,
        }
        response = self.client.post(next_url, data=post_data)
        assert response.status_code == 302
        expected_job_seeker_session["user"] |= post_data | {"department": "12", "address_line_2": ""}
        assert self.client.session[job_seeker_session_name] == expected_job_seeker_session

        next_url = reverse(
            "apply:create_job_seeker_step_3_for_sender",
            kwargs={"siae_pk": siae.pk, "session_uuid": job_seeker_session_name},
        )
        assert response.url == next_url

        response = self.client.get(next_url)
        assert response.status_code == 200

        post_data = {
            "education_level": dummy_job_seeker_profile.education_level,
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
            "lack_of_pole_emploi_id_reason": User.REASON_NOT_REGISTERED,
        }
        assert self.client.session[job_seeker_session_name] == expected_job_seeker_session

        next_url = reverse(
            "apply:create_job_seeker_step_end_for_sender",
            kwargs={"siae_pk": siae.pk, "session_uuid": job_seeker_session_name},
        )
        assert response.url == next_url

        response = self.client.get(next_url)
        assert response.status_code == 200

        response = self.client.post(next_url)
        assert response.status_code == 302

        assert job_seeker_session_name not in self.client.session
        new_job_seeker = User.objects.get(email=dummy_job_seeker_profile.user.email)
        expected_session_data = self.default_session_data | {
            "nir": dummy_job_seeker_profile.user.nir,
            "job_seeker_pk": new_job_seeker.pk,
        }
        assert self.client.session[f"job_application-{siae.pk}"] == expected_session_data

        next_url = reverse("apply:application_jobs", kwargs={"siae_pk": siae.pk})
        assert response.url == next_url

        # Step application's jobs.
        # ----------------------------------------------------------------------

        response = self.client.get(next_url)
        assert response.status_code == 200

        response = self.client.post(next_url, data={"selected_jobs": [siae.job_description_through.first().pk]})
        assert response.status_code == 302

        assert self.client.session[f"job_application-{siae.pk}"] == self.default_session_data | {
            "nir": dummy_job_seeker_profile.user.nir,
            "job_seeker_pk": new_job_seeker.pk,
            "selected_jobs": [siae.job_description_through.first().pk],
        }

        next_url = reverse("apply:application_eligibility", kwargs={"siae_pk": siae.pk})
        assert response.url == next_url

        # Step application's eligibility.
        # ----------------------------------------------------------------------
        response = self.client.get(next_url)
        assert response.status_code == 200
        assert not EligibilityDiagnosis.objects.has_considered_valid(new_job_seeker, for_siae=siae)
        self.assertTemplateUsed(response, "apply/includes/known_criteria.html", count=1)

        response = self.client.post(next_url, {"level_1_1": True})
        assert response.status_code == 302
        assert EligibilityDiagnosis.objects.has_considered_valid(new_job_seeker, for_siae=siae)

        next_url = reverse("apply:application_resume", kwargs={"siae_pk": siae.pk})
        assert response.url == next_url

        # Step application's resume.
        # ----------------------------------------------------------------------
        response = self.client.get(next_url)
        assert response.status_code == 200

        # Test fields mandatory to upload to S3
        s3_upload = S3Upload(kind="resume")
        # Don't test S3 form fields as it led to flaky tests, it's already done by the Boto library.
        self.assertContains(response, s3_upload.form_values["url"])
        # Config variables
        s3_upload.config.pop("upload_expiration")
        for value in s3_upload.config.values():
            self.assertContains(response, value)

        response = self.client.post(
            next_url,
            data={
                "selected_jobs": [siae.job_description_through.first().pk, siae.job_description_through.last().pk],
                "message": "Lorem ipsum dolor sit amet, consectetur adipiscing elit.",
                "resume_link": "https://server.com/rocky-balboa.pdf",
            },
        )
        assert response.status_code == 302

        job_application = JobApplication.objects.get(sender=user, to_siae=siae)
        assert job_application.job_seeker == new_job_seeker
        assert job_application.sender_kind == SenderKind.PRESCRIBER
        assert job_application.sender_siae is None
        assert job_application.sender_prescriber_organization == prescriber_organization
        assert job_application.state == job_application.state.workflow.STATE_NEW
        assert job_application.message == "Lorem ipsum dolor sit amet, consectetur adipiscing elit."
        assert list(job_application.selected_jobs.all()) == [
            siae.job_description_through.first(),
            siae.job_description_through.last(),
        ]
        assert job_application.resume_link == "https://server.com/rocky-balboa.pdf"

        assert f"job_application-{siae.pk}" not in self.client.session

        next_url = reverse("apply:application_end", kwargs={"siae_pk": siae.pk, "application_pk": job_application.pk})
        assert response.url == next_url

        # Step application's end.
        # ----------------------------------------------------------------------
        response = self.client.get(next_url)
        assert response.status_code == 200

    def test_apply_as_authorized_prescriber_to_siae_for_approval_in_waiting_period(self):
        """
        Apply as authorized prescriber to a SIAE for a job seeker with an approval in waiting period.
        Being an authorized prescriber bypasses the waiting period.
        """

        siae = SiaeWithMembershipAndJobsFactory(romes=("N1101", "N1105"))

        job_seeker = JobSeekerFactory()

        # Create an approval in waiting period.
        end_at = datetime.date.today() - relativedelta(days=30)
        start_at = end_at - relativedelta(years=2)
        ApprovalFactory(user=job_seeker, start_at=start_at, end_at=end_at)

        prescriber_organization = PrescriberOrganizationWithMembershipFactory(authorized=True)
        user = prescriber_organization.members.first()
        self.client.force_login(user)

        # Follow all redirections…
        response = self.client.get(reverse("apply:start", kwargs={"siae_pk": siae.pk}), {"back_url": "/"}, follow=True)

        # …until a job seeker has to be determined…
        assert response.status_code == 200
        last_url = response.redirect_chain[-1][0]
        assert last_url == reverse("apply:check_nir_for_sender", kwargs={"siae_pk": siae.pk})

        # …choose one, then follow all redirections…
        post_data = {"nir": job_seeker.nir, "confirm": 1}
        response = self.client.post(last_url, data=post_data, follow=True)

        # …until the eligibility step which should trigger a 200 OK.
        assert response.status_code == 200
        last_url = response.redirect_chain[-1][0]
        assert last_url == reverse("apply:application_jobs", kwargs={"siae_pk": siae.pk})


class ApplyAsPrescriberTest(S3AccessingTestCase):
    def setUp(self):
        create_test_cities(["67"], num_per_department=10)
        self.city = City.objects.first()

    @property
    def default_session_data(self):
        return {
            "back_url": "/",
            "job_seeker_pk": None,
            "nir": None,
            "selected_jobs": [],
        }

    def test_apply_as_prescriber(self):
        siae = SiaeWithMembershipAndJobsFactory(romes=("N1101", "N1105"))

        user = PrescriberFactory()
        self.client.force_login(user)

        dummy_job_seeker_profile = JobSeekerProfileFactory.build()

        # Entry point.
        # ----------------------------------------------------------------------

        response = self.client.get(reverse("apply:start", kwargs={"siae_pk": siae.pk}), {"back_url": "/"})
        assert response.status_code == 302

        session_data = self.client.session[f"job_application-{siae.pk}"]
        assert session_data == self.default_session_data

        next_url = reverse("apply:check_nir_for_sender", kwargs={"siae_pk": siae.pk})
        assert response.url == next_url

        # Step determine the job seeker with a NIR.
        # ----------------------------------------------------------------------

        response = self.client.get(next_url)
        assert response.status_code == 200

        response = self.client.post(next_url, data={"nir": dummy_job_seeker_profile.user.nir, "confirm": 1})
        assert response.status_code == 302

        expected_session_data = self.default_session_data | {
            "nir": dummy_job_seeker_profile.user.nir,
        }
        assert self.client.session[f"job_application-{siae.pk}"] == expected_session_data

        next_url = reverse("apply:check_email_for_sender", kwargs={"siae_pk": siae.pk})
        assert response.url == next_url

        # Step get job seeker e-mail.
        # ----------------------------------------------------------------------

        response = self.client.get(next_url)
        assert response.status_code == 200

        response = self.client.post(next_url, data={"email": dummy_job_seeker_profile.user.email, "confirm": "1"})
        assert response.status_code == 302
        job_seeker_session_name = str(resolve(response.url).kwargs["session_uuid"])

        expected_job_seeker_session = {
            "user": {
                "email": dummy_job_seeker_profile.user.email,
                "nir": dummy_job_seeker_profile.user.nir,
            }
        }
        assert self.client.session[job_seeker_session_name] == expected_job_seeker_session

        next_url = reverse(
            "apply:create_job_seeker_step_1_for_sender",
            kwargs={"siae_pk": siae.pk, "session_uuid": job_seeker_session_name},
        )
        assert response.url == next_url

        # Step create a job seeker.
        # ----------------------------------------------------------------------

        response = self.client.get(next_url)
        assert response.status_code == 200

        post_data = {
            "title": dummy_job_seeker_profile.user.title,
            "first_name": dummy_job_seeker_profile.user.first_name,
            "last_name": dummy_job_seeker_profile.user.last_name,
            "birthdate": dummy_job_seeker_profile.user.birthdate,
        }
        response = self.client.post(next_url, data=post_data)
        assert response.status_code == 302
        expected_job_seeker_session["user"] |= post_data
        assert self.client.session[job_seeker_session_name] == expected_job_seeker_session

        next_url = reverse(
            "apply:create_job_seeker_step_2_for_sender",
            kwargs={"siae_pk": siae.pk, "session_uuid": job_seeker_session_name},
        )
        assert response.url == next_url

        response = self.client.get(next_url)
        assert response.status_code == 200

        post_data = {
            "address_line_1": dummy_job_seeker_profile.user.address_line_1,
            "post_code": self.city.post_codes[0],
            "city_slug": self.city.slug,
            "city": self.city.name,
            "phone": dummy_job_seeker_profile.user.phone,
        }
        response = self.client.post(next_url, data=post_data)
        assert response.status_code == 302
        expected_job_seeker_session["user"] |= post_data | {"department": "67", "address_line_2": ""}
        assert self.client.session[job_seeker_session_name] == expected_job_seeker_session

        next_url = reverse(
            "apply:create_job_seeker_step_3_for_sender",
            kwargs={"siae_pk": siae.pk, "session_uuid": job_seeker_session_name},
        )
        assert response.url == next_url

        response = self.client.get(next_url)
        assert response.status_code == 200

        post_data = {
            "education_level": dummy_job_seeker_profile.education_level,
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
            "lack_of_pole_emploi_id_reason": User.REASON_NOT_REGISTERED,
        }
        assert self.client.session[job_seeker_session_name] == expected_job_seeker_session

        next_url = reverse(
            "apply:create_job_seeker_step_end_for_sender",
            kwargs={"siae_pk": siae.pk, "session_uuid": job_seeker_session_name},
        )
        assert response.url == next_url

        response = self.client.get(next_url)
        assert response.status_code == 200

        # Let's add another job seeker with exactly the same NIR, in the middle of the process.
        # ----------------------------------------------------------------------
        other_job_seeker = JobSeekerFactory(nir=dummy_job_seeker_profile.user.nir)

        response = self.client.post(next_url)
        [message] = list(get_messages(response.wsgi_request))
        assert message.tags == "error"
        assert message.message == "Un objet Utilisateur avec ce champ NIR existe déjà."
        self.assertRedirects(response, reverse("dashboard:index"))

        # Remove that extra job seeker and proceed with "normal" flow
        # ----------------------------------------------------------------------
        other_job_seeker.delete()

        response = self.client.post(next_url)
        assert response.status_code == 302

        assert job_seeker_session_name not in self.client.session
        new_job_seeker = User.objects.get(email=dummy_job_seeker_profile.user.email)
        expected_session_data = self.default_session_data | {
            "nir": dummy_job_seeker_profile.user.nir,
            "job_seeker_pk": new_job_seeker.pk,
        }
        assert self.client.session[f"job_application-{siae.pk}"] == expected_session_data

        next_url = reverse("apply:application_jobs", kwargs={"siae_pk": siae.pk})
        assert response.url == next_url

        # Step application's jobs.
        # ----------------------------------------------------------------------

        response = self.client.get(next_url)
        assert response.status_code == 200

        response = self.client.post(next_url, data={"selected_jobs": [siae.job_description_through.first().pk]})
        assert response.status_code == 302

        assert self.client.session[f"job_application-{siae.pk}"] == self.default_session_data | {
            "nir": dummy_job_seeker_profile.user.nir,
            "job_seeker_pk": new_job_seeker.pk,
            "selected_jobs": [siae.job_description_through.first().pk],
        }

        next_url = reverse("apply:application_eligibility", kwargs={"siae_pk": siae.pk})
        assert response.url == next_url

        # Step application's eligibility.
        # ----------------------------------------------------------------------
        response = self.client.get(next_url)
        assert response.status_code == 302

        next_url = reverse("apply:application_resume", kwargs={"siae_pk": siae.pk})
        assert response.url == next_url

        # Step application's resume.
        # ----------------------------------------------------------------------
        response = self.client.get(next_url)
        assert response.status_code == 200

        # Test fields mandatory to upload to S3
        s3_upload = S3Upload(kind="resume")
        # Don't test S3 form fields as it led to flaky tests, it's already done by the Boto library.
        self.assertContains(response, s3_upload.form_values["url"])
        # Config variables
        s3_upload.config.pop("upload_expiration")
        for value in s3_upload.config.values():
            self.assertContains(response, value)

        response = self.client.post(
            next_url,
            data={
                "selected_jobs": [siae.job_description_through.first().pk, siae.job_description_through.last().pk],
                "message": "Lorem ipsum dolor sit amet, consectetur adipiscing elit.",
                "resume_link": "https://server.com/rocky-balboa.pdf",
            },
        )
        assert response.status_code == 302

        job_application = JobApplication.objects.get(sender=user, to_siae=siae)
        assert job_application.job_seeker == new_job_seeker
        assert job_application.sender_kind == SenderKind.PRESCRIBER
        assert job_application.sender_siae is None
        assert job_application.sender_prescriber_organization is None
        assert job_application.state == job_application.state.workflow.STATE_NEW
        assert job_application.message == "Lorem ipsum dolor sit amet, consectetur adipiscing elit."
        assert list(job_application.selected_jobs.all()) == [
            siae.job_description_through.first(),
            siae.job_description_through.last(),
        ]
        assert job_application.resume_link == "https://server.com/rocky-balboa.pdf"

        assert f"job_application-{siae.pk}" not in self.client.session

        next_url = reverse("apply:application_end", kwargs={"siae_pk": siae.pk, "application_pk": job_application.pk})
        assert response.url == next_url

        # Step application's end.
        # ----------------------------------------------------------------------
        response = self.client.get(next_url)
        assert response.status_code == 200

    def test_apply_as_prescriber_for_approval_in_waiting_period(self):
        """Apply as prescriber for a job seeker with an approval in waiting period."""

        siae = SiaeWithMembershipAndJobsFactory(romes=("N1101", "N1105"))

        job_seeker = JobSeekerFactory()

        # Create an approval in waiting period.
        end_at = datetime.date.today() - relativedelta(days=30)
        start_at = end_at - relativedelta(years=2)
        ApprovalFactory(user=job_seeker, start_at=start_at, end_at=end_at)

        user = PrescriberFactory()
        self.client.force_login(user)

        # Follow all redirections…
        response = self.client.get(reverse("apply:start", kwargs={"siae_pk": siae.pk}), {"back_url": "/"}, follow=True)

        # …until a job seeker has to be determined…
        assert response.status_code == 200
        last_url = response.redirect_chain[-1][0]
        assert last_url == reverse("apply:check_nir_for_sender", kwargs={"siae_pk": siae.pk})

        # …choose one, then follow all redirections…
        post_data = {"nir": job_seeker.nir, "confirm": 1}
        response = self.client.post(last_url, data=post_data, follow=True)

        # …until the expected 403.
        assert response.status_code == 403
        assert "Le candidat a terminé un parcours" in response.context["exception"]
        last_url = response.redirect_chain[-1][0]
        assert last_url == reverse("apply:step_check_job_seeker_info", kwargs={"siae_pk": siae.pk})

    def test_apply_as_prescriber_on_job_seeker_tunnel(self):
        siae = SiaeFactory()
        user = PrescriberFactory()
        self.client.force_login(user)

        # Without a session namespace
        response = self.client.get(reverse("apply:check_nir_for_job_seeker", kwargs={"siae_pk": siae.pk}))
        assert response.status_code == 403

        # With a session namespace
        self.client.get(
            reverse("apply:start", kwargs={"siae_pk": siae.pk}), {"back_url": "/"}
        )  # Use that view to init the session
        response = self.client.get(reverse("apply:check_nir_for_job_seeker", kwargs={"siae_pk": siae.pk}))
        assert response.status_code == 302
        assert response.url == reverse("apply:start", kwargs={"siae_pk": siae.pk})


class ApplyAsPrescriberNirExceptionsTest(S3AccessingTestCase):
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
        siae = SiaeWithMembershipAndJobsFactory(romes=("N1101", "N1105"))
        # Only authorized prescribers can add a NIR.
        # See User.can_add_nir
        prescriber_organization = PrescriberOrganizationWithMembershipFactory(authorized=True)
        user = prescriber_organization.members.first()
        return siae, user

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
        siae, user = self.create_test_data()
        self.client.force_login(user)

        # Follow all redirections…
        response = self.client.get(reverse("apply:start", kwargs={"siae_pk": siae.pk}), {"back_url": "/"}, follow=True)

        # …until a job seeker has to be determined.
        assert response.status_code == 200
        last_url = response.redirect_chain[-1][0]
        assert last_url == reverse("apply:check_nir_for_sender", kwargs={"siae_pk": siae.pk})

        # Enter a non-existing NIR.
        # ----------------------------------------------------------------------
        nir = "141068078200557"
        post_data = {"nir": nir, "confirm": 1}
        response = self.client.post(last_url, data=post_data)
        next_url = reverse("apply:check_email_for_sender", kwargs={"siae_pk": siae.pk})
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
            response, reverse("apply:step_check_job_seeker_info", kwargs={"siae_pk": siae.pk}), target_status_code=302
        )

        response = self.client.post(next_url, data=post_data, follow=True)
        assert response.status_code == 200
        assert 0 == len(list(response.context["messages"]))

        # Make sure the job seeker NIR is now filled in.
        # ----------------------------------------------------------------------
        job_seeker.refresh_from_db()
        assert job_seeker.nir == nir


class ApplyAsSiaeTest(S3AccessingTestCase):
    def setUp(self):
        create_test_cities(["67"], num_per_department=1)
        self.city = City.objects.first()

    @property
    def default_session_data(self):
        return {
            "back_url": "/",
            "job_seeker_pk": None,
            "nir": None,
            "selected_jobs": [],
        }

    def test_perms_for_siae(self):
        """An SIAE can postulate only for itself."""
        siae1 = SiaeFactory(with_membership=True)
        siae2 = SiaeFactory(with_membership=True)

        user = siae1.members.first()
        self.client.force_login(user)

        response = self.client.get(reverse("apply:start", kwargs={"siae_pk": siae2.pk}), {"back_url": "/"})
        assert response.status_code == 403

    def test_apply_as_siae(self):
        """Apply as SIAE."""

        siae = SiaeWithMembershipAndJobsFactory(romes=("N1101", "N1105"))

        user = siae.members.first()
        self.client.force_login(user)

        dummy_job_seeker_profile = JobSeekerProfileFactory.build()

        # Entry point.
        # ----------------------------------------------------------------------

        response = self.client.get(reverse("apply:start", kwargs={"siae_pk": siae.pk}), {"back_url": "/"})
        assert response.status_code == 302

        session_data = self.client.session[f"job_application-{siae.pk}"]
        assert session_data == self.default_session_data

        next_url = reverse("apply:check_nir_for_sender", kwargs={"siae_pk": siae.pk})
        assert response.url == next_url

        # Step determine the job seeker with a NIR.
        # ----------------------------------------------------------------------

        response = self.client.get(next_url)
        assert response.status_code == 200

        response = self.client.post(next_url, data={"nir": dummy_job_seeker_profile.user.nir, "confirm": 1})
        assert response.status_code == 302

        expected_session_data = self.default_session_data | {
            "nir": dummy_job_seeker_profile.user.nir,
        }
        assert self.client.session[f"job_application-{siae.pk}"] == expected_session_data

        next_url = reverse("apply:check_email_for_sender", kwargs={"siae_pk": siae.pk})
        assert response.url == next_url

        # Step get job seeker e-mail.
        # ----------------------------------------------------------------------

        response = self.client.get(next_url)
        assert response.status_code == 200

        response = self.client.post(next_url, data={"email": dummy_job_seeker_profile.user.email, "confirm": "1"})
        assert response.status_code == 302
        job_seeker_session_name = str(resolve(response.url).kwargs["session_uuid"])

        expected_job_seeker_session = {
            "user": {
                "email": dummy_job_seeker_profile.user.email,
                "nir": dummy_job_seeker_profile.user.nir,
            }
        }
        assert self.client.session[job_seeker_session_name] == expected_job_seeker_session

        next_url = reverse(
            "apply:create_job_seeker_step_1_for_sender",
            kwargs={"siae_pk": siae.pk, "session_uuid": job_seeker_session_name},
        )
        assert response.url == next_url

        # Step create a job seeker.
        # ----------------------------------------------------------------------

        response = self.client.get(next_url)
        assert response.status_code == 200

        post_data = {
            "title": dummy_job_seeker_profile.user.title,
            "first_name": dummy_job_seeker_profile.user.first_name,
            "last_name": dummy_job_seeker_profile.user.last_name,
            "birthdate": dummy_job_seeker_profile.user.birthdate,
        }
        response = self.client.post(next_url, data=post_data)
        assert response.status_code == 302
        expected_job_seeker_session["user"] |= post_data
        assert self.client.session[job_seeker_session_name] == expected_job_seeker_session

        next_url = reverse(
            "apply:create_job_seeker_step_2_for_sender",
            kwargs={"siae_pk": siae.pk, "session_uuid": job_seeker_session_name},
        )
        assert response.url == next_url

        response = self.client.get(next_url)
        assert response.status_code == 200

        post_data = {
            "address_line_1": dummy_job_seeker_profile.user.address_line_1,
            "post_code": self.city.post_codes[0],
            "city_slug": self.city.slug,
            "city": self.city.name,
            "phone": dummy_job_seeker_profile.user.phone,
        }
        response = self.client.post(next_url, data=post_data)
        assert response.status_code == 302
        expected_job_seeker_session["user"] |= post_data | {"department": "67", "address_line_2": ""}
        assert self.client.session[job_seeker_session_name] == expected_job_seeker_session

        next_url = reverse(
            "apply:create_job_seeker_step_3_for_sender",
            kwargs={"siae_pk": siae.pk, "session_uuid": job_seeker_session_name},
        )
        assert response.url == next_url

        response = self.client.get(next_url)
        assert response.status_code == 200

        post_data = {
            "education_level": dummy_job_seeker_profile.education_level,
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
            "lack_of_pole_emploi_id_reason": User.REASON_NOT_REGISTERED,
        }
        assert self.client.session[job_seeker_session_name] == expected_job_seeker_session

        next_url = reverse(
            "apply:create_job_seeker_step_end_for_sender",
            kwargs={"siae_pk": siae.pk, "session_uuid": job_seeker_session_name},
        )
        assert response.url == next_url

        response = self.client.get(next_url)
        assert response.status_code == 200

        response = self.client.post(next_url)
        assert response.status_code == 302

        assert job_seeker_session_name not in self.client.session
        new_job_seeker = User.objects.get(email=dummy_job_seeker_profile.user.email)
        expected_session_data = self.default_session_data | {
            "nir": dummy_job_seeker_profile.user.nir,
            "job_seeker_pk": new_job_seeker.pk,
        }
        assert self.client.session[f"job_application-{siae.pk}"] == expected_session_data

        next_url = reverse("apply:application_jobs", kwargs={"siae_pk": siae.pk})
        assert response.url == next_url

        # Step application's jobs.
        # ----------------------------------------------------------------------

        response = self.client.get(next_url)
        assert response.status_code == 200

        response = self.client.post(next_url, data={"selected_jobs": [siae.job_description_through.first().pk]})
        assert response.status_code == 302

        assert self.client.session[f"job_application-{siae.pk}"] == self.default_session_data | {
            "nir": dummy_job_seeker_profile.user.nir,
            "job_seeker_pk": new_job_seeker.pk,
            "selected_jobs": [siae.job_description_through.first().pk],
        }

        next_url = reverse("apply:application_eligibility", kwargs={"siae_pk": siae.pk})
        assert response.url == next_url

        # Step application's eligibility.
        # ----------------------------------------------------------------------
        response = self.client.get(next_url)
        assert response.status_code == 302

        next_url = reverse("apply:application_resume", kwargs={"siae_pk": siae.pk})
        assert response.url == next_url

        # Step application's resume.
        # ----------------------------------------------------------------------
        response = self.client.get(next_url)
        assert response.status_code == 200

        # Test fields mandatory to upload to S3
        s3_upload = S3Upload(kind="resume")
        # Don't test S3 form fields as it led to flaky tests, it's already done by the Boto library.
        self.assertContains(response, s3_upload.form_values["url"])
        # Config variables
        s3_upload.config.pop("upload_expiration")
        for value in s3_upload.config.values():
            self.assertContains(response, value)

        response = self.client.post(
            next_url,
            data={
                "selected_jobs": [siae.job_description_through.first().pk, siae.job_description_through.last().pk],
                "message": "Lorem ipsum dolor sit amet, consectetur adipiscing elit.",
                "resume_link": "https://server.com/rocky-balboa.pdf",
            },
        )
        assert response.status_code == 302

        job_application = JobApplication.objects.get(sender=user, to_siae=siae)
        assert job_application.job_seeker == new_job_seeker
        assert job_application.sender_kind == SenderKind.SIAE_STAFF
        assert job_application.sender_siae == siae
        assert job_application.sender_prescriber_organization is None
        assert job_application.state == job_application.state.workflow.STATE_NEW
        assert job_application.message == "Lorem ipsum dolor sit amet, consectetur adipiscing elit."
        assert list(job_application.selected_jobs.all()) == [
            siae.job_description_through.first(),
            siae.job_description_through.last(),
        ]
        assert job_application.resume_link == "https://server.com/rocky-balboa.pdf"

        assert f"job_application-{siae.pk}" not in self.client.session

        next_url = reverse("apply:application_end", kwargs={"siae_pk": siae.pk, "application_pk": job_application.pk})
        assert response.url == next_url

        # Step application's end.
        # ----------------------------------------------------------------------
        response = self.client.get(next_url)
        assert response.status_code == 200

    def test_apply_as_siae_for_approval_in_waiting_period(self):
        """Apply as SIAE for a job seeker with an approval in waiting period."""

        siae = SiaeWithMembershipAndJobsFactory(romes=("N1101", "N1105"))

        job_seeker = JobSeekerFactory()

        # Create an approval in waiting period.
        end_at = datetime.date.today() - relativedelta(days=30)
        start_at = end_at - relativedelta(years=2)
        ApprovalFactory(user=job_seeker, start_at=start_at, end_at=end_at)

        user = siae.members.first()
        self.client.force_login(user)

        # Follow all redirections…
        response = self.client.get(reverse("apply:start", kwargs={"siae_pk": siae.pk}), {"back_url": "/"}, follow=True)

        # …until a job seeker has to be determined…
        assert response.status_code == 200
        last_url = response.redirect_chain[-1][0]
        assert last_url == reverse("apply:check_nir_for_sender", kwargs={"siae_pk": siae.pk})

        # …choose one, then follow all redirections…
        post_data = {
            "nir": job_seeker.nir,
            "confirm": 1,
        }
        response = self.client.post(last_url, data=post_data, follow=True)

        # …until the expected 403.
        assert response.status_code == 403
        assert "Le candidat a terminé un parcours" in response.context["exception"]
        last_url = response.redirect_chain[-1][0]
        assert last_url == reverse("apply:step_check_job_seeker_info", kwargs={"siae_pk": siae.pk})


class ApplyAsOtherTest(TestCase):
    ROUTES = [
        "apply:start",
        "apply:check_nir_for_job_seeker",
        "apply:check_nir_for_sender",
    ]

    def test_labor_inspectors_are_not_allowed_to_submit_application(self):
        siae = SiaeFactory()
        institution = InstitutionWithMembershipFactory()

        self.client.force_login(institution.members.first())

        for route in self.ROUTES:
            with self.subTest(route=route):
                response = self.client.get(reverse(route, kwargs={"siae_pk": siae.pk}), follow=True)
                assert response.status_code == 403

    def test_an_account_without_rights_is_not_allowed_to_submit_application(self):
        siae = SiaeFactory()
        user = UserFactory(is_job_seeker=False, is_prescriber=False, is_siae_staff=False, is_labor_inspector=False)

        self.client.force_login(user)

        for route in self.ROUTES:
            with self.subTest(route=route):
                response = self.client.get(reverse(route, kwargs={"siae_pk": siae.pk}), follow=True)
                assert response.status_code == 403


class ApplicationViewTest(S3AccessingTestCase):
    def test_application_jobs_use_previously_selected_jobs(self):
        siae = SiaeFactory(subject_to_eligibility=True, with_membership=True, with_jobs=True)

        self.client.force_login(siae.members.first())
        apply_session = SessionNamespace(self.client.session, f"job_application-{siae.pk}")
        apply_session.init(
            {
                "job_seeker_pk": JobSeekerFactory(),
                "selected_jobs": siae.job_description_through.all(),
            }
        )
        apply_session.save()

        response = self.client.get(reverse("apply:application_jobs", kwargs={"siae_pk": siae.pk}))
        assert response.status_code == 200
        assert response.context["form"].initial["selected_jobs"] == [
            jd.pk for jd in siae.job_description_through.all()
        ]

    def test_application_resume_hidden_fields(self):
        siae = SiaeFactory(with_membership=True, with_jobs=True)

        self.client.force_login(siae.members.first())
        apply_session = SessionNamespace(self.client.session, f"job_application-{siae.pk}")
        apply_session.init(
            {
                "job_seeker_pk": JobSeekerFactory(),
                "selected_jobs": siae.job_description_through.all(),
            }
        )
        apply_session.save()

        response = self.client.get(reverse("apply:application_resume", kwargs={"siae_pk": siae.pk}))
        assert response.status_code == 200
        self.assertContains(response, 'name="selected_jobs"')
        self.assertContains(response, 'name="resume_link"')

    def test_application_eligibility_is_bypassed_for_siae_not_subject_to_eligibility_rules(self):
        siae = SiaeFactory(not_subject_to_eligibility=True, with_membership=True)

        self.client.force_login(siae.members.first())
        apply_session = SessionNamespace(self.client.session, f"job_application-{siae.pk}")
        apply_session.init({"job_seeker_pk": JobSeekerFactory()})
        apply_session.save()

        response = self.client.get(reverse("apply:application_eligibility", kwargs={"siae_pk": siae.pk}))
        self.assertRedirects(
            response, reverse("apply:application_resume", kwargs={"siae_pk": siae.pk}), fetch_redirect_response=False
        )

    def test_application_eligibility_is_bypassed_for_unauthorized_prescriber(self):
        siae = SiaeFactory(not_subject_to_eligibility=True, with_membership=True)
        prescriber = PrescriberOrganizationWithMembershipFactory().members.first()

        self.client.force_login(prescriber)
        apply_session = SessionNamespace(self.client.session, f"job_application-{siae.pk}")
        apply_session.init({"job_seeker_pk": JobSeekerFactory()})
        apply_session.save()

        response = self.client.get(reverse("apply:application_eligibility", kwargs={"siae_pk": siae.pk}))
        self.assertRedirects(
            response, reverse("apply:application_resume", kwargs={"siae_pk": siae.pk}), fetch_redirect_response=False
        )

    def test_application_eligibility_is_bypassed_when_the_job_seeker_already_has_an_approval(self):
        siae = SiaeFactory(not_subject_to_eligibility=True, with_membership=True)
        eligibility_diagnosis = EligibilityDiagnosisFactory()

        self.client.force_login(siae.members.first())
        apply_session = SessionNamespace(self.client.session, f"job_application-{siae.pk}")
        apply_session.init({"job_seeker_pk": eligibility_diagnosis.job_seeker})
        apply_session.save()

        response = self.client.get(reverse("apply:application_eligibility", kwargs={"siae_pk": siae.pk}))
        self.assertRedirects(
            response, reverse("apply:application_resume", kwargs={"siae_pk": siae.pk}), fetch_redirect_response=False
        )

    def test_application_eligibility_update_diagnosis_only_if_not_shrouded(self):
        siae = SiaeFactory(subject_to_eligibility=True, with_membership=True)
        prescriber = PrescriberOrganizationWithMembershipFactory(authorized=True).members.first()
        eligibility_diagnosis = EligibilityDiagnosisFactory()

        self.client.force_login(prescriber)
        apply_session = SessionNamespace(self.client.session, f"job_application-{siae.pk}")
        apply_session.init({"job_seeker_pk": eligibility_diagnosis.job_seeker})
        apply_session.save()

        # if "shrouded" is present then we don't update the eligibility diagnosis
        response = self.client.post(
            reverse("apply:application_eligibility", kwargs={"siae_pk": siae.pk}),
            {"level_1_1": True, "shrouded": "whatever"},
        )
        self.assertRedirects(
            response, reverse("apply:application_resume", kwargs={"siae_pk": siae.pk}), fetch_redirect_response=False
        )
        assert [eligibility_diagnosis] == list(
            EligibilityDiagnosis.objects.for_job_seeker(eligibility_diagnosis.job_seeker)
        )

        # If "shrouded" is NOT present then we update the eligibility diagnosis
        response = self.client.post(
            reverse("apply:application_eligibility", kwargs={"siae_pk": siae.pk}),
            {"level_1_1": True},
        )
        self.assertRedirects(
            response, reverse("apply:application_resume", kwargs={"siae_pk": siae.pk}), fetch_redirect_response=False
        )
        new_eligibility_diagnosis = (
            EligibilityDiagnosis.objects.for_job_seeker(eligibility_diagnosis.job_seeker).order_by().last()
        )
        assert new_eligibility_diagnosis != eligibility_diagnosis
        assert new_eligibility_diagnosis.author == prescriber


class LastCheckedAtViewTest(TestCase):
    @classmethod
    def setUpTestData(cls):
        cls.siae = SiaeFactory(subject_to_eligibility=True, with_membership=True)
        cls.job_seeker = JobSeekerFactory()

    def _check_last_checked_at(self, user, sees_warning, sees_verify_link):
        self.client.force_login(user)
        apply_session = SessionNamespace(self.client.session, f"job_application-{self.siae.pk}")
        apply_session.init(
            {
                "job_seeker_pk": self.job_seeker.pk,
                "selected_jobs": [],
            }
        )
        apply_session.save()

        url = reverse("apply:application_jobs", kwargs={"siae_pk": self.siae.pk})
        response = self.client.get(url)
        assert response.status_code == 200

        # Check the presence of the verify link
        update_url = reverse(
            "apply:update_job_seeker_step_1", kwargs={"siae_pk": self.siae.pk, "job_seeker_pk": self.job_seeker.pk}
        )
        link_check = self.assertContains if sees_verify_link else self.assertNotContains
        link_check(response, f'<a class="btn btn-link" href="{update_url}">Vérifier le profil</a>', html=True)
        # Check last_checked_at is shown
        self.assertContains(response, "Dernière actualisation du profil : ")
        self.assertNotContains(response, "Merci de vérifier la validité des informations")

        self.job_seeker.last_checked_at -= datetime.timedelta(days=500)
        self.job_seeker.save(update_fields=["last_checked_at"])
        response = self.client.get(url)
        assert response.status_code == 200
        warning_check = self.assertContains if sees_warning else self.assertNotContains
        warning_check(response, "Merci de vérifier la validité des informations")
        link_check(response, f'<a class="btn btn-link" href="{update_url}">Vérifier le profil</a>', html=True)

    def test_siae_employee(self):
        self._check_last_checked_at(self.siae.members.first(), sees_warning=True, sees_verify_link=True)

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


class UpdateJobSeekerViewTestCase(TestCase):
    @classmethod
    def setUpTestData(cls):
        cls.siae = SiaeFactory(subject_to_eligibility=True, with_membership=True)
        cls.job_seeker = JobSeekerFactory()
        cls.step_1_url = reverse(
            "apply:update_job_seeker_step_1", kwargs={"siae_pk": cls.siae.pk, "job_seeker_pk": cls.job_seeker.pk}
        )
        cls.step_2_url = reverse(
            "apply:update_job_seeker_step_2", kwargs={"siae_pk": cls.siae.pk, "job_seeker_pk": cls.job_seeker.pk}
        )
        cls.step_3_url = reverse(
            "apply:update_job_seeker_step_3", kwargs={"siae_pk": cls.siae.pk, "job_seeker_pk": cls.job_seeker.pk}
        )
        cls.step_end_url = reverse(
            "apply:update_job_seeker_step_end", kwargs={"siae_pk": cls.siae.pk, "job_seeker_pk": cls.job_seeker.pk}
        )
        create_test_cities(["67"], num_per_department=1)
        cls.city = City.objects.first()

        cls.INFO_MODIFIABLE_PAR_CANDIDAT_UNIQUEMENT = "Informations modifiables par le candidat uniquement"
        cls.job_seeker_session_key = f"job_seeker-{cls.job_seeker.pk}"

    def _check_nothing_permitted(self, user):
        self.client.force_login(user)
        apply_session = SessionNamespace(self.client.session, f"job_application-{self.siae.pk}")
        apply_session.init(
            {
                "job_seeker_pk": self.job_seeker.pk,
                "selected_jobs": [],
            }
        )
        apply_session.save()
        for url in [
            self.step_1_url,
            self.step_2_url,
            self.step_3_url,
            self.step_end_url,
        ]:
            response = self.client.get(url)
            assert response.status_code == 403

    def _check_everything_allowed(self, user):
        self.client.force_login(user)
        apply_session = SessionNamespace(self.client.session, f"job_application-{self.siae.pk}")
        apply_session.init(
            {
                "job_seeker_pk": self.job_seeker.pk,
                "selected_jobs": [],
            }
        )
        apply_session.save()

        # STEP 1
        response = self.client.get(self.step_1_url)
        assert response.status_code == 200
        self.assertContains(response, self.job_seeker.first_name)
        self.assertNotContains(response, self.INFO_MODIFIABLE_PAR_CANDIDAT_UNIQUEMENT)

        NEW_FIRST_NAME = "New first name"

        post_data = {
            "title": "M",
            "first_name": NEW_FIRST_NAME,
            "last_name": "New last name",
            "birthdate": self.job_seeker.birthdate,
        }
        response = self.client.post(self.step_1_url, data=post_data)
        assertRedirects(response, self.step_2_url, fetch_redirect_response=False)

        # Data is stored in the session but user is untouched
        expected_job_seeker_session = {"user": post_data}
        assert self.client.session[self.job_seeker_session_key] == expected_job_seeker_session
        self.job_seeker.refresh_from_db()
        assert self.job_seeker.first_name != NEW_FIRST_NAME

        # If you go back to step 1, new data is shown
        response = self.client.get(self.step_1_url)
        assert response.status_code == 200
        self.assertContains(response, NEW_FIRST_NAME)

        # STEP 2
        response = self.client.get(self.step_2_url)
        assert response.status_code == 200
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
        assert response.status_code == 200
        self.assertContains(response, NEW_ADDRESS_LINE)

        # STEP 3
        response = self.client.get(self.step_3_url)
        assert response.status_code == 200

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
            "lack_of_pole_emploi_id_reason": User.REASON_NOT_REGISTERED,
        }
        assert self.client.session[self.job_seeker_session_key] == expected_job_seeker_session
        self.job_seeker.refresh_from_db()
        assert not self.job_seeker.has_jobseeker_profile

        # If you go back to step 3, new data is shown
        response = self.client.get(self.step_3_url)
        assert response.status_code == 200
        self.assertContains(response, '<option value="40" selected="">Formation de niveau BAC</option>', html=True)

        # Step END
        response = self.client.get(self.step_end_url)
        assert response.status_code == 200

        self.assertContains(response, NEW_FIRST_NAME)
        self.assertContains(response, NEW_ADDRESS_LINE)
        self.assertContains(response, "Formation de niveau BAC")

        previous_last_checked_at = self.job_seeker.last_checked_at

        response = self.client.post(self.step_end_url)
        assertRedirects(
            response,
            reverse("apply:application_jobs", kwargs={"siae_pk": self.siae.pk}),
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
        apply_session = SessionNamespace(self.client.session, f"job_application-{self.siae.pk}")
        apply_session.init(
            {
                "job_seeker_pk": self.job_seeker.pk,
                "selected_jobs": [],
            }
        )
        apply_session.save()

        # STEP 1
        response = self.client.get(self.step_1_url)
        assert response.status_code == 200
        self.assertContains(response, self.job_seeker.first_name)
        self.assertContains(response, self.INFO_MODIFIABLE_PAR_CANDIDAT_UNIQUEMENT)

        response = self.client.post(self.step_1_url)
        assertRedirects(response, self.step_2_url, fetch_redirect_response=False)

        # Session is created
        expected_job_seeker_session = {"user": {}}
        assert self.client.session[self.job_seeker_session_key] == expected_job_seeker_session

        # STEP 2
        response = self.client.get(self.step_2_url)
        assert response.status_code == 200
        self.assertContains(response, self.job_seeker.phone)
        self.assertContains(response, self.INFO_MODIFIABLE_PAR_CANDIDAT_UNIQUEMENT)

        response = self.client.post(self.step_2_url)
        assertRedirects(response, self.step_3_url, fetch_redirect_response=False)

        # Data is stored in the session but user is untouched
        assert self.client.session[self.job_seeker_session_key] == expected_job_seeker_session

        # STEP 3
        response = self.client.get(self.step_3_url)
        assert response.status_code == 200

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
            "lack_of_pole_emploi_id_reason": User.REASON_NOT_REGISTERED,
        }
        assert self.client.session[self.job_seeker_session_key] == expected_job_seeker_session
        self.job_seeker.refresh_from_db()
        assert not self.job_seeker.has_jobseeker_profile

        # If you go back to step 3, new data is shown
        response = self.client.get(self.step_3_url)
        assert response.status_code == 200
        self.assertContains(response, '<option value="40" selected="">Formation de niveau BAC</option>', html=True)

        # Step END
        response = self.client.get(self.step_end_url)
        assert response.status_code == 200

        self.assertContains(response, "Formation de niveau BAC")

        previous_last_checked_at = self.job_seeker.last_checked_at

        response = self.client.post(self.step_end_url)
        assertRedirects(
            response,
            reverse("apply:application_jobs", kwargs={"siae_pk": self.siae.pk}),
            fetch_redirect_response=False,
        )
        assert self.client.session.get(self.job_seeker_session_key) is None

        self.job_seeker.refresh_from_db()
        assert self.job_seeker.has_jobseeker_profile is True
        assert self.job_seeker.jobseeker_profile.education_level == EducationLevel.BAC_LEVEL
        assert self.job_seeker.last_checked_at != previous_last_checked_at

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
        self.job_seeker.created_by = UserFactory()
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

    def test_as_siae_with_proxied_job_seeker(self):
        # Make sure the job seeker does not manage its own account
        self.job_seeker.created_by = UserFactory()
        self.job_seeker.last_login = None
        self.job_seeker.save(update_fields=["created_by", "last_login"])
        self._check_everything_allowed(self.siae.members.first())

    def test_as_siae_with_non_proxied_job_seeker(self):
        # Make sure the job seeker does manage its own account
        self.job_seeker.last_login = timezone.now() - relativedelta(months=1)
        self.job_seeker.save(update_fields=["last_login"])
        self._check_only_administrative_allowed(self.siae.members.first())


class UpdateJobSeekerStep3ViewTestCase(TestCase):
    def test_job_seeker_with_profile_has_check_boxes_ticked_in_step3(self):
        siae = SiaeFactory(subject_to_eligibility=True, with_membership=True)
        job_seeker = JobSeekerFactory()
        JobSeekerProfileFactory(user=job_seeker, ass_allocation_since=AllocationDuration.FROM_6_TO_11_MONTHS)

        self.client.force_login(siae.members.first())
        apply_session = SessionNamespace(self.client.session, f"job_application-{siae.pk}")
        apply_session.init(
            {
                "job_seeker_pk": job_seeker.pk,
                "selected_jobs": [],
            }
        )
        apply_session.save()

        # STEP 1 to setup jobseeker session
        response = self.client.get(
            reverse("apply:update_job_seeker_step_1", kwargs={"siae_pk": siae.pk, "job_seeker_pk": job_seeker.pk})
        )
        assert response.status_code == 200

        # Go straight to STEP 3
        response = self.client.get(
            reverse("apply:update_job_seeker_step_3", kwargs={"siae_pk": siae.pk, "job_seeker_pk": job_seeker.pk})
        )
        assert response.status_code == 200

        self.assertContains(
            response,
            '<input type="checkbox" name="ass_allocation" class="form-check-input" id="id_ass_allocation" checked="">',
            html=True,
        )
