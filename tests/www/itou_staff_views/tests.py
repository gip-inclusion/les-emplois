import datetime
import io
from functools import partial

import openpyxl
import pytest
from django.contrib import messages
from django.contrib.auth.models import Permission
from django.contrib.contenttypes.models import ContentType
from django.urls import reverse
from django.utils import timezone
from django_otp.oath import TOTP
from django_otp.plugins.otp_totp.models import TOTPDevice
from freezegun import freeze_time
from pytest_django.asserts import (
    assertContains,
    assertMessages,
    assertNotContains,
    assertQuerySetEqual,
    assertRedirects,
)
from rest_framework.authtoken.models import Token

from itou.companies.models import CompanyMembership
from itou.job_applications.enums import JobApplicationState
from itou.job_applications.models import JobApplicationTransitionLog
from itou.prescribers.models import PrescriberMembership
from itou.users.models import User
from itou.utils.models import PkSupportRemark
from itou.www.itou_staff_views.forms import DEPARTMENTS_CHOICES
from tests.approvals.factories import (
    ApprovalFactory,
    ProlongationFactory,
    ProlongationRequestFactory,
    SuspensionFactory,
)
from tests.companies.factories import CompanyFactory, CompanyMembershipFactory
from tests.eligibility.factories import GEIQEligibilityDiagnosisFactory, IAEEligibilityDiagnosisFactory
from tests.gps.factories import FollowUpGroupMembershipFactory
from tests.invitations.factories import EmployerInvitationFactory
from tests.job_applications.factories import JobApplicationFactory
from tests.prescribers.factories import PrescriberMembershipFactory, PrescriberOrganizationFactory
from tests.users.factories import (
    EmployerFactory,
    ItouStaffFactory,
    JobSeekerFactory,
    LaborInspectorFactory,
    PrescriberFactory,
)
from tests.utils.test import assertSnapshotQueries, parse_response_to_soup, pretty_indented


class TestExportJobApplications:
    @pytest.mark.parametrize(
        "factory,factory_kwargs,expected_status",
        [
            (JobSeekerFactory, {}, 403),
            (EmployerFactory, {"with_company": True}, 403),
            (PrescriberFactory, {}, 403),
            (LaborInspectorFactory, {"membership": True}, 403),
            (ItouStaffFactory, {}, 302),
            (ItouStaffFactory, {"is_superuser": True}, 200),
        ],
    )
    def test_requires_superuser(self, client, factory, factory_kwargs, expected_status):
        user = factory(**factory_kwargs)
        client.force_login(user)
        response = client.get(reverse("itou_staff_views:export_job_applications_unknown_to_ft"))
        assert response.status_code == expected_status

    def test_requires_permission(self, settings, client):
        user = ItouStaffFactory()
        client.force_login(user)

        url = reverse("itou_staff_views:export_job_applications_unknown_to_ft")
        response = client.get(url)
        assertRedirects(response, f"{settings.LOGIN_URL}?next={url}", fetch_redirect_response=False)

        user.user_permissions.add(Permission.objects.get(codename="export_job_applications_unknown_to_ft"))
        response = client.get(reverse("itou_staff_views:export_job_applications_unknown_to_ft"))
        assert response.status_code == 200

    @pytest.mark.parametrize(
        "start,end",
        [
            pytest.param("2024-05-09", "2024-05-09", id="before"),
            pytest.param("2024-05-10", "2024-05-10", id="contains"),
            pytest.param("2024-05-11", "2024-05-11", id="after"),
        ],
    )
    def test_export(self, client, start, end, snapshot):
        client.force_login(ItouStaffFactory(is_superuser=True))
        siae = CompanyFactory(for_snapshot=True, with_membership=True, siret="32112345600020", naf="1234Z")
        with freeze_time("2024-05-10T11:11:11+02:00"):
            job_seeker = JobSeekerFactory(
                for_snapshot=True,
                jobseeker_profile__pe_last_certification_attempt_at=timezone.now(),
                jobseeker_profile__hexa_post_code="35000",
            )
            eligibility_diag = IAEEligibilityDiagnosisFactory(
                from_prescriber=True,
                job_seeker=job_seeker,
                author_prescriber_organization__siret="12345678900012",
            )
            job_app = JobApplicationFactory(
                for_snapshot=True,
                job_seeker=job_seeker,
                to_company=siae,
                state=JobApplicationState.ACCEPTED,
                eligibility_diagnosis=eligibility_diag,
            )
            approval = ApprovalFactory(
                user=job_seeker,
                eligibility_diagnosis=eligibility_diag,
                number="XXXXX1234567",
            )
            job_app.approval = approval
            job_app.save()
            ProlongationFactory(
                for_snapshot=True,
                validated_by=PrescriberFactory(membership__organization__authorized=True),
                declared_by_siae=siae,
                approval=approval,
            )
        with (
            freeze_time("2024-05-17T11:11:11+02:00"),
            assertSnapshotQueries(snapshot(name="SQL queries")),
        ):
            response = client.post(
                reverse("itou_staff_views:export_job_applications_unknown_to_ft"),
                {
                    "date_joined_from": start,
                    "date_joined_to": end,
                    "departments": DEPARTMENTS_CHOICES,
                },
            )
            assert response.status_code == 200
            assert response["Content-Disposition"] == (
                "attachment; "
                'filename="candidats_emplois_inclusion_multiple_departements_non_certifies_2024-05-17_11-11-11.csv"'
            )
            assert b"".join(response.streaming_content).decode() == snapshot(name="streaming content")

    def test_export_today(self, client):
        client.force_login(ItouStaffFactory(is_superuser=True))
        with freeze_time("2024-05-22T11:11:11+02:00"):
            response = client.post(
                reverse("itou_staff_views:export_job_applications_unknown_to_ft"),
                {
                    "date_joined_from": datetime.date.min.isoformat(),
                    "date_joined_to": timezone.localdate(),
                    "departments": DEPARTMENTS_CHOICES,
                },
            )
        assertContains(
            response,
            '<div class="invalid-feedback">Assurez-vous que cette valeur est inférieure ou égale à 2024-05-21.</div>',
        )


