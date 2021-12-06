import datetime
import uuid
from unittest import mock

from django.core.exceptions import ValidationError
from django.core.management import call_command
from django.test import TestCase
from django.utils import timezone

import itou.asp.factories as asp
from itou.approvals.factories import ApprovalFactory
from itou.asp.models import AllocationDuration, EmployerType
from itou.eligibility.models import EligibilityDiagnosis
from itou.institutions.factories import InstitutionWithMembershipFactory
from itou.institutions.models import Institution
from itou.job_applications.factories import (
    JobApplicationSentByJobSeekerFactory,
    JobApplicationWithApprovalFactory,
    JobApplicationWithEligibilityDiagnosis,
)
from itou.job_applications.models import JobApplication, JobApplicationWorkflow
from itou.prescribers.factories import (
    AuthorizedPrescriberOrganizationWithMembershipFactory,
    PrescriberMembershipFactory,
    PrescriberOrganizationWithMembershipFactory,
)
from itou.prescribers.models import PrescriberOrganization
from itou.siaes.factories import SiaeFactory, SiaeWithMembershipFactory
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


class ManagementCommandsTest(TestCase):
    """
    Test the deduplication of several users.

    This is temporary and should be deleted after the release of the NIR
    which should prevent duplication.
    """

    def test_deduplicate_job_seekers(self):
        """
        Easy case : among all the duplicates, only one has a PASS IAE.
        """

        # Attributes shared by all users.
        # Deduplication is based on these values.
        kwargs = {
            "job_seeker__pole_emploi_id": "6666666B",
            "job_seeker__birthdate": datetime.date(2002, 12, 12),
        }

        # Create `user1`.
        job_app1 = JobApplicationWithApprovalFactory(job_seeker__nir=None, **kwargs)
        user1 = job_app1.job_seeker

        self.assertIsNone(user1.nir)
        self.assertEqual(1, user1.approvals.count())
        self.assertEqual(1, user1.job_applications.count())
        self.assertEqual(1, user1.eligibility_diagnoses.count())

        # Create `user2`.
        job_app2 = JobApplicationWithEligibilityDiagnosis(job_seeker__nir=None, **kwargs)
        user2 = job_app2.job_seeker

        self.assertIsNone(user2.nir)
        self.assertEqual(0, user2.approvals.count())
        self.assertEqual(1, user2.job_applications.count())
        self.assertEqual(1, user2.eligibility_diagnoses.count())

        # Create `user3`.
        job_app3 = JobApplicationWithEligibilityDiagnosis(**kwargs)
        user3 = job_app3.job_seeker
        expected_nir = user3.nir

        self.assertIsNotNone(user3.nir)
        self.assertEqual(0, user3.approvals.count())
        self.assertEqual(1, user3.job_applications.count())
        self.assertEqual(1, user3.eligibility_diagnoses.count())

        # Merge all users into `user1`.
        call_command("deduplicate_job_seekers", verbosity=0, no_csv=True)

        # If only one NIR exists for all the duplicates, it should
        # be reassigned to the target account.
        user1.refresh_from_db()
        self.assertEqual(user1.nir, expected_nir)

        self.assertEqual(3, user1.job_applications.count())
        self.assertEqual(3, user1.eligibility_diagnoses.count())
        self.assertEqual(1, user1.approvals.count())

        self.assertEqual(0, User.objects.filter(email=user2.email).count())
        self.assertEqual(0, User.objects.filter(email=user3.email).count())

        self.assertEqual(0, JobApplication.objects.filter(job_seeker=user2).count())
        self.assertEqual(0, JobApplication.objects.filter(job_seeker=user3).count())

        self.assertEqual(0, EligibilityDiagnosis.objects.filter(job_seeker=user2).count())
        self.assertEqual(0, EligibilityDiagnosis.objects.filter(job_seeker=user3).count())

    def test_deduplicate_job_seekers_without_empty_sender_field(self):
        """
        Easy case: among all the duplicates, only one has a PASS IAE.
        Ensure that the `sender` field is never left empty.
        """

        # Attributes shared by all users.
        # Deduplication is based on these values.
        kwargs = {
            "job_seeker__pole_emploi_id": "6666666B",
            "job_seeker__birthdate": datetime.date(2002, 12, 12),
        }

        # Create `user1` through a job application sent by him.
        job_app1 = JobApplicationSentByJobSeekerFactory(job_seeker__nir=None, **kwargs)
        user1 = job_app1.job_seeker

        self.assertEqual(1, user1.job_applications.count())
        self.assertEqual(job_app1.sender, user1)

        # Create `user2` through a job application sent by him.
        job_app2 = JobApplicationSentByJobSeekerFactory(job_seeker__nir=None, **kwargs)
        user2 = job_app2.job_seeker

        self.assertEqual(1, user2.job_applications.count())
        self.assertEqual(job_app2.sender, user2)

        # Create `user3` through a job application sent by a prescriber.
        job_app3 = JobApplicationWithEligibilityDiagnosis(job_seeker__nir=None, **kwargs)
        user3 = job_app3.job_seeker
        self.assertNotEqual(job_app3.sender, user3)
        job_app3_sender = job_app3.sender  # The sender is a prescriber.

        # Ensure that `user1` will always be the target into which duplicates will be merged
        # by attaching a PASS IAE to him.
        self.assertEqual(0, user1.approvals.count())
        self.assertEqual(0, user2.approvals.count())
        self.assertEqual(0, user3.approvals.count())
        ApprovalFactory(user=user1)

        # Merge all users into `user1`.
        call_command("deduplicate_job_seekers", verbosity=0, no_csv=True)

        self.assertEqual(3, user1.job_applications.count())

        job_app1.refresh_from_db()
        job_app2.refresh_from_db()
        job_app3.refresh_from_db()

        self.assertEqual(job_app1.sender, user1)
        self.assertEqual(job_app2.sender, user1)  # The sender must now be user1.
        self.assertEqual(job_app3.sender, job_app3_sender)  # The sender must still be a prescriber.

        self.assertEqual(0, User.objects.filter(email=user2.email).count())
        self.assertEqual(0, User.objects.filter(email=user3.email).count())

        self.assertEqual(0, JobApplication.objects.filter(job_seeker=user2).count())
        self.assertEqual(0, JobApplication.objects.filter(job_seeker=user3).count())

        self.assertEqual(0, EligibilityDiagnosis.objects.filter(job_seeker=user2).count())
        self.assertEqual(0, EligibilityDiagnosis.objects.filter(job_seeker=user3).count())


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

    def test_last_hire_was_made_by_siae(self):
        job_application = JobApplicationSentByJobSeekerFactory(state=JobApplicationWorkflow.STATE_ACCEPTED)
        user = job_application.job_seeker
        siae = job_application.to_siae
        self.assertTrue(user.last_hire_was_made_by_siae(siae))
        siae2 = SiaeFactory()
        self.assertFalse(user.last_hire_was_made_by_siae(siae2))

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
        siae = SiaeWithMembershipFactory()
        siae_staff = siae.members.first()
        prescriber_org = AuthorizedPrescriberOrganizationWithMembershipFactory()
        authorized_prescriber = prescriber_org.members.first()
        unauthorized_prescriber = PrescriberFactory()
        job_seeker_no_nir = JobSeekerFactory(nir="")
        job_seeker_with_nir = JobSeekerFactory()

        self.assertTrue(authorized_prescriber.can_add_nir(job_seeker_no_nir))
        self.assertFalse(unauthorized_prescriber.can_add_nir(job_seeker_no_nir))
        self.assertTrue(siae_staff.can_add_nir(job_seeker_no_nir))
        self.assertFalse(authorized_prescriber.can_add_nir(job_seeker_with_nir))

    def test_nir_with_spaces(self):
        job_seeker = JobSeekerFactory.build(nir="141068078200557")
        self.assertEqual(job_seeker.nir_with_spaces, "1 41 06 80 782 005 57")

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

    def test_can_view_stats_siae(self):
        # An employer can only view stats of their own SIAE.
        siae1 = SiaeWithMembershipFactory()
        user1 = siae1.members.get()
        siae2 = SiaeFactory()

        self.assertTrue(siae1.has_member(user1))
        self.assertTrue(user1.can_view_stats_siae(current_org=siae1))
        self.assertFalse(siae2.has_member(user1))
        self.assertFalse(user1.can_view_stats_siae(current_org=siae2))

        # Even non admin members can view their SIAE stats.
        siae3 = SiaeWithMembershipFactory(membership__is_admin=False)
        user3 = siae3.members.get()
        self.assertTrue(user3.can_view_stats_siae(current_org=siae3))

    def test_can_view_stats_cd(self):
        """
        CD as in "Conseil Départemental".
        """
        # Admin prescriber of authorized CD can access.
        org = AuthorizedPrescriberOrganizationWithMembershipFactory(
            kind=PrescriberOrganization.Kind.DEPT, department="93"
        )
        user = org.members.get()
        self.assertTrue(user.can_view_stats_cd(current_org=org))
        self.assertTrue(user.can_view_stats_dashboard_widget(current_org=org))
        self.assertEqual(user.get_stats_cd_department(current_org=org), org.department)

        # Non admin prescriber can access as well.
        org = AuthorizedPrescriberOrganizationWithMembershipFactory(
            kind=PrescriberOrganization.Kind.DEPT, membership__is_admin=False, department="93"
        )
        user = org.members.get()
        self.assertTrue(user.can_view_stats_cd(current_org=org))
        self.assertTrue(user.can_view_stats_dashboard_widget(current_org=org))

        # Non authorized organization does not give access.
        org = PrescriberOrganizationWithMembershipFactory(kind=PrescriberOrganization.Kind.DEPT)
        user = org.members.get()
        self.assertFalse(user.can_view_stats_cd(current_org=org))
        self.assertFalse(user.can_view_stats_dashboard_widget(current_org=org))

        # Non CD organization does not give access.
        org = AuthorizedPrescriberOrganizationWithMembershipFactory()
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
        institution = InstitutionWithMembershipFactory(kind=Institution.Kind.DDETS, department="93")
        user = institution.members.get()
        self.assertTrue(user.can_view_stats_ddets(current_org=institution))
        self.assertTrue(user.can_view_stats_dashboard_widget(current_org=institution))
        self.assertEqual(user.get_stats_ddets_department(current_org=institution), institution.department)

        # Non admin member of DDETS can access as well.
        institution = InstitutionWithMembershipFactory(
            kind=Institution.Kind.DDETS, membership__is_admin=False, department="93"
        )
        user = institution.members.get()
        self.assertTrue(user.can_view_stats_ddets(current_org=institution))
        self.assertTrue(user.can_view_stats_dashboard_widget(current_org=institution))
        self.assertEqual(user.get_stats_ddets_department(current_org=institution), institution.department)

        # Member of institution of wrong kind cannot access.
        institution = InstitutionWithMembershipFactory(kind=Institution.Kind.OTHER, department="93")
        user = institution.members.get()
        self.assertFalse(user.can_view_stats_ddets(current_org=institution))
        self.assertFalse(user.can_view_stats_dashboard_widget(current_org=institution))

    def test_can_view_stats_dreets(self):
        """
        DREETS as in "Directions régionales de l’économie, de l’emploi, du travail et des solidarités"
        """
        # Admin member of DREETS can access.
        institution = InstitutionWithMembershipFactory(kind=Institution.Kind.DREETS, department="93")
        user = institution.members.get()
        self.assertTrue(user.can_view_stats_dreets(current_org=institution))
        self.assertTrue(user.can_view_stats_dashboard_widget(current_org=institution))
        self.assertEqual(user.get_stats_dreets_region(current_org=institution), institution.region)

        # Non admin member of DREETS can access as well.
        institution = InstitutionWithMembershipFactory(
            kind=Institution.Kind.DREETS, membership__is_admin=False, department="93"
        )
        user = institution.members.get()
        self.assertTrue(user.can_view_stats_dreets(current_org=institution))
        self.assertTrue(user.can_view_stats_dashboard_widget(current_org=institution))
        self.assertEqual(user.get_stats_dreets_region(current_org=institution), institution.region)

        # Member of institution of wrong kind cannot access.
        institution = InstitutionWithMembershipFactory(kind=Institution.Kind.OTHER, department="93")
        user = institution.members.get()
        self.assertFalse(user.can_view_stats_dreets(current_org=institution))
        self.assertFalse(user.can_view_stats_dashboard_widget(current_org=institution))

    def test_can_view_stats_dgefp(self):
        """
        DGEFP as in "délégation générale à l'Emploi et à la Formation professionnelle"
        """
        # Admin member of DGEFP can access.
        institution = InstitutionWithMembershipFactory(kind=Institution.Kind.DGEFP, department="93")
        user = institution.members.get()
        self.assertTrue(user.can_view_stats_dgefp(current_org=institution))
        self.assertTrue(user.can_view_stats_dashboard_widget(current_org=institution))

        # Non admin member of DGEFP can access as well.
        institution = InstitutionWithMembershipFactory(
            kind=Institution.Kind.DGEFP, membership__is_admin=False, department="93"
        )
        user = institution.members.get()
        self.assertTrue(user.can_view_stats_dgefp(current_org=institution))
        self.assertTrue(user.can_view_stats_dashboard_widget(current_org=institution))

        # Member of institution of wrong kind cannot access.
        institution = InstitutionWithMembershipFactory(kind=Institution.Kind.OTHER, department="93")
        user = institution.members.get()
        self.assertFalse(user.can_view_stats_dgefp(current_org=institution))
        self.assertFalse(user.can_view_stats_dashboard_widget(current_org=institution))


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

        # FIXME Crap, must find a better way of creating fixture
        asp.MockedCommuneFactory()
        data = BAN_GEOCODING_API_RESULTS_MOCK[0]

        user.address_line_1 = data.get("address_line_1")

    def test_job_seeker_details(self):

        # No title on User
        with self.assertRaises(ValidationError):
            self.profile.clean_model()

        self.profile.user.title = User.Title.M

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
        self.profile.user.title = User.Title.M
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

        self.profile.user.title = User.Title.M

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
        self.profile.user.title = User.Title.M
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
