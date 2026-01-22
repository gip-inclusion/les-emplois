import contextlib
import datetime
import json
import random
import re
import uuid
from operator import attrgetter
from unittest import mock

import freezegun
import pytest
from dateutil.relativedelta import relativedelta
from django.contrib.gis.geos import Point
from django.core.exceptions import ValidationError
from django.core.serializers.json import DjangoJSONEncoder
from django.db import IntegrityError, transaction
from django.test import override_settings
from django.urls import reverse
from django.utils import timezone
from pytest_django.asserts import assertQuerySetEqual, assertRedirects

from itou.approvals.models import Approval
from itou.asp.models import AllocationDuration, Commune, Country, EducationLevel, RSAAllocation
from itou.cities.models import City
from itou.companies.enums import CompanyKind
from itou.users.enums import (
    IdentityCertificationAuthorities,
    IdentityProvider,
    LackOfNIRReason,
    LackOfPoleEmploiId,
    Title,
    UserKind,
)
from itou.users.models import IdentityCertification, JobSeekerProfile, User
from itou.utils import triggers
from itou.utils.mocks.address_format import BAN_GEOCODING_API_RESULTS_MOCK, mock_get_geocoding_data
from itou.utils.urls import get_absolute_url
from tests.approvals.factories import ApprovalFactory
from tests.companies.factories import CompanyFactory
from tests.eligibility.factories import GEIQEligibilityDiagnosisFactory, IAEEligibilityDiagnosisFactory
from tests.job_applications.factories import JobApplicationFactory
from tests.prescribers.factories import (
    PrescriberMembershipFactory,
    PrescriberOrganizationFactory,
)
from tests.users.factories import (
    DEFAULT_PASSWORD,
    EmployerFactory,
    ItouStaffFactory,
    JobSeekerFactory,
    JobSeekerProfileFactory,
    LaborInspectorFactory,
    PrescriberFactory,
    UserFactory,
)
from tests.utils.testing import normalize_fields_history


class TestManager:
    def test_get_duplicated_pole_emploi_ids(self):
        # Unique user.
        JobSeekerFactory(jobseeker_profile__pole_emploi_id="5555555A")

        # 2 users using the same `pole_emploi_id`.
        JobSeekerFactory(jobseeker_profile__pole_emploi_id="6666666B")
        JobSeekerFactory(jobseeker_profile__pole_emploi_id="6666666B")

        # 3 users using the same `pole_emploi_id`.
        JobSeekerFactory(jobseeker_profile__pole_emploi_id="7777777C")
        JobSeekerFactory(jobseeker_profile__pole_emploi_id="7777777C")
        JobSeekerFactory(jobseeker_profile__pole_emploi_id="7777777C")

        duplicated_pole_emploi_ids = User.objects.get_duplicated_pole_emploi_ids()

        expected_result = ["6666666B", "7777777C"]
        assertQuerySetEqual(duplicated_pole_emploi_ids, expected_result, ordered=False)

    def test_get_duplicates_by_pole_emploi_id(self):
        # 2 users using the same `pole_emploi_id` and different birthdates.
        JobSeekerFactory(
            jobseeker_profile__pole_emploi_id="6666666B", jobseeker_profile__birthdate=datetime.date(1988, 2, 2)
        )
        JobSeekerFactory(
            jobseeker_profile__pole_emploi_id="6666666B", jobseeker_profile__birthdate=datetime.date(2001, 12, 12)
        )

        # 2 users using the same `pole_emploi_id` and the same birthdates.
        user1 = JobSeekerFactory(
            jobseeker_profile__pole_emploi_id="7777777B", jobseeker_profile__birthdate=datetime.date(1988, 2, 2)
        )
        user2 = JobSeekerFactory(
            jobseeker_profile__pole_emploi_id="7777777B", jobseeker_profile__birthdate=datetime.date(1988, 2, 2)
        )

        # 3 users using the same `pole_emploi_id` and the same birthdates.
        user3 = JobSeekerFactory(
            jobseeker_profile__pole_emploi_id="8888888C", jobseeker_profile__birthdate=datetime.date(2002, 12, 12)
        )
        user4 = JobSeekerFactory(
            jobseeker_profile__pole_emploi_id="8888888C", jobseeker_profile__birthdate=datetime.date(2002, 12, 12)
        )
        user5 = JobSeekerFactory(
            jobseeker_profile__pole_emploi_id="8888888C", jobseeker_profile__birthdate=datetime.date(2002, 12, 12)
        )
        # + 1 user using the same `pole_emploi_id` but a different birthdate.
        JobSeekerFactory(
            jobseeker_profile__pole_emploi_id="8888888C", jobseeker_profile__birthdate=datetime.date(1978, 12, 20)
        )

        duplicated_users = User.objects.get_duplicates_by_pole_emploi_id()
        # sort sub lists in result
        for key in duplicated_users.keys():
            duplicated_users[key] = sorted(duplicated_users[key], key=attrgetter("pk"))

        expected_result = {
            "7777777B": [user1, user2],
            "8888888C": [user3, user4, user5],
        }
        assert duplicated_users == expected_result

    def test_search_by_full_name(self):
        user_1 = JobSeekerFactory(first_name="Jean-Paul", last_name="II")
        JobSeekerFactory(first_name="Jean-Michel", last_name="Relou")

        assert User.objects.search_by_full_name("Jean").count() == 2
        assert User.objects.search_by_full_name("Jean II").get() == user_1

    def test_linked_job_seeker_ids(self):
        organization = PrescriberOrganizationFactory()
        other_organization = PrescriberOrganizationFactory()
        prescriber = PrescriberMembershipFactory(organization=organization).user

        # From the prescriber as a member of no organization
        job_seeker_created_by_user_no_organization = JobSeekerFactory(created_by=prescriber)
        job_seeker_with_sent_job_app_no_organization = JobApplicationFactory(sender=prescriber).job_seeker
        # It's not possible to make a eligibility diagnosis with no organization

        # From the prescriber as a member of the organization
        job_seeker_created_by_user_in_organization = JobSeekerFactory(
            created_by=prescriber,
            jobseeker_profile__created_by_prescriber_organization=organization,
        )
        job_seeker_with_sent_job_app_in_organization = JobApplicationFactory(
            sender=prescriber,
            sender_prescriber_organization=organization,
        ).job_seeker
        job_seeker_with_authored_iae_diagnosis_in_organization = IAEEligibilityDiagnosisFactory(
            author=prescriber,
            author_prescriber_organization=organization,
            from_prescriber=True,
        ).job_seeker
        job_seeker_with_authored_geiq_diagnosis_in_organization = GEIQEligibilityDiagnosisFactory(
            author=prescriber,
            author_prescriber_organization=organization,
            from_prescriber=True,
        ).job_seeker

        # From the prescriber as a member of another organization. We won't display those
        JobSeekerFactory(
            created_by=prescriber,
            jobseeker_profile__created_by_prescriber_organization=other_organization,
        )
        JobApplicationFactory(
            sender=prescriber,
            sender_prescriber_organization=other_organization,
        )
        IAEEligibilityDiagnosisFactory(
            author=prescriber,
            author_prescriber_organization=other_organization,
            from_prescriber=True,
        )
        GEIQEligibilityDiagnosisFactory(
            author=prescriber,
            author_prescriber_organization=other_organization,
            from_prescriber=True,
        )

        job_seeker_created_by_organization_coworker = JobSeekerFactory(
            jobseeker_profile__created_by_prescriber_organization=organization
        )
        job_seeker_with_job_app_sent_by_organization_coworker = JobApplicationFactory(
            sender_prescriber_organization=organization,
        ).job_seeker
        job_seeker_with_iae_diagnosis_authored_by_organization_coworker = IAEEligibilityDiagnosisFactory(
            author_prescriber_organization=organization,
            author=PrescriberMembershipFactory(organization=organization).user,
            from_prescriber=True,
        ).job_seeker
        job_seeker_with_geiq_diagnosis_authored_by_organization_coworker = GEIQEligibilityDiagnosisFactory(
            author_prescriber_organization=organization,
            author=PrescriberMembershipFactory(organization=organization).user,
            from_prescriber=True,
        ).job_seeker

        assertQuerySetEqual(
            User.objects.linked_job_seeker_ids(prescriber, organization=None),
            [
                job_seeker_created_by_user_no_organization.pk,
                job_seeker_with_sent_job_app_no_organization.pk,
            ],
            ordered=False,
        )

        # NB: Nothing changes as there's no organization
        assertQuerySetEqual(
            User.objects.linked_job_seeker_ids(prescriber, organization=None, from_all_coworkers=True),
            [
                job_seeker_created_by_user_no_organization.pk,
                job_seeker_with_sent_job_app_no_organization.pk,
            ],
            ordered=False,
        )

        assertQuerySetEqual(
            User.objects.linked_job_seeker_ids(prescriber, organization=organization),
            [
                job_seeker_created_by_user_no_organization.pk,
                job_seeker_with_sent_job_app_no_organization.pk,
                job_seeker_created_by_user_in_organization.pk,
                job_seeker_with_sent_job_app_in_organization.pk,
                job_seeker_with_authored_iae_diagnosis_in_organization.pk,
                job_seeker_with_authored_geiq_diagnosis_in_organization.pk,
            ],
            ordered=False,
        )

        assertQuerySetEqual(
            User.objects.linked_job_seeker_ids(prescriber, organization=organization, from_all_coworkers=True),
            [
                job_seeker_created_by_user_no_organization.pk,
                job_seeker_with_sent_job_app_no_organization.pk,
                job_seeker_created_by_user_in_organization.pk,
                job_seeker_with_sent_job_app_in_organization.pk,
                job_seeker_with_authored_iae_diagnosis_in_organization.pk,
                job_seeker_with_authored_geiq_diagnosis_in_organization.pk,
                job_seeker_created_by_organization_coworker.pk,
                job_seeker_with_job_app_sent_by_organization_coworker.pk,
                job_seeker_with_iae_diagnosis_authored_by_organization_coworker.pk,
                job_seeker_with_geiq_diagnosis_authored_by_organization_coworker.pk,
            ],
            ordered=False,
        )


