from django.test import TestCase

from itou.siaes.factories import SiaeWithMembershipAndJobsFactory
from itou.siaes.factories import SiaeWithMembershipFactory


class FactoriesTest(TestCase):
    def test_siae_with_membership_factory(self):
        siae = SiaeWithMembershipFactory()
        self.assertEqual(siae.members.count(), 1)

    def test_siae_with_membership_and_jobs_factory(self):
        siae = SiaeWithMembershipAndJobsFactory(romes=("N1101", "N1105"))
        self.assertEqual(siae.jobs.count(), 4)
