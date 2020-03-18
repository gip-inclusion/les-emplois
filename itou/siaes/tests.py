from django.test import TestCase

from itou.siaes.factories import (
    SiaeFactory,
    SiaeWith2MembershipsFactory,
    SiaeWith4MembershipsFactory,
    SiaeWithMembershipAndJobsFactory,
    SiaeWithMembershipFactory,
)
from itou.siaes.models import Siae


class FactoriesTest(TestCase):
    def test_siae_with_membership_factory(self):
        siae = SiaeWithMembershipFactory()
        self.assertEqual(siae.members.count(), 1)
        user = siae.members.get()
        self.assertTrue(siae.has_admin(user))

    def test_siae_with_membership_and_jobs_factory(self):
        siae = SiaeWithMembershipAndJobsFactory(romes=("N1101", "N1105"))
        self.assertEqual(siae.jobs.count(), 4)

    def test_siae_with_2_memberships_factory(self):
        siae = SiaeWith2MembershipsFactory()
        self.assertEqual(siae.members.count(), 2)
        self.assertEqual(siae.active_members.count(), 2)
        self.assertEqual(siae.active_admin_members.count(), 1)
        admin_user = siae.active_admin_members.get()
        self.assertTrue(siae.has_admin(admin_user))
        all_users = list(siae.members.all())
        self.assertEqual(len(all_users), 2)
        all_users.remove(admin_user)
        self.assertEqual(len(all_users), 1)
        regular_user = all_users[0]
        self.assertFalse(siae.has_admin(regular_user))

    def test_siae_with_4_memberships_factory(self):
        siae = SiaeWith4MembershipsFactory()
        self.assertEqual(siae.members.count(), 4)
        self.assertEqual(siae.active_members.count(), 2)
        self.assertEqual(siae.active_admin_members.count(), 1)


class ModelTest(TestCase):
    def test_is_subject_to_eligibility_rules(self):
        siae = SiaeFactory(kind=Siae.KIND_GEIQ)
        self.assertFalse(siae.is_subject_to_eligibility_rules)

        siae = SiaeFactory(kind=Siae.KIND_EI)
        self.assertTrue(siae.is_subject_to_eligibility_rules)

    def test_has_members(self):
        siae1 = SiaeFactory()
        siae2 = SiaeWithMembershipFactory()

        self.assertFalse(siae1.has_members)
        self.assertTrue(siae2.has_members)

    def test_has_member(self):
        siae1 = SiaeWithMembershipFactory()
        siae2 = SiaeWithMembershipFactory()

        user1 = siae1.members.get()
        user2 = siae2.members.get()

        self.assertTrue(siae1.has_member(user1))
        self.assertFalse(siae1.has_member(user2))

        self.assertTrue(siae2.has_member(user2))
        self.assertFalse(siae2.has_member(user1))

    def test_active_members(self):
        siae = SiaeWith2MembershipsFactory(membership2__user__is_active=False)
        self.assertEqual(siae.members.count(), 2)
        self.assertEqual(siae.active_members.count(), 1)

    def test_active_admin_members(self):
        """
        Test that if a user is admin of siae1 and regular user
        of siae2 it does not get considered as admin of siae2.
        """
        siae1 = SiaeWith4MembershipsFactory()
        siae1_admin_user = siae1.active_admin_members.get()
        siae2 = SiaeWith4MembershipsFactory(membership2__user=siae1_admin_user)

        self.assertEqual(siae1.members.count(), 4)
        self.assertEqual(siae1.active_members.count(), 2)
        self.assertEqual(siae1.active_admin_members.count(), 1)

        self.assertEqual(siae2.members.count(), 4)
        self.assertEqual(siae2.active_members.count(), 2)
        self.assertEqual(siae2.active_admin_members.count(), 1)

    def test_has_admin(self):
        siae1 = SiaeWith2MembershipsFactory()
        siae1_admin_user = siae1.active_admin_members.get()
        siae1_regular_user = siae1.active_members.exclude(pk=siae1_admin_user.pk).get()
        siae2 = SiaeWith4MembershipsFactory(membership2__user=siae1_admin_user)

        self.assertTrue(siae1.has_member(siae1_admin_user))
        self.assertTrue(siae1.has_admin(siae1_admin_user))

        self.assertTrue(siae1.has_member(siae1_regular_user))
        self.assertFalse(siae1.has_admin(siae1_regular_user))

        self.assertTrue(siae2.has_member(siae1_admin_user))
        self.assertFalse(siae2.has_admin(siae1_admin_user))