class TestModel:
    def test_generate_unique_username(self):
        unique_username = User.generate_unique_username()
        assert unique_username == uuid.UUID(unique_username, version=4).hex

    def test_create_job_seeker_by_proxy(self, client, snapshot):
        proxy_user = PrescriberFactory(for_snapshot=True)

        sent_emails = []

        def mock_send_email(self, **kwargs):
            sent_emails.append(self)

        user_data = {
            "email": "john@doe.com",
            "title": "M",
            "first_name": "John",
            "last_name": "Doe",
            "phone": "0610101010",
        }
        with mock.patch("django.core.mail.EmailMessage.send", mock_send_email):
            user = User.create_job_seeker_by_proxy(
                proxy_user, acting_organization=PrescriberOrganizationFactory(for_snapshot=True), **user_data
            )

        assert user.kind == UserKind.JOB_SEEKER
        assert user.password is not None
        assert user.username is not None

        assert user.username == uuid.UUID(user.username, version=4).hex
        assert user.email == user_data["email"]
        assert user.first_name == user_data["first_name"]
        assert user.last_name == user_data["last_name"]
        assert user.phone == user_data["phone"]
        assert user.created_by == proxy_user
        assert user.last_login is None

        # An email is sent to the new user
        assert len(sent_emails) == 1
        assert sent_emails[0].to == [user.email]
        assert sent_emails[0].subject == "[TEST] Création de votre compte candidat"

        # Get the token from the email for testing
        reset_url = get_absolute_url(
            reverse(
                "account_reset_password_from_key",
                kwargs={"uidb36": "1", "key": "key"},
            )
        )
        # http://localhost:8000/accounts/password/reset/key/([A-Za-z0-9]+(-[A-Za-z0-9]+)+)/
        pattern = re.sub("1-key/", r"([A-Za-z0-9]+(-[A-Za-z0-9]+)+)/", reset_url)
        password_change_url = re.search(pattern, sent_emails[0].body)[0]

        # Test the email content is valid
        assert re.sub(pattern, "[RESET PASSWORD LINK REMOVED]", sent_emails[0].body) == snapshot(
            name="email jobseeker created by proxy"
        )

        # Test the link can be used to reset password and login directly
        response = client.get(password_change_url)
        password_change_url_with_hidden_key = response.url
        post_data = {"password1": DEFAULT_PASSWORD, "password2": DEFAULT_PASSWORD}
        response = client.post(password_change_url_with_hidden_key, data=post_data)
        assertRedirects(response, reverse("welcoming_tour:index"))
        assert user.has_verified_email
        client.logout()

        # E-mail already exists, this should raise an error.
        with pytest.raises(ValidationError):
            User.create_job_seeker_by_proxy(proxy_user, **user_data)

    def test_clean_pole_emploi_fields(self):
        # Both fields cannot be empty.
        job_seeker = JobSeekerFactory(
            jobseeker_profile__pole_emploi_id="", jobseeker_profile__lack_of_pole_emploi_id_reason=""
        )
        cleaned_data = {
            "pole_emploi_id": job_seeker.jobseeker_profile.pole_emploi_id,
            "lack_of_pole_emploi_id_reason": job_seeker.jobseeker_profile.lack_of_pole_emploi_id_reason,
        }
        with pytest.raises(ValidationError):
            JobSeekerProfile.clean_pole_emploi_fields(cleaned_data)

        # If both fields are present at the same time, `pole_emploi_id` takes precedence.
        job_seeker = JobSeekerFactory(
            jobseeker_profile__pole_emploi_id="69970749",
            jobseeker_profile__lack_of_pole_emploi_id_reason=LackOfPoleEmploiId.REASON_FORGOTTEN,
        )
        cleaned_data = {
            "pole_emploi_id": job_seeker.jobseeker_profile.pole_emploi_id,
            "lack_of_pole_emploi_id_reason": job_seeker.jobseeker_profile.lack_of_pole_emploi_id_reason,
        }
        JobSeekerProfile.clean_pole_emploi_fields(cleaned_data)
        assert cleaned_data["pole_emploi_id"] == job_seeker.jobseeker_profile.pole_emploi_id
        assert cleaned_data["lack_of_pole_emploi_id_reason"] == ""

        # No exception should be raised for the following cases.

        job_seeker = JobSeekerFactory(
            jobseeker_profile__pole_emploi_id="62723349", jobseeker_profile__lack_of_pole_emploi_id_reason=""
        )
        cleaned_data = {
            "pole_emploi_id": job_seeker.jobseeker_profile.pole_emploi_id,
            "lack_of_pole_emploi_id_reason": job_seeker.jobseeker_profile.lack_of_pole_emploi_id_reason,
        }
        JobSeekerProfile.clean_pole_emploi_fields(cleaned_data)

        job_seeker = JobSeekerFactory(
            jobseeker_profile__pole_emploi_id="",
            jobseeker_profile__lack_of_pole_emploi_id_reason=LackOfPoleEmploiId.REASON_FORGOTTEN,
        )
        cleaned_data = {
            "pole_emploi_id": job_seeker.jobseeker_profile.pole_emploi_id,
            "lack_of_pole_emploi_id_reason": job_seeker.jobseeker_profile.lack_of_pole_emploi_id_reason,
        }
        JobSeekerProfile.clean_pole_emploi_fields(cleaned_data)

    def test_email_already_exists(self):
        JobSeekerFactory(email="foo@bar.com")
        assert User.email_already_exists("foo@bar.com")
        assert User.email_already_exists("FOO@bar.com")

    def test_save_for_unique_email_on_create_and_update(self):
        """
        Ensure `email` is unique when using the save() method for creating or updating a User instance.
        """

        email = "juste@leblanc.com"
        JobSeekerFactory(email=email)

        # Creating a user with an existing email should raise an error.
        with pytest.raises(ValidationError):
            JobSeekerFactory(email=email)

        # Updating a user with an existing email should raise an error.
        user = JobSeekerFactory(email="francois@pignon.com")
        user.email = email
        with pytest.raises(ValidationError):
            user.save()

        # Make sure it's case insensitive.
        email = email.title()
        with pytest.raises(ValidationError):
            JobSeekerFactory(email=email)

    def test_is_handled_by_proxy(self):
        job_seeker = JobSeekerFactory()
        assert not job_seeker.is_handled_by_proxy

        prescriber = PrescriberFactory()
        job_seeker = JobSeekerFactory(created_by=prescriber)
        assert job_seeker.is_handled_by_proxy

        # Job seeker activates his account. He is in control now!
        job_seeker.last_login = timezone.now()
        assert not job_seeker.is_handled_by_proxy

    def test_has_sso_provider(self):
        user = JobSeekerFactory()
        assert not user.has_sso_provider

        user = JobSeekerFactory(identity_provider=IdentityProvider.DJANGO)
        assert not user.has_sso_provider

        user = JobSeekerFactory(identity_provider=IdentityProvider.FRANCE_CONNECT)
        assert user.has_sso_provider

        user = JobSeekerFactory(identity_provider=IdentityProvider.PE_CONNECT)
        assert user.has_sso_provider

        user = PrescriberFactory()
        assert user.has_sso_provider

        user = PrescriberFactory(identity_provider=IdentityProvider.PRO_CONNECT)
        assert user.has_sso_provider

    def test_update_external_data_source_history_field(self):
        user = PrescriberFactory()
        assert not user.external_data_source_history

        provider = IdentityProvider.FRANCE_CONNECT
        now = timezone.now()
        # Because external_data_source_history is a JSONField
        # dates are actually stored as strings in the database
        now_str = json.loads(DjangoJSONEncoder().encode(now))
        with mock.patch("django.utils.timezone.now", return_value=now):
            has_performed_update = user.update_external_data_source_history_field(
                provider=provider, field="first_name", value="Lola"
            )
        user.save()
        user.refresh_from_db()  # Retrieve object as stored in DB to get raw JSON values and avoid surprises.
        assert has_performed_update
        assert user.external_data_source_history == [
            {
                "field_name": "first_name",
                "value": "Lola",
                "source": provider.value,
                "created_at": now_str,
            }
        ]

        # Update history.
        with mock.patch("django.utils.timezone.now", return_value=now):
            has_performed_update = user.update_external_data_source_history_field(
                provider=provider, field="first_name", value="Jeanne"
            )
        user.save()
        user.refresh_from_db()
        assert has_performed_update
        assert user.external_data_source_history == [
            {
                "field_name": "first_name",
                "value": "Lola",
                "source": provider.value,
                "created_at": now_str,
            },
            {
                "field_name": "first_name",
                "value": "Jeanne",
                "source": provider.value,
                "created_at": now_str,
            },
        ]

        # Don't update the history if value is the same.
        has_performed_update = user.update_external_data_source_history_field(
            provider=provider, field="first_name", value="Jeanne"
        )
        user.save()
        user.refresh_from_db()
        assert not has_performed_update
        # NB: created_at would have changed if has_performed_update had been True since we did not use mock.patch \
        assert user.external_data_source_history == [
            {
                "field_name": "first_name",
                "value": "Lola",
                "source": provider.value,
                "created_at": now_str,
            },
            {
                "field_name": "first_name",
                "value": "Jeanne",
                "source": provider.value,
                "created_at": now_str,
            },
        ]

        # Allow storing empty values.
        with mock.patch("django.utils.timezone.now", return_value=now):
            has_performed_update = user.update_external_data_source_history_field(
                provider=provider, field="last_name", value=""
            )
        user.save()
        user.refresh_from_db()
        assert has_performed_update
        assert user.external_data_source_history == [
            {
                "field_name": "first_name",
                "value": "Lola",
                "source": provider.value,
                "created_at": now_str,
            },
            {
                "field_name": "first_name",
                "value": "Jeanne",
                "source": provider.value,
                "created_at": now_str,
            },
            {
                "field_name": "last_name",
                "value": "",
                "source": provider.value,
                "created_at": now_str,
            },
        ]

        # Allow replacing empty values.
        with mock.patch("django.utils.timezone.now", return_value=now):
            has_performed_update = user.update_external_data_source_history_field(
                provider=provider, field="last_name", value="Trombignard"
            )
        user.save()
        user.refresh_from_db()
        assert has_performed_update
        assert user.external_data_source_history == [
            {
                "field_name": "first_name",
                "value": "Lola",
                "source": provider.value,
                "created_at": now_str,
            },
            {
                "field_name": "first_name",
                "value": "Jeanne",
                "source": provider.value,
                "created_at": now_str,
            },
            {
                "field_name": "last_name",
                "value": "",
                "source": provider.value,
                "created_at": now_str,
            },
            {
                "field_name": "last_name",
                "value": "Trombignard",
                "source": provider.value,
                "created_at": now_str,
            },
        ]

    def test_can_edit_email(self):
        user = PrescriberFactory()
        job_seeker = JobSeekerFactory()

        # Same user.
        assert not user.can_edit_email(user)

        # All conditions are met.
        job_seeker = JobSeekerFactory(created_by=user)
        assert user.can_edit_email(job_seeker)

        # Job seeker logged in, he is not longer handled by a proxy.
        job_seeker = JobSeekerFactory(last_login=timezone.now())
        assert not user.can_edit_email(job_seeker)

        # User did not create the job seeker's account.
        job_seeker = JobSeekerFactory(created_by=PrescriberFactory())
        assert not user.can_edit_email(job_seeker)

        # Job seeker has verified his email.
        job_seeker = JobSeekerFactory(created_by=user, with_verified_email=True)
        assert not user.can_edit_email(job_seeker)

    @pytest.mark.parametrize("email", ["user@example.com", None])
    @pytest.mark.parametrize("upcoming_deletion_notified", [True, False])
    @pytest.mark.parametrize("has_sso_provider", [True, False])
    @pytest.mark.parametrize("username", ["a-username", ""])
    @pytest.mark.parametrize("is_active", [True, False])
    @pytest.mark.parametrize("kind", UserKind)
    @pytest.mark.no_django_db
    def test_can_be_reactivated(self, kind, is_active, username, has_sso_provider, upcoming_deletion_notified, email):
        # Local override when some cases are not possible
        has_sso_provider = has_sso_provider if kind != UserKind.LABOR_INSPECTOR else False  # No SSO available

        # Build the user
        factory_kwargs = {
            "is_active": is_active,
            "username": username,
            "email": email,
            "upcoming_deletion_notified_at": timezone.now() if upcoming_deletion_notified else None,
        }
        factory_kwargs |= {"identity_provider": IdentityProvider.DJANGO} if not has_sso_provider else {}
        user = {
            UserKind.JOB_SEEKER: JobSeekerFactory,
            UserKind.PRESCRIBER: PrescriberFactory,
            UserKind.EMPLOYER: EmployerFactory,
            UserKind.LABOR_INSPECTOR: LaborInspectorFactory,
            UserKind.ITOU_STAFF: ItouStaffFactory,
        }[kind].build(**factory_kwargs)

        assert user.can_be_reactivated() is all(
            [
                kind in UserKind.professionals(),
                not is_active,
                username,
                has_sso_provider,
                upcoming_deletion_notified,
                not email,
            ]
        )

    def test_is_account_creator(self):
        user = PrescriberFactory()

        job_seeker = JobSeekerFactory(created_by=user)
        assert job_seeker.is_created_by(user)

        job_seeker = JobSeekerFactory()
        assert not job_seeker.is_created_by(user)

        job_seeker = JobSeekerFactory(created_by=PrescriberFactory())
        assert not job_seeker.is_created_by(user)

    def test_has_verified_email(self):
        user = JobSeekerFactory()

        assert not user.has_verified_email
        address = user.emailaddress_set.create(email=user.email, verified=False)
        del user.has_verified_email
        assert not user.has_verified_email
        address.delete()

        user.emailaddress_set.create(email=user.email, verified=True)
        del user.has_verified_email
        assert user.has_verified_email

    def test_user_kind(self):
        non_staff_kinds = [
            UserKind.JOB_SEEKER,
            UserKind.PRESCRIBER,
            UserKind.EMPLOYER,
            UserKind.LABOR_INSPECTOR,
        ]

        for kind in non_staff_kinds:
            user = UserFactory(kind=kind, is_staff=True)
            assert not user.is_staff
        user = UserFactory(kind=UserKind.ITOU_STAFF, is_staff=False)
        assert user.is_staff

    def test_get_kind_display(self):
        job_seeker = JobSeekerFactory()
        assert "candidat" == job_seeker.get_kind_display()

        prescriber = PrescriberFactory()
        assert "prescripteur" == prescriber.get_kind_display()

        employer = EmployerFactory()
        assert "employeur" == employer.get_kind_display()

        labor_inspector = LaborInspectorFactory()
        assert "inspecteur du travail" == labor_inspector.get_kind_display()

    def test_constraint_user_lack_of_nir_reason_or_nir(self):
        no_nir_profile = JobSeekerProfileFactory(nir="")
        # This works
        assert no_nir_profile.nir == ""
        no_nir_profile.lack_of_nir_reason = LackOfNIRReason.NO_NIR
        no_nir_profile.save()

        nir_profile = JobSeekerProfileFactory()
        # This doesn't
        assert nir_profile.nir
        nir_profile.lack_of_nir_reason = LackOfNIRReason.NO_NIR
        with pytest.raises(
            ValidationError,
            match="Un utilisateur ayant un NIR ne peut avoir un motif justifiant l'absence de son NIR.",
        ):
            nir_profile.save()

    def test_identity_provider_vs_kind(self, subtests):
        cases = [
            [JobSeekerFactory, IdentityProvider.DJANGO, False],
            [JobSeekerFactory, IdentityProvider.PE_CONNECT, False],
            [JobSeekerFactory, IdentityProvider.FRANCE_CONNECT, False],
            [JobSeekerFactory, IdentityProvider.INCLUSION_CONNECT, True],
            [PrescriberFactory, IdentityProvider.DJANGO, False],
            [PrescriberFactory, IdentityProvider.PE_CONNECT, True],
            [PrescriberFactory, IdentityProvider.FRANCE_CONNECT, True],
            [PrescriberFactory, IdentityProvider.INCLUSION_CONNECT, False],
            [EmployerFactory, IdentityProvider.DJANGO, False],
            [EmployerFactory, IdentityProvider.PE_CONNECT, True],
            [EmployerFactory, IdentityProvider.FRANCE_CONNECT, True],
            [EmployerFactory, IdentityProvider.INCLUSION_CONNECT, False],
            [LaborInspectorFactory, IdentityProvider.DJANGO, False],
            [LaborInspectorFactory, IdentityProvider.PE_CONNECT, True],
            [LaborInspectorFactory, IdentityProvider.FRANCE_CONNECT, True],
            [LaborInspectorFactory, IdentityProvider.INCLUSION_CONNECT, True],
            [ItouStaffFactory, IdentityProvider.DJANGO, False],
            [ItouStaffFactory, IdentityProvider.PE_CONNECT, True],
            [ItouStaffFactory, IdentityProvider.FRANCE_CONNECT, True],
            [ItouStaffFactory, IdentityProvider.INCLUSION_CONNECT, True],
        ]
        for factory, identity_provider, raises in cases:
            with subtests.test(f"{factory} / {identity_provider}"):
                if raises:
                    with pytest.raises(ValidationError):
                        factory(identity_provider=identity_provider)
                else:
                    factory(identity_provider=identity_provider)

    def test_get_full_name(self):
        assert JobSeekerFactory(first_name="CLÉMENT", last_name="Dupont").get_full_name() == "Clément DUPONT"
        assert (
            JobSeekerFactory(first_name="JEAN-FRANÇOIS", last_name="de Saint Exupéry").get_full_name()
            == "Jean-François DE SAINT EXUPÉRY"
        )
        assert (
            JobSeekerFactory(first_name=" marie aurore", last_name="maréchal").get_full_name()
            == "Marie Aurore MARÉCHAL"
        )

    @pytest.mark.parametrize(
        "first_name,last_name,expected",
        [
            ("Johan Sebastian", "Bach", "J***n S*******n B**h"),
            ("Max", "Weber", "M** W***r"),
            ("Charlemagne", "", "C*********e"),
            ("Salvador Felipe Jacinto", "Dalí y Domenech", "S******r F****e J*****o D**í Y D******h"),
            ("Harald", "Blue-tooth", "H****d B********h"),
            ("Llanfairpwllgwyngyllgogerychwyrndrobwllllantysiliogogogoch", "", "L**********h"),
            ("Max", "", "M**"),
            ("", "", ""),
        ],
    )
    def test_get_redacted_full_name(self, first_name, last_name, expected):
        user = JobSeekerFactory(first_name=first_name, last_name=last_name)
        assert user.get_redacted_full_name() == expected

    @pytest.mark.parametrize(
        "first_name,last_name,expected",
        [
            ("Johan Sebastian", "Bach", "Johan Sebastian B."),
            ("Max", "Weber", "Max W."),
            ("Charlemagne", "", "Charlemagne"),
            ("Salvador Felipe Jacinto", "Dalí y Domenech", "Salvador Felipe Jacinto D."),
            ("Harald", "Blue-tooth", "Harald B."),
            ("", "", ""),
            ("", "Dalí", ""),
        ],
    )
    def test_get_truncated_full_name(self, first_name, last_name, expected):
        user = JobSeekerFactory(first_name=first_name, last_name=last_name)
        assert user.get_truncated_full_name() == expected


