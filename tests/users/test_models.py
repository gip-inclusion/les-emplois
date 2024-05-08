import datetime
import json
import random
import uuid
from unittest import mock

import freezegun
import pytest
from dateutil.relativedelta import relativedelta
from django.contrib.gis.geos import Point
from django.core.exceptions import ValidationError
from django.core.serializers.json import DjangoJSONEncoder
from django.db import IntegrityError, transaction
from django.test import override_settings
from django.utils import timezone

import tests.asp.factories as asp
from itou.approvals.models import Approval
from itou.asp.models import AllocationDuration, EducationLevel
from itou.cities.models import City
from itou.companies.enums import CompanyKind
from itou.job_applications.enums import JobApplicationState, Origin
from itou.users.enums import IdentityProvider, LackOfNIRReason, LackOfPoleEmploiId, Title, UserKind
from itou.users.models import JobSeekerProfile, User
from itou.utils.mocks.address_format import BAN_GEOCODING_API_RESULTS_MOCK, mock_get_geocoding_data
from tests.approvals.factories import ApprovalFactory, PoleEmploiApprovalFactory
from tests.companies.factories import CompanyFactory, CompanyMembershipFactory
from tests.eligibility.factories import EligibilityDiagnosisFactory, EligibilityDiagnosisMadeBySiaeFactory
from tests.institutions.factories import InstitutionMembershipFactory
from tests.job_applications.factories import JobApplicationFactory, JobApplicationSentByJobSeekerFactory
from tests.prescribers.factories import (
    PrescriberMembershipFactory,
    PrescriberOrganizationFactory,
    PrescriberOrganizationWithMembershipFactory,
)
from tests.users.factories import (
    EmployerFactory,
    ItouStaffFactory,
    JobSeekerFactory,
    JobSeekerProfileFactory,
    JobSeekerWithAddressFactory,
    LaborInspectorFactory,
    PrescriberFactory,
    UserFactory,
)
from tests.utils.test import TestCase


class ManagerTest(TestCase):
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
        self.assertCountEqual(duplicated_pole_emploi_ids, expected_result)

    def test_get_duplicates_by_pole_emploi_id(self):
        # 2 users using the same `pole_emploi_id` and different birthdates.
        JobSeekerFactory(jobseeker_profile__pole_emploi_id="6666666B", birthdate=datetime.date(1988, 2, 2))
        JobSeekerFactory(jobseeker_profile__pole_emploi_id="6666666B", birthdate=datetime.date(2001, 12, 12))

        # 2 users using the same `pole_emploi_id` and the same birthdates.
        user1 = JobSeekerFactory(jobseeker_profile__pole_emploi_id="7777777B", birthdate=datetime.date(1988, 2, 2))
        user2 = JobSeekerFactory(jobseeker_profile__pole_emploi_id="7777777B", birthdate=datetime.date(1988, 2, 2))

        # 3 users using the same `pole_emploi_id` and the same birthdates.
        user3 = JobSeekerFactory(jobseeker_profile__pole_emploi_id="8888888C", birthdate=datetime.date(2002, 12, 12))
        user4 = JobSeekerFactory(jobseeker_profile__pole_emploi_id="8888888C", birthdate=datetime.date(2002, 12, 12))
        user5 = JobSeekerFactory(jobseeker_profile__pole_emploi_id="8888888C", birthdate=datetime.date(2002, 12, 12))
        # + 1 user using the same `pole_emploi_id` but a different birthdate.
        JobSeekerFactory(jobseeker_profile__pole_emploi_id="8888888C", birthdate=datetime.date(1978, 12, 20))

        duplicated_users = User.objects.get_duplicates_by_pole_emploi_id()

        expected_result = {
            "7777777B": [user1, user2],
            "8888888C": [user3, user4, user5],
        }
        self.assertCountEqual(duplicated_users, expected_result)


