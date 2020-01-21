import datetime

from dateutil.relativedelta import relativedelta

from django.core import mail
from django.core.exceptions import ValidationError
from django.test import TestCase
from django.utils import timezone

from itou.approvals.factories import ApprovalFactory
from itou.approvals.factories import PoleEmploiApprovalFactory
from itou.approvals.models import Approval, PoleEmploiApproval
from itou.approvals.models import ApprovalsWrapper
from itou.job_applications.factories import (
    JobApplicationSentByAuthorizedPrescriberOrganizationFactory,
)
from itou.job_applications.models import JobApplicationWorkflow
from itou.users.factories import JobSeekerFactory


class CommonApprovalQuerySetTest(TestCase):
    """
    Test CommonApprovalQuerySet.
    """

    def test_valid_for_pole_emploi_approval_model(self):
        """
        Test for PoleEmploiApproval model.
        """

        start_at = datetime.date.today() - relativedelta(years=1)
        end_at = start_at + relativedelta(years=1)
        PoleEmploiApprovalFactory(start_at=start_at, end_at=end_at)

        start_at = datetime.date.today() - relativedelta(years=5)
        end_at = start_at + relativedelta(years=2)
        PoleEmploiApprovalFactory(start_at=start_at, end_at=end_at)

        self.assertEqual(2, PoleEmploiApproval.objects.count())
        self.assertEqual(1, PoleEmploiApproval.objects.valid().count())

    def test_valid_for_approval_model(self):
        """
        Test for Approval model.
        """

        start_at = datetime.date.today() - relativedelta(years=1)
        end_at = start_at + relativedelta(years=1)
        ApprovalFactory(start_at=start_at, end_at=end_at)

        start_at = datetime.date.today() - relativedelta(years=5)
        end_at = start_at + relativedelta(years=2)
        ApprovalFactory(start_at=start_at, end_at=end_at)

        self.assertEqual(2, Approval.objects.count())
        self.assertEqual(1, Approval.objects.valid().count())

    def test_valid(self):

        # Start today, end in 2 years.
        start_at = datetime.date.today()
        end_at = start_at + relativedelta(years=2)
        approval = ApprovalFactory(start_at=start_at, end_at=end_at)
        self.assertTrue(Approval.objects.filter(id=approval.id).valid().exists())

        # End today.
        end_at = datetime.date.today()
        start_at = end_at - relativedelta(years=2)
        approval = ApprovalFactory(start_at=start_at, end_at=end_at)
        self.assertTrue(Approval.objects.filter(id=approval.id).valid().exists())

        # Ended 1 year ago.
        end_at = datetime.date.today() - relativedelta(years=1)
        start_at = end_at - relativedelta(years=2)
        approval = ApprovalFactory(start_at=start_at, end_at=end_at)
        self.assertFalse(Approval.objects.filter(id=approval.id).valid().exists())

        # Ended yesterday.
        end_at = datetime.date.today() - relativedelta(days=1)
        start_at = end_at - relativedelta(years=2)
        approval = ApprovalFactory(start_at=start_at, end_at=end_at)
        self.assertFalse(Approval.objects.filter(id=approval.id).valid().exists())

        # In the future.
        start_at = datetime.date.today() + relativedelta(years=2)
        end_at = start_at + relativedelta(years=2)
        approval = ApprovalFactory(start_at=start_at, end_at=end_at)
        self.assertTrue(Approval.objects.filter(id=approval.id).valid().exists())