class TestJobSeekerProfileModel:
    def setup_method(self):
        self.user = JobSeekerFactory(
            with_address=True,
            address_line_1=BAN_GEOCODING_API_RESULTS_MOCK[0]["address_line_1"],
            jobseeker_profile__education_level=random.choice(EducationLevel.values),
            jobseeker_profile__pole_emploi_since=AllocationDuration.MORE_THAN_24_MONTHS,
        )
        self.profile = self.user.jobseeker_profile

    def test_job_seeker_details(self):
        self.user.title = None
        with pytest.raises(ValidationError):
            self.profile.clean_model()

        self.profile.user.title = Title.M

        # Won't raise exception
        self.profile.clean_model()

    @mock.patch(
        "itou.common_apps.address.format.get_geocoding_data",
        side_effect=mock_get_geocoding_data,
    )
    def test_update_hexa_address(self, _mock):
        """
        Check creation of an HEXA address from job seeker address
        """
        self.profile.user.title = Title.M
        self.profile.update_hexa_address()
        self.profile.clean_model()

    @mock.patch(
        "itou.common_apps.address.format.get_geocoding_data",
        side_effect=mock_get_geocoding_data,
    )
    def test_job_seeker_hexa_address_complete(self, _mock):
        # Nothing to validate if no address is given
        self.profile._clean_job_seeker_hexa_address()

        # If any field of the hexa address is filled
        # the whole address must be valid
        self.profile.hexa_lane_name = "Privet Drive"
        with pytest.raises(ValidationError):
            self.profile._clean_job_seeker_hexa_address()

        self.profile.hexa_lane_number = "4"
        with pytest.raises(ValidationError):
            self.profile._clean_job_seeker_hexa_address()

        self.profile.hexa_lane_type = "RUE"
        with pytest.raises(ValidationError):
            self.profile._clean_job_seeker_hexa_address()

        self.profile.hexa_post_code = "12345"
        with pytest.raises(ValidationError):
            self.profile._clean_job_seeker_hexa_address()

        # address should be complete now
        self.profile.hexa_commune = Commune.objects.order_by("?").first()
        self.profile._clean_job_seeker_hexa_address()

    @mock.patch(
        "itou.common_apps.address.format.get_geocoding_data",
        side_effect=mock_get_geocoding_data,
    )
    def test_job_seeker_hexa_address_with_unknown_lane_type(self, _mock):
        self.profile._clean_job_seeker_hexa_address()
        user = self.profile.user
        user.address_line_1 = "8 la boutrie - caillot"
        user.address_line_2 = "saint hilaire de loulay"
        user.post_code = "85600"
        self.profile.update_hexa_address()

        # undefined lane type should fallback to "Lieu-Dit" (LD) as lane type
        assert "LD" == self.profile.hexa_lane_type

    @mock.patch("itou.common_apps.address.format.get_geocoding_data")
    def test_job_seeker_hexa_address_with_not_referenced_insee_code(self, get_geocoding_data_mock):
        get_geocoding_data_mock.return_value = {
            "additional_address": "",
            "city": "Paris",
            "insee_code": "75056",
            "lane": "Paris",
            "lane_type": "LD",
            "non_std_extension": "",
            "number": "",
            "post_code": "75001",
        }
        with pytest.raises(ValidationError, match="Le code INSEE 75056 n'est pas référencé par l'ASP"):
            self.profile.update_hexa_address()

    @mock.patch("itou.common_apps.address.format.get_geocoding_data")
    def test_job_seeker_hexa_address_when_the_ban_does_not_return_a_postal_code(self, get_geocoding_data_mock):
        City.objects.create(
            name="Saint-Martin",
            slug="saint-martin-978",
            department="978",
            coords=Point(-63.0619, 18.0859),
            post_codes=["97150"],
            code_insee="97801",
        )

        get_geocoding_data_mock.return_value = {
            "additional_address": "",
            "city": "Saint-Martin",
            "insee_code": "97801",
            "lane": "Queen Parrot Fish",
            "lane_type": "IMP",
            "non_std_extension": "",
            "number": "",
            "post_code": None,
        }
        self.profile.update_hexa_address()
        self.profile.refresh_from_db()
        assert self.profile.hexa_post_code == "97150"

    def test_job_seeker_details_complete(self):
        self.profile.user.title = None

        # No user title provided
        with pytest.raises(ValidationError):
            self.profile._clean_job_seeker_details()

        self.profile.user.title = Title.M

        # No education level provided
        self.profile.education_level = None
        with pytest.raises(ValidationError):
            self.profile._clean_job_seeker_details()

        self.profile.education_level = "00"
        self.profile._clean_job_seeker_details()

        # Birth place / birth country are checked in User tests

    def test_job_seeker_previous_employer(self):
        """
        Check coherence of the `is_employed` field,
        and a fix about unchecked / badly checkedfield on ASP process side (`salarieEnEmploi`)
        """
        # Needed for model validation
        self.profile.user.title = Title.M
        self.profile.education_level = "00"

        self.profile.unemployed_since = AllocationDuration.MORE_THAN_24_MONTHS
        assert not self.profile.is_employed

        self.profile.unemployed_since = None
        assert self.profile.is_employed

    @pytest.mark.parametrize(
        "factory_kwargs",
        [
            {"born_in_france": True, "jobseeker_profile__birth_place": None},
            {"born_outside_france": True, "with_birth_place": True},
            {"jobseeker_profile__birth_country": None, "with_birth_place": True},
        ],
    )
    @pytest.mark.usefixtures("trigger_context")
    def test_valid_birth_place_and_country_constraint(self, factory_kwargs):
        profile = JobSeekerFactory().jobseeker_profile
        profile_values = JobSeekerFactory.build(**factory_kwargs).jobseeker_profile
        with pytest.raises(
            IntegrityError,
            match='new row for relation ".*" violates check constraint "jobseekerprofile_birth_country_and_place"',
        ):
            # Use update query to bypass model validation
            JobSeekerProfile.objects.filter(pk=profile.pk).update(
                birth_place=profile_values.birth_place,
                birth_country=profile_values.birth_country,
            )

    @pytest.mark.parametrize(
        "factory_kwargs, expect_error",
        [
            ({"has_rsa_allocation": "", "rsa_allocation_since": ""}, False),
            (
                {
                    "has_rsa_allocation": RSAAllocation.YES_WITHOUT_MARKUP,
                    "rsa_allocation_since": AllocationDuration.LESS_THAN_6_MONTHS,
                },
                False,
            ),
            (
                {
                    "has_rsa_allocation": RSAAllocation.NO,
                    "rsa_allocation_since": "",
                },
                False,
            ),
            (
                {
                    "has_rsa_allocation": RSAAllocation.YES_WITHOUT_MARKUP,
                    "rsa_allocation_since": "",
                },
                True,
            ),
            (
                {
                    "has_rsa_allocation": RSAAllocation.NO,
                    "rsa_allocation_since": AllocationDuration.MORE_THAN_24_MONTHS,
                },
                True,
            ),
            (
                {
                    "has_rsa_allocation": "",
                    "rsa_allocation_since": AllocationDuration.FROM_12_TO_23_MONTHS,
                },
                True,
            ),
        ],
    )
    def test_rsa_constraint(self, factory_kwargs, expect_error):
        ctxt = (
            pytest.raises(
                IntegrityError,
                match=(
                    'new row for relation ".*" violates check constraint "jobseekerprofile_rsa_allocation_consistency"'
                ),
            )
            if expect_error
            else contextlib.nullcontext()
        )
        profile = JobSeekerProfileFactory()
        with ctxt:
            JobSeekerProfile.objects.filter(pk=profile.pk).update(**factory_kwargs)