class ModelTest(TestCase):
    def test_generate_unique_username(self):
        unique_username = User.generate_unique_username()
        assert unique_username == uuid.UUID(unique_username, version=4).hex

    def test_create_job_seeker_by_proxy(self):
        proxy_user = PrescriberFactory()

        user_data = {
            "email": "john@doe.com",
            "first_name": "John",
            "last_name": "Doe",
            "birthdate": "1978-12-20",
            "phone": "0610101010",
        }
        user = User.create_job_seeker_by_proxy(proxy_user, **user_data)

        assert user.kind == UserKind.JOB_SEEKER
        assert user.password is not None
        assert user.username is not None

        assert user.username == uuid.UUID(user.username, version=4).hex
        assert user.email == user_data["email"]
        assert user.first_name == user_data["first_name"]
        assert user.last_name == user_data["last_name"]
        assert user.birthdate == user_data["birthdate"]
        assert user.phone == user_data["phone"]
        assert user.created_by == proxy_user
        assert user.last_login is None

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

        user = PrescriberFactory(identity_provider=IdentityProvider.INCLUSION_CONNECT)
        assert user.has_sso_provider

        user = JobSeekerFactory(identity_provider=IdentityProvider.PE_CONNECT)
        assert user.has_sso_provider

    def test_update_external_data_source_history_field(self):
        # TODO: (celine-m-s) I'm not very comfortable with this behaviour as we don't really
        # keep a history of changes but only the last one.
        # Field name don't reflect actual behaviour.
        # Also, keeping a trace of old data is interesting in a debug purpose.
        # Maybe split this test in smaller tests at the same time.
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

    def test_last_hire_was_made_by_company(self):
        job_application = JobApplicationSentByJobSeekerFactory(state=JobApplicationState.ACCEPTED)
        user = job_application.job_seeker
        company_1 = job_application.to_company
        assert user.last_hire_was_made_by_company(company_1)
        company_2 = CompanyFactory()
        assert not user.last_hire_was_made_by_company(company_2)

    def test_last_accepted_job_application(self):
        # Set 2 job applications with:
        # - origin set to PE_APPROVAL (the simplest method to test created_at ordering)
        # - different creation date
        # `last_accepted_job_application` is the one with the greater `created_at`
        now = timezone.now()
        job_application_1 = JobApplicationFactory(
            state=JobApplicationState.ACCEPTED,
            origin=Origin.PE_APPROVAL,
            created_at=now + relativedelta(days=1),
        )

        user = job_application_1.job_seeker

        job_application_2 = JobApplicationFactory(
            job_seeker=user,
            state=JobApplicationState.ACCEPTED,
            origin=Origin.PE_APPROVAL,
            created_at=now,
        )

        assert job_application_1 == user.last_accepted_job_application
        assert job_application_2 != user.last_accepted_job_application

    def test_last_accepted_job_application_full_ordering(self):
        # Set 2 job applications with:
        # - origin set to PE_APPROVAL (the simplest method to test created_at ordering)
        # - same creation date
        # - different hiring date
        # `last_accepted_job_application` is the one with the greater `hiring_start_at`
        now = timezone.now()
        job_application_1 = JobApplicationFactory(
            state=JobApplicationState.ACCEPTED,
            origin=Origin.PE_APPROVAL,
            created_at=now,
            hiring_start_at=now + relativedelta(days=1),
        )

        user = job_application_1.job_seeker

        job_application_2 = JobApplicationFactory(
            job_seeker=user,
            state=JobApplicationState.ACCEPTED,
            origin=Origin.PE_APPROVAL,
            created_at=now,
            hiring_start_at=now,
        )

        assert job_application_1 == user.last_accepted_job_application
        assert job_application_2 != user.last_accepted_job_application

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
        job_seeker = JobSeekerFactory(created_by=user)
        job_seeker.emailaddress_set.create(email=job_seeker.email, verified=True)
        assert not user.can_edit_email(job_seeker)

    def test_can_edit_personal_information(self):
        authorized_prescriber = PrescriberOrganizationWithMembershipFactory(authorized=True).members.first()
        unauthorized_prescriber = PrescriberFactory()
        employer = CompanyFactory(with_membership=True).members.first()
        job_seeker = JobSeekerFactory()
        user_created_by_prescriber = JobSeekerFactory(created_by=unauthorized_prescriber, last_login=None)
        logged_user_created_by_prescriber = JobSeekerFactory(
            created_by=unauthorized_prescriber, last_login=timezone.now()
        )
        user_created_by_employer = JobSeekerFactory(created_by=employer, last_login=None)
        logged_user_created_by_employer = JobSeekerFactory(created_by=employer, last_login=timezone.now())

        specs = {
            "authorized_prescriber": {
                "authorized_prescriber": True,
                "unauthorized_prescriber": False,
                "employer": False,
                "job_seeker": False,
                "user_created_by_prescriber": True,
                "logged_user_created_by_prescriber": False,
                "user_created_by_employer": True,
                "logged_user_created_by_employer": False,
            },
            "unauthorized_prescriber": {
                "authorized_prescriber": False,
                "unauthorized_prescriber": True,
                "employer": False,
                "job_seeker": False,
                "user_created_by_prescriber": True,
                "logged_user_created_by_prescriber": False,
                "user_created_by_employer": False,
                "logged_user_created_by_employer": False,
            },
            "employer": {
                "authorized_prescriber": False,
                "unauthorized_prescriber": False,
                "employer": True,
                "job_seeker": False,
                "user_created_by_prescriber": True,
                "logged_user_created_by_prescriber": False,
                "user_created_by_employer": True,
                "logged_user_created_by_employer": False,
            },
            "job_seeker": {
                "authorized_prescriber": False,
                "unauthorized_prescriber": False,
                "employer": False,
                "job_seeker": True,
                "user_created_by_prescriber": False,
                "logged_user_created_by_prescriber": False,
                "user_created_by_employer": False,
                "logged_user_created_by_employer": False,
            },
        }
        for user_type, user_specs in specs.items():
            for other_user_type, expected in user_specs.items():
                assert (
                    locals()[user_type].can_edit_personal_information(locals()[other_user_type]) is expected
                ), f"{user_type}.can_edit_personal_information({other_user_type})"

    def test_can_view_personal_information(self):
        authorized_prescriber = PrescriberOrganizationWithMembershipFactory(authorized=True).members.first()
        unauthorized_prescriber = PrescriberFactory()
        employer = CompanyFactory(with_membership=True).members.first()
        job_seeker = JobSeekerFactory()
        user_created_by_prescriber = JobSeekerFactory(created_by=unauthorized_prescriber, last_login=None)
        user_created_by_employer = JobSeekerFactory(created_by=employer, last_login=None)

        specs = {
            "authorized_prescriber": {
                "authorized_prescriber": True,
                "unauthorized_prescriber": False,
                "employer": False,
                "job_seeker": True,
                "user_created_by_prescriber": True,
                "user_created_by_employer": True,
            },
            "unauthorized_prescriber": {
                "authorized_prescriber": False,
                "unauthorized_prescriber": True,
                "employer": False,
                "job_seeker": False,
                "user_created_by_prescriber": True,
                "user_created_by_employer": False,
            },
            "employer": {
                "authorized_prescriber": False,
                "unauthorized_prescriber": False,
                "employer": True,
                "job_seeker": True,
                "user_created_by_prescriber": True,
                "user_created_by_employer": True,
            },
            "job_seeker": {
                "authorized_prescriber": False,
                "unauthorized_prescriber": False,
                "employer": False,
                "job_seeker": True,
                "user_created_by_prescriber": False,
                "user_created_by_employer": False,
            },
        }
        for user_type, user_specs in specs.items():
            for other_user_type, expected in user_specs.items():
                assert (
                    locals()[user_type].can_view_personal_information(locals()[other_user_type]) is expected
                ), f"{user_type}.can_view_personal_information({other_user_type})"

    def test_can_add_nir(self):
        company = CompanyFactory(with_membership=True)
        employer = company.members.first()
        prescriber_org = PrescriberOrganizationWithMembershipFactory(authorized=True)
        authorized_prescriber = prescriber_org.members.first()
        unauthorized_prescriber = PrescriberFactory()
        job_seeker_no_nir = JobSeekerFactory(jobseeker_profile__nir="")
        job_seeker_with_nir = JobSeekerFactory()

        assert authorized_prescriber.can_add_nir(job_seeker_no_nir)
        assert not unauthorized_prescriber.can_add_nir(job_seeker_no_nir)
        assert employer.can_add_nir(job_seeker_no_nir)
        assert not authorized_prescriber.can_add_nir(job_seeker_with_nir)

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

    def test_admin_ability_to_create_siae_antenna(self):
        for kind in CompanyKind:
            with self.subTest(kind=kind):
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
        no_nir_profile = JobSeekerProfileFactory(nir="")
        # This works
        assert no_nir_profile.nir == ""
        no_nir_profile.lack_of_nir_reason = LackOfNIRReason.TEMPORARY_NUMBER
        no_nir_profile.save()

        nir_profile = JobSeekerProfileFactory()
        # This doesn't
        assert nir_profile.nir
        nir_profile.lack_of_nir_reason = LackOfNIRReason.TEMPORARY_NUMBER
        with pytest.raises(
            ValidationError,
            match="Un utilisateur ayant un NIR ne peut avoir un motif justifiant l'absence de son NIR.",
        ):
            nir_profile.save()

    def test_identity_provider_vs_kind(self):
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
            with self.subTest(f"{factory} / {identity_provider}"):
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


