from django.test import TestCase

from itou.siaes.factories import SiaeWithMembershipAndJobsFactory


class FactoriesTest(TestCase):
    def test_siae_with_membership_and_jobs_factory(self):
        siae = SiaeWithMembershipAndJobsFactory(romes=("N1101", "N1105"))
        self.assertEqual(siae.jobs.count(), 4)