def user_with_approval_in_waiting_period():
    user = JobSeekerFactory()
    end_at = timezone.localdate() - relativedelta(days=30)
    start_at = end_at - datetime.timedelta(days=Approval.DEFAULT_APPROVAL_DAYS)
    # diagnosis.created_at is a datetime, approval.start_at is a date
    diagnosis_created_at = timezone.now() - datetime.timedelta(days=Approval.DEFAULT_APPROVAL_DAYS)
    approval = ApprovalFactory(
        user=user,
        start_at=start_at,
        end_at=end_at,
        eligibility_diagnosis__created_at=diagnosis_created_at,
    )
    assert approval.is_in_waiting_period
    assert not approval.eligibility_diagnosis.is_valid
    return user


class TestLatestApproval:
    def test_status_without_approval(self):
        user = JobSeekerFactory()
        assert not user.has_valid_approval
        assert not user.has_latest_approval_in_waiting_period
        assert user.latest_approval is None

    def test_status_with_valid_approval(self):
        user = JobSeekerFactory()
        approval = ApprovalFactory(user=user, start_at=timezone.localdate() - relativedelta(days=1))
        assert user.has_valid_approval
        assert not user.has_latest_approval_in_waiting_period
        assert user.latest_approval == approval

    def test_status_approval_in_waiting_period(self):
        user = user_with_approval_in_waiting_period()
        assert not user.has_valid_approval
        assert user.has_latest_approval_in_waiting_period
        assert user.latest_approval == user.latest_approval

    def test_status_approval_with_elapsed_waiting_period(self):
        user = JobSeekerFactory()
        end_at = timezone.localdate() - relativedelta(years=3)
        start_at = end_at - relativedelta(years=2)
        ApprovalFactory(user=user, start_at=start_at, end_at=end_at)
        assert not user.has_valid_approval
        assert not user.has_latest_approval_in_waiting_period
        assert user.latest_approval is None

    def test_new_approval_blocked_by_waiting_period(self):
        user = user_with_approval_in_waiting_period()

        # note (fv):
        # I had some doubts about the validity and/or the comments of some tests below.
        # After a quick meeting, comments and tests are now aligned with business expectations.
        # One point was not correctly tested: the absence of a *valid* eligibility diagnosis
        # made by an authorized prescriber in the waiting period.
        # If such a diagnosis exists when approval is in waiting period, it *can't* be renewed.
        # However, SIAE can still approve job applications for the job seeker
        # without an approval in this specific case.
        # => aligned with code

        # Waiting period cannot be bypassed for SIAE if no prescriber
        # and there is no valid eligibility diagnosis this in period
        assert user.new_approval_blocked_by_waiting_period(
            siae=CompanyFactory(kind=CompanyKind.ETTI), sender_prescriber_organization=None
        )

        # Waiting period cannot be bypassed for SIAE if unauthorized prescriber
        # and there is no valid eligibility diagnosis this in period
        assert user.new_approval_blocked_by_waiting_period(
            siae=CompanyFactory(kind=CompanyKind.ETTI),
            sender_prescriber_organization=PrescriberOrganizationFactory(),
        )

        # Waiting period is bypassed for SIAE if authorized prescriber.
        assert not user.new_approval_blocked_by_waiting_period(
            siae=CompanyFactory(kind=CompanyKind.ETTI),
            sender_prescriber_organization=PrescriberOrganizationFactory(authorized=True),
        )

        # Waiting period is bypassed for GEIQ even if no prescriber.
        assert not user.new_approval_blocked_by_waiting_period(
            siae=CompanyFactory(kind=CompanyKind.GEIQ), sender_prescriber_organization=None
        )

        # Waiting period is bypassed for GEIQ even if unauthorized prescriber.
        assert not user.new_approval_blocked_by_waiting_period(
            siae=CompanyFactory(kind=CompanyKind.GEIQ),
            sender_prescriber_organization=PrescriberOrganizationFactory(),
        )

        # Waiting period is bypassed if a valid diagnosis made by an authorized prescriber exists.
        diag = IAEEligibilityDiagnosisFactory(from_prescriber=True, job_seeker=user)
        assert not user.new_approval_blocked_by_waiting_period(
            siae=CompanyFactory(kind=CompanyKind.ETTI),
            sender_prescriber_organization=None,
        )
        diag.delete()

        # Waiting period cannot be bypassed if a valid diagnosis exists
        # but was not made by an authorized prescriber.
        diag = IAEEligibilityDiagnosisFactory(job_seeker=user, from_employer=True)
        assert user.new_approval_blocked_by_waiting_period(
            siae=CompanyFactory(kind=CompanyKind.ETTI),
            sender_prescriber_organization=None,
        )


