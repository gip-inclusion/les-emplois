import datetime
import itertools
import json
import uuid
from unittest import mock

from dateutil.relativedelta import relativedelta
from django.conf import settings
from django.core.exceptions import ValidationError
from django.core.serializers.json import DjangoJSONEncoder
from django.test import TestCase
from django.utils import timezone

import itou.asp.factories as asp
from itou.approvals.factories import ApprovalFactory, PoleEmploiApprovalFactory
from itou.approvals.models import Approval
from itou.asp.models import AllocationDuration, EmployerType
from itou.common_apps.address.departments import DEPARTMENTS
from itou.eligibility.factories import EligibilityDiagnosisFactory, EligibilityDiagnosisMadeBySiaeFactory
from itou.institutions.enums import InstitutionKind
from itou.institutions.factories import InstitutionWithMembershipFactory
from itou.job_applications.factories import JobApplicationSentByJobSeekerFactory
from itou.job_applications.models import JobApplicationWorkflow
from itou.prescribers.enums import PrescriberOrganizationKind
from itou.prescribers.factories import (
    PrescriberMembershipFactory,
    PrescriberOrganizationFactory,
    PrescriberOrganizationWithMembershipFactory,
)
from itou.siaes.enums import SiaeKind
from itou.siaes.factories import SiaeFactory
from itou.users.enums import IdentityProvider, Title
from itou.users.factories import JobSeekerFactory, JobSeekerProfileFactory, PrescriberFactory, UserFactory
from itou.users.models import User
from itou.utils.mocks.address_format import BAN_GEOCODING_API_RESULTS_MOCK, RESULTS_BY_ADDRESS


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

        self.assertFalse(prescriber.is_prescriber_of_authorized_organization(1))

        prescribermembership = PrescriberMembershipFactory(user=prescriber, organization__is_authorized=False)
        self.assertFalse(prescriber.is_prescriber_of_authorized_organization(prescribermembership.organization_id))

        prescribermembership = PrescriberMembershipFactory(user=prescriber, organization__is_authorized=True)
        self.assertTrue(prescriber.is_prescriber_of_authorized_organization(prescribermembership.organization_id))

    def test_generate_unique_username(self):
        unique_username = User.generate_unique_username()
        self.assertEqual(unique_username, uuid.UUID(unique_username, version=4).hex)

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

        self.assertTrue(user.is_job_seeker)
        self.assertIsNotNone(user.password)
        self.assertIsNotNone(user.username)

        self.assertEqual(user.username, uuid.UUID(user.username, version=4).hex)
        self.assertEqual(user.email, user_data["email"])
        self.assertEqual(user.first_name, user_data["first_name"])
        self.assertEqual(user.last_name, user_data["last_name"])
        self.assertEqual(user.birthdate, user_data["birthdate"])
        self.assertEqual(user.phone, user_data["phone"])
        self.assertEqual(user.created_by, proxy_user)
        self.assertEqual(user.last_login, None)
        self.assertEqual(user.resume_link, user_data["resume_link"])

        # E-mail already exists, this should raise an error.
        with self.assertRaises(ValidationError):
            User.create_job_seeker_by_proxy(proxy_user, **user_data)

    def test_clean_pole_emploi_fields(self):

        # Both fields cannot be empty.
        job_seeker = JobSeekerFactory(pole_emploi_id="", lack_of_pole_emploi_id_reason="")
        cleaned_data = {
            "pole_emploi_id": job_seeker.pole_emploi_id,
            "lack_of_pole_emploi_id_reason": job_seeker.lack_of_pole_emploi_id_reason,
        }
        with self.assertRaises(ValidationError):
            User.clean_pole_emploi_fields(cleaned_data)

        # If both fields are present at the same time, `pole_emploi_id` takes precedence.
        job_seeker = JobSeekerFactory(pole_emploi_id="69970749", lack_of_pole_emploi_id_reason=User.REASON_FORGOTTEN)
        cleaned_data = {
            "pole_emploi_id": job_seeker.pole_emploi_id,
            "lack_of_pole_emploi_id_reason": job_seeker.lack_of_pole_emploi_id_reason,
        }
        User.clean_pole_emploi_fields(cleaned_data)
        self.assertEqual(cleaned_data["pole_emploi_id"], job_seeker.pole_emploi_id)
        self.assertEqual(cleaned_data["lack_of_pole_emploi_id_reason"], "")

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
        self.assertTrue(User.email_already_exists("foo@bar.com"))
        self.assertTrue(User.email_already_exists("FOO@bar.com"))

    def test_nir_already_exists(self):
        user = JobSeekerFactory()
        self.assertTrue(User.nir_already_exists(user.nir))
        self.assertFalse(User.nir_already_exists(JobSeekerFactory.build().nir))

    def test_save_for_unique_email_on_create_and_update(self):
        """
        Ensure `email` is unique when using the save() method for creating or updating a User instance.
        """

        email = "juste@leblanc.com"
        UserFactory(email=email)

        # Creating a user with an existing email should raise an error.
        with self.assertRaises(ValidationError):
            UserFactory(email=email)

        # Updating a user with an existing email should raise an error.
        user = UserFactory(email="francois@pignon.com")
        user.email = email
        with self.assertRaises(ValidationError):
            user.save()

        # Make sure it's case insensitive.
        email = email.title()
        with self.assertRaises(ValidationError):
            UserFactory(email=email)

    def test_is_handled_by_proxy(self):
        job_seeker = JobSeekerFactory()
        self.assertFalse(job_seeker.is_handled_by_proxy)

        prescriber = PrescriberFactory()
        job_seeker = JobSeekerFactory(created_by=prescriber)
        self.assertTrue(job_seeker.is_handled_by_proxy)

        # Job seeker activates his account. He is in control now!
        job_seeker.last_login = timezone.now()
        self.assertFalse(job_seeker.is_handled_by_proxy)

    def test_has_sso_provider(self):
        job_seeker = JobSeekerFactory.build()
        self.assertFalse(job_seeker.has_sso_provider)

        job_seeker = JobSeekerFactory.build(identity_provider=IdentityProvider.FRANCE_CONNECT)
        self.assertTrue(job_seeker.has_sso_provider)

        job_seeker = JobSeekerFactory.build(identity_provider=IdentityProvider.INCLUSION_CONNECT)
        self.assertTrue(job_seeker.has_sso_provider)

        job_seeker = JobSeekerFactory()
        job_seeker.socialaccount_set.create(provider="peamu")
        self.assertTrue(job_seeker.has_sso_provider)

    def test_update_external_data_source_history_field(self):
        # TODO: (celine-m-s) I'm not very comfortable with this behaviour as we don't really
        # keep a history of changes but only the last one.
        # Field name don't reflect actual behaviour.
        # Also, keeping a trace of old data is interesting in a debug purpose.
        # Maybe split this test in smaller tests at the same time.
        user = UserFactory()
        self.assertFalse(user.external_data_source_history)

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
        self.assertTrue(has_performed_update)
        self.assertEqual(
            user.external_data_source_history,
            [{"field_name": "first_name", "value": "Lola", "source": provider.value, "created_at": now_str}],
        )

        # Update history.
        with mock.patch("django.utils.timezone.now", return_value=now):
            has_performed_update = user.update_external_data_source_history_field(
                provider=provider, field="first_name", value="Jeanne"
            )
        user.save()
        user.refresh_from_db()
        self.assertTrue(has_performed_update)
        self.assertEqual(
            user.external_data_source_history,
            [
                {"field_name": "first_name", "value": "Lola", "source": provider.value, "created_at": now_str},
                {"field_name": "first_name", "value": "Jeanne", "source": provider.value, "created_at": now_str},
            ],
        )

        # Don't update the history if value is the same.
        has_performed_update = user.update_external_data_source_history_field(
            provider=provider, field="first_name", value="Jeanne"
        )
        user.save()
        user.refresh_from_db()
        self.assertFalse(has_performed_update)
        self.assertEqual(
            user.external_data_source_history,
            # NB: created_at would have changed if has_performed_update had been True since we did not use mock.patch
            [
                {"field_name": "first_name", "value": "Lola", "source": provider.value, "created_at": now_str},
                {"field_name": "first_name", "value": "Jeanne", "source": provider.value, "created_at": now_str},
            ],
        )

        # Allow storing empty values.
        with mock.patch("django.utils.timezone.now", return_value=now):
            has_performed_update = user.update_external_data_source_history_field(
                provider=provider, field="last_name", value=""
            )
        user.save()
        user.refresh_from_db()
        self.assertTrue(has_performed_update)
        self.assertEqual(
            user.external_data_source_history,
            [
                {"field_name": "first_name", "value": "Lola", "source": provider.value, "created_at": now_str},
                {"field_name": "first_name", "value": "Jeanne", "source": provider.value, "created_at": now_str},
                {"field_name": "last_name", "value": "", "source": provider.value, "created_at": now_str},
            ],
        )

        # Allow replacing empty values.
        with mock.patch("django.utils.timezone.now", return_value=now):
            has_performed_update = user.update_external_data_source_history_field(
                provider=provider, field="last_name", value="Trombignard"
            )
        user.save()
        user.refresh_from_db()
        self.assertTrue(has_performed_update)
        self.assertEqual(
            user.external_data_source_history,
            [
                {"field_name": "first_name", "value": "Lola", "source": provider.value, "created_at": now_str},
                {"field_name": "first_name", "value": "Jeanne", "source": provider.value, "created_at": now_str},
                {"field_name": "last_name", "value": "", "source": provider.value, "created_at": now_str},
                {"field_name": "last_name", "value": "Trombignard", "source": provider.value, "created_at": now_str},
            ],
        )

    def test_last_hire_was_made_by_siae(self):
        job_application = JobApplicationSentByJobSeekerFactory(state=JobApplicationWorkflow.STATE_ACCEPTED)
        user = job_application.job_seeker
        siae = job_application.to_siae
        self.assertTrue(user.last_hire_was_made_by_siae(siae))
        siae2 = SiaeFactory()
        self.assertFalse(user.last_hire_was_made_by_siae(siae2))

    def test_last_accepted_job_application(self):
        # Set 2 job applications with:
        # - different hiring date
        # - same creation date
        # `last_accepted_job_application` is the one with the greater `hiring_start_at`
        now = timezone.now()
        job_application_1 = JobApplicationSentByJobSeekerFactory(
            state=JobApplicationWorkflow.STATE_ACCEPTED,
            created_at=now,
            hiring_start_at=now + relativedelta(days=1),
        )

        user = job_application_1.job_seeker

        job_application_2 = JobApplicationSentByJobSeekerFactory(
            state=JobApplicationWorkflow.STATE_ACCEPTED,
            created_at=now,
            job_seeker=user,
            hiring_start_at=now,
        )

        self.assertEqual(job_application_1, user.last_accepted_job_application)
        self.assertNotEqual(job_application_2, user.last_accepted_job_application)

    def test_valid_birth_place_and_country(self):
        """
        Birth place and country are not mandatory except for ASP / FS
        We must check that if the job seeker is born in France,
        if the commune is provided

        Otherwise, if the job seeker is born in another country,
        the commune must remain empty.
        """
        job_seeker = JobSeekerFactory()

        # Valid use cases:

        # No commune and no country
        self.assertIsNone(job_seeker.clean())

        # France and Commune filled
        job_seeker.birth_country = asp.CountryFranceFactory()
        job_seeker.birth_place = asp.CommuneFactory()
        self.assertIsNone(job_seeker.clean())

        # Europe and no commune
        job_seeker.birth_place = None
        job_seeker.birth_country = asp.CountryEuropeFactory()
        self.assertIsNone(job_seeker.clean())

        # Outside Europe and no commune
        job_seeker.birth_country = asp.CountryOutsideEuropeFactory()
        self.assertIsNone(job_seeker.clean())

        # Invalid use cases:

        # Europe and Commune filled
        job_seeker.birth_country = asp.CountryEuropeFactory()
        job_seeker.birth_place = asp.CommuneFactory()
        with self.assertRaises(ValidationError):
            job_seeker.clean()

        # Outside Europe and Commune filled
        job_seeker.birth_country = asp.CountryOutsideEuropeFactory()
        with self.assertRaises(ValidationError):
            job_seeker.clean()

    def test_can_edit_email(self):
        user = UserFactory()
        job_seeker = JobSeekerFactory()

        # Same user.
        self.assertFalse(user.can_edit_email(user))

        # All conditions are met.
        job_seeker = JobSeekerFactory(created_by=user)
        self.assertTrue(user.can_edit_email(job_seeker))

        # Job seeker logged in, he is not longer handled by a proxy.
        job_seeker = JobSeekerFactory(last_login=timezone.now())
        self.assertFalse(user.can_edit_email(job_seeker))

        # User did not create the job seeker's account.
        job_seeker = JobSeekerFactory(created_by=UserFactory())
        self.assertFalse(user.can_edit_email(job_seeker))

        # Job seeker has verified his email.
        job_seeker = JobSeekerFactory(created_by=user)
        job_seeker.emailaddress_set.create(email=job_seeker.email, verified=True)
        self.assertFalse(user.can_edit_email(job_seeker))

    def test_can_add_nir(self):
        siae = SiaeFactory(with_membership=True)
        siae_staff = siae.members.first()
        prescriber_org = PrescriberOrganizationWithMembershipFactory(authorized=True)
        authorized_prescriber = prescriber_org.members.first()
        unauthorized_prescriber = PrescriberFactory()
        job_seeker_no_nir = JobSeekerFactory(nir="")
        job_seeker_with_nir = JobSeekerFactory()

        self.assertTrue(authorized_prescriber.can_add_nir(job_seeker_no_nir))
        self.assertFalse(unauthorized_prescriber.can_add_nir(job_seeker_no_nir))
        self.assertTrue(siae_staff.can_add_nir(job_seeker_no_nir))
        self.assertFalse(authorized_prescriber.can_add_nir(job_seeker_with_nir))

    def test_is_account_creator(self):
        user = UserFactory()

        job_seeker = JobSeekerFactory(created_by=user)
        self.assertTrue(job_seeker.is_created_by(user))

        job_seeker = JobSeekerFactory()
        self.assertFalse(job_seeker.is_created_by(user))

        job_seeker = JobSeekerFactory(created_by=UserFactory())
        self.assertFalse(job_seeker.is_created_by(user))

    def test_has_verified_email(self):
        user = UserFactory()

        self.assertFalse(user.has_verified_email)
        address = user.emailaddress_set.create(email=user.email, verified=False)
        self.assertFalse(user.has_verified_email)
        address.delete()

        user.emailaddress_set.create(email=user.email, verified=True)
        self.assertTrue(user.has_verified_email)

    def test_siae_admin_can_create_siae_antenna(self):
        siae = SiaeFactory(with_membership=True, membership__is_admin=True)
        user = siae.members.get()
        self.assertTrue(user.can_create_siae_antenna(siae))

    def test_siae_normal_member_cannot_create_siae_antenna(self):
        siae = SiaeFactory(with_membership=True, membership__is_admin=False)
        user = siae.members.get()
        self.assertFalse(user.can_create_siae_antenna(siae))

    def test_siae_admin_without_convention_cannot_create_siae_antenna(self):
        siae = SiaeFactory(with_membership=True, convention=None)
        user = siae.members.get()
        self.assertFalse(user.can_create_siae_antenna(siae))

    def test_admin_ability_to_create_siae_antenna(self):
        for kind in SiaeKind:
            with self.subTest(kind=kind):
                siae = SiaeFactory(kind=kind, with_membership=True, membership__is_admin=True)
                user = siae.members.get()
                self.assertEqual(user.can_create_siae_antenna(siae), siae.should_have_convention)

    def test_can_view_stats_siae_hiring(self):
        # An employer can only view hiring stats of their own SIAE.
        deployed_department = settings.STATS_SIAE_DEPARTMENT_WHITELIST[0]
        siae1 = SiaeFactory(with_membership=True, department=deployed_department)
        user1 = siae1.members.get()
        siae2 = SiaeFactory(department=deployed_department)

        self.assertTrue(siae1.has_member(user1))
        self.assertTrue(user1.can_view_stats_siae_hiring(current_org=siae1))
        self.assertFalse(siae2.has_member(user1))
        self.assertFalse(user1.can_view_stats_siae_hiring(current_org=siae2))

        # Even non admin members can view their SIAE stats.
        siae3 = SiaeFactory(department=deployed_department, with_membership=True, membership__is_admin=False)
        user3 = siae3.members.get()
        self.assertTrue(user3.can_view_stats_siae_hiring(current_org=siae3))

        # Non deployed department cannot be accessed.
        non_deployed_departments = [dpt for dpt in DEPARTMENTS if dpt not in settings.STATS_SIAE_DEPARTMENT_WHITELIST]
        non_deployed_department = non_deployed_departments[0]
        siae4 = SiaeFactory(department=non_deployed_department, with_membership=True)
        user4 = siae4.members.get()
        self.assertFalse(user4.can_view_stats_siae_hiring(current_org=siae4))

    def test_can_view_stats_cd(self):
        """
        CD as in "Conseil Départemental".
        """
        # Admin prescriber of authorized CD can access.
        org = PrescriberOrganizationWithMembershipFactory(
            authorized=True, kind=PrescriberOrganizationKind.DEPT, department="93"
        )
        user = org.members.get()
        self.assertTrue(user.can_view_stats_cd(current_org=org))
        self.assertTrue(user.can_view_stats_dashboard_widget(current_org=org))
        self.assertEqual(user.get_stats_cd_department(current_org=org), org.department)

        # Non admin prescriber can access as well.
        org = PrescriberOrganizationWithMembershipFactory(
            authorized=True, kind=PrescriberOrganizationKind.DEPT, membership__is_admin=False, department="93"
        )
        user = org.members.get()
        self.assertTrue(user.can_view_stats_cd(current_org=org))
        self.assertTrue(user.can_view_stats_dashboard_widget(current_org=org))

        # Non authorized organization does not give access.
        org = PrescriberOrganizationWithMembershipFactory(kind=PrescriberOrganizationKind.DEPT)
        user = org.members.get()
        self.assertFalse(user.can_view_stats_cd(current_org=org))
        self.assertFalse(user.can_view_stats_dashboard_widget(current_org=org))

        # Non CD organization does not give access.
        org = PrescriberOrganizationWithMembershipFactory(authorized=True)
        user = org.members.get()
        self.assertFalse(user.can_view_stats_cd(current_org=org))
        self.assertFalse(user.can_view_stats_dashboard_widget(current_org=org))

        # Prescriber without organization cannot access.
        org = None
        user = PrescriberFactory()
        self.assertFalse(user.can_view_stats_cd(current_org=org))
        self.assertFalse(user.can_view_stats_dashboard_widget(current_org=org))

    def test_can_view_stats_ddets(self):
        """
        DDETS as in "Directions départementales de l’emploi, du travail et des solidarités"
        """
        # Admin member of DDETS can access.
        institution = InstitutionWithMembershipFactory(kind=InstitutionKind.DDETS, department="93")
        user = institution.members.get()
        self.assertTrue(user.can_view_stats_ddets(current_org=institution))
        self.assertTrue(user.can_view_stats_dashboard_widget(current_org=institution))
        self.assertEqual(user.get_stats_ddets_department(current_org=institution), institution.department)

        # Non admin member of DDETS can access as well.
        institution = InstitutionWithMembershipFactory(
            kind=InstitutionKind.DDETS, membership__is_admin=False, department="93"
        )
        user = institution.members.get()
        self.assertTrue(user.can_view_stats_ddets(current_org=institution))
        self.assertTrue(user.can_view_stats_dashboard_widget(current_org=institution))
        self.assertEqual(user.get_stats_ddets_department(current_org=institution), institution.department)

        # Member of institution of wrong kind cannot access.
        institution = InstitutionWithMembershipFactory(kind=InstitutionKind.OTHER, department="93")
        user = institution.members.get()
        self.assertFalse(user.can_view_stats_ddets(current_org=institution))
        self.assertFalse(user.can_view_stats_dashboard_widget(current_org=institution))

    def test_can_view_stats_dreets(self):
        """
        DREETS as in "Directions régionales de l’économie, de l’emploi, du travail et des solidarités"
        """
        # Admin member of DREETS can access.
        institution = InstitutionWithMembershipFactory(kind=InstitutionKind.DREETS, department="93")
        user = institution.members.get()
        self.assertTrue(user.can_view_stats_dreets(current_org=institution))
        self.assertTrue(user.can_view_stats_dashboard_widget(current_org=institution))
        self.assertEqual(user.get_stats_dreets_region(current_org=institution), institution.region)

        # Non admin member of DREETS can access as well.
        institution = InstitutionWithMembershipFactory(
            kind=InstitutionKind.DREETS, membership__is_admin=False, department="93"
        )
        user = institution.members.get()
        self.assertTrue(user.can_view_stats_dreets(current_org=institution))
        self.assertTrue(user.can_view_stats_dashboard_widget(current_org=institution))
        self.assertEqual(user.get_stats_dreets_region(current_org=institution), institution.region)

        # Member of institution of wrong kind cannot access.
        institution = InstitutionWithMembershipFactory(kind=InstitutionKind.OTHER, department="93")
        user = institution.members.get()
        self.assertFalse(user.can_view_stats_dreets(current_org=institution))
        self.assertFalse(user.can_view_stats_dashboard_widget(current_org=institution))

    def test_can_view_stats_dgefp(self):
        """
        DGEFP as in "délégation générale à l'Emploi et à la Formation professionnelle"
        """
        # Admin member of DGEFP can access.
        institution = InstitutionWithMembershipFactory(kind=InstitutionKind.DGEFP, department="93")
        user = institution.members.get()
        self.assertTrue(user.can_view_stats_dgefp(current_org=institution))
        self.assertTrue(user.can_view_stats_dashboard_widget(current_org=institution))

        # Non admin member of DGEFP can access as well.
        institution = InstitutionWithMembershipFactory(
            kind=InstitutionKind.DGEFP, membership__is_admin=False, department="93"
        )
        user = institution.members.get()
        self.assertTrue(user.can_view_stats_dgefp(current_org=institution))
        self.assertTrue(user.can_view_stats_dashboard_widget(current_org=institution))

        # Member of institution of wrong kind cannot access.
        institution = InstitutionWithMembershipFactory(kind=InstitutionKind.OTHER, department="93")
        user = institution.members.get()
        self.assertFalse(user.can_view_stats_dgefp(current_org=institution))
        self.assertFalse(user.can_view_stats_dashboard_widget(current_org=institution))

    def test_a_user_can_only_have_one_kind(self):
        unique_fields = ["is_job_seeker", "is_prescriber", "is_siae_staff", "is_labor_inspector"]

        for field in unique_fields:
            UserFactory(**{field: True})

        for n in range(2, 5):
            for fields in itertools.combinations(unique_fields, n):
                with self.assertRaises(ValidationError):
                    UserFactory(**dict(zip(fields, itertools.repeat(True))))


