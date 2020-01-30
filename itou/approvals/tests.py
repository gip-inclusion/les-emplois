import datetime

from dateutil.relativedelta import relativedelta

from django.conf import settings
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

    def test_can_obtain_new(self):

        # 1 day before `YEARS_BEFORE_NEW_APPROVAL`.
        end_at = (
            datetime.date.today()
            - relativedelta(years=Approval.YEARS_BEFORE_NEW_APPROVAL)
            + relativedelta(days=1)
        )
        start_at = end_at - relativedelta(years=2)
        approval = ApprovalFactory(start_at=start_at, end_at=end_at)
        self.assertFalse(approval.can_obtain_new)

        # Exactly `YEARS_BEFORE_NEW_APPROVAL`.
        end_at = datetime.date.today() - relativedelta(
            years=Approval.YEARS_BEFORE_NEW_APPROVAL
        )
        start_at = end_at - relativedelta(years=2)
        approval = ApprovalFactory(start_at=start_at, end_at=end_at)
        self.assertFalse(approval.can_obtain_new)

        # 1 day after `YEARS_BEFORE_NEW_APPROVAL`.
        end_at = (
            datetime.date.today()
            - relativedelta(years=Approval.YEARS_BEFORE_NEW_APPROVAL)
            - relativedelta(days=1)
        )
        start_at = end_at - relativedelta(years=2)
        approval = ApprovalFactory(start_at=start_at, end_at=end_at)
        self.assertTrue(approval.can_obtain_new)


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
        hiring_start_at = now - relativedelta(years=3)
        year = hiring_start_at.strftime("%y")
        ApprovalFactory(number=f"{PREFIX}{year}99998", start_at=hiring_start_at)
        expected_number = f"{PREFIX}{year}99999"
        self.assertEqual(Approval.get_next_number(hiring_start_at), expected_number)
        Approval.objects.all().delete()

        # Date of hiring in the future.
        hiring_start_at = now + relativedelta(years=3)
        year = hiring_start_at.strftime("%y")
        ApprovalFactory(number=f"{PREFIX}{year}00020", start_at=hiring_start_at)
        expected_number = f"{PREFIX}{year}00021"
        self.assertEqual(Approval.get_next_number(hiring_start_at), expected_number)
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
        self.assertIn(approval.number_with_spaces, email.body)
        self.assertIn(approval.user.last_name, email.body)
        self.assertIn(approval.user.first_name, email.body)
        self.assertIn(approval.user.birthdate.strftime("%d/%m/%Y"), email.body)
        self.assertIn(
            approval.job_application.hiring_start_at.strftime("%d/%m/%Y"), email.body
        )
        self.assertIn(
            approval.job_application.hiring_end_at.strftime("%d/%m/%Y"), email.body
        )
        self.assertIn(approval.job_application.to_siae.display_name, email.body)
        self.assertIn(approval.job_application.to_siae.get_kind_display(), email.body)
        self.assertIn(approval.job_application.to_siae.address_line_1, email.body)
        self.assertIn(approval.job_application.to_siae.address_line_2, email.body)
        self.assertIn(approval.job_application.to_siae.post_code, email.body)
        self.assertIn(approval.job_application.to_siae.city, email.body)
        self.assertIn(settings.ITOU_EMAIL_CONTACT, email.body)

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

    def test_number_with_spaces(self):

        approval = ApprovalFactory(number="999990000001")
        expected = "99999 00 00001"
        self.assertEqual(approval.number_with_spaces, expected)


class PoleEmploiApprovalModelTest(TestCase):
    """
    Test PoleEmploiApproval model.
    """

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

    def test_number_with_spaces(self):

        # 12 chars.
        pole_emploi_approval = PoleEmploiApprovalFactory(number="400121910144")
        expected = "40012 19 10144"
        self.assertEqual(pole_emploi_approval.number_with_spaces, expected)

        # 15 chars.
        pole_emploi_approval = PoleEmploiApprovalFactory(number="010331610106A01")
        expected = "01033 16 10106 A01"
        self.assertEqual(pole_emploi_approval.number_with_spaces, expected)


class PoleEmploiApprovalManagerTest(TestCase):
    """
    Test PoleEmploiApprovalManager.
    """

    def test_find_for(self):

        user = JobSeekerFactory()
        pe_approval = PoleEmploiApprovalFactory(
            pole_emploi_id=user.pole_emploi_id, birthdate=user.birthdate
        )
        search_results = PoleEmploiApproval.objects.find_for(user)
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
        self.assertEqual(status.code, ApprovalsWrapper.CAN_OBTAIN_NEW)
        self.assertEqual(status.approval, None)

    def test_status_with_valid_approval(self):
        user = JobSeekerFactory()
        approval = ApprovalFactory(
            user=user, start_at=datetime.date.today() - relativedelta(days=1)
        )
        status = ApprovalsWrapper(user).get_status()
        self.assertEqual(status.code, ApprovalsWrapper.VALID)
        self.assertEqual(status.approval, approval)

    def test_status_with_recently_expired_approval(self):
        user = JobSeekerFactory()
        end_at = datetime.date.today() - relativedelta(days=30)
        start_at = end_at - relativedelta(years=2)
        approval = ApprovalFactory(user=user, start_at=start_at, end_at=end_at)
        status = ApprovalsWrapper(user).get_status()
        self.assertEqual(status.code, ApprovalsWrapper.CANNOT_OBTAIN_NEW)
        self.assertEqual(status.approval, approval)

    def test_status_with_formerly_expired_approval(self):
        user = JobSeekerFactory()
        end_at = datetime.date.today() - relativedelta(years=3)
        start_at = end_at - relativedelta(years=2)
        approval = ApprovalFactory(user=user, start_at=start_at, end_at=end_at)
        status = ApprovalsWrapper(user).get_status()
        self.assertEqual(status.code, ApprovalsWrapper.CAN_OBTAIN_NEW)
        self.assertEqual(status.approval, approval)

    def test_status_with_multiple_results(self):
        user = JobSeekerFactory()
        PoleEmploiApprovalFactory(
            pole_emploi_id=user.pole_emploi_id, birthdate=user.birthdate
        )
        PoleEmploiApprovalFactory(
            pole_emploi_id=user.pole_emploi_id, birthdate=user.birthdate
        )
        status = ApprovalsWrapper(user).get_status()
        self.assertEqual(status.code, ApprovalsWrapper.MULTIPLE_RESULTS)
        self.assertEqual(status.approval, None)

    def test_status_with_valid_pole_emploi_approval(self):
        user = JobSeekerFactory()
        approval = PoleEmploiApprovalFactory(
            pole_emploi_id=user.pole_emploi_id, birthdate=user.birthdate
        )
        status = ApprovalsWrapper(user).get_status()
        self.assertEqual(status.code, ApprovalsWrapper.VALID)
        self.assertEqual(status.approval, approval)