@pytest.mark.parametrize("initial_asp_uid", ("000000000000000000000000000000", ""))
@override_settings(SECRET_KEY="test")
def test_job_seeker_profile_asp_uid(initial_asp_uid):
    profile = JobSeekerProfileFactory(user__pk=42, asp_uid=initial_asp_uid)
    assert profile.asp_uid == initial_asp_uid or "08b4e9f755a688b554a6487d96d2a0"


def test_job_seeker_profile_asp_uid_field_history():
    profile = JobSeekerProfileFactory(asp_uid="000000000000000000000000000000")
    assert profile.fields_history == []

    profile.asp_uid = "000000000000000000000000000001"
    with triggers.context():
        profile.save()
    profile.refresh_from_db()
    assert normalize_fields_history(profile.fields_history) == [
        {
            "before": {"asp_uid": "000000000000000000000000000000"},
            "after": {"asp_uid": "000000000000000000000000000001"},
            "_timestamp": "[TIMESTAMP]",
            "_context": {},
        }
    ]
    assert datetime.datetime.fromisoformat(profile.fields_history[-1]["_timestamp"]).timestamp() == pytest.approx(
        datetime.datetime.now().timestamp()
    )

    profile.asp_uid = "000000000000000000000000000002"
    with triggers.context(profile=profile.pk):
        profile.save()
    profile.refresh_from_db()
    assert normalize_fields_history(profile.fields_history) == [
        {
            "before": {"asp_uid": "000000000000000000000000000000"},
            "after": {"asp_uid": "000000000000000000000000000001"},
            "_timestamp": "[TIMESTAMP]",
            "_context": {},
        },
        {
            "before": {"asp_uid": "000000000000000000000000000001"},
            "after": {"asp_uid": "000000000000000000000000000002"},
            "_timestamp": "[TIMESTAMP]",
            "_context": {"profile": profile.pk},
        },
    ]
    assert datetime.datetime.fromisoformat(profile.fields_history[-1]["_timestamp"]).timestamp() == pytest.approx(
        datetime.datetime.now().timestamp()
    )


