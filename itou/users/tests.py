import datetime

from dateutil.relativedelta import relativedelta
from django.contrib.auth import get_user_model
from django.core.exceptions import ValidationError
from django.test import TestCase

from itou.approvals.factories import PoleEmploiApprovalFactory
from itou.eligibility.factories import (
    ExpiredPrescriberEligibilityDiagnosisFactory,
    ExpiredSiaeEligibilityDiagnosisFactory,
    PrescriberEligibilityDiagnosisFactory,
    SiaeEligibilityDiagnosisFactory,
)
from itou.users.factories import JobSeekerFactory, PrescriberFactory


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

    def test_has_valid_prescriber_diagnosis(self):

        # No diagnosis.
        job_seeker = JobSeekerFactory()
        self.assertFalse(job_seeker.has_valid_prescriber_diagnosis)

        # Has a diagnosis made by a prescriber.
        job_seeker = JobSeekerFactory()
        PrescriberEligibilityDiagnosisFactory(job_seeker=job_seeker)
        self.assertTrue(job_seeker.has_valid_prescriber_diagnosis)

        # Has a diagnosis made by an SIAE.
        job_seeker = JobSeekerFactory()
        SiaeEligibilityDiagnosisFactory(job_seeker=job_seeker)
        self.assertFalse(job_seeker.has_valid_prescriber_diagnosis)

        # Has a valid Pôle emploi diagnosis.
        job_seeker = JobSeekerFactory()
        PoleEmploiApprovalFactory(pole_emploi_id=job_seeker.pole_emploi_id, birthdate=job_seeker.birthdate)
        self.assertTrue(job_seeker.has_valid_prescriber_diagnosis)

        # Has an expired Pôle emploi diagnosis.
        job_seeker = JobSeekerFactory()
        end_at = datetime.date.today() - relativedelta(years=2)
        start_at = end_at - relativedelta(years=2)
        PoleEmploiApprovalFactory(
            pole_emploi_id=job_seeker.pole_emploi_id, birthdate=job_seeker.birthdate, start_at=start_at, end_at=end_at
        )
        self.assertFalse(job_seeker.has_valid_prescriber_diagnosis)

        # Has an expired diagnosis made by a Prescriber
        job_seeker = JobSeekerFactory()
        ExpiredPrescriberEligibilityDiagnosisFactory(job_seeker=job_seeker)
        self.assertFalse(job_seeker.has_valid_prescriber_diagnosis)

        # Has an expired diagnosis made by an Employer
        job_seeker = JobSeekerFactory()
        ExpiredSiaeEligibilityDiagnosisFactory(job_seeker=job_seeker)
        self.assertFalse(job_seeker.has_valid_prescriber_diagnosis)

    def test_get_eligibility_diagnosis(self):
        # No eligibility_diagnosis
        job_seeker = JobSeekerFactory()
        self.assertFalse(job_seeker.get_eligibility_diagnosis())

        # Diagnosis from prescribers
        job_seeker = JobSeekerFactory()
        diagnosis = PrescriberEligibilityDiagnosisFactory(job_seeker=job_seeker)
        self.assertEqual(job_seeker.get_eligibility_diagnosis(), diagnosis)

        # Diagnosis from prescribers and SIAE. Last diagnosis is from an SIAE.
        job_seeker = JobSeekerFactory()
        PrescriberEligibilityDiagnosisFactory(job_seeker=job_seeker)
        diagnosis = SiaeEligibilityDiagnosisFactory(job_seeker=job_seeker)
        self.assertEqual(job_seeker.get_eligibility_diagnosis(siae=diagnosis.author_siae), diagnosis)

        # Diagnosis from prescribers and SIAE. Last diagnosis is from a prescriber.
        job_seeker = JobSeekerFactory()
        SiaeEligibilityDiagnosisFactory(job_seeker=job_seeker)
        diagnosis = PrescriberEligibilityDiagnosisFactory(job_seeker=job_seeker)
        self.assertEqual(job_seeker.get_eligibility_diagnosis(siae=diagnosis.author_siae), diagnosis)

        # Diagnosis from prescribers and SIAE. Get only prescribers diagnosis.
        job_seeker = JobSeekerFactory()
        prescriber_diagnosis = PrescriberEligibilityDiagnosisFactory(job_seeker=job_seeker)
        SiaeEligibilityDiagnosisFactory(job_seeker=job_seeker)
        self.assertEqual(job_seeker.get_eligibility_diagnosis(), prescriber_diagnosis)

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
        User = get_user_model()

        unique_email = "foo@foo.com"

        User.objects.create(username="foo", email=unique_email)

        with self.assertRaises(ValidationError):
            # Creating a user with an existing email should raise an error.
            User.objects.create(username="foo2", email=unique_email)

        bar = User.objects.create(username="bar", email="bar@bar.com")
        # Update email.
        bar.email = "baz@baz.com"
        bar.save()
        with self.assertRaises(ValidationError):
            # Updating a user with an existing email should raise an error.
            bar.email = unique_email
            bar.save()