class JobSeekerProfileModelTest(TestCase):
    def setUp(self):
        super().setUp()
        self.user = JobSeekerWithAddressFactory(
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
        self.profile.hexa_commune = asp.CommuneFactory()
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
        profile = JobSeekerFactory().jobseeker_profile
        profile.birth_country = asp.CountryFranceFactory()
        profile.birth_place = asp.CommuneFactory()
        assert profile._clean_birth_fields() is None

        # Europe and no commune
        profile = JobSeekerFactory().jobseeker_profile
        profile.birth_place = None
        profile.birth_country = asp.CountryEuropeFactory()
        assert profile._clean_birth_fields() is None

        # Outside Europe and no commune
        profile.birth_country = asp.CountryOutsideEuropeFactory()
        assert profile._clean_birth_fields() is None

        # Invalid use cases:

        # Europe and Commune filled
        profile.birth_country = asp.CountryEuropeFactory()
        profile.birth_place = asp.CommuneFactory()
        with pytest.raises(ValidationError):
            profile._clean_birth_fields()

        # Outside Europe and Commune filled
        profile.birth_country = asp.CountryOutsideEuropeFactory()
        with pytest.raises(ValidationError):
            profile._clean_birth_fields()


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


class LatestApprovalTestCase(TestCase):
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
            birthdate=user.birthdate,
            start_at=datetime.date(2018, 12, 20),
            end_at=datetime.date(2020, 12, 20),
        )

        # PoleEmploiApproval 2.
        # Same `start_at` as PoleEmploiApproval 1.
        # But `end_at` earlier than PoleEmploiApproval 1.
        PoleEmploiApprovalFactory(
            pole_emploi_id=user.jobseeker_profile.pole_emploi_id,
            birthdate=user.birthdate,
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
            birthdate=user.birthdate,
            start_at=datetime.date(2020, 3, 17),
            end_at=datetime.date(2020, 6, 16),
        )

        # PoleEmploiApproval 2.
        # `start_at` earlier than PoleEmploiApproval 1.
        # `end_at` after PoleEmploiApproval 1.
        pe_approval_2 = PoleEmploiApprovalFactory(
            pole_emploi_id=user.jobseeker_profile.pole_emploi_id,
            birthdate=user.birthdate,
            start_at=datetime.date(2020, 3, 2),
            end_at=datetime.date(2022, 3, 2),
        )

        # Check timeline.
        assert user.latest_common_approval == pe_approval_2
        assert user.latest_approval is None
        assert user.latest_pe_approval == pe_approval_2

    def test_merge_approvals_pass_and_pe_valid(self):
        user = JobSeekerFactory()
        start_at = timezone.now() - relativedelta(months=2)
        end_at = start_at + datetime.timedelta(days=Approval.DEFAULT_APPROVAL_DAYS)

        # PASS IAE
        pass_iae = ApprovalFactory(
            user=user,
            start_at=start_at,
            end_at=end_at,
        )

        # PoleEmploiApproval
        PoleEmploiApprovalFactory(
            pole_emploi_id=user.jobseeker_profile.pole_emploi_id,
            birthdate=user.birthdate,
            start_at=start_at,
            end_at=end_at + relativedelta(days=1),
        )

        PoleEmploiApprovalFactory(
            pole_emploi_id=user.jobseeker_profile.pole_emploi_id,
            birthdate=user.birthdate,
            start_at=start_at,
            end_at=end_at + relativedelta(days=2),
        )

        assert user.latest_approval == pass_iae

    def test_status_without_approval(self):
        user = JobSeekerFactory()
        assert user.has_no_common_approval
        assert not user.has_valid_common_approval
        assert not user.has_common_approval_in_waiting_period
        assert user.latest_approval is None

    def test_status_with_valid_approval(self):
        user = JobSeekerFactory()
        approval = ApprovalFactory(user=user, start_at=timezone.localdate() - relativedelta(days=1))
        assert not user.has_no_common_approval
        assert user.has_valid_common_approval
        assert not user.has_common_approval_in_waiting_period
        assert user.latest_approval == approval

    def test_status_approval_in_waiting_period(self):
        user = user_with_approval_in_waiting_period()
        assert not user.has_no_common_approval
        assert not user.has_valid_common_approval
        assert user.has_common_approval_in_waiting_period
        assert user.latest_approval == user.latest_approval

    def test_status_approval_with_elapsed_waiting_period(self):
        user = JobSeekerFactory()
        end_at = timezone.localdate() - relativedelta(years=3)
        start_at = end_at - relativedelta(years=2)
        ApprovalFactory(user=user, start_at=start_at, end_at=end_at)
        assert user.has_no_common_approval
        assert not user.has_valid_common_approval
        assert not user.has_common_approval_in_waiting_period
        assert user.latest_approval is None

    def test_status_with_valid_pole_emploi_approval(self):
        user = JobSeekerFactory(with_pole_emploi_id=True)
        pe_approval = PoleEmploiApprovalFactory(
            pole_emploi_id=user.jobseeker_profile.pole_emploi_id, birthdate=user.birthdate
        )
        assert not user.has_no_common_approval
        assert user.has_valid_common_approval
        assert not user.has_common_approval_in_waiting_period
        assert user.latest_approval is None
        assert user.latest_pe_approval == pe_approval

    def test_cannot_bypass_waiting_period(self):
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
        assert user.approval_can_be_renewed_by(
            siae=CompanyFactory(kind=CompanyKind.ETTI), sender_prescriber_organization=None
        )

        # Waiting period cannot be bypassed for SIAE if unauthorized prescriber
        # and there is no valid eligibility diagnosis this in period
        assert user.approval_can_be_renewed_by(
            siae=CompanyFactory(kind=CompanyKind.ETTI),
            sender_prescriber_organization=PrescriberOrganizationFactory(),
        )

        # Waiting period is bypassed for SIAE if authorized prescriber.
        assert not user.approval_can_be_renewed_by(
            siae=CompanyFactory(kind=CompanyKind.ETTI),
            sender_prescriber_organization=PrescriberOrganizationFactory(authorized=True),
        )

        # Waiting period is bypassed for GEIQ even if no prescriber.
        assert not user.approval_can_be_renewed_by(
            siae=CompanyFactory(kind=CompanyKind.GEIQ), sender_prescriber_organization=None
        )

        # Waiting period is bypassed for GEIQ even if unauthorized prescriber.
        assert not user.approval_can_be_renewed_by(
            siae=CompanyFactory(kind=CompanyKind.GEIQ),
            sender_prescriber_organization=PrescriberOrganizationFactory(),
        )

        # Waiting period is bypassed if a valid diagnosis made by an authorized prescriber exists.
        diag = EligibilityDiagnosisFactory(job_seeker=user)
        assert not user.approval_can_be_renewed_by(
            siae=CompanyFactory(kind=CompanyKind.ETTI),
            sender_prescriber_organization=None,
        )
        diag.delete()

        # Waiting period cannot be bypassed if a valid diagnosis exists
        # but was not made by an authorized prescriber.
        diag = EligibilityDiagnosisMadeBySiaeFactory(job_seeker=user)
        assert user.approval_can_be_renewed_by(
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


@pytest.mark.parametrize("initial_asp_uid", ("08b4e9f755a688b554a6487d96d2a0", ""))
@override_settings(SECRET_KEY="test")
def test_job_seeker_profile_asp_uid(initial_asp_uid):
    profile = JobSeekerProfileFactory(user__pk=42)
    JobSeekerProfile.objects.filter(pk=profile.pk).update(asp_uid=initial_asp_uid)
    profile.save()
    profile.refresh_from_db()
    assert profile.asp_uid == "08b4e9f755a688b554a6487d96d2a0"


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

    reset_profile()
    profile = JobSeekerProfile.objects.get(user__email="foobar@truc.com")
    profile.nir = "1234567890123"
    profile.save()
    profile.refresh_from_db()
    assert profile.pe_obfuscated_nir is None
    assert profile.pe_last_certification_attempt_at is None

    reset_profile()
    user = User.objects.get(email="foobar@truc.com")
    user.birthdate = datetime.date(2018, 8, 22)
    user.save()
    user.jobseeker_profile.refresh_from_db()
    assert user.jobseeker_profile.pe_obfuscated_nir is None
    assert user.jobseeker_profile.pe_last_certification_attempt_at is None

    reset_profile()
    user = User.objects.get(email="foobar@truc.com")
    user.first_name = "Wazzzzaaaa"
    user.save()
    user.jobseeker_profile.refresh_from_db()
    assert user.jobseeker_profile.pe_obfuscated_nir is None
    assert user.jobseeker_profile.pe_last_certification_attempt_at is None

    reset_profile()
    user = User.objects.get(email="foobar@truc.com")
    user.last_name = "Heyyyyyyyyy"
    user.save()
    user.jobseeker_profile.refresh_from_db()
    assert user.jobseeker_profile.pe_obfuscated_nir is None
    assert user.jobseeker_profile.pe_last_certification_attempt_at is None

    reset_profile()
    # then reload the user, and don't change anything in the monitored fields
    user = User.objects.get(email="foobar@truc.com")
    user.first_name = "Wazzzzaaaa"
    user.last_name = "Heyyyyyyyyy"
    user.birthdate = datetime.date(2018, 8, 22)
    user.email = "brutal@toto.at"  # change the email though
    user.save()
    user.jobseeker_profile.nir = "1234567890123"
    user.jobseeker_profile.save()
    assert user.jobseeker_profile.pe_obfuscated_nir == "XXX_1234567890123_YYY"
    assert user.jobseeker_profile.pe_last_certification_attempt_at == datetime.datetime(
        2022, 8, 10, 0, 0, 0, 0, tzinfo=datetime.timezone.utc
    )


@pytest.mark.parametrize("initial", [None, ""])
def test_save_erases_pe_obfuscated_nir_when_the_nir_changes_after_a_failed_attempt(faker, initial):
    profile = JobSeekerProfileFactory(
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
def test_is_prescriber_with_authorized_org(user_active, membership_active, organization_authorized):
    prescriber = PrescriberFactory(is_active=user_active)
    PrescriberMembershipFactory(
        is_active=membership_active, user=prescriber, organization__is_authorized=organization_authorized
    )
    assert prescriber.is_prescriber_with_authorized_org is all(
        [user_active, membership_active, organization_authorized]
    )


def test_prescriber_organizations():
    prescriber = PrescriberFactory()
    PrescriberMembershipFactory(is_active=True, is_admin=False, user=prescriber)
    admin_membership = PrescriberMembershipFactory(is_active=True, is_admin=True, user=prescriber)
    PrescriberMembershipFactory(is_active=True, is_admin=False, user=prescriber)

    assert len(prescriber.organizations) == 3

    # The organization we are admin of should come first
    assert prescriber.organizations[0] == admin_membership.organization


def test_employer_organizations():
    employer = EmployerFactory()
    CompanyMembershipFactory(is_active=True, is_admin=False, user=employer)
    admin_membership = CompanyMembershipFactory(is_active=True, is_admin=True, user=employer)
    CompanyMembershipFactory(is_active=True, is_admin=False, user=employer)

    assert len(employer.organizations) == 3

    # The organization we are admin of should come first
    assert employer.organizations[0] == admin_membership.company


def test_labor_inspector_organizations():
    labor_inspector = LaborInspectorFactory()
    InstitutionMembershipFactory(is_active=True, is_admin=False, user=labor_inspector)
    admin_membership = InstitutionMembershipFactory(is_active=True, is_admin=True, user=labor_inspector)
    InstitutionMembershipFactory(is_active=True, is_admin=False, user=labor_inspector)

    assert len(labor_inspector.organizations) == 3

    # The organization we are admin of should come first
    assert labor_inspector.organizations[0] == admin_membership.institution