@pytest.mark.parametrize(
    "obj_attr,field,value",
    [
        pytest.param("jobseeker_profile", "asp_uid", "000000000000000000000000000002", id="asp_uid"),
        pytest.param("jobseeker_profile", "birthdate", datetime.date(2000, 1, 1), id="birthdate"),
        pytest.param("jobseeker_profile", "birth_country_id", "BAHAMAS", id="birth_country"),
        pytest.param("jobseeker_profile", "birth_place_id", "STRASBOURG", id="birth_place"),
        pytest.param("jobseeker_profile", "is_not_stalled_anymore", False, id="is_not_stalled_anymore"),
        pytest.param("jobseeker_profile", "pole_emploi_id", "12345678944", id="pole_emploi_id"),
        pytest.param(None, "first_name", "Dolorès", id="first_name"),
        pytest.param(None, "last_name", "Madrigal", id="last_name"),
        pytest.param(None, "title", "MME", id="title"),
        pytest.param(None, "email", "hush@madrigal.com", id="email"),
        pytest.param(None, "phone", "0612345678", id="phone"),
        pytest.param(None, "address_line_1", "Calle del encanto", id="address_line_1"),
        pytest.param(None, "address_line_2", "Finca Madrigal", id="address_line_2"),
        pytest.param(None, "post_code", "34570", id="post_code"),
        pytest.param(None, "city", "Montarnaud", id="city"),
    ],
)
def test_user_and_job_seeker_profile_field_history(obj_attr, field, value):
    """
    Light version of `test_job_seeker_profile_asp_uid_field_history`
    that only check if keys are present because the whole
    system is already tested.
    Also, types of monitored fields are different, making testing their value
    not that obvious.
    """
    factory_kwargs = {}
    match field:
        case "birth_country_id":
            value = Country.objects.get(name=value).pk
        case "birth_place_id":
            factory_kwargs["born_in_france"] = True
            value = Commune.objects.current().get(name=value).pk
        case "title":
            # JobSeekerFactory.title being random, force its value
            # to ensure a change is made.
            factory_kwargs["title"] = "M"

    obj = JobSeekerFactory(**factory_kwargs)
    if obj_attr:
        obj = getattr(obj, obj_attr)
    assert obj.fields_history == []

    setattr(obj, field, value)
    with triggers.context():
        obj.save(update_fields=[field])
    obj.refresh_from_db()
    assert field in obj.fields_history[0]["after"].keys()