class TestExportPEApiRejections:
    @pytest.mark.parametrize(
        "factory,factory_kwargs,expected_status",
        [
            (JobSeekerFactory, {}, 403),
            (EmployerFactory, {"with_company": True}, 403),
            (PrescriberFactory, {}, 403),
            (LaborInspectorFactory, {"membership": True}, 403),
            (ItouStaffFactory, {}, 302),
            (ItouStaffFactory, {"is_superuser": True}, 302),  # redirects to dashboard if no file
        ],
    )
    def test_requires_superuser(self, client, factory, factory_kwargs, expected_status):
        user = factory(**factory_kwargs)
        client.force_login(user)
        response = client.get(reverse("itou_staff_views:export_ft_api_rejections"))
        assert response.status_code == expected_status

    def test_requires_permission(self, settings, client):
        user = ItouStaffFactory()
        client.force_login(user)

        url = reverse("itou_staff_views:export_ft_api_rejections")
        response = client.get(url)
        assertRedirects(response, f"{settings.LOGIN_URL}?next={url}", fetch_redirect_response=False)

        user.user_permissions.add(Permission.objects.get(codename="export_ft_api_rejections"))
        response = client.get(reverse("itou_staff_views:export_ft_api_rejections"))
        assertRedirects(response, reverse("dashboard:index"))

    @freeze_time("2022-09-13T11:11:11+02:00")
    def test_export(self, client, snapshot):
        # generate an approval that should not be found.
        ApprovalFactory(
            pe_notification_status="notification_error",
            pe_notification_time=datetime.datetime(2022, 7, 5, tzinfo=datetime.UTC),
            pe_notification_exit_code="NOTFOUND",
        )
        ApprovalFactory(
            pe_notification_status="notification_error",
            pe_notification_time=datetime.datetime(2022, 8, 31, tzinfo=datetime.UTC),
            pe_notification_exit_code="FOOBAR",
            user__for_snapshot=True,
            user__jobseeker_profile__pole_emploi_id="PE777",
            origin_siae_kind="EI",
            origin_siae_siret="12345678900000",
            number="XXXXX1234567",
        )
        client.force_login(ItouStaffFactory(is_superuser=True))

        with assertSnapshotQueries(snapshot(name="SQL queries")):
            response = client.get(
                reverse("itou_staff_views:export_ft_api_rejections"),
            )
            assert response.status_code == 200
            assert response["Content-Disposition"] == (
                'attachment; filename="rejets_api_france_travail_2022-09-13_11-11-11.xlsx"'
            )
            assert response["Content-Type"] == "application/vnd.openxmlformats-officedocument.spreadsheetml.sheet"

            workbook = openpyxl.load_workbook(filename=io.BytesIO(b"".join(response.streaming_content)))
            assert list(workbook.active.values) == snapshot(name="workbook values")


