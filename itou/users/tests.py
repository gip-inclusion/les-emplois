from unittest import mock

from django.contrib.auth import get_user_model
from django.core.exceptions import ValidationError
from django.test import TestCase
from django.utils import timezone

import itou.asp.factories as asp
from itou.job_applications.factories import JobApplicationSentByJobSeekerFactory
from itou.job_applications.models import JobApplicationWorkflow
from itou.siaes.factories import SiaeFactory
from itou.users.factories import JobSeekerFactory, JobSeekerProfileFactory, PrescriberFactory, UserFactory
from itou.utils.mocks.address_format import BAN_GEOCODING_API_RESULTS_MOCK, RESULTS_BY_ADDRESS


class ModelTest(TestCase):
    def test_create_job_seeker_by_proxy(self):

        User = get_user_model()

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

        User = get_user_model()

        job_seeker = JobSeekerFactory(pole_emploi_id="", lack_of_pole_emploi_id_reason="")

        # Both fields cannot be empty.
        with self.assertRaises(ValidationError):
            User.clean_pole_emploi_fields(job_seeker.pole_emploi_id, job_seeker.lack_of_pole_emploi_id_reason)

        # Both fields cannot be present at the same time.
        job_seeker = JobSeekerFactory(pole_emploi_id="69970749", lack_of_pole_emploi_id_reason=User.REASON_FORGOTTEN)
        with self.assertRaises(ValidationError):
            User.clean_pole_emploi_fields(job_seeker.pole_emploi_id, job_seeker.lack_of_pole_emploi_id_reason)

        # No exception should be raised for the following cases.

        job_seeker = JobSeekerFactory(pole_emploi_id="62723349", lack_of_pole_emploi_id_reason="")
        User.clean_pole_emploi_fields(job_seeker.pole_emploi_id, job_seeker.lack_of_pole_emploi_id_reason)

        job_seeker = JobSeekerFactory(pole_emploi_id="", lack_of_pole_emploi_id_reason=User.REASON_FORGOTTEN)
        User.clean_pole_emploi_fields(job_seeker.pole_emploi_id, job_seeker.lack_of_pole_emploi_id_reason)

    def test_email_already_exists(self):
        JobSeekerFactory(email="foo@bar.com")
        User = get_user_model()
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

    def test_create_job_seeker_profile(self):
        """
        User title is not needed for validation of a User objects

        It is mandatory for validation of JobSeekerProfile objects
        """
        job_seeker = JobSeekerFactory()
        job_seeker.get_or_create_job_seeker_profile()

        self.assertIsNotNone(job_seeker.jobseeker_profile)


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
        # user.
        # user.post_code = data.get("post_code")

    def test_job_seeker_details(self):
        User = get_user_model()

        # No title on User
        with self.assertRaises(ValidationError):
            self.profile.clean()

        self.profile.user.title = User.Title.M

        # Won't raise exception
        self.profile.clean()

    def test_social_allowances(self):
        """
        Check if the social allowances part is coherent
        """
        User = get_user_model()
        self.profile.user.title = User.Title.M

        self.profile.resourceless = True
        self.profile.rqth_employee = True

        with self.assertRaises(ValidationError):
            self.profile.clean()

        self.profile.resourceless = False
        self.profile.clean()

        self.profile.resourceless = True
        self.profile.oeth_employee = True
        self.profile.rqth_employee = False

        with self.assertRaises(ValidationError):
            self.profile.clean()

        self.profile.resourceless = False
        self.profile.clean()

        # More to come ...

    @mock.patch(
        "itou.utils.address.format.get_geocoding_data",
        side_effect=mock_get_geocoding_data,
    )
    def test_update_hexa_address(self, _mock):
        """
        Check creation of an HEXA address from job seeker address
        """
        User = get_user_model()
        self.profile.user.title = User.Title.M
        self.profile.update_hexa_address()
        self.profile.clean()

    @mock.patch(
        "itou.utils.address.format.get_geocoding_data",
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

        user.pole_emploi_id = None
        self.profile.pole_emploi_since = "MORE_THAN_24_MONTHS"
        with self.assertRaises(ValidationError):
            self.profile._clean_job_seeker_situation()

        # Both PE fields are provided: OK
        user.pole_emploi_id = "1234567"
        self.profile._clean_job_seeker_situation()

    def test_job_seeker_details_complete(self):
        self.profile.user.title = None

        # No user title provided
        with self.assertRaises(ValidationError):
            self.profile._clean_job_seeker_details()

        self.profile.user.title = get_user_model().Title.M

        # No education level provided
        self.profile.education_level = None
        with self.assertRaises(ValidationError):
            self.profile._clean_job_seeker_details()

        self.profile.education_level = "00"
        self.profile._clean_job_seeker_details()

        # Birth place / birth country are checked in User tests