@pytest.mark.parametrize(
    "factory",
    [
        JobSeekerFactory,
        PrescriberFactory,
        EmployerFactory,
        LaborInspectorFactory,
    ],
)
def test_user_not_is_staff_nor_superuser(factory):
    factory()

    # Avoid crashing the database connection because of the IntegrityError
    with transaction.atomic():
        with pytest.raises(IntegrityError):
            User.objects.update(is_staff=True)

    # Avoid crashing the database connection because of the IntegrityError
    with transaction.atomic():
        with pytest.raises(IntegrityError):
            User.objects.update(is_superuser=True)


def test_staff_user():
    ItouStaffFactory(is_superuser=True)

    User.objects.update(is_superuser=False)

    # Avoid crashing the database connection because of the IntegrityError
    with transaction.atomic():
        with pytest.raises(IntegrityError):
            User.objects.update(is_staff=False)


def test_user_invalid_kind():
    with pytest.raises(
        ValidationError,
        match="Le type d’utilisateur est incorrect.",
    ):
        UserFactory(kind="")


@pytest.mark.parametrize(
    "user_kind,profile_expected",
    [
        (UserKind.JOB_SEEKER, True),
        (UserKind.PRESCRIBER, False),
        (UserKind.EMPLOYER, False),
        (UserKind.LABOR_INSPECTOR, False),
    ],
)
def test_save_creates_a_job_seeker_profile(user_kind, profile_expected):
    user = User(kind=user_kind)
    user.save()
    assert hasattr(user, "jobseeker_profile") == profile_expected