class TestExportCTA:
    @pytest.mark.parametrize(
        "factory,factory_kwargs,expected_status",
        [
            (JobSeekerFactory, {}, 403),
            (EmployerFactory, {"with_company": True}, 403),
            (PrescriberFactory, {}, 403),
            (LaborInspectorFactory, {"membership": True}, 403),
            (ItouStaffFactory, {}, 302),
            (ItouStaffFactory, {"is_superuser": True}, 200),
        ],
    )
    def test_requires_superuser(self, client, factory, factory_kwargs, expected_status):
        user = factory(**factory_kwargs)
        client.force_login(user)
        response = client.get(reverse("itou_staff_views:export_cta"))
        assert response.status_code == expected_status

    def test_requires_permission(self, settings, client):
        user = ItouStaffFactory()
        client.force_login(user)

        url = reverse("itou_staff_views:export_cta")
        response = client.get(url)
        assertRedirects(response, f"{settings.LOGIN_URL}?next={url}", fetch_redirect_response=False)

        user.user_permissions.add(Permission.objects.get(codename="export_cta"))
        response = client.get(reverse("itou_staff_views:export_cta"))
        assert response.status_code == 200

    @freeze_time("2024-05-17T11:11:11+02:00")
    def test_export(self, client, snapshot):
        # generate an approval that should not be found.
        client.force_login(ItouStaffFactory(is_superuser=True))
        PrescriberMembershipFactory(organization__for_snapshot=True, user__for_snapshot=True)
        CompanyFactory(with_membership=True, for_snapshot=True)

        with assertSnapshotQueries(snapshot(name="SQL queries")):
            response = client.get(
                reverse("itou_staff_views:export_cta"),
            )
            assert response.status_code == 200
            assert response["Content-Disposition"] == ('attachment; filename="export_cta_2024-05-17_11-11-11.csv"')
            assert b"".join(response.streaming_content).decode() == snapshot(name="streaming content")


