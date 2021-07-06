from django.test import TestCase

from itou.institutions.factories import InstitutionWith2MembershipFactory, InstitutionWithMembershipFactory


class InstitutionModelTest(TestCase):
    def test_active_admin_members(self):
        """
        Test that if a user is admin of org1 and regular user
        of org2 it does not get considered as admin of org2.
        # Same as itou.prescribers.tests.PrescriberOrganizationModelTest.test_active_admin_members
        """
        institution1 = InstitutionWithMembershipFactory()
        institution1_admin_user = institution1.active_admin_members.get()
        institution2 = InstitutionWithMembershipFactory()
        institution2.members.add(institution1_admin_user)

        self.assertEqual(institution1.members.count(), 1)
        self.assertEqual(institution1.active_members.count(), 1)
        self.assertEqual(institution1.active_admin_members.count(), 1)

        self.assertEqual(institution2.members.count(), 2)
        self.assertEqual(institution2.active_members.count(), 2)
        self.assertEqual(institution2.active_admin_members.count(), 1)

    def test_active_member_with_many_memberships(self):
        institution1 = InstitutionWith2MembershipFactory(membership2__is_active=False)
        user = institution1.members.filter(institutionmembership__is_admin=False).first()
        institution2 = InstitutionWith2MembershipFactory()
        institution2.members.add(user)

        self.assertFalse(user in institution1.active_members)
        self.assertEqual(institution1.members.count(), 2)
        self.assertEqual(institution1.active_members.count(), 1)
        self.assertEqual(institution2.members.count(), 3)
        self.assertEqual(institution2.active_members.count(), 3)