class CommonApprovalMixinTest(TestCase):
    """
    Test CommonApprovalMixin.
    """

    def test_is_valid(self):

        # End today.
        end_at = datetime.date.today()
        start_at = end_at - relativedelta(years=2)
        approval = PoleEmploiApprovalFactory(start_at=start_at, end_at=end_at)
        self.assertTrue(approval.is_valid)

        # Ended yesterday.
        end_at = datetime.date.today() - relativedelta(days=1)
        start_at = end_at - relativedelta(years=2)
        approval = PoleEmploiApprovalFactory(start_at=start_at, end_at=end_at)
        self.assertFalse(approval.is_valid)

        # Start tomorrow.
        start_at = datetime.date.today() + relativedelta(days=1)
        end_at = start_at + relativedelta(years=2)
        approval = PoleEmploiApprovalFactory(start_at=start_at, end_at=end_at)
        self.assertTrue(approval.is_valid)

    def test_time_since_end(self):

        end_at = datetime.date.today() - relativedelta(days=1)
        start_at = end_at - relativedelta(years=2)
        approval = PoleEmploiApprovalFactory(start_at=start_at, end_at=end_at)
        self.assertEqual(approval.time_since_end.days, 1)

    def test_can_obtain_new_approval(self):

        # 1 day before `YEARS_BEFORE_NEW_APPROVAL`.
        end_at = (
            datetime.date.today()
            - relativedelta(years=Approval.YEARS_BEFORE_NEW_APPROVAL)
            + relativedelta(days=1)
        )
        start_at = end_at - relativedelta(years=2)
        approval = ApprovalFactory(start_at=start_at, end_at=end_at)
        self.assertFalse(approval.can_obtain_new_approval)

        # Exactly `YEARS_BEFORE_NEW_APPROVAL`.
        end_at = datetime.date.today() - relativedelta(
            years=Approval.YEARS_BEFORE_NEW_APPROVAL
        )
        start_at = end_at - relativedelta(years=2)
        approval = ApprovalFactory(start_at=start_at, end_at=end_at)
        self.assertFalse(approval.can_obtain_new_approval)

        # 1 day after `YEARS_BEFORE_NEW_APPROVAL`.
        end_at = (
            datetime.date.today()
            - relativedelta(years=Approval.YEARS_BEFORE_NEW_APPROVAL)
            - relativedelta(days=1)
        )
        start_at = end_at - relativedelta(years=2)
        approval = ApprovalFactory(start_at=start_at, end_at=end_at)
        self.assertTrue(approval.can_obtain_new_approval)


class ApprovalModelTest(TestCase):
    """
    Test Approval model.
    """

    def test_clean(self):
        approval = ApprovalFactory()
        approval.start_at = datetime.date.today()
        approval.end_at = datetime.date.today() - datetime.timedelta(days=365 * 2)
        with self.assertRaises(ValidationError):
            approval.save()

    def test_get_next_number(self):

        PREFIX = Approval.ASP_ITOU_PREFIX

        now = timezone.now().date()
        current_year = now.strftime("%y")

        # No pre-existing objects.
        expected_number = f"{PREFIX}{current_year}00001"
        self.assertEqual(Approval.get_next_number(), expected_number)

        # With pre-existing objects.
        ApprovalFactory(number=f"{PREFIX}{current_year}00038", start_at=now)
        ApprovalFactory(number=f"{PREFIX}{current_year}00039", start_at=now)
        ApprovalFactory(number=f"{PREFIX}{current_year}00040", start_at=now)
        expected_number = f"{PREFIX}{current_year}00041"
        self.assertEqual(Approval.get_next_number(), expected_number)
        Approval.objects.all().delete()

        # Date of hiring in the past.
        date_of_hiring = now - relativedelta(years=3)
        year = date_of_hiring.strftime("%y")
        ApprovalFactory(number=f"{PREFIX}{year}99998", start_at=date_of_hiring)
        expected_number = f"{PREFIX}{year}99999"
        self.assertEqual(Approval.get_next_number(date_of_hiring), expected_number)
        Approval.objects.all().delete()

        # Date of hiring in the future.
        date_of_hiring = now + relativedelta(years=3)
        year = date_of_hiring.strftime("%y")
        ApprovalFactory(number=f"{PREFIX}{year}00020", start_at=date_of_hiring)
        expected_number = f"{PREFIX}{year}00021"
        self.assertEqual(Approval.get_next_number(date_of_hiring), expected_number)
        Approval.objects.all().delete()

        # With pre-existing Pôle emploi approval.
        ApprovalFactory(number=f"625741810182", start_at=now)
        expected_number = f"{PREFIX}{current_year}00001"
        self.assertEqual(Approval.get_next_number(), expected_number)
        Approval.objects.all().delete()

        # With various pre-existing objects.
        ApprovalFactory(number=f"{PREFIX}{current_year}00222", start_at=now)
        ApprovalFactory(number=f"625741810182", start_at=now)
        expected_number = f"{PREFIX}{current_year}00223"
        self.assertEqual(Approval.get_next_number(), expected_number)
        Approval.objects.all().delete()

    def test_send_number_by_email(self):

        job_application = JobApplicationSentByAuthorizedPrescriberOrganizationFactory(
            state=JobApplicationWorkflow.STATE_PROCESSING
        )
        job_application.accept(user=job_application.to_siae.members.first())
        approval = ApprovalFactory(job_application=job_application)

        # Delete `accept` and `accept_trigger_manual_approval` emails.
        mail.outbox = []

        approval.send_number_by_email()
        self.assertEqual(len(mail.outbox), 1)
        email = mail.outbox[0]
        self.assertIn(approval.user.get_full_name(), email.subject)
        self.assertIn(approval.user.get_full_name(), email.body)
        self.assertIn(approval.number, email.body)

    def test_is_valid(self):

        # Start today, end in 2 years.
        start_at = datetime.date.today()
        end_at = start_at + relativedelta(years=2)
        approval = ApprovalFactory(start_at=start_at, end_at=end_at)
        self.assertTrue(approval.is_valid)

        # End today.
        end_at = datetime.date.today()
        start_at = end_at - relativedelta(years=2)
        approval = ApprovalFactory(start_at=start_at, end_at=end_at)
        self.assertTrue(approval.is_valid)

        # Ended 1 year ago.
        end_at = datetime.date.today() - relativedelta(years=1)
        start_at = end_at - relativedelta(years=2)
        approval = ApprovalFactory(start_at=start_at, end_at=end_at)
        self.assertFalse(approval.is_valid)

        # Ended yesterday.
        end_at = datetime.date.today() - relativedelta(days=1)
        start_at = end_at - relativedelta(years=2)
        approval = ApprovalFactory(start_at=start_at, end_at=end_at)
        self.assertFalse(approval.is_valid)