class TestMergeUsers:
    @pytest.mark.parametrize(
        "factory,factory_kwargs,expected_status",
        [
            (JobSeekerFactory, {"for_snapshot": True}, 403),
            (EmployerFactory, {"with_company": True}, 403),
            (PrescriberFactory, {}, 403),
            (LaborInspectorFactory, {"membership": True}, 403),
            (ItouStaffFactory, {}, 302),
            (ItouStaffFactory, {"is_superuser": True}, 200),
        ],
    )
    def test_requires_superuser(self, client, factory, factory_kwargs, expected_status):
        user = factory(**factory_kwargs)
        client.force_login(user)
        response = client.get(reverse("itou_staff_views:merge_users"))
        assert response.status_code == expected_status
        response = client.get(reverse("itou_staff_views:merge_users_confirm", args=(user.public_id, user.public_id)))
        assert response.status_code == expected_status

    def test_requires_permission(self, settings, client):
        user = ItouStaffFactory()
        client.force_login(user)

        url = reverse("itou_staff_views:merge_users")
        response = client.get(url)
        assertRedirects(response, f"{settings.LOGIN_URL}?next={url}", fetch_redirect_response=False)

        user.user_permissions.add(Permission.objects.get(codename="merge_users"))
        response = client.get(reverse("itou_staff_views:merge_users"))
        assert response.status_code == 200

    def test_merge_users(self, client):
        client.force_login(ItouStaffFactory(is_superuser=True))
        url = reverse("itou_staff_views:merge_users")

        response = client.post(url, data={"email_1": "", "email_2": ""})
        assert response.context["form"].errors == {
            "email_1": ["Ce champ est obligatoire."],
            "email_2": ["Ce champ est obligatoire."],
        }

        response = client.post(url, data={"email_1": "one@mailinator.com", "email_2": "two@mailinator.com"})
        assert response.context["form"].errors == {
            "email_1": ["Cet utilisateur n'existe pas."],
            "email_2": ["Cet utilisateur n'existe pas."],
        }

        user_1 = PrescriberFactory(email="one@mailinator.com")
        response = client.post(url, data={"email_1": "one@mailinator.com", "email_2": "two@mailinator.com"})
        assert response.context["form"].errors == {
            "email_2": ["Cet utilisateur n'existe pas."],
        }

        response = client.post(url, data={"email_1": "one@mailinator.com", "email_2": "one@mailinator.com"})
        assert response.context["form"].errors == {
            "__all__": ["Les deux adresses doivent être différentes."],
        }

        user_2 = PrescriberFactory(email="two@mailinator.com")
        response = client.post(url, data={"email_1": "one@mailinator.com", "email_2": "two@mailinator.com"})
        assertRedirects(
            response, reverse("itou_staff_views:merge_users_confirm", args=(user_1.public_id, user_2.public_id))
        )

    def test_check_user_kind(self, client, mocker):
        prescriber = PrescriberFactory()
        employer = EmployerFactory()
        job_seeker = JobSeekerFactory()
        labor_inspector = LaborInspectorFactory()
        itou_staff = ItouStaffFactory(is_superuser=True)

        client.force_login(itou_staff)
        merge_users_mock = mocker.patch("itou.www.itou_staff_views.merge_utils.merge_users")

        BUTTON_TXT = "Confirmer la fusion"
        DATA_TITLE = "<h2>Données qui seront transférées</h2>"

        # if user is the same
        url = reverse("itou_staff_views:merge_users_confirm", args=(prescriber.public_id, prescriber.public_id))
        response = client.get(url)
        assertContains(response, "Les utilisateurs doivent être différents", count=2)
        assertNotContains(response, BUTTON_TXT)
        assertNotContains(response, DATA_TITLE)
        response = client.post(url)
        assert merge_users_mock.call_count == 0

        # if the users are not employers of prescribers
        url = reverse("itou_staff_views:merge_users_confirm", args=(job_seeker.public_id, labor_inspector.public_id))
        response = client.get(url)
        assertContains(response, "L’utilisateur doit être employeur ou prescripteur", count=2)
        assertNotContains(response, BUTTON_TXT)
        assertNotContains(response, DATA_TITLE)
        response = client.post(url)
        assert merge_users_mock.call_count == 0

        # if kind is different
        url = reverse("itou_staff_views:merge_users_confirm", args=(employer.public_id, prescriber.public_id))
        response = client.get(url)
        assertContains(response, "Les utilisateurs doivent être du même type", count=2)
        assertNotContains(response, BUTTON_TXT)
        assertNotContains(response, DATA_TITLE)
        response = client.post(url)
        assert merge_users_mock.call_count == 0

        # everything is OK
        other_employer = EmployerFactory()
        url = reverse("itou_staff_views:merge_users_confirm", args=(employer.public_id, other_employer.public_id))
        response = client.get(url)
        assertContains(response, BUTTON_TXT)
        assertContains(response, DATA_TITLE)
        response = client.post(url, data={"user_to_keep": "from_user"}, follow=True)
        assert merge_users_mock.call_count == 1
        assertContains(response, f"Fusion {employer.email} & {other_employer.email} effectuée")
        assertRedirects(response, reverse("itou_staff_views:merge_users"))

    def test_merge_order(self, client, snapshot):
        # always merge into the user with the smallest pk
        client.force_login(ItouStaffFactory(is_superuser=True))

        prescriber_1 = PrescriberFactory(
            first_name="Pierre",
            last_name="Dupont",
            email="pierre.dupont@test.local",
            username="8487651a-a6c8-4a57-9663-64fadf1dc764",
        )
        prescriber_2 = PrescriberFactory(
            first_name="Jean",
            last_name="Laurent",
            email="jean.laurent@test.local",
            username="471d1de6-e1ff-4cd2-be2e-61f603c04687",
        )
        assert prescriber_1.pk < prescriber_2.pk

        url = reverse("itou_staff_views:merge_users_confirm", args=(prescriber_1.public_id, prescriber_2.public_id))
        response = client.get(url)
        assert pretty_indented(
            parse_response_to_soup(
                response,
                "#users_info",
                replace_in_attr=[
                    ("href", f"/admin/users/user/{prescriber_1.pk}", "/admin/users/user/[PK of User_1]"),
                    ("href", f"/admin/users/user/{prescriber_2.pk}", "/admin/users/user/[PK of User_2]"),
                ],
            )
        ) == snapshot(name="same_order")
        client.post(url, data={"user_to_keep": "from_user"})
        assert User.objects.filter(pk=prescriber_1.pk).exists()
        assert not User.objects.filter(pk=prescriber_2.pk).exists()

        # reset accounts
        prescriber_1.save()
        prescriber_2.save()

        url = reverse("itou_staff_views:merge_users_confirm", args=(prescriber_2.public_id, prescriber_1.public_id))
        response = client.get(url)
        assert pretty_indented(
            parse_response_to_soup(
                response,
                "#users_info",
                replace_in_attr=[
                    ("href", f"/admin/users/user/{prescriber_1.pk}", "/admin/users/user/[PK of User_1]"),
                    ("href", f"/admin/users/user/{prescriber_2.pk}", "/admin/users/user/[PK of User_2]"),
                ],
            )
        ) == snapshot(name="same_order")
        client.post(url, data={"user_to_keep": "from_user"})
        assert User.objects.filter(pk=prescriber_1.pk).exists()
        assert not User.objects.filter(pk=prescriber_2.pk).exists()

    @freeze_time("2024-11-19")
    def test_merge_personal_data(self, client, caplog):
        prescriber_1 = PrescriberFactory()
        prescriber_2 = PrescriberFactory()

        client.force_login(ItouStaffFactory(is_superuser=True))

        url = reverse("itou_staff_views:merge_users_confirm", args=(prescriber_1.public_id, prescriber_2.public_id))
        client.post(url, data={"user_to_keep": "from_user"})
        merged_user = User.objects.get(pk=prescriber_1.pk)
        assert not User.objects.filter(pk=prescriber_2.pk).exists()
        assert merged_user.email == prescriber_2.email
        assert merged_user.first_name == prescriber_2.first_name
        assert merged_user.last_name == prescriber_2.last_name
        assert merged_user.username == prescriber_2.username
        assert merged_user.identity_provider == prescriber_2.identity_provider

        assert caplog.messages == [
            f"Fusion utilisateurs {prescriber_1.pk} ← {prescriber_2.pk} — Updated personal data",
            f"Fusion utilisateurs {prescriber_1.pk} ← {prescriber_2.pk} — Done !",
            "HTTP 302 Found",
        ]

        admin_remark = PkSupportRemark.objects.get(
            content_type=ContentType.objects.get_for_model(prescriber_1), object_id=prescriber_1.pk
        )
        assert admin_remark.remark == (
            f"2024-11-19: Fusion des utilisateurs {prescriber_1.email} et {prescriber_2.email} "
            "en mettant à jour les infos personnelles"
        )
        admin_remark.delete()

        caplog.clear()
        prescriber_1.save()
        prescriber_2.save()
        url = reverse("itou_staff_views:merge_users_confirm", args=(prescriber_1.public_id, prescriber_2.public_id))
        client.post(url, data={"user_to_keep": "to_user"})
        merged_user = User.objects.get(pk=prescriber_1.pk)
        assert not User.objects.filter(pk=prescriber_2.pk).exists()
        assert merged_user.email == prescriber_1.email
        assert merged_user.first_name == prescriber_1.first_name
        assert merged_user.last_name == prescriber_1.last_name
        assert merged_user.username == prescriber_1.username
        assert merged_user.identity_provider == prescriber_1.identity_provider

        assert caplog.messages == [
            f"Fusion utilisateurs {prescriber_1.pk} ← {prescriber_2.pk} — Done !",
            "HTTP 302 Found",
        ]

        admin_remark = PkSupportRemark.objects.get(
            content_type=ContentType.objects.get_for_model(prescriber_1), object_id=prescriber_1.pk
        )
        assert (
            admin_remark.remark == f"2024-11-19: Fusion des utilisateurs {prescriber_1.email} et {prescriber_2.email}"
        )

    def test_merge_prescriber_memberships(self, client, caplog):
        prescriber_1 = PrescriberFactory()
        prescriber_2 = PrescriberFactory()
        other_prescriber = PrescriberFactory()
        org = PrescriberOrganizationFactory()
        membership_1 = PrescriberMembershipFactory(user=prescriber_1, organization=org, is_active=False, is_admin=True)
        membership_2 = PrescriberMembershipFactory(
            user=prescriber_2, organization=org, is_active=True, is_admin=False, updated_by=other_prescriber
        )

        with freeze_time() as frozen_now:
            client.force_login(ItouStaffFactory(is_superuser=True))
            url = reverse(
                "itou_staff_views:merge_users_confirm", args=(prescriber_1.public_id, prescriber_2.public_id)
            )
            client.post(url, data={"user_to_keep": "to_user"})
            membership = PrescriberMembership.objects.get()
            assert membership.user == prescriber_1
            assert membership.is_admin is True
            assert membership.is_active is True
            assert membership.joined_at == min(membership_1.joined_at, membership_2.joined_at)
            assert membership.created_at == min(membership_1.created_at, membership_2.created_at)
            assert membership.updated_at == frozen_now().replace(tzinfo=datetime.UTC)
            assert membership.updated_by == other_prescriber

        assert caplog.messages == [
            f"Fusion utilisateurs {prescriber_1.pk} ← {prescriber_2.pk} — "
            f"itou.prescribers.models.PrescriberMembership.user updated : [{membership_1.pk}]",
            f"Fusion utilisateurs {prescriber_1.pk} ← {prescriber_2.pk} — Done !",
            "HTTP 302 Found",
        ]

    def test_merge_employer_memberships(self, client, caplog):
        employer_1 = EmployerFactory()
        employer_2 = EmployerFactory()
        other_employer = EmployerFactory()
        company = CompanyFactory()
        membership_1 = CompanyMembershipFactory(user=employer_1, company=company, is_active=False, is_admin=True)
        membership_2 = CompanyMembershipFactory(
            user=employer_2, company=company, is_active=True, is_admin=False, updated_by=other_employer
        )

        with freeze_time() as frozen_now:
            client.force_login(ItouStaffFactory(is_superuser=True))
            url = reverse("itou_staff_views:merge_users_confirm", args=(employer_1.public_id, employer_2.public_id))
            client.post(url, data={"user_to_keep": "to_user"})
            membership = CompanyMembership.objects.get()
            assert membership.user == employer_1
            assert membership.is_admin is True
            assert membership.is_active is True
            assert membership.joined_at == min(membership_1.joined_at, membership_2.joined_at)
            assert membership.created_at == min(membership_1.created_at, membership_2.created_at)
            assert membership.updated_at == frozen_now().replace(tzinfo=datetime.UTC)
            assert membership.updated_by == other_employer

        assert caplog.messages == [
            f"Fusion utilisateurs {employer_1.pk} ← {employer_2.pk} — "
            f"itou.companies.models.CompanyMembership.user updated : [{membership_1.pk}]",
            f"Fusion utilisateurs {employer_1.pk} ← {employer_2.pk} — Done !",
            "HTTP 302 Found",
        ]

    def test_merge_other_relations(self, client, caplog):
        prescriber_1 = PrescriberFactory()
        prescriber_2 = PrescriberFactory()
        job_app = JobApplicationFactory(
            sender=prescriber_2,
            approval_manually_refused_by=prescriber_2,
            archived_by=prescriber_2,
            archived_at=timezone.now(),
            transferred_by=prescriber_2,
            eligibility_diagnosis=None,
        )
        log = JobApplicationTransitionLog(job_application=job_app, user=prescriber_2)
        log.save()
        prolongation = ProlongationFactory(
            created_by=prescriber_2,
            updated_by=prescriber_2,
            validated_by=prescriber_2,
            declared_by=prescriber_2,
        )
        prolongation_request = ProlongationRequestFactory(
            created_by=prescriber_2,
            updated_by=prescriber_2,
            validated_by=prescriber_2,
            declared_by=prescriber_2,
            processed_by=prescriber_2,
        )
        job_seeker = JobSeekerFactory(created_by=prescriber_2)
        invitation = EmployerInvitationFactory(sender=prescriber_2)
        gps_group = FollowUpGroupMembershipFactory(member=prescriber_2)
        iae_diagnosis = IAEEligibilityDiagnosisFactory(author=prescriber_2, from_prescriber=True)
        geiq_diagnosis = GEIQEligibilityDiagnosisFactory(author=prescriber_2, from_prescriber=True)
        suspension = SuspensionFactory(created_by=prescriber_2, updated_by=prescriber_2)

        client.force_login(ItouStaffFactory(is_superuser=True))
        url = reverse("itou_staff_views:merge_users_confirm", args=(prescriber_1.public_id, prescriber_2.public_id))
        client.post(url, data={"user_to_keep": "to_user"})

        job_app.refresh_from_db()
        assert job_app.sender == prescriber_1
        assert job_app.approval_manually_refused_by == prescriber_1
        assert job_app.archived_by == prescriber_1
        assert job_app.transferred_by == prescriber_1
        log.refresh_from_db()
        assert log.user == prescriber_1
        prolongation.refresh_from_db()
        assert prolongation.created_by == prescriber_1
        assert prolongation.updated_by == prescriber_1
        assert prolongation.validated_by == prescriber_1
        assert prolongation.declared_by == prescriber_1
        prolongation_request.refresh_from_db()
        assert prolongation_request.created_by == prescriber_1
        assert prolongation_request.updated_by == prescriber_1
        assert prolongation_request.validated_by == prescriber_1
        assert prolongation_request.declared_by == prescriber_1
        assert prolongation_request.processed_by == prescriber_1
        job_seeker.refresh_from_db()
        assert job_seeker.created_by == prescriber_1
        invitation.refresh_from_db()
        assert invitation.sender == prescriber_1
        gps_group.refresh_from_db()
        assert gps_group.member == prescriber_1
        iae_diagnosis.refresh_from_db()
        assert iae_diagnosis.author == prescriber_1
        geiq_diagnosis.refresh_from_db()
        assert geiq_diagnosis.author == prescriber_1
        suspension.refresh_from_db()
        assert suspension.created_by == prescriber_1
        assert suspension.updated_by == prescriber_1

        prefix = f"Fusion utilisateurs {prescriber_1.pk} ← {prescriber_2.pk} — "
        assert caplog.messages == [
            f"{prefix}itou.approvals.models.Prolongation.created_by : [{prolongation.pk}]",
            f"{prefix}itou.approvals.models.Prolongation.declared_by : [{prolongation.pk}]",
            f"{prefix}itou.approvals.models.Prolongation.updated_by : [{prolongation.pk}]",
            f"{prefix}itou.approvals.models.Prolongation.validated_by : [{prolongation.pk}]",
            f"{prefix}itou.approvals.models.ProlongationRequest.created_by : [{prolongation_request.pk}]",
            f"{prefix}itou.approvals.models.ProlongationRequest.declared_by : [{prolongation_request.pk}]",
            f"{prefix}itou.approvals.models.ProlongationRequest.processed_by : [{prolongation_request.pk}]",
            f"{prefix}itou.approvals.models.ProlongationRequest.updated_by : [{prolongation_request.pk}]",
            f"{prefix}itou.approvals.models.ProlongationRequest.validated_by : [{prolongation_request.pk}]",
            f"{prefix}itou.approvals.models.Suspension.created_by : [{suspension.pk}]",
            f"{prefix}itou.approvals.models.Suspension.updated_by : [{suspension.pk}]",
            f"{prefix}itou.eligibility.models.geiq.GEIQEligibilityDiagnosis.author : [{geiq_diagnosis.pk}]",
            f"{prefix}itou.eligibility.models.iae.EligibilityDiagnosis.author : [{iae_diagnosis.pk}]",
            f"{prefix}itou.gps.models.FollowUpGroupMembership.member : [{gps_group.pk}]",
            f"{prefix}itou.invitations.models.EmployerInvitation.sender : [{invitation.pk}]",
            f"{prefix}itou.job_applications.models.JobApplication.approval_manually_refused_by : [{job_app.pk}]",
            f"{prefix}itou.job_applications.models.JobApplication.archived_by : [{job_app.pk}]",
            f"{prefix}itou.job_applications.models.JobApplication.sender : [{job_app.pk}]",
            f"{prefix}itou.job_applications.models.JobApplication.transferred_by : [{job_app.pk}]",
            f"{prefix}itou.job_applications.models.JobApplicationTransitionLog.user : [{log.pk}]",
            f"{prefix}itou.users.models.User.created_by : [{job_seeker.pk}]",
            f"Fusion utilisateurs {prescriber_1.pk} ← {prescriber_2.pk} — Done !",
            "HTTP 302 Found",
        ]

    def test_merge_tokens(self, client, caplog):
        employer_1 = EmployerFactory()
        Token.objects.create(user=employer_1)

        employer_2 = EmployerFactory()
        Token.objects.create(user=employer_2)

        client.force_login(ItouStaffFactory(is_superuser=True))
        url = reverse("itou_staff_views:merge_users_confirm", args=(employer_1.public_id, employer_2.public_id))
        client.post(url, data={"user_to_keep": "to_user"})
        assert not User.objects.filter(pk=employer_2.pk).exists()

        assert caplog.messages == [
            f"Fusion utilisateurs {employer_1.pk} ← {employer_2.pk} — Done !",
            "HTTP 302 Found",
        ]