def mock_get_geocoding_data(address, post_code=None, limit=1):
    return RESULTS_BY_ADDRESS.get(address)


class JobSeekerProfileModelTest(TestCase):
    """
    Model test for JobSeekerProfile

    Job seeker profile is extra-data from the ASP and EmployeeRecord domains
    """

    def setUp(self):
        self.profile = JobSeekerProfileFactory()
        user = self.profile.user
        user.title = None

        # FIXME Crap, must find a better way of creating fixture
        asp.MockedCommuneFactory()
        data = BAN_GEOCODING_API_RESULTS_MOCK[0]

        user.address_line_1 = data.get("address_line_1")

    def test_job_seeker_details(self):

        # No title on User
        with self.assertRaises(ValidationError):
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
        with self.assertRaises(ValidationError):
            self.profile._clean_job_seeker_hexa_address()

        self.profile.hexa_lane_number = "4"
        with self.assertRaises(ValidationError):
            self.profile._clean_job_seeker_hexa_address()

        self.profile.hexa_lane_type = "RUE"
        with self.assertRaises(ValidationError):
            self.profile._clean_job_seeker_hexa_address()

        self.profile.hexa_post_code = "12345"
        with self.assertRaises(ValidationError):
            self.profile._clean_job_seeker_hexa_address()

        # address should be complete now
        self.profile.hexa_commune = asp.CommuneFactory()
        self.profile._clean_job_seeker_hexa_address()

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
        with self.assertRaises(ValidationError):
            self.profile._clean_job_seeker_details()

        self.profile.user.title = Title.M

        # No education level provided
        self.profile.education_level = None
        with self.assertRaises(ValidationError):
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
        self.assertFalse(self.profile.is_employed)

        self.profile.unemployed_since = None
        self.profile.previous_employer_kind = EmployerType.ACI

        self.profile._clean_job_seeker_situation()
        self.assertTrue(self.profile.is_employed)

        # Check coherence
        with self.assertRaises(ValidationError):
            # Can't have both
            self.profile.unemployed_since = AllocationDuration.MORE_THAN_24_MONTHS
            self.profile.previous_employer_kind = EmployerType.ACI
            self.profile._clean_job_seeker_situation()


