import datetime

from dateutil.relativedelta import relativedelta

from django.contrib.auth import get_user_model
from django.test import TestCase

from itou.approvals.factories import PoleEmploiApprovalFactory
from itou.eligibility.factories import EligibilityDiagnosisFactory
from itou.users.factories import JobSeekerFactory
from itou.users.factories import PrescriberFactory


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

    def test_has_eligibility_diagnosis(self):

        # No diagnosis.
        job_seeker = JobSeekerFactory()
        self.assertFalse(job_seeker.has_eligibility_diagnosis)

        # Has Itou diagnosis.
        job_seeker = JobSeekerFactory()
        EligibilityDiagnosisFactory(job_seeker=job_seeker)
        self.assertTrue(job_seeker.has_eligibility_diagnosis)

        # Has valid Pôle emploi diagnosis.
        job_seeker = JobSeekerFactory()
        PoleEmploiApprovalFactory(
            first_name=job_seeker.first_name,
            last_name=job_seeker.last_name,
            birthdate=job_seeker.birthdate,
        )
        self.assertTrue(job_seeker.has_eligibility_diagnosis)

        # Has expired Pôle emploi diagnosis.
        job_seeker = JobSeekerFactory()
        end_at = datetime.date.today() - relativedelta(years=2)
        start_at = end_at - relativedelta(years=2)
        PoleEmploiApprovalFactory(
            first_name=job_seeker.first_name,
            last_name=job_seeker.last_name,
            birthdate=job_seeker.birthdate,
            start_at=start_at,
            end_at=end_at,
        )
        self.assertFalse(job_seeker.has_eligibility_diagnosis)
