from django.test import TestCase

from itou.siaes.factories import SiaeFactory
from itou.siaes.factories import SiaeWithMembershipAndJobsFactory
from itou.siaes.factories import SiaeWithMembershipFactory
from itou.siaes.models import Siae


class FactoriesTest(TestCase):
    def test_siae_with_membership_factory(self):
        siae = SiaeWithMembershipFactory()
        self.assertEqual(siae.members.count(), 1)

    def test_siae_with_membership_and_jobs_factory(self):
        siae = SiaeWithMembershipAndJobsFactory(romes=("N1101", "N1105"))
        self.assertEqual(siae.jobs.count(), 4)


class ModelTest(TestCase):
    def test_is_subject_to_eligibility_rules(self):
        siae = SiaeFactory(kind=Siae.KIND_GEIQ)
        self.assertFalse(siae.is_subject_to_eligibility_rules)

        siae = SiaeFactory(kind=Siae.KIND_EI)
        self.assertTrue(siae.is_subject_to_eligibility_rules)

    def test_has_member(self):
        siae1 = SiaeWithMembershipFactory()
        siae2 = SiaeWithMembershipFactory()

        user1 = siae1.members.first()
        user2 = siae2.members.first()

        self.assertTrue(siae1.has_member(user1))
        self.assertFalse(siae1.has_member(user2))

        self.assertTrue(siae2.has_member(user2))
        self.assertFalse(siae2.has_member(user1))
