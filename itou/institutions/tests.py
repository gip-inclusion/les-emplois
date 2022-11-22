from itou.institutions.factories import InstitutionWith2MembershipFactory, InstitutionWithMembershipFactory
from itou.utils.test import TestCase


class InstitutionModelTest(TestCase):
    def test_active_admin_members(self):
        """
        Test that if a user is admin of org1 and regular user
        of org2 he is not considered as admin of org2.
        """
        institution1 = InstitutionWithMembershipFactory()
        institution1_admin_user = institution1.members.first()
        institution2 = InstitutionWithMembershipFactory()
        institution2.members.add(institution1_admin_user)

        self.assertIn(institution1_admin_user, institution1.active_admin_members)
        self.assertNotIn(institution1_admin_user, institution2.active_admin_members)

    def test_active_members(self):
        institution = InstitutionWith2MembershipFactory(membership2__is_active=False)
        user_with_active_membership = institution.members.first()
        user_with_inactive_membership = institution.members.last()

        self.assertNotIn(user_with_inactive_membership, institution.active_members)
        self.assertIn(user_with_active_membership, institution.active_members)

        # Deactivate a user
        user_with_active_membership.is_active = False
        user_with_active_membership.save()

        self.assertNotIn(user_with_active_membership, institution.active_members)