class PoleEmploiApprovalModelTest(TestCase):
    """
    Test PoleEmploiApproval model.
    """

    def test_number_as_pe_format(self):

        # 12 chars.
        pole_emploi_approval = PoleEmploiApprovalFactory(number="400121910144")
        expected = "40012 19 10144"
        self.assertEqual(pole_emploi_approval.number_as_pe_format, expected)

        # 15 chars.
        pole_emploi_approval = PoleEmploiApprovalFactory(number="010331610106A01")
        expected = "01033 16 10106 A01"
        self.assertEqual(pole_emploi_approval.number_as_pe_format, expected)

    def test_name_format(self):
        self.assertEqual(PoleEmploiApproval.name_format(" François"), "FRANCOIS")
        self.assertEqual(PoleEmploiApproval.name_format("M'Hammed "), "M'HAMMED")
        self.assertEqual(
            PoleEmploiApproval.name_format("     jean kevin  "), "JEAN KEVIN"
        )
        self.assertEqual(
            PoleEmploiApproval.name_format("     Jean-Kevin  "), "JEAN-KEVIN"
        )
        self.assertEqual(
            PoleEmploiApproval.name_format("Kertész István"), "KERTESZ ISTVAN"
        )
        self.assertEqual(
            PoleEmploiApproval.name_format("Backer-Grøndahl"), "BACKER-GRONDAHL"
        )
        self.assertEqual(
            PoleEmploiApproval.name_format("désirée artôt"), "DESIREE ARTOT"
        )
        self.assertEqual(PoleEmploiApproval.name_format("N'Guessan"), "N'GUESSAN")
        self.assertEqual(PoleEmploiApproval.name_format("N Guessan"), "N GUESSAN")


