from django.contrib.auth import get_user_model
from django.core.exceptions import ValidationError
from django.test import TestCase
from django.utils import timezone

from itou.job_applications.factories import JobApplicationSentByJobSeekerFactory
from itou.job_applications.models import JobApplicationWorkflow
from itou.siaes.factories import SiaeFactory
from itou.users.factories import JobSeekerFactory, PrescriberFactory, UserFactory


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

    def test_is_currently_hired_by_siae(self):
        job_application = JobApplicationSentByJobSeekerFactory(state=JobApplicationWorkflow.STATE_ACCEPTED)
        user = job_application.job_seeker
        siae = job_application.to_siae
        self.assertTrue(user.is_currently_hired_by_siae(siae))
        siae2 = SiaeFactory()
        self.assertFalse(user.is_currently_hired_by_siae(siae2))