class TestOTP:
    @pytest.mark.parametrize(
        "factory,expected_status",
        [
            (JobSeekerFactory, 403),
            (partial(EmployerFactory, with_company=True), 403),
            (PrescriberFactory, 403),
            (partial(LaborInspectorFactory, membership=True), 403),
            (ItouStaffFactory, 200),
        ],
    )
    def test_permissions(self, client, factory, expected_status):
        user = factory()
        client.force_login(user)
        response = client.get(reverse("itou_staff_views:otp_devices"))
        assert response.status_code == expected_status

        device = TOTPDevice.objects.create(user=user, confirmed=False)
        response = client.get(reverse("itou_staff_views:otp_confirm_device", args=(device.pk,)))
        assert response.status_code == expected_status

    @freeze_time("2025-03-11 05:18:56")
    def test_devices(self, client, snapshot):
        staff_user = ItouStaffFactory()
        client.force_login(staff_user)
        url = reverse("itou_staff_views:otp_devices")

        response = client.get(url)
        assert pretty_indented(parse_response_to_soup(response, ".s-section")) == snapshot(name="no_device")

        response = client.post(url, data={"action": "new"})
        device = TOTPDevice.objects.get()
        assertRedirects(response, reverse("itou_staff_views:otp_confirm_device", args=(device.pk,)))

        # As long as the device isn't confirmed it isn't shown, and we don't create a new one.
        response = client.get(url)
        assert pretty_indented(parse_response_to_soup(response, ".s-section")) == snapshot(name="no_device")

        response = client.post(url, data={"action": "new"})
        device = TOTPDevice.objects.get()  # Still only one
        assertRedirects(response, reverse("itou_staff_views:otp_confirm_device", args=(device.pk,)))

        # When the user already confirmed a device he must first confirm the otp token
        device.name = "Mon appareil"
        device.confirmed = True
        device.save()
        post_data = {
            "name": "Mon appareil",
            "otp_token": TOTP(device.bin_key).token(),
        }
        response = client.post(reverse("login:verify_otp"), data=post_data)
        # The devices page is different
        response = client.get(url)
        assert pretty_indented(
            parse_response_to_soup(
                response,
                ".s-section",
                replace_in_attr=[
                    ("value", f"{device.pk}", "[PK of device]"),
                    ("id", f"delete_{device.pk}_modal", "delete_[PK of device]_modal"),
                    ("data-bs-target", f"#delete_{device.pk}_modal", "#delete_[PK of device]_modal"),
                ],
            )
        ) == snapshot(name="with_device")

        response = client.post(url, data={"action": "new"})
        device = TOTPDevice.objects.exclude(pk=device.pk).get()
        assertRedirects(response, reverse("itou_staff_views:otp_confirm_device", args=(device.pk,)))

    def test_confirm(self, client):
        staff_user = ItouStaffFactory()
        client.force_login(staff_user)

        device = TOTPDevice.objects.create(
            user=staff_user, confirmed=False, key="8fe0a9983c7dddb4acb0146c5507553371e9f211"
        )
        url = reverse("itou_staff_views:otp_confirm_device", args=(device.pk,))
        response = client.get(url)
        assertContains(response, "R7QKTGB4PXO3JLFQCRWFKB2VGNY6T4QR")  # the otp secret matching the hex key

        totp = TOTP(device.bin_key, drift=100)
        post_data = {
            "name": "Mon appareil",
            "otp_token": totp.token(),  # a token from a long time ago
        }
        response = client.post(url, data=post_data)
        assert response.status_code == 200
        assert response.context["form"].errors == {"otp_token": ["Mauvais code OTP"]}
        device.refresh_from_db()
        assert device.confirmed is False

        # there's throttling
        totp = TOTP(device.bin_key)
        post_data["otp_token"] = totp.token()
        response = client.post(url, data=post_data)
        assert response.status_code == 200
        assert response.context["form"].errors == {"otp_token": ["Mauvais code OTP"]}
        device.refresh_from_db()
        assert device.confirmed is False

        # When resetting the failure count
        device.throttling_failure_timestamp = None
        device.throttling_failure_count = 0
        device.save()
        response = client.post(url, data=post_data)
        assertMessages(
            response, [messages.Message(messages.SUCCESS, "Votre nouvel appareil est confirmé", extra_tags="toast")]
        )
        assertRedirects(response, reverse("itou_staff_views:otp_devices"))
        device.refresh_from_db()
        assert device.confirmed is True

    def test_delete_devices(self, client, snapshot, settings):
        settings.REQUIRE_OTP_FOR_STAFF = True
        staff_user = ItouStaffFactory()
        url = reverse("itou_staff_views:otp_devices")

        with freeze_time("2025-03-11 05:18:56") as frozen_time:
            client.force_login(staff_user)

            device_1 = TOTPDevice.objects.create(user=staff_user, confirmed=True, name="bitwarden")
            frozen_time.tick(60)

            device_2 = TOTPDevice.objects.create(user=staff_user, confirmed=True, name="authenticator")
            frozen_time.tick(60)

            # Verify user
            post_data = {
                "name": "Mon appareil",
                "otp_token": TOTP(device_1.bin_key).token(),
            }
            client.post(reverse("login:verify_otp"), data=post_data)

            # List devices
            response = client.get(url)
            assertContains(response, device_1.name)
            assertContains(response, device_2.name)
            assert pretty_indented(
                parse_response_to_soup(
                    response,
                    ".s-section",
                    replace_in_attr=[
                        ("value", f"{device_1.pk}", "[PK of device_1]"),
                        ("id", f"delete_{device_1.pk}_modal", "delete_[PK of device_1]_modal"),
                        ("data-bs-target", f"#delete_{device_1.pk}_modal", "#delete_[PK of device_1]_modal"),
                        ("value", f"{device_2.pk}", "[PK of device_2]"),
                        ("id", f"delete_{device_2.pk}_modal", "delete_[PK of device_2]_modal"),
                        ("data-bs-target", f"#delete_{device_2.pk}_modal", "#delete_[PK of device_2]_modal"),
                    ],
                )
            ) == snapshot(name="with_device")

            # We cannot remove the used device
            response = client.post(url, data={"delete-device": str(device_1.pk)}, follow=True)
            assertQuerySetEqual(TOTPDevice.objects.all(), [device_1, device_2], ordered=False)
            assertMessages(
                response,
                [
                    messages.Message(
                        messages.ERROR, "Impossible de supprimer l’appareil qui a été utilisé pour se connecter."
                    )
                ],
            )

            # The user removes his other device
            response = client.post(url, data={"delete-device": str(device_2.pk)})
            assertQuerySetEqual(TOTPDevice.objects.all(), [device_1])
            assertContains(response, device_1.name)
            assertNotContains(response, device_2.name)
            assertMessages(response, [messages.Message(messages.SUCCESS, "L’appareil a été supprimé.")])
