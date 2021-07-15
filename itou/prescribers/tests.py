from django.conf import settings
from django.core.exceptions import ValidationError
from django.test import TestCase

from itou.job_applications import factories as job_applications_factories, models as job_applications_models
from itou.prescribers.factories import (
    AuthorizedPrescriberOrganizationFactory,
    PrescriberOrganizationFactory,
    PrescriberOrganizationWith2MembershipFactory,
    PrescriberOrganizationWithMembershipFactory,
)
from itou.prescribers.management.commands.merge_organizations import organization_merge_into
from itou.prescribers.models import PrescriberOrganization


class PrescriberOrganizationManagerTest(TestCase):
    """
    Test PrescriberOrganizationManager.
    """

    def test_get_accredited_orgs_for(self):
        """
        Test `get_accredited_orgs_for`.
        """
        departmental_council_org = AuthorizedPrescriberOrganizationFactory(kind=PrescriberOrganization.Kind.DEPT)

        # An org accredited by a departmental council:
        # - is in the same department
        # - is accredited BRSA
        accredited_org = AuthorizedPrescriberOrganizationFactory(
            department=departmental_council_org.department,
            kind=PrescriberOrganization.Kind.OTHER,
            is_brsa=True,
        )

        other_org = AuthorizedPrescriberOrganizationFactory(
            department=departmental_council_org.department, kind=PrescriberOrganization.Kind.CAP_EMPLOI
        )

        # `expected_num` orgs should be accredited by the departmental council.
        accredited_orgs = PrescriberOrganization.objects.get_accredited_orgs_for(departmental_council_org)
        self.assertEqual(accredited_org, accredited_orgs.first())

        # No orgs should be accredited by the other org.
        accredited_orgs = PrescriberOrganization.objects.get_accredited_orgs_for(other_org)
        self.assertEqual(accredited_orgs.count(), 0)


class PrescriberOrganizationModelTest(TestCase):
    def test_accept_survey_url(self):

        org = PrescriberOrganizationFactory(kind=PrescriberOrganization.Kind.PE, department="57")
        url = org.accept_survey_url
        self.assertTrue(url.startswith(f"{settings.TYPEFORM_URL}/to/EDHZSU7p?"))
        self.assertIn(f"idorganisation={org.pk}", url)
        self.assertIn("typeorga=P%C3%B4le+emploi", url)
        self.assertIn("region=Grand+Est", url)
        self.assertIn("departement=57", url)

        # Ensure that the URL does not break when there is no department.
        org = PrescriberOrganizationFactory(kind=PrescriberOrganization.Kind.CAP_EMPLOI, department="")
        url = org.accept_survey_url
        self.assertTrue(url.startswith(f"{settings.TYPEFORM_URL}/to/EDHZSU7p?"))
        self.assertIn(f"idorganisation={org.pk}", url)
        self.assertIn("typeorga=CAP+emploi", url)
        self.assertIn("region=", url)
        self.assertIn("departement=", url)

    def test_clean_siret(self):
        """
        Test that a SIRET number is required only for non-PE organizations.
        """
        org = PrescriberOrganizationFactory.build(siret="", kind=PrescriberOrganization.Kind.PE)
        org.clean_siret()
        with self.assertRaises(ValidationError):
            org = PrescriberOrganizationFactory.build(siret="", kind=PrescriberOrganization.Kind.CAP_EMPLOI)
            org.clean_siret()

    def test_clean_code_safir_pole_emploi(self):
        """
        Test that a code SAFIR can only be set for PE agencies.
        """
        org = PrescriberOrganizationFactory.build(code_safir_pole_emploi="12345", kind=PrescriberOrganization.Kind.PE)
        org.clean_code_safir_pole_emploi()
        with self.assertRaises(ValidationError):
            org = PrescriberOrganizationFactory.build(
                code_safir_pole_emploi="12345", kind=PrescriberOrganization.Kind.CAP_EMPLOI
            )
            org.clean_code_safir_pole_emploi()

    def test_has_pending_authorization_proof(self):

        org = PrescriberOrganizationFactory(
            kind=PrescriberOrganization.Kind.OTHER,
            authorization_status=PrescriberOrganization.AuthorizationStatus.NOT_SET,
        )
        self.assertTrue(org.has_pending_authorization())
        self.assertTrue(org.has_pending_authorization_proof())

        org = PrescriberOrganizationFactory(
            kind=PrescriberOrganization.Kind.CAP_EMPLOI,
            authorization_status=PrescriberOrganization.AuthorizationStatus.NOT_SET,
        )
        self.assertTrue(org.has_pending_authorization())
        self.assertFalse(org.has_pending_authorization_proof())

    def test_active_admin_members(self):
        """
        Test that if a user is admin of org_1 and regular user
        of org2 he is not considered as admin of org_2.
        """
        org_1 = PrescriberOrganizationWithMembershipFactory()
        org_1_admin_user = org_1.members.first()
        org_2 = PrescriberOrganizationWithMembershipFactory()
        org_2.members.add(org_1_admin_user)

        self.assertIn(org_1_admin_user, org_1.active_admin_members)
        self.assertNotIn(org_1_admin_user, org_2.active_admin_members)

    def test_active_members(self):
        org = PrescriberOrganizationWith2MembershipFactory(membership2__is_active=False)
        user_with_active_membership = org.members.first()
        user_with_inactive_membership = org.members.last()

        self.assertNotIn(user_with_inactive_membership, org.active_members)
        self.assertIn(user_with_active_membership, org.active_members)

        # Deactivate a user
        user_with_active_membership.is_active = False
        user_with_active_membership.save()

        self.assertNotIn(user_with_active_membership, org.active_members)

    def test_merge_two_organizations(self):
        job_application_1 = job_applications_factories.JobApplicationSentByPrescriberOrganizationFactory()
        organization_1 = job_application_1.sender_prescriber_organization

        job_application_2 = job_applications_factories.JobApplicationSentByPrescriberOrganizationFactory()
        organization_2 = job_application_2.sender_prescriber_organization

        count_job_applications = job_applications_models.JobApplication.objects.count()
        self.assertEqual(PrescriberOrganization.objects.count(), 2)
        self.assertEqual(count_job_applications, 2)
        organization_merge_into(organization_1.id, organization_2.id)
        self.assertEqual(count_job_applications, job_applications_models.JobApplication.objects.count())
        self.assertEqual(PrescriberOrganization.objects.count(), 1)