class PoleEmploiApprovalManagerTest(TestCase):
    """
    Test PoleEmploiApprovalManager.
    """

    def test_find_for(self):

        first_name = "Désirée"
        last_name = "Backer-Grøndahl"
        birthdate = datetime.date(1988, 12, 20)
        pe_approval = PoleEmploiApprovalFactory(
            first_name=first_name, last_name=last_name, birthdate=birthdate
        )
        search_results = PoleEmploiApproval.objects.find_for(
            first_name, last_name, birthdate
        )
        self.assertEqual(search_results.count(), 1)
        self.assertEqual(search_results.first(), pe_approval)
        PoleEmploiApproval.objects.all().delete()

        # Ensure `birthdate` is checked.
        PoleEmploiApprovalFactory(
            first_name="Kertész",
            last_name="István",
            birthdate=datetime.date(1988, 12, 20),
        )
        pe_approval = PoleEmploiApprovalFactory(
            first_name="Kertész",
            last_name="István",
            birthdate=datetime.date(1987, 2, 12),
        )
        search_results = PoleEmploiApproval.objects.find_for(
            "Kertész", "István", datetime.date(1987, 2, 12)
        )
        self.assertEqual(search_results.count(), 1)
        self.assertEqual(search_results.first(), pe_approval)
        PoleEmploiApproval.objects.all().delete()

        # Test search on `birth_name`.
        pe_approval = PoleEmploiApprovalFactory(
            first_name="Marie-Louise",
            last_name="Dufour",
            birth_name="Durand",
            birthdate=datetime.date(1992, 1, 1),
        )
        search_results = PoleEmploiApproval.objects.find_for(
            "marie-louise", "durand", datetime.date(1992, 1, 1)
        )
        self.assertEqual(search_results.count(), 1)
        self.assertEqual(search_results.first(), pe_approval)
        PoleEmploiApproval.objects.all().delete()


class ApprovalsWrapperTest(TestCase):
    """
    Test ApprovalsWrapper.
    """

    def test_status_without_approval(self):
        user = JobSeekerFactory()
        status = ApprovalsWrapper(user).get_status()
        self.assertEqual(status.code, ApprovalsWrapper.CAN_OBTAIN_NEW_APPROVAL)
        self.assertEqual(status.result, None)

    def test_status_with_valid_approval(self):
        user = JobSeekerFactory()
        approval = ApprovalFactory(
            user=user, start_at=datetime.date.today() - relativedelta(days=1)
        )
        status = ApprovalsWrapper(user).get_status()
        self.assertEqual(status.code, ApprovalsWrapper.VALID_APPROVAL_FOUND)
        self.assertEqual(status.result, approval)

    def test_status_with_recently_expired_approval(self):
        user = JobSeekerFactory()
        end_at = datetime.date.today() - relativedelta(days=30)
        start_at = end_at - relativedelta(years=2)
        approval = ApprovalFactory(user=user, start_at=start_at, end_at=end_at)
        status = ApprovalsWrapper(user).get_status()
        self.assertEqual(status.code, ApprovalsWrapper.CANNOT_OBTAIN_NEW_APPROVAL)
        self.assertEqual(status.result, approval)

    def test_status_with_formerly_expired_approval(self):
        user = JobSeekerFactory()
        end_at = datetime.date.today() - relativedelta(years=3)
        start_at = end_at - relativedelta(years=2)
        approval = ApprovalFactory(user=user, start_at=start_at, end_at=end_at)
        status = ApprovalsWrapper(user).get_status()
        self.assertEqual(status.code, ApprovalsWrapper.CAN_OBTAIN_NEW_APPROVAL)
        self.assertEqual(status.result, approval)

    def test_status_with_multiple_homonym_pole_emploi_approvals(self):
        first_name = "Marie-Louise"
        last_name = "Dufour"
        birthdate = datetime.date(1992, 1, 1)
        user = JobSeekerFactory(
            first_name=first_name, last_name=last_name, birthdate=birthdate
        )
        approval1 = PoleEmploiApprovalFactory(
            first_name=first_name, last_name=last_name, birthdate=birthdate
        )
        approval2 = PoleEmploiApprovalFactory(
            first_name=first_name, last_name=last_name, birthdate=birthdate
        )
        status = ApprovalsWrapper(user).get_status()
        self.assertEqual(status.code, ApprovalsWrapper.MULTIPLE_APPROVALS_FOUND)
        self.assertEqual(2, len(status.result))
        self.assertIn(approval1, status.result)
        self.assertIn(approval2, status.result)

    def test_status_with_valid_pole_emploi_approval(self):
        user = JobSeekerFactory()
        approval = PoleEmploiApprovalFactory(
            first_name=user.first_name,
            last_name=user.last_name,
            birthdate=user.birthdate,
        )
        status = ApprovalsWrapper(user).get_status()
        self.assertEqual(status.code, ApprovalsWrapper.VALID_APPROVAL_FOUND)
        self.assertEqual(status.result, approval)
