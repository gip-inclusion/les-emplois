import datetime
import itertools
import json
import random
import uuid
from unittest import mock

import freezegun
import pytest
from dateutil.relativedelta import relativedelta
from django.core.exceptions import ValidationError
from django.core.serializers.json import DjangoJSONEncoder
from django.db import IntegrityError, transaction
from django.test import override_settings
from django.utils import timezone

import tests.asp.factories as asp
from itou.approvals.models import Approval
from itou.asp.models import AllocationDuration, EducationLevel, EmployerType
from itou.common_apps.address.departments import DEPARTMENTS
from itou.institutions.enums import InstitutionKind
from itou.job_applications.enums import Origin
from itou.job_applications.models import JobApplicationWorkflow
from itou.prescribers.enums import PrescriberOrganizationKind
from itou.siaes.enums import SiaeKind
from itou.users.enums import IdentityProvider, LackOfNIRReason, Title, UserKind
from itou.users.models import JobSeekerProfile, User
from itou.utils.mocks.address_format import BAN_GEOCODING_API_RESULTS_MOCK, RESULTS_BY_ADDRESS
from tests.approvals.factories import ApprovalFactory, PoleEmploiApprovalFactory
from tests.eligibility.factories import EligibilityDiagnosisFactory, EligibilityDiagnosisMadeBySiaeFactory
from tests.institutions.factories import InstitutionWithMembershipFactory
from tests.job_applications.factories import JobApplicationFactory, JobApplicationSentByJobSeekerFactory
from tests.prescribers.factories import (
    PrescriberMembershipFactory,
    PrescriberOrganizationFactory,
    PrescriberOrganizationWithMembershipFactory,
)
from tests.siaes.factories import SiaeFactory
from tests.users.factories import (
    ItouStaffFactory,
    JobSeekerFactory,
    JobSeekerWithAddressFactory,
    LaborInspectorFactory,
    PrescriberFactory,
    SiaeStaffFactory,
    UserFactory,
)
from tests.utils.test import TestCase


class ManagerTest(TestCase):
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
        self.assertCountEqual(duplicated_pole_emploi_ids, expected_result)

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

        duplicated_users = User.objects.get_duplicates_by_pole_emploi_id()

        expected_result = {
            "7777777B": [user1, user2],
            "8888888C": [user3, user4, user5],
        }
        self.assertCountEqual(duplicated_users, expected_result)


