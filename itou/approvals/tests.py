import datetime

from django.test import TestCase
from django.core.exceptions import ValidationError

from itou.approvals.factories import ApprovalFactory
from itou.approvals.models import Approval


class ModelTest(TestCase):
    def test_clean(self):
        approval = ApprovalFactory()
        approval.start_at = datetime.date.today()
        approval.end_at = datetime.date.today() - datetime.timedelta(days=365 * 2)
        with self.assertRaises(ValidationError):
            approval.save()

    def test_get_next_number(self):
        approval = ApprovalFactory(number="999991900030")
        self.assertEqual(Approval.get_next_number(), 999991900031)