def user_with_approval_in_waiting_period():
    user = JobSeekerFactory()
    end_at = timezone.now().date() - relativedelta(days=30)
    start_at = end_at - relativedelta(years=2)
    ApprovalFactory(user=user, start_at=start_at, end_at=end_at)
    return user


class LatestApprovalTestCase(TestCase):
    def test_merge_approvals_timeline_case1(self):

        user = JobSeekerFactory()

        ApprovalFactory(user=user, start_at=datetime.date(2016, 12, 20), end_at=datetime.date(2018, 12, 20))

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
        self.assertEqual(user.latest_common_approval, pe_approval_1)
        self.assertEqual(user.latest_approval, None)
        self.assertEqual(user.latest_pe_approval, pe_approval_1)

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
        self.assertEqual(user.latest_common_approval, pe_approval_2)
        self.assertEqual(user.latest_approval, None)
        self.assertEqual(user.latest_pe_approval, pe_approval_2)

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

        self.assertEqual(user.latest_approval, pass_iae)

    def test_status_without_approval(self):
        user = JobSeekerFactory()
        self.assertTrue(user.has_no_common_approval)
        self.assertFalse(user.has_valid_common_approval)
        self.assertFalse(user.has_common_approval_in_waiting_period)
        self.assertEqual(user.latest_approval, None)

    def test_status_with_valid_approval(self):
        user = JobSeekerFactory()
        approval = ApprovalFactory(user=user, start_at=timezone.now().date() - relativedelta(days=1))
        self.assertFalse(user.has_no_common_approval)
        self.assertTrue(user.has_valid_common_approval)
        self.assertFalse(user.has_common_approval_in_waiting_period)
        self.assertEqual(user.latest_approval, approval)

    def test_status_approval_in_waiting_period(self):
        user = user_with_approval_in_waiting_period()
        self.assertFalse(user.has_no_common_approval)
        self.assertFalse(user.has_valid_common_approval)
        self.assertTrue(user.has_common_approval_in_waiting_period)
        self.assertEqual(user.latest_approval, user.latest_approval)

    def test_status_approval_with_elapsed_waiting_period(self):
        user = JobSeekerFactory()
        end_at = timezone.now().date() - relativedelta(years=3)
        start_at = end_at - relativedelta(years=2)
        ApprovalFactory(user=user, start_at=start_at, end_at=end_at)
        self.assertTrue(user.has_no_common_approval)
        self.assertFalse(user.has_valid_common_approval)
        self.assertFalse(user.has_common_approval_in_waiting_period)
        self.assertEqual(user.latest_approval, None)

    def test_status_with_valid_pole_emploi_approval(self):
        user = JobSeekerFactory()
        pe_approval = PoleEmploiApprovalFactory(pole_emploi_id=user.pole_emploi_id, birthdate=user.birthdate)
        self.assertFalse(user.has_no_common_approval)
        self.assertTrue(user.has_valid_common_approval)
        self.assertFalse(user.has_common_approval_in_waiting_period)
        self.assertEqual(user.latest_approval, None)
        self.assertEqual(user.latest_pe_approval, pe_approval)

    def test_cannot_bypass_waiting_period(self):
        user = user_with_approval_in_waiting_period()

        # Waiting period cannot be bypassed for SIAE if no prescriber.
        self.assertTrue(
            user.approval_can_be_renewed_by(siae=SiaeFactory(kind=SiaeKind.ETTI), sender_prescriber_organization=None)
        )

        # Waiting period cannot be bypassed for SIAE if unauthorized prescriber.
        self.assertTrue(
            user.approval_can_be_renewed_by(
                siae=SiaeFactory(kind=SiaeKind.ETTI),
                sender_prescriber_organization=PrescriberOrganizationFactory(),
            )
        )

        # Waiting period is bypassed for SIAE if authorized prescriber.
        self.assertFalse(
            user.approval_can_be_renewed_by(
                siae=SiaeFactory(kind=SiaeKind.ETTI),
                sender_prescriber_organization=PrescriberOrganizationFactory(authorized=True),
            )
        )

        # Waiting period is bypassed for GEIQ even if no prescriber.
        self.assertFalse(
            user.approval_can_be_renewed_by(siae=SiaeFactory(kind=SiaeKind.GEIQ), sender_prescriber_organization=None)
        )

        # Waiting period is bypassed for GEIQ even if unauthorized prescriber.
        self.assertFalse(
            user.approval_can_be_renewed_by(
                siae=SiaeFactory(kind=SiaeKind.GEIQ),
                sender_prescriber_organization=PrescriberOrganizationFactory(),
            )
        )

        # Waiting period is bypassed if a valid diagnosis made by an authorized prescriber exists.
        diag = EligibilityDiagnosisFactory(job_seeker=user)
        self.assertFalse(
            user.approval_can_be_renewed_by(
                siae=SiaeFactory(kind=SiaeKind.ETTI),
                sender_prescriber_organization=None,
            )
        )
        diag.delete()

        # Waiting period cannot be bypassed if a valid diagnosis exists
        # but was not made by an authorized prescriber.
        diag = EligibilityDiagnosisMadeBySiaeFactory(job_seeker=user)
        self.assertTrue(
            user.approval_can_be_renewed_by(
                siae=SiaeFactory(kind=SiaeKind.ETTI),
                sender_prescriber_organization=None,
            )
        )

    def test_latest_common_approval_no_approval(self):
        user = JobSeekerFactory()
        self.assertIsNone(user.latest_common_approval)

    def test_latest_common_approval_when_only_pe_approval(self):
        user = JobSeekerFactory()
        pe_approval = PoleEmploiApprovalFactory(nir=user.nir)
        self.assertEqual(user.latest_common_approval, pe_approval)

    def test_latest_common_approval_is_approval_if_valid(self):
        user = JobSeekerFactory()
        approval = ApprovalFactory(user=user)
        PoleEmploiApprovalFactory(nir=user.nir)
        self.assertEqual(user.latest_common_approval, approval)

    def test_latest_common_approval_is_pe_approval_if_approval_is_expired(self):
        user = JobSeekerFactory()
        end_at = timezone.now().date() - relativedelta(years=3)
        start_at = end_at - relativedelta(years=2)
        # expired approval
        ApprovalFactory(user=user, start_at=start_at, end_at=end_at)
        pe_approval = PoleEmploiApprovalFactory(nir=user.nir)
        self.assertEqual(user.latest_common_approval, pe_approval)

    def test_latest_common_approval_is_pe_approval_edge_case(self):
        user = JobSeekerFactory()
        end_at = timezone.now().date() - relativedelta(days=10)
        start_at = end_at - relativedelta(years=2)
        # approval in waiting period
        ApprovalFactory(user=user, start_at=start_at, end_at=end_at)
        pe_approval = PoleEmploiApprovalFactory(nir=user.nir)
        self.assertEqual(user.latest_common_approval, pe_approval)

    def test_latest_common_approval_is_none_if_both_expired(self):
        user = JobSeekerFactory()
        end_at = timezone.now().date() - relativedelta(years=3)
        start_at = end_at - relativedelta(years=2)
        ApprovalFactory(user=user, start_at=start_at, end_at=end_at)
        PoleEmploiApprovalFactory(nir=user.nir, start_at=start_at, end_at=end_at)
        self.assertIsNone(user.latest_common_approval)