class ModelTest(TestCase):
    def test_prescriber_of_authorized_organization(self):
        prescriber = PrescriberFactory()

        assert not prescriber.is_prescriber_of_authorized_organization(1)

        prescribermembership = PrescriberMembershipFactory(user=prescriber, organization__is_authorized=False)
        assert not prescriber.is_prescriber_of_authorized_organization(prescribermembership.organization_id)

        prescribermembership = PrescriberMembershipFactory(user=prescriber, organization__is_authorized=True)
        assert prescriber.is_prescriber_of_authorized_organization(prescribermembership.organization_id)

    def test_is_orienter(self):
        job_seeker = JobSeekerFactory()
        assert job_seeker.is_orienter is False

        siae_staff = SiaeStaffFactory()
        assert siae_staff.is_orienter is False

        label_inspector = LaborInspectorFactory()
        assert label_inspector.is_orienter is False

        # PrescriberFactory create the simplest form of prescriber: an orienter
        orienter = PrescriberFactory()
        assert orienter.is_orienter is True

        # PrescriberFactory does not create a prescriber organization
        prescriber = PrescriberOrganizationWithMembershipFactory()
        assert prescriber.members.first().is_orienter is True

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
            "resume_link": "https://urlseemslegit.com/my-cv",
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
        assert user.resume_link == user_data["resume_link"]

        # E-mail already exists, this should raise an error.
        with pytest.raises(ValidationError):
            User.create_job_seeker_by_proxy(proxy_user, **user_data)

    def test_clean_pole_emploi_fields(self):
        # Both fields cannot be empty.
        job_seeker = JobSeekerFactory(pole_emploi_id="", lack_of_pole_emploi_id_reason="")
        cleaned_data = {
            "pole_emploi_id": job_seeker.pole_emploi_id,
            "lack_of_pole_emploi_id_reason": job_seeker.lack_of_pole_emploi_id_reason,
        }
        with pytest.raises(ValidationError):
            User.clean_pole_emploi_fields(cleaned_data)

        # If both fields are present at the same time, `pole_emploi_id` takes precedence.
        job_seeker = JobSeekerFactory(
            pole_emploi_id="69970749",
            lack_of_pole_emploi_id_reason=User.REASON_FORGOTTEN,
        )
        cleaned_data = {
            "pole_emploi_id": job_seeker.pole_emploi_id,
            "lack_of_pole_emploi_id_reason": job_seeker.lack_of_pole_emploi_id_reason,
        }
        User.clean_pole_emploi_fields(cleaned_data)
        assert cleaned_data["pole_emploi_id"] == job_seeker.pole_emploi_id
        assert cleaned_data["lack_of_pole_emploi_id_reason"] == ""

        # No exception should be raised for the following cases.

        job_seeker = JobSeekerFactory(pole_emploi_id="62723349", lack_of_pole_emploi_id_reason="")
        cleaned_data = {
            "pole_emploi_id": job_seeker.pole_emploi_id,
            "lack_of_pole_emploi_id_reason": job_seeker.lack_of_pole_emploi_id_reason,
        }
        User.clean_pole_emploi_fields(cleaned_data)

        job_seeker = JobSeekerFactory(pole_emploi_id="", lack_of_pole_emploi_id_reason=User.REASON_FORGOTTEN)
        cleaned_data = {
            "pole_emploi_id": job_seeker.pole_emploi_id,
            "lack_of_pole_emploi_id_reason": job_seeker.lack_of_pole_emploi_id_reason,
        }
        User.clean_pole_emploi_fields(cleaned_data)

    def test_email_already_exists(self):
        JobSeekerFactory(email="foo@bar.com")
        assert User.email_already_exists("foo@bar.com")
        assert User.email_already_exists("FOO@bar.com")

    def test_nir_already_exists(self):
        user = JobSeekerFactory()
        assert User.nir_already_exists(user.nir)
        assert not User.nir_already_exists(JobSeekerFactory.build().nir)

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

    def test_last_hire_was_made_by_siae(self):
        job_application = JobApplicationSentByJobSeekerFactory(state=JobApplicationWorkflow.STATE_ACCEPTED)
        user = job_application.job_seeker
        siae = job_application.to_siae
        assert user.last_hire_was_made_by_siae(siae)
        siae2 = SiaeFactory()
        assert not user.last_hire_was_made_by_siae(siae2)

    def test_last_accepted_job_application(self):
        # Set 2 job applications with:
        # - origin set to PE_APPROVAL (the simplest method to test created_at ordering)
        # - different creation date
        # `last_accepted_job_application` is the one with the greater `created_at`
        now = timezone.now()
        job_application_1 = JobApplicationFactory(
            state=JobApplicationWorkflow.STATE_ACCEPTED,
            origin=Origin.PE_APPROVAL,
            created_at=now + relativedelta(days=1),
        )

        user = job_application_1.job_seeker

        job_application_2 = JobApplicationFactory(
            job_seeker=user,
            state=JobApplicationWorkflow.STATE_ACCEPTED,
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
            state=JobApplicationWorkflow.STATE_ACCEPTED,
            origin=Origin.PE_APPROVAL,
            created_at=now,
            hiring_start_at=now + relativedelta(days=1),
        )

        user = job_application_1.job_seeker

        job_application_2 = JobApplicationFactory(
            job_seeker=user,
            state=JobApplicationWorkflow.STATE_ACCEPTED,
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
        siae_member = SiaeFactory(with_membership=True).members.first()
        job_seeker = JobSeekerFactory()
        user_created_by_prescriber = JobSeekerFactory(created_by=unauthorized_prescriber, last_login=None)
        logged_user_created_by_prescriber = JobSeekerFactory(
            created_by=unauthorized_prescriber, last_login=timezone.now()
        )
        user_created_by_siae_staff = JobSeekerFactory(created_by=siae_member, last_login=None)
        logged_user_created_by_siae_staff = JobSeekerFactory(created_by=siae_member, last_login=timezone.now())

        specs = {
            "authorized_prescriber": {
                "authorized_prescriber": True,
                "unauthorized_prescriber": False,
                "siae_member": False,
                "job_seeker": False,
                "user_created_by_prescriber": True,
                "logged_user_created_by_prescriber": False,
                "user_created_by_siae_staff": True,
                "logged_user_created_by_siae_staff": False,
            },
            "unauthorized_prescriber": {
                "authorized_prescriber": False,
                "unauthorized_prescriber": True,
                "siae_member": False,
                "job_seeker": False,
                "user_created_by_prescriber": True,
                "logged_user_created_by_prescriber": False,
                "user_created_by_siae_staff": False,
                "logged_user_created_by_siae_staff": False,
            },
            "siae_member": {
                "authorized_prescriber": False,
                "unauthorized_prescriber": False,
                "siae_member": True,
                "job_seeker": False,
                "user_created_by_prescriber": True,
                "logged_user_created_by_prescriber": False,
                "user_created_by_siae_staff": True,
                "logged_user_created_by_siae_staff": False,
            },
            "job_seeker": {
                "authorized_prescriber": False,
                "unauthorized_prescriber": False,
                "siae_member": False,
                "job_seeker": True,
                "user_created_by_prescriber": False,
                "logged_user_created_by_prescriber": False,
                "user_created_by_siae_staff": False,
                "logged_user_created_by_siae_staff": False,
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
        siae_member = SiaeFactory(with_membership=True).members.first()
        job_seeker = JobSeekerFactory()
        user_created_by_prescriber = JobSeekerFactory(created_by=unauthorized_prescriber, last_login=None)
        user_created_by_siae_staff = JobSeekerFactory(created_by=siae_member, last_login=None)

        specs = {
            "authorized_prescriber": {
                "authorized_prescriber": True,
                "unauthorized_prescriber": False,
                "siae_member": False,
                "job_seeker": True,
                "user_created_by_prescriber": True,
                "user_created_by_siae_staff": True,
            },
            "unauthorized_prescriber": {
                "authorized_prescriber": False,
                "unauthorized_prescriber": True,
                "siae_member": False,
                "job_seeker": False,
                "user_created_by_prescriber": True,
                "user_created_by_siae_staff": False,
            },
            "siae_member": {
                "authorized_prescriber": False,
                "unauthorized_prescriber": False,
                "siae_member": True,
                "job_seeker": True,
                "user_created_by_prescriber": True,
                "user_created_by_siae_staff": True,
            },
            "job_seeker": {
                "authorized_prescriber": False,
                "unauthorized_prescriber": False,
                "siae_member": False,
                "job_seeker": True,
                "user_created_by_prescriber": False,
                "user_created_by_siae_staff": False,
            },
        }
        for user_type, user_specs in specs.items():
            for other_user_type, expected in user_specs.items():
                assert (
                    locals()[user_type].can_view_personal_information(locals()[other_user_type]) is expected
                ), f"{user_type}.can_view_personal_information({other_user_type})"

    def test_can_add_nir(self):
        siae = SiaeFactory(with_membership=True)
        siae_staff = siae.members.first()
        prescriber_org = PrescriberOrganizationWithMembershipFactory(authorized=True)
        authorized_prescriber = prescriber_org.members.first()
        unauthorized_prescriber = PrescriberFactory()
        job_seeker_no_nir = JobSeekerFactory(nir="")
        job_seeker_with_nir = JobSeekerFactory()

        assert authorized_prescriber.can_add_nir(job_seeker_no_nir)
        assert not unauthorized_prescriber.can_add_nir(job_seeker_no_nir)
        assert siae_staff.can_add_nir(job_seeker_no_nir)
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
        siae = SiaeFactory(with_membership=True, membership__is_admin=True)
        user = siae.members.get()
        assert user.can_create_siae_antenna(siae)

    def test_siae_normal_member_cannot_create_siae_antenna(self):
        siae = SiaeFactory(with_membership=True, membership__is_admin=False)
        user = siae.members.get()
        assert not user.can_create_siae_antenna(siae)

    def test_siae_admin_without_convention_cannot_create_siae_antenna(self):
        siae = SiaeFactory(with_membership=True, convention=None)
        user = siae.members.get()
        assert not user.can_create_siae_antenna(siae)

    def test_admin_ability_to_create_siae_antenna(self):
        for kind in SiaeKind:
            with self.subTest(kind=kind):
                siae = SiaeFactory(kind=kind, with_membership=True, membership__is_admin=True)
                user = siae.members.get()
                if kind == SiaeKind.GEIQ:
                    assert user.can_create_siae_antenna(siae)
                else:
                    assert user.can_create_siae_antenna(siae) == siae.should_have_convention

    def test_can_view_stats_siae(self):
        # An employer can only view hiring stats of their own SIAE.
        siae1 = SiaeFactory(with_membership=True)
        user1 = siae1.members.get()
        siae2 = SiaeFactory()

        assert siae1.has_member(user1)
        assert user1.can_view_stats_siae(current_org=siae1)
        assert not siae2.has_member(user1)
        assert not user1.can_view_stats_siae(current_org=siae2)

        # Even non admin members can view their SIAE stats.
        siae3 = SiaeFactory(with_membership=True, membership__is_admin=False)
        user3 = siae3.members.get()
        assert user3.can_view_stats_siae(current_org=siae3)

    @override_settings(STATS_CD_DEPARTMENT_WHITELIST=["93"])
    def test_can_view_stats_cd(self):
        """
        CD as in "Conseil Départemental".
        """
        # Department outside of the whitelist cannot access.
        org = PrescriberOrganizationWithMembershipFactory(
            authorized=True, kind=PrescriberOrganizationKind.DEPT, department="01"
        )
        user = org.members.get()
        assert not user.can_view_stats_cd(current_org=org)
        assert not user.can_view_stats_dashboard_widget(current_org=org)

        # Admin prescriber of authorized CD can access.
        org = PrescriberOrganizationWithMembershipFactory(
            authorized=True, kind=PrescriberOrganizationKind.DEPT, department="93"
        )
        user = org.members.get()
        assert user.can_view_stats_cd(current_org=org)
        assert user.can_view_stats_dashboard_widget(current_org=org)

        # Non admin prescriber can access as well.
        org = PrescriberOrganizationWithMembershipFactory(
            authorized=True,
            kind=PrescriberOrganizationKind.DEPT,
            membership__is_admin=False,
            department="93",
        )
        user = org.members.get()
        assert user.can_view_stats_cd(current_org=org)
        assert user.can_view_stats_dashboard_widget(current_org=org)

        # Non authorized organization does not give access.
        org = PrescriberOrganizationWithMembershipFactory(
            kind=PrescriberOrganizationKind.DEPT,
            department="93",
        )
        user = org.members.get()
        assert not user.can_view_stats_cd(current_org=org)
        assert not user.can_view_stats_dashboard_widget(current_org=org)

        # Non CD organization does not give access.
        org = PrescriberOrganizationWithMembershipFactory(
            authorized=True,
            kind=PrescriberOrganizationKind.CHRS,
            department="93",
        )
        user = org.members.get()
        assert not user.can_view_stats_cd(current_org=org)
        assert not user.can_view_stats_dashboard_widget(current_org=org)

        # Prescriber without organization cannot access.
        org = None
        user = PrescriberFactory()
        assert not user.can_view_stats_cd(current_org=org)
        assert not user.can_view_stats_dashboard_widget(current_org=org)

    def test_can_view_stats_pe_as_regular_pe_agency(self):
        regular_pe_agency = PrescriberOrganizationWithMembershipFactory(
            authorized=True, kind=PrescriberOrganizationKind.PE, department="93"
        )
        user = regular_pe_agency.members.get()
        assert not regular_pe_agency.is_dtpe
        assert not regular_pe_agency.is_drpe
        assert not regular_pe_agency.is_dgpe
        assert user.can_view_stats_pe(current_org=regular_pe_agency)
        assert user.get_stats_pe_departments(current_org=regular_pe_agency) == ["93"]

    def test_can_view_stats_pe_as_dtpe_with_single_department(self):
        dtpe_with_single_department = PrescriberOrganizationWithMembershipFactory(
            authorized=True,
            kind=PrescriberOrganizationKind.PE,
            code_safir_pole_emploi="49104",
            department="49",
        )
        user = dtpe_with_single_department.members.get()
        assert dtpe_with_single_department.is_dtpe
        assert not dtpe_with_single_department.is_drpe
        assert not dtpe_with_single_department.is_dgpe
        assert user.can_view_stats_pe(current_org=dtpe_with_single_department)
        assert user.get_stats_pe_departments(current_org=dtpe_with_single_department) == ["49"]

    def test_can_view_stats_pe_as_dtpe_with_multiple_departments(self):
        dtpe_with_multiple_departments = PrescriberOrganizationWithMembershipFactory(
            authorized=True,
            kind=PrescriberOrganizationKind.PE,
            code_safir_pole_emploi="72203",
            department="72",
        )
        user = dtpe_with_multiple_departments.members.get()
        assert dtpe_with_multiple_departments.is_dtpe
        assert not dtpe_with_multiple_departments.is_drpe
        assert not dtpe_with_multiple_departments.is_dgpe
        assert user.can_view_stats_pe(current_org=dtpe_with_multiple_departments)
        assert user.get_stats_pe_departments(current_org=dtpe_with_multiple_departments) == ["72", "53"]

    def test_can_view_stats_pe_as_drpe(self):
        drpe = PrescriberOrganizationWithMembershipFactory(
            authorized=True,
            kind=PrescriberOrganizationKind.PE,
            department="93",
            code_safir_pole_emploi="75980",
        )
        user = drpe.members.get()
        assert drpe.is_drpe
        assert not drpe.is_dgpe
        assert not drpe.is_dtpe
        assert user.can_view_stats_pe(current_org=drpe)
        assert user.get_stats_pe_departments(current_org=drpe) == [
            "75",
            "77",
            "78",
            "91",
            "92",
            "93",
            "94",
            "95",
        ]

    def test_can_view_stats_pe_as_dgpe(self):
        dgpe = PrescriberOrganizationWithMembershipFactory(
            authorized=True,
            kind=PrescriberOrganizationKind.PE,
            department="93",
            code_safir_pole_emploi="00162",
        )
        user = dgpe.members.get()
        assert not dgpe.is_drpe
        assert not dgpe.is_dtpe
        assert dgpe.is_dgpe
        assert user.can_view_stats_pe(current_org=dgpe)
        assert user.get_stats_pe_departments(current_org=dgpe) == DEPARTMENTS.keys()

    def test_can_view_stats_ddets_iae(self):
        # Admin member of DDETS IAE can access.
        institution = InstitutionWithMembershipFactory(kind=InstitutionKind.DDETS_IAE, department="93")
        user = institution.members.get()
        assert user.can_view_stats_ddets_iae(current_org=institution)
        assert user.can_view_stats_dashboard_widget(current_org=institution)

        # Non admin member of DDETS IAE can access as well.
        institution = InstitutionWithMembershipFactory(
            kind=InstitutionKind.DDETS_IAE, membership__is_admin=False, department="93"
        )
        user = institution.members.get()
        assert user.can_view_stats_ddets_iae(current_org=institution)
        assert user.can_view_stats_dashboard_widget(current_org=institution)

        # Member of institution of wrong kind cannot access.
        institution = InstitutionWithMembershipFactory(kind=InstitutionKind.OTHER, department="93")
        user = institution.members.get()
        assert not user.can_view_stats_ddets_iae(current_org=institution)
        assert not user.can_view_stats_dashboard_widget(current_org=institution)

    def test_can_view_stats_dreets_iae(self):
        # Admin member of DREETS IAE can access.
        institution = InstitutionWithMembershipFactory(kind=InstitutionKind.DREETS_IAE, department="93")
        user = institution.members.get()
        assert user.can_view_stats_dreets_iae(current_org=institution)
        assert user.can_view_stats_dashboard_widget(current_org=institution)

        # Non admin member of DREETS IAE can access as well.
        institution = InstitutionWithMembershipFactory(
            kind=InstitutionKind.DREETS_IAE, membership__is_admin=False, department="93"
        )
        user = institution.members.get()
        assert user.can_view_stats_dreets_iae(current_org=institution)
        assert user.can_view_stats_dashboard_widget(current_org=institution)

        # Member of institution of wrong kind cannot access.
        institution = InstitutionWithMembershipFactory(kind=InstitutionKind.OTHER, department="93")
        user = institution.members.get()
        assert not user.can_view_stats_dreets_iae(current_org=institution)
        assert not user.can_view_stats_dashboard_widget(current_org=institution)

    def test_can_view_stats_dgefp(self):
        # Admin member of DGEFP can access.
        institution = InstitutionWithMembershipFactory(kind=InstitutionKind.DGEFP, department="93")
        user = institution.members.get()
        assert user.can_view_stats_dgefp(current_org=institution)
        assert user.can_view_stats_dashboard_widget(current_org=institution)

        # Non admin member of DGEFP can access as well.
        institution = InstitutionWithMembershipFactory(
            kind=InstitutionKind.DGEFP, membership__is_admin=False, department="93"
        )
        user = institution.members.get()
        assert user.can_view_stats_dgefp(current_org=institution)
        assert user.can_view_stats_dashboard_widget(current_org=institution)

        # Member of institution of wrong kind cannot access.
        institution = InstitutionWithMembershipFactory(kind=InstitutionKind.OTHER, department="93")
        user = institution.members.get()
        assert not user.can_view_stats_dgefp(current_org=institution)
        assert not user.can_view_stats_dashboard_widget(current_org=institution)

    def test_user_kind(self):
        non_staff_kinds = [
            UserKind.JOB_SEEKER,
            UserKind.PRESCRIBER,
            UserKind.SIAE_STAFF,
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

        siae_staff = SiaeStaffFactory()
        assert "employeur" == siae_staff.get_kind_display()

        labor_inspector = LaborInspectorFactory()
        assert "inspecteur du travail" == labor_inspector.get_kind_display()

    def test_constraint_user_lack_of_nir_reason_or_nir(self):
        no_nir_user = JobSeekerFactory(nir="")
        # This works
        assert no_nir_user.nir == ""
        no_nir_user.lack_of_nir_reason = LackOfNIRReason.TEMPORARY_NUMBER
        no_nir_user.save()

        user = JobSeekerFactory()
        # This doesn't
        assert user.nir
        user.lack_of_nir_reason = LackOfNIRReason.TEMPORARY_NUMBER
        with pytest.raises(
            ValidationError,
            match="Un utilisateur ayant un NIR ne peut avoir un motif justifiant l'absence de son NIR.",
        ):
            user.save()

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
            [SiaeStaffFactory, IdentityProvider.DJANGO, False],
            [SiaeStaffFactory, IdentityProvider.PE_CONNECT, True],
            [SiaeStaffFactory, IdentityProvider.FRANCE_CONNECT, True],
            [SiaeStaffFactory, IdentityProvider.INCLUSION_CONNECT, False],
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


def mock_get_geocoding_data(address, post_code=None, limit=1):
    return RESULTS_BY_ADDRESS.get(address)


class JobSeekerProfileModelTest(TestCase):
    def setUp(self):
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
        # FIXME: rework geolocation mock and move this kind of tests to
        # a test suite for utils.format_address
        self.profile._clean_job_seeker_hexa_address()
        user = self.profile.user
        user.address_line_1 = "8 la boutrie - caillot"
        user.address_line_2 = "saint hilaire de loulay"
        user.post_code = "85600"
        self.profile.update_hexa_address()

        # undefined lane type should fallback to "Lieu-Dit" (LD) as lane type
        assert "LD" == self.profile.hexa_lane_type

    def test_job_seeker_situation_complete(self):
        # Both PE ID and situation must be filled or none
        self.profile._clean_job_seeker_situation()

        user = self.profile.user

        # FIXME or kill me
        # user.pole_emploi_id = None
        # self.profile.pole_emploi_since = "MORE_THAN_24_MONTHS"
        # with self.assertRaises(ValidationError):
        #    self.profile._clean_job_seeker_situation()

        # Both PE fields are provided: OK
        user.pole_emploi_id = "1234567"
        self.profile._clean_job_seeker_situation()

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

        self.profile._clean_job_seeker_situation()
        assert not self.profile.is_employed

        self.profile.unemployed_since = None
        self.profile.previous_employer_kind = EmployerType.ACI

        self.profile._clean_job_seeker_situation()
        assert self.profile.is_employed

        # Check coherence
        with pytest.raises(ValidationError):
            # Can't have both
            self.profile.unemployed_since = AllocationDuration.MORE_THAN_24_MONTHS
            self.profile.previous_employer_kind = EmployerType.ACI
            self.profile._clean_job_seeker_situation()

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
    start_at = end_at - relativedelta(years=Approval.DEFAULT_APPROVAL_YEARS)
    # diagnosis.created_at is a datetime, approval.start_at is a date
    diagnosis_created_at = timezone.now() - relativedelta(years=Approval.DEFAULT_APPROVAL_YEARS)
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
        user = JobSeekerFactory()

        ApprovalFactory(
            user=user,
            start_at=datetime.date(2016, 12, 20),
            end_at=datetime.date(2018, 12, 20),
        )

        # PoleEmploiApproval 1.
        pe_approval_1 = PoleEmploiApprovalFactory(
            pole_emploi_id=user.pole_emploi_id,
            birthdate=user.birthdate,
            start_at=datetime.date(2018, 12, 20),
            end_at=datetime.date(2020, 12, 20),
        )

        # PoleEmploiApproval 2.
        # Same `start_at` as PoleEmploiApproval 1.
        # But `end_at` earlier than PoleEmploiApproval 1.
        PoleEmploiApprovalFactory(
            pole_emploi_id=user.pole_emploi_id,
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
        user = JobSeekerFactory()

        # PoleEmploiApproval 1.
        PoleEmploiApprovalFactory(
            pole_emploi_id=user.pole_emploi_id,
            birthdate=user.birthdate,
            start_at=datetime.date(2020, 3, 17),
            end_at=datetime.date(2020, 6, 16),
        )

        # PoleEmploiApproval 2.
        # `start_at` earlier than PoleEmploiApproval 1.
        # `end_at` after PoleEmploiApproval 1.
        pe_approval_2 = PoleEmploiApprovalFactory(
            pole_emploi_id=user.pole_emploi_id,
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
        end_at = start_at + relativedelta(years=Approval.DEFAULT_APPROVAL_YEARS)

        # PASS IAE
        pass_iae = ApprovalFactory(
            user=user,
            start_at=start_at,
            end_at=end_at,
        )

        # PoleEmploiApproval
        PoleEmploiApprovalFactory(
            pole_emploi_id=user.pole_emploi_id,
            birthdate=user.birthdate,
            start_at=start_at,
            end_at=end_at + relativedelta(days=1),
        )

        PoleEmploiApprovalFactory(
            pole_emploi_id=user.pole_emploi_id,
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
        user = JobSeekerFactory()
        pe_approval = PoleEmploiApprovalFactory(pole_emploi_id=user.pole_emploi_id, birthdate=user.birthdate)
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
            siae=SiaeFactory(kind=SiaeKind.ETTI), sender_prescriber_organization=None
        )

        # Waiting period cannot be bypassed for SIAE if unauthorized prescriber
        # and there is no valid eligibility diagnosis this in period
        assert user.approval_can_be_renewed_by(
            siae=SiaeFactory(kind=SiaeKind.ETTI),
            sender_prescriber_organization=PrescriberOrganizationFactory(),
        )

        # Waiting period is bypassed for SIAE if authorized prescriber.
        assert not user.approval_can_be_renewed_by(
            siae=SiaeFactory(kind=SiaeKind.ETTI),
            sender_prescriber_organization=PrescriberOrganizationFactory(authorized=True),
        )

        # Waiting period is bypassed for GEIQ even if no prescriber.
        assert not user.approval_can_be_renewed_by(
            siae=SiaeFactory(kind=SiaeKind.GEIQ), sender_prescriber_organization=None
        )

        # Waiting period is bypassed for GEIQ even if unauthorized prescriber.
        assert not user.approval_can_be_renewed_by(
            siae=SiaeFactory(kind=SiaeKind.GEIQ),
            sender_prescriber_organization=PrescriberOrganizationFactory(),
        )

        # Waiting period is bypassed if a valid diagnosis made by an authorized prescriber exists.
        diag = EligibilityDiagnosisFactory(job_seeker=user)
        assert not user.approval_can_be_renewed_by(
            siae=SiaeFactory(kind=SiaeKind.ETTI),
            sender_prescriber_organization=None,
        )
        diag.delete()

        # Waiting period cannot be bypassed if a valid diagnosis exists
        # but was not made by an authorized prescriber.
        diag = EligibilityDiagnosisMadeBySiaeFactory(job_seeker=user)
        assert user.approval_can_be_renewed_by(
            siae=SiaeFactory(kind=SiaeKind.ETTI),
            sender_prescriber_organization=None,
        )

    def test_latest_common_approval_no_approval(self):
        user = JobSeekerFactory()
        assert user.latest_common_approval is None

    def test_latest_common_approval_when_only_pe_approval(self):
        user = JobSeekerFactory()
        pe_approval = PoleEmploiApprovalFactory(nir=user.nir)
        assert user.latest_common_approval == pe_approval

    def test_latest_common_approval_is_approval_if_valid(self):
        user = JobSeekerFactory()
        approval = ApprovalFactory(user=user)
        PoleEmploiApprovalFactory(nir=user.nir)
        assert user.latest_common_approval == approval

    def test_latest_common_approval_is_pe_approval_if_approval_is_expired(self):
        user = JobSeekerFactory()
        end_at = timezone.localdate() - relativedelta(years=3)
        start_at = end_at - relativedelta(years=2)
        # expired approval
        ApprovalFactory(user=user, start_at=start_at, end_at=end_at)
        pe_approval = PoleEmploiApprovalFactory(nir=user.nir)
        assert user.latest_common_approval == pe_approval

    def test_latest_common_approval_is_pe_approval_edge_case(self):
        user = JobSeekerFactory()
        end_at = timezone.localdate() - relativedelta(days=10)
        start_at = end_at - relativedelta(years=2)
        # approval in waiting period
        ApprovalFactory(user=user, start_at=start_at, end_at=end_at)
        pe_approval = PoleEmploiApprovalFactory(nir=user.nir)
        assert user.latest_common_approval == pe_approval

    def test_latest_common_approval_is_none_if_both_expired(self):
        user = JobSeekerFactory()
        end_at = timezone.localdate() - relativedelta(years=3)
        start_at = end_at - relativedelta(years=2)
        ApprovalFactory(user=user, start_at=start_at, end_at=end_at)
        PoleEmploiApprovalFactory(nir=user.nir, start_at=start_at, end_at=end_at)
        assert user.latest_common_approval is None


@pytest.mark.parametrize(
    "factory,expected",
    [
        (JobSeekerFactory, "08b4e9f755a688b554a6487d96d2a0"),
        (PrescriberFactory, None),
        (SiaeStaffFactory, None),
        (LaborInspectorFactory, None),
    ],
)
@override_settings(SECRET_KEY="test")
def test_user_asp_uid(factory, expected):
    user = factory.build(pk=42, asp_uid="")

    assert user.asp_uid == ""
    user.save()

    if expected is None:
        assert user.asp_uid is None
    else:
        assert user.asp_uid == expected


@pytest.mark.parametrize("from_kind,to_kind", itertools.combinations(UserKind, 2))
@override_settings(SECRET_KEY="test")
def test_user_asp_uid_when_its_kind_changes(from_kind, to_kind):
    user = UserFactory(pk=42, asp_uid="", kind=from_kind)
    print(user.pk)

    if user.is_job_seeker:
        assert user.asp_uid == "08b4e9f755a688b554a6487d96d2a0"
    else:
        assert user.asp_uid is None

    user.kind = to_kind
    user.save()

    print(user.pk)

    if user.is_job_seeker:
        assert user.asp_uid == "08b4e9f755a688b554a6487d96d2a0"
    else:
        assert user.asp_uid is None


@pytest.mark.parametrize(
    "factory",
    [
        JobSeekerFactory,
        PrescriberFactory,
        SiaeStaffFactory,
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
        (UserKind.SIAE_STAFF, False),
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

    def reset_profile_and_save_user():
        user.jobseeker_profile.pe_last_certification_attempt_at = timezone.now()
        user.jobseeker_profile.pe_obfuscated_nir = "XXX_1234567890123_YYY"
        user.jobseeker_profile.save(update_fields=["pe_obfuscated_nir", "pe_last_certification_attempt_at"])
        user.save()  # triggers an eventual change in the profile
        user.jobseeker_profile.refresh_from_db()

    user.nir = "1234567890123"
    reset_profile_and_save_user()
    assert user.jobseeker_profile.pe_obfuscated_nir is None
    assert user.jobseeker_profile.pe_last_certification_attempt_at is None

    user.birthdate = datetime.date(2018, 8, 22)
    reset_profile_and_save_user()
    assert user.jobseeker_profile.pe_obfuscated_nir is None
    assert user.jobseeker_profile.pe_last_certification_attempt_at is None

    user.first_name = "Wazzzzaaaa"
    reset_profile_and_save_user()
    assert user.jobseeker_profile.pe_obfuscated_nir is None
    assert user.jobseeker_profile.pe_last_certification_attempt_at is None

    user.last_name = "Heyyyyyyyyy"
    reset_profile_and_save_user()
    assert user.jobseeker_profile.pe_obfuscated_nir is None
    assert user.jobseeker_profile.pe_last_certification_attempt_at is None

    # then reload the user, and don't change anything in the monitored fields
    user = User.objects.get(email="foobar@truc.com")
    user.first_name = "Wazzzzaaaa"
    user.last_name = "Heyyyyyyyyy"
    user.nir = "1234567890123"
    user.birthdate = datetime.date(2018, 8, 22)
    user.email = "brutal@toto.at"  # change the email though
    reset_profile_and_save_user()
    assert user.jobseeker_profile.pe_obfuscated_nir == "XXX_1234567890123_YYY"
    assert user.jobseeker_profile.pe_last_certification_attempt_at == datetime.datetime(
        2022, 8, 10, 0, 0, 0, 0, tzinfo=datetime.timezone.utc
    )


def test_jobseeker_factory_works_alongside_user_has_data_changed():
    js = JobSeekerFactory(jobseeker_profile__pe_obfuscated_nir="JAIME_LES_CHATS")
    assert js._saved_obfuscated_nir == "JAIME_LES_CHATS"
    assert js.jobseeker_profile.pe_obfuscated_nir == "JAIME_LES_CHATS"
    profile = JobSeekerProfile.objects.get(user=js)
    assert profile.pe_obfuscated_nir == "JAIME_LES_CHATS"
    assert profile.pk == js.jobseeker_profile.pk