@freezegun.freeze_time("2022-08-10")
@pytest.mark.usefixtures("trigger_context")
def test_save_erases_ft_fields_if_details_change():
    UserFactory(
        email="foobar@truc.com",
        kind=UserKind.JOB_SEEKER,
    )

    # trigger the .from_db() method, otherwise the factory would not...
    user = User.objects.get(email="foobar@truc.com")

    def reset_profile():
        user.jobseeker_profile.pe_last_certification_attempt_at = timezone.now()
        user.jobseeker_profile.pe_obfuscated_nir = "XXX_1234567890123_YYY"
        user.jobseeker_profile.ft_gps_id = "7f4d1259-78e3-4818-b357-5befea239990"
        user.jobseeker_profile.save(
            update_fields=["pe_obfuscated_nir", "pe_last_certification_attempt_at", "ft_gps_id"]
        )
        IdentityCertification.objects.upsert_certifications(
            [
                IdentityCertification(
                    certifier=IdentityCertificationAuthorities.API_FT_RECHERCHE_INDIVIDU_CERTIFIE,
                    jobseeker_profile=user.jobseeker_profile,
                )
            ]
        )

    reset_profile()
    profile = JobSeekerProfile.objects.get(user__email="foobar@truc.com")
    profile.nir = "1234567890123"
    profile.save()
    profile.refresh_from_db()
    assert profile.pe_obfuscated_nir is None
    assert profile.pe_last_certification_attempt_at is None
    assert profile.ft_gps_id is None
    assertQuerySetEqual(profile.identity_certifications.all(), [])

    reset_profile()
    user = User.objects.get(email="foobar@truc.com")
    user.jobseeker_profile.birthdate = datetime.date(2018, 8, 22)
    user.jobseeker_profile.save()
    user.jobseeker_profile.refresh_from_db()
    assert user.jobseeker_profile.pe_obfuscated_nir is None
    assert user.jobseeker_profile.pe_last_certification_attempt_at is None
    assert user.jobseeker_profile.ft_gps_id is None
    assertQuerySetEqual(profile.identity_certifications.all(), [])

    reset_profile()
    user = User.objects.get(email="foobar@truc.com")
    user.first_name = "Wazzzzaaaa"
    user.save()
    user.jobseeker_profile.refresh_from_db()
    assert user.jobseeker_profile.pe_obfuscated_nir is None
    assert user.jobseeker_profile.pe_last_certification_attempt_at is None
    assert user.jobseeker_profile.ft_gps_id is None
    assertQuerySetEqual(profile.identity_certifications.all(), [])

    reset_profile()
    user = User.objects.get(email="foobar@truc.com")
    user.last_name = "Heyyyyyyyyy"
    user.save()
    user.jobseeker_profile.refresh_from_db()
    assert user.jobseeker_profile.pe_obfuscated_nir is None
    assert user.jobseeker_profile.pe_last_certification_attempt_at is None
    assert user.jobseeker_profile.ft_gps_id is None
    assertQuerySetEqual(profile.identity_certifications.all(), [])

    reset_profile()
    # then reload the user, and don't change anything in the monitored fields
    user = User.objects.get(email="foobar@truc.com")
    user.first_name = "Wazzzzaaaa"
    user.last_name = "Heyyyyyyyyy"
    user.email = "brutal@toto.at"  # change the email though
    user.save()
    user.jobseeker_profile.birthdate = datetime.date(2018, 8, 22)
    user.jobseeker_profile.nir = "1234567890123"
    user.jobseeker_profile.save()
    assert user.jobseeker_profile.pe_obfuscated_nir == "XXX_1234567890123_YYY"
    assert user.jobseeker_profile.pe_last_certification_attempt_at == datetime.datetime(
        2022, 8, 10, 0, 0, 0, 0, tzinfo=datetime.UTC
    )
    assert user.jobseeker_profile.ft_gps_id == "7f4d1259-78e3-4818-b357-5befea239990"
    assertQuerySetEqual(
        profile.identity_certifications.values_list("certifier", flat=True),
        [IdentityCertificationAuthorities.API_FT_RECHERCHE_INDIVIDU_CERTIFIE],
    )


@pytest.mark.parametrize("user_active", [False, True])
@pytest.mark.parametrize("membership_active", [False, True])
@pytest.mark.parametrize("organization_authorized", [False, True])
def test_is_prescriber_with_authorized_org_memberships(user_active, membership_active, organization_authorized):
    prescriber = PrescriberFactory(is_active=user_active)
    PrescriberMembershipFactory(
        is_active=membership_active, user=prescriber, organization__authorized=organization_authorized
    )
    assert prescriber.is_prescriber_with_authorized_org_memberships is all(
        [user_active, membership_active, organization_authorized]
    )


def test_user_first_login(client):
    user = JobSeekerFactory()
    assert user.last_login is None
    assert user.first_login is None

    client.force_login(user)
    user.refresh_from_db()
    assert user.last_login is not None
    assert user.first_login == user.last_login
    initial_first_login = user.first_login

    client.force_login(user)
    user.refresh_from_db()
    assert user.last_login != initial_first_login
    assert user.first_login == initial_first_login
