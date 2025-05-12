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
from itou.asp.models import AllocationDuration, Commune, EducationLevel
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
from itou.users.models import IdentityCertification, JobSeeker, JobSeekerProfile, User
from itou.utils.mocks.address_format import BAN_GEOCODING_API_RESULTS_MOCK, mock_get_geocoding_data
from itou.utils.urls import get_absolute_url
from tests.approvals.factories import ApprovalFactory, PoleEmploiApprovalFactory
from tests.companies.factories import CompanyFactory
from tests.eligibility.factories import GEIQEligibilityDiagnosisFactory, IAEEligibilityDiagnosisFactory
from tests.gps.factories import FollowUpGroupFactory
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
    LaborInspectorFactory,
    PrescriberFactory,
    UserFactory,
)


class TestManager:
    def test_get_duplicated_pole_emploi_ids(self):
        # Unique user.
        JobSeekerFactory(pole_emploi_id="5555555A")

        # 2 users using the same `pole_emploi_id`.
        JobSeekerFactory(pole_emploi_id="6666666B")
        JobSeekerFactory(pole_emploi_id="6666666B")

        # 3 users using the same `pole_emploi_id`.
        JobSeekerFactory(pole_emploi_id="7777777C")
        JobSeekerFactory(pole_emploi_id="7777777C")
        JobSeekerFactory(pole_emploi_id="7777777C")

        duplicated_pole_emploi_ids = User.objects.get_duplicated_pole_emploi_ids()

        expected_result = ["6666666B", "7777777C"]
        assertQuerySetEqual(duplicated_pole_emploi_ids, expected_result, ordered=False)

    def test_get_duplicates_by_pole_emploi_id(self):
        # 2 users using the same `pole_emploi_id` and different birthdates.
        JobSeekerFactory(pole_emploi_id="6666666B", birthdate=datetime.date(1988, 2, 2))
        JobSeekerFactory(pole_emploi_id="6666666B", birthdate=datetime.date(2001, 12, 12))

        # 2 users using the same `pole_emploi_id` and the same birthdates.
        user1 = JobSeekerFactory(pole_emploi_id="7777777B", birthdate=datetime.date(1988, 2, 2))
        user2 = JobSeekerFactory(pole_emploi_id="7777777B", birthdate=datetime.date(1988, 2, 2))

        # 3 users using the same `pole_emploi_id` and the same birthdates.
        user3 = JobSeekerFactory(pole_emploi_id="8888888C", birthdate=datetime.date(2002, 12, 12))
        user4 = JobSeekerFactory(pole_emploi_id="8888888C", birthdate=datetime.date(2002, 12, 12))
        user5 = JobSeekerFactory(pole_emploi_id="8888888C", birthdate=datetime.date(2002, 12, 12))
        # + 1 user using the same `pole_emploi_id` but a different birthdate.
        JobSeekerFactory(pole_emploi_id="8888888C", birthdate=datetime.date(1978, 12, 20))

        duplicated_users = JobSeeker.objects.get_duplicates_by_pole_emploi_id()
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

        assert JobSeeker.objects.search_by_full_name("Jean").count() == 2
        assert JobSeeker.objects.search_by_full_name("Jean II").get() == user_1

    def test_linked_job_seeker_ids(self):
        organization = PrescriberOrganizationFactory()
        other_organization = PrescriberOrganizationFactory()
        prescriber = PrescriberMembershipFactory(organization=organization).user

        # From the prescriber as a member of no organization
        job_seeker_created_by_user_no_organization = JobSeekerFactory(created_by=prescriber)
        job_seeker_with_sent_job_app_no_organization = JobApplicationFactory(
            sender=prescriber, eligibility_diagnosis=None
        ).job_seeker
        # It's not possible to make a eligibility diagnosis with no organization

        # From the prescriber as a member of the organization
        job_seeker_created_by_user_in_organization = JobSeekerFactory(
            created_by=prescriber,
            created_by_prescriber_organization=organization,
        )
        job_seeker_with_sent_job_app_in_organization = JobApplicationFactory(
            sender=prescriber,
            sender_prescriber_organization=organization,
            eligibility_diagnosis=None,
        ).job_seeker
        job_seeker_with_authored_diagnosis_in_organization = IAEEligibilityDiagnosisFactory(
            author=prescriber,
            author_prescriber_organization=organization,
            from_prescriber=True,
        ).job_seeker

        # From the prescriber as a member of another organization. We won't display those
        JobSeekerFactory(
            created_by=prescriber,
            created_by_prescriber_organization=other_organization,
        )
        JobApplicationFactory(
            sender=prescriber,
            sender_prescriber_organization=other_organization,
            eligibility_diagnosis=None,
        )
        IAEEligibilityDiagnosisFactory(
            author=prescriber,
            author_prescriber_organization=other_organization,
            from_prescriber=True,
        )

        job_seeker_created_by_organization_coworker = JobSeekerFactory(created_by_prescriber_organization=organization)
        job_seeker_with_job_app_sent_by_organization_coworker = JobApplicationFactory(
            sender_prescriber_organization=organization,
            eligibility_diagnosis=None,
        ).job_seeker
        job_seeker_with_diagnosis_authored_by_organization_coworker = IAEEligibilityDiagnosisFactory(
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
                job_seeker_with_authored_diagnosis_in_organization.pk,
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
                job_seeker_with_authored_diagnosis_in_organization.pk,
                job_seeker_created_by_organization_coworker.pk,
                job_seeker_with_job_app_sent_by_organization_coworker.pk,
                job_seeker_with_diagnosis_authored_by_organization_coworker.pk,
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
        assert sent_emails[0].subject == "[DEV] Création de votre compte candidat"

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
        job_seeker = JobSeekerFactory(pole_emploi_id="", lack_of_pole_emploi_id_reason="")
        cleaned_data = {
            "pole_emploi_id": job_seeker.jobseeker_profile.pole_emploi_id,
            "lack_of_pole_emploi_id_reason": job_seeker.jobseeker_profile.lack_of_pole_emploi_id_reason,
        }
        with pytest.raises(ValidationError):
            JobSeekerProfile.clean_pole_emploi_fields(cleaned_data)

        # If both fields are present at the same time, `pole_emploi_id` takes precedence.
        job_seeker = JobSeekerFactory(
            pole_emploi_id="69970749",
            lack_of_pole_emploi_id_reason=LackOfPoleEmploiId.REASON_FORGOTTEN,
        )
        cleaned_data = {
            "pole_emploi_id": job_seeker.jobseeker_profile.pole_emploi_id,
            "lack_of_pole_emploi_id_reason": job_seeker.jobseeker_profile.lack_of_pole_emploi_id_reason,
        }
        JobSeekerProfile.clean_pole_emploi_fields(cleaned_data)
        assert cleaned_data["pole_emploi_id"] == job_seeker.jobseeker_profile.pole_emploi_id
        assert cleaned_data["lack_of_pole_emploi_id_reason"] == ""

        # No exception should be raised for the following cases.

        job_seeker = JobSeekerFactory(pole_emploi_id="62723349", lack_of_pole_emploi_id_reason="")
        cleaned_data = {
            "pole_emploi_id": job_seeker.jobseeker_profile.pole_emploi_id,
            "lack_of_pole_emploi_id_reason": job_seeker.jobseeker_profile.lack_of_pole_emploi_id_reason,
        }
        JobSeekerProfile.clean_pole_emploi_fields(cleaned_data)

        job_seeker = JobSeekerFactory(
            pole_emploi_id="",
            lack_of_pole_emploi_id_reason=LackOfPoleEmploiId.REASON_FORGOTTEN,
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
        print("FIRST", job_seeker.asp_uid)

        # Same user.
        assert not user.can_edit_email(user)

        # All conditions are met.
        job_seeker = JobSeekerFactory(created_by=user)
        print("SECOND", job_seeker.asp_uid)
        assert user.can_edit_email(job_seeker)

        # Job seeker logged in, he is not longer handled by a proxy.
        job_seeker = JobSeekerFactory(last_login=timezone.now())
        assert not user.can_edit_email(job_seeker)

        # User did not create the job seeker's account.
        job_seeker = JobSeekerFactory(created_by=PrescriberFactory())
        assert not user.can_edit_email(job_seeker)

        # Job seeker has verified his email.
        job_seeker = JobSeekerFactory(created_by=user)
        job_seeker.emailaddress_set.create(email=job_seeker.email, verified=True)
        assert not user.can_edit_email(job_seeker)

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

    def test_siae_admin_can_create_siae_antenna(self):
        company = CompanyFactory(with_membership=True, membership__is_admin=True)
        user = company.members.get()
        assert user.can_create_siae_antenna(company)

    def test_siae_normal_member_cannot_create_siae_antenna(self):
        company = CompanyFactory(with_membership=True, membership__is_admin=False)
        user = company.members.get()
        assert not user.can_create_siae_antenna(company)

    def test_siae_admin_without_convention_cannot_create_siae_antenna(self):
        company = CompanyFactory(with_membership=True, convention=None)
        user = company.members.get()
        assert not user.can_create_siae_antenna(company)

    @pytest.mark.parametrize("kind", CompanyKind)
    def test_admin_ability_to_create_siae_antenna(self, kind):
        company = CompanyFactory(kind=kind, with_membership=True, membership__is_admin=True)
        user = company.members.get()
        if kind == CompanyKind.GEIQ:
            assert user.can_create_siae_antenna(company)
        else:
            assert user.can_create_siae_antenna(company) == company.should_have_convention

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
        no_nir_profile = JobSeekerFactory(nir="")
        # This works
        assert no_nir_profile.nir == ""
        no_nir_profile.lack_of_nir_reason = LackOfNIRReason.TEMPORARY_NUMBER
        no_nir_profile.save()

        nir_profile = JobSeekerFactory()
        # This doesn't
        assert nir_profile.nir
        nir_profile.lack_of_nir_reason = LackOfNIRReason.TEMPORARY_NUMBER
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
        too_long_name = "a" * 149

        assert len(JobSeekerFactory(first_name=too_long_name, last_name="maréchal").get_full_name()) == 70

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
            education_level=random.choice(EducationLevel.values),
            pole_emploi_since=AllocationDuration.MORE_THAN_24_MONTHS,
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

    def test_valid_birth_place_and_country(self):
        """
        Birth place and country are not mandatory except for ASP / FS
        We must check that if the job seeker is born in France,
        if the commune is provided

        Otherwise, if the job seeker is born in another country,
        the commune must remain empty.
        """
        profile = JobSeekerFactory().jobseeker_profile

        # Valid use cases:

        # No commune and no country
        assert profile._clean_birth_fields() is None

        # France and Commune filled
        profile = JobSeekerFactory(born_in_france=True).jobseeker_profile
        assert profile._clean_birth_fields() is None

        profile = JobSeekerFactory(born_outside_france=True).jobseeker_profile
        assert profile._clean_birth_fields() is None


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
    @freezegun.freeze_time("2022-08-10")
    def test_merge_approvals_timeline_case1(self):
        user = JobSeekerFactory(with_pole_emploi_id=True)

        ApprovalFactory(
            user=user,
            start_at=datetime.date(2016, 12, 20),
            end_at=datetime.date(2018, 12, 20),
        )

        # PoleEmploiApproval 1.
        pe_approval_1 = PoleEmploiApprovalFactory(
            pole_emploi_id=user.jobseeker_profile.pole_emploi_id,
            birthdate=user.jobseeker_profile.birthdate,
            start_at=datetime.date(2018, 12, 20),
            end_at=datetime.date(2020, 12, 20),
        )

        # PoleEmploiApproval 2.
        # Same `start_at` as PoleEmploiApproval 1.
        # But `end_at` earlier than PoleEmploiApproval 1.
        PoleEmploiApprovalFactory(
            pole_emploi_id=user.jobseeker_profile.pole_emploi_id,
            birthdate=user.jobseeker_profile.birthdate,
            start_at=datetime.date(2018, 12, 20),
            end_at=datetime.date(2019, 12, 19),
        )

        # Check timeline.
        assert user.latest_common_approval == pe_approval_1
        assert user.latest_approval is None
        assert user.latest_pe_approval == pe_approval_1

    @freezegun.freeze_time("2022-08-10")
    def test_merge_approvals_timeline_case2(self):
        user = JobSeekerFactory(with_pole_emploi_id=True)

        # PoleEmploiApproval 1.
        PoleEmploiApprovalFactory(
            pole_emploi_id=user.jobseeker_profile.pole_emploi_id,
            birthdate=user.jobseeker_profile.birthdate,
            start_at=datetime.date(2020, 3, 17),
            end_at=datetime.date(2020, 6, 16),
        )

        # PoleEmploiApproval 2.
        # `start_at` earlier than PoleEmploiApproval 1.
        # `end_at` after PoleEmploiApproval 1.
        pe_approval_2 = PoleEmploiApprovalFactory(
            pole_emploi_id=user.jobseeker_profile.pole_emploi_id,
            birthdate=user.jobseeker_profile.birthdate,
            start_at=datetime.date(2020, 3, 2),
            end_at=datetime.date(2022, 3, 2),
        )

        # Check timeline.
        assert user.latest_common_approval == pe_approval_2
        assert user.latest_approval is None
        assert user.latest_pe_approval == pe_approval_2

    def test_merge_approvals_pass_and_pe_valid(self):
        user = JobSeekerFactory()
        start_at = timezone.localdate() - relativedelta(months=2)
        end_at = start_at + datetime.timedelta(days=Approval.DEFAULT_APPROVAL_DAYS)

        # PASS IAE
        pass_iae = ApprovalFactory(
            user=user,
            start_at=start_at,
            end_at=end_at,
        )

        # PoleEmploiApproval
        PoleEmploiApprovalFactory(
            pole_emploi_id=user.jobseeker_profile.pole_emploi_id,
            birthdate=user.jobseeker_profile.birthdate,
            start_at=start_at,
            end_at=end_at + relativedelta(days=1),
        )

        PoleEmploiApprovalFactory(
            pole_emploi_id=user.jobseeker_profile.pole_emploi_id,
            birthdate=user.jobseeker_profile.birthdate,
            start_at=start_at,
            end_at=end_at + relativedelta(days=2),
        )

        assert user.latest_approval == pass_iae

    def test_status_without_approval(self):
        user = JobSeekerFactory()
        assert user.has_no_common_approval
        assert not user.has_valid_approval
        assert not user.has_latest_common_approval_in_waiting_period
        assert user.latest_approval is None

    def test_status_with_valid_approval(self):
        user = JobSeekerFactory()
        approval = ApprovalFactory(user=user, start_at=timezone.localdate() - relativedelta(days=1))
        assert not user.has_no_common_approval
        assert user.has_valid_approval
        assert not user.has_latest_common_approval_in_waiting_period
        assert user.latest_approval == approval

    def test_status_approval_in_waiting_period(self):
        user = user_with_approval_in_waiting_period()
        assert not user.has_no_common_approval
        assert not user.has_valid_approval
        assert user.has_latest_common_approval_in_waiting_period
        assert user.latest_approval == user.latest_approval

    def test_status_approval_with_elapsed_waiting_period(self):
        user = JobSeekerFactory()
        end_at = timezone.localdate() - relativedelta(years=3)
        start_at = end_at - relativedelta(years=2)
        ApprovalFactory(user=user, start_at=start_at, end_at=end_at)
        assert user.has_no_common_approval
        assert not user.has_valid_approval
        assert not user.has_latest_common_approval_in_waiting_period
        assert user.latest_approval is None

    def test_status_with_valid_pole_emploi_approval(self):
        user = JobSeekerFactory(with_pole_emploi_id=True)
        print("USER", user, type(user))
        print("PROFILE", user.jobseeker_profile, type(user.jobseeker_profile))
        print(user.birthdate, user.jobseeker_profile.birthdate)
        pe_approval = PoleEmploiApprovalFactory(
            pole_emploi_id=user.jobseeker_profile.pole_emploi_id, birthdate=user.jobseeker_profile.birthdate
        )
        assert not user.has_no_common_approval
        assert not user.has_valid_approval  # PoleEmploiFactory aren't checked anymore
        assert not user.has_latest_common_approval_in_waiting_period
        assert user.latest_approval is None
        assert user.latest_pe_approval == pe_approval

    def test_status_with_expired_pole_emploi_approval_and_valid_approval(self):
        user = JobSeekerFactory(with_pole_emploi_id=True)
        pe_approval = PoleEmploiApprovalFactory(
            pole_emploi_id=user.jobseeker_profile.pole_emploi_id,
            birthdate=user.jobseeker_profile.birthdate,
            start_at=timezone.localdate() - datetime.timedelta(3 * 365),
        )
        assert not pe_approval.is_valid()
        approval = ApprovalFactory(user=user)
        assert approval.is_valid()

        assert not user.has_no_common_approval
        assert user.has_valid_approval  # PoleEmploiFactory aren't checked anymore
        assert not user.has_latest_common_approval_in_waiting_period
        assert user.latest_approval == approval
        assert user.latest_pe_approval == pe_approval

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

    def test_latest_common_approval_no_approval(self):
        user = JobSeekerFactory()
        assert user.latest_common_approval is None

    def test_latest_common_approval_when_only_pe_approval(self):
        user = JobSeekerFactory()
        pe_approval = PoleEmploiApprovalFactory(nir=user.jobseeker_profile.nir)
        assert user.latest_common_approval == pe_approval

    def test_latest_common_approval_with_expired_pe_approval(self):
        user = JobSeekerFactory()
        today = timezone.localdate()
        PoleEmploiApprovalFactory(
            nir=user.jobseeker_profile.nir,
            start_at=today - datetime.timedelta(days=30),
            end_at=today - datetime.timedelta(days=1),
        )
        approval = ApprovalFactory(
            user=user,
            start_at=today - datetime.timedelta(days=10),
            end_at=today - datetime.timedelta(days=7),
        )
        assert user.latest_common_approval == approval

    def test_latest_common_approval_is_approval_if_valid(self):
        user = JobSeekerFactory()
        approval = ApprovalFactory(user=user)
        PoleEmploiApprovalFactory(nir=user.jobseeker_profile.nir)
        assert user.latest_common_approval == approval

    def test_latest_common_approval_is_pe_approval_if_approval_is_expired(self):
        user = JobSeekerFactory()
        end_at = timezone.localdate() - relativedelta(years=3)
        start_at = end_at - relativedelta(years=2)
        # expired approval
        ApprovalFactory(user=user, start_at=start_at, end_at=end_at)
        pe_approval = PoleEmploiApprovalFactory(nir=user.jobseeker_profile.nir)
        assert user.latest_common_approval == pe_approval

    def test_latest_common_approval_is_pe_approval_edge_case(self):
        user = JobSeekerFactory()
        end_at = timezone.localdate() - relativedelta(days=10)
        start_at = end_at - relativedelta(years=2)
        # approval in waiting period
        ApprovalFactory(user=user, start_at=start_at, end_at=end_at)
        pe_approval = PoleEmploiApprovalFactory(nir=user.jobseeker_profile.nir)
        assert user.latest_common_approval == pe_approval

    def test_latest_common_approval_is_none_if_both_expired(self):
        user = JobSeekerFactory()
        end_at = timezone.localdate() - relativedelta(years=3)
        start_at = end_at - relativedelta(years=2)
        ApprovalFactory(user=user, start_at=start_at, end_at=end_at)
        PoleEmploiApprovalFactory(nir=user.jobseeker_profile.nir, start_at=start_at, end_at=end_at)
        assert user.latest_common_approval is None


@pytest.mark.parametrize("initial_asp_uid", ("000000000000000000000000000000", ""))
@override_settings(SECRET_KEY="test")
def test_job_seeker_profile_asp_uid(initial_asp_uid):
    profile = JobSeekerFactory(pk=42, asp_uid=initial_asp_uid)
    assert profile.asp_uid == initial_asp_uid or "08b4e9f755a688b554a6487d96d2a0"


def test_job_seeker_profile_asp_uid_field_history():
    profile = JobSeekerFactory(asp_uid="000000000000000000000000000000")
    assert profile.fields_history == []

    profile.asp_uid = "000000000000000000000000000001"
    profile.save()
    profile.refresh_from_db()
    fields_history = [
        {k: v for k, v in operation.items() if k != "_timestamp"} for operation in profile.fields_history
    ]
    assert fields_history == [
        {
            "before": {"asp_uid": "000000000000000000000000000000"},
            "after": {"asp_uid": "000000000000000000000000000001"},
        }
    ]

    profile.asp_uid = "000000000000000000000000000002"
    profile.save()
    profile.refresh_from_db()
    fields_history = [
        {k: v for k, v in operation.items() if k != "_timestamp"} for operation in profile.fields_history
    ]
    assert fields_history == [
        {
            "before": {"asp_uid": "000000000000000000000000000000"},
            "after": {"asp_uid": "000000000000000000000000000001"},
        },
        {
            "before": {"asp_uid": "000000000000000000000000000001"},
            "after": {"asp_uid": "000000000000000000000000000002"},
        },
    ]
    assert datetime.datetime.fromisoformat(profile.fields_history[1]["_timestamp"]).timestamp() == pytest.approx(
        datetime.datetime.now().timestamp()
    )


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
def test_save_erases_pe_obfuscated_nir_if_details_change():
    UserFactory(
        email="foobar@truc.com",
        kind=UserKind.JOB_SEEKER,
    )

    # trigger the .from_db() method, otherwise the factory would not...
    user = User.objects.get(email="foobar@truc.com")

    def reset_profile():
        user.jobseeker_profile.pe_last_certification_attempt_at = timezone.now()
        user.jobseeker_profile.pe_obfuscated_nir = "XXX_1234567890123_YYY"
        user.jobseeker_profile.save(update_fields=["pe_obfuscated_nir", "pe_last_certification_attempt_at"])
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
    assertQuerySetEqual(profile.identity_certifications.all(), [])

    reset_profile()
    user = User.objects.get(email="foobar@truc.com")
    user.jobseeker_profile.birthdate = datetime.date(2018, 8, 22)
    user.jobseeker_profile.save()
    user.jobseeker_profile.refresh_from_db()
    assert user.jobseeker_profile.pe_obfuscated_nir is None
    assert user.jobseeker_profile.pe_last_certification_attempt_at is None
    assertQuerySetEqual(profile.identity_certifications.all(), [])

    reset_profile()
    user = User.objects.get(email="foobar@truc.com")
    user.first_name = "Wazzzzaaaa"
    user.save()
    user.jobseeker_profile.refresh_from_db()
    assert user.jobseeker_profile.pe_obfuscated_nir is None
    assert user.jobseeker_profile.pe_last_certification_attempt_at is None
    assertQuerySetEqual(profile.identity_certifications.all(), [])

    reset_profile()
    user = User.objects.get(email="foobar@truc.com")
    user.last_name = "Heyyyyyyyyy"
    user.save()
    user.jobseeker_profile.refresh_from_db()
    assert user.jobseeker_profile.pe_obfuscated_nir is None
    assert user.jobseeker_profile.pe_last_certification_attempt_at is None
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
    assertQuerySetEqual(
        profile.identity_certifications.values_list("certifier", flat=True),
        [IdentityCertificationAuthorities.API_FT_RECHERCHE_INDIVIDU_CERTIFIE],
    )


@pytest.mark.parametrize("initial", [None, ""])
def test_save_erases_pe_obfuscated_nir_when_the_nir_changes_after_a_failed_attempt(faker, initial):
    profile = JobSeekerFactory(
        pe_obfuscated_nir=initial,
        pe_last_certification_attempt_at=faker.date_time(tzinfo=datetime.UTC),
    )
    profile = JobSeekerProfile.objects.get(pk=profile.pk)  # trigger the .from_db() to fill `_old_values`

    assert profile.pe_last_certification_attempt_at is not None
    profile.nir = faker.ssn()
    profile.save(update_fields={"nir"})
    assert profile.pe_last_certification_attempt_at is None


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


@pytest.mark.parametrize(
    "factory, related_object_factory, expected_last_activity",
    [
        pytest.param(
            JobSeekerFactory,
            None,
            lambda jobseeker: jobseeker.date_joined,
            id="jobseeker_without_login",
        ),
        pytest.param(
            lambda: JobSeekerFactory(joined_days_ago=365, last_login=timezone.now()),
            None,
            lambda jobseeker: jobseeker.last_login,
            id="jobseeker_with_login",
        ),
        pytest.param(
            lambda: JobSeekerFactory(joined_days_ago=365, last_login=timezone.now() - datetime.timedelta(days=1)),
            lambda jobseeker: JobApplicationFactory(job_seeker=jobseeker),
            lambda jobseeker: jobseeker.job_applications.last().updated_at,
            id="jobseeker_with_recent_jobapplication",
        ),
        pytest.param(
            lambda: JobSeekerFactory(joined_days_ago=365, last_login=timezone.now() - datetime.timedelta(days=1)),
            lambda jobseeker: ApprovalFactory(user=jobseeker),
            lambda jobseeker: jobseeker.approvals.last().updated_at,
            id="jobseeker_with_recent_approval",
        ),
        pytest.param(
            lambda: JobSeekerFactory(joined_days_ago=365, last_login=timezone.now() - datetime.timedelta(days=1)),
            lambda jobseeker: IAEEligibilityDiagnosisFactory(job_seeker=jobseeker, from_prescriber=True),
            lambda jobseeker: jobseeker.eligibility_diagnoses.last().updated_at,
            id="jobseeker_with_eligibility_diagnosis",
        ),
        pytest.param(
            lambda: JobSeekerFactory(joined_days_ago=365, last_login=timezone.now() - datetime.timedelta(days=1)),
            lambda jobseeker: GEIQEligibilityDiagnosisFactory(job_seeker=jobseeker, from_prescriber=True),
            lambda jobseeker: jobseeker.geiq_eligibility_diagnoses.last().updated_at,
            id="jobseeker_with_geiq_eligibility_diagnosis",
        ),
        pytest.param(
            lambda: JobSeekerFactory(joined_days_ago=365, last_login=timezone.now() - datetime.timedelta(days=1)),
            lambda jobseeker: FollowUpGroupFactory(beneficiary=jobseeker),
            lambda jobseeker: jobseeker.follow_up_group.updated_at,
            id="jobseeker_with_followup_group",
        ),
        pytest.param(PrescriberFactory, None, None, id="prescriber"),
        pytest.param(EmployerFactory, None, None, id="employer"),
        pytest.param(LaborInspectorFactory, None, None, id="labor_inspector"),
        pytest.param(ItouStaffFactory, None, None, id="itou_staff"),
    ],
)
def test_jobseeker_with_last_activity(factory, related_object_factory, expected_last_activity):
    user = factory()
    if related_object_factory:
        related_object_factory(user)
    if expected_last_activity:
        user_from_qs = User.objects.job_seekers_with_last_activity().get()
        assert user_from_qs.last_activity == expected_last_activity(user)
    else:
        assert User.objects.job_seekers_with_last_activity().exists() is False


def test_jobseeker():
    j = JobSeeker(
        kind=UserKind.JOB_SEEKER,
        email="test@example.com",
        asp_uid=uuid.uuid4(),
        username=uuid.uuid4(),
    )
    j.save()
    print("JOBSEEKER", j)

    jf = JobSeekerFactory()
    print("JOBSEEKER FACTORY", jf)

    print("JOBSEEKER LIST", list(JobSeeker.objects.all()))
    print("JOBSEEKERPROFILE LIST", list(JobSeekerProfile.objects.all()))
    print("USERS LIST", list(User.objects.all()))

    # assert False
