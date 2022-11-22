from datetime import datetime

import httpx
import respx
from django.conf import settings
from django.contrib.auth.models import Permission
from django.contrib.contenttypes.models import ContentType
from django.core import mail
from django.core.exceptions import ValidationError
from django.core.management import call_command
from django.test import override_settings
from django.urls import reverse
from django.utils.timezone import get_current_timezone

from itou.job_applications import factories as job_applications_factories, models as job_applications_models
from itou.prescribers.enums import PrescriberAuthorizationStatus, PrescriberOrganizationKind
from itou.prescribers.factories import (
    PrescriberOrganizationFactory,
    PrescriberOrganizationWith2MembershipFactory,
    PrescriberOrganizationWithMembershipFactory,
)
from itou.prescribers.management.commands.merge_organizations import organization_merge_into
from itou.prescribers.models import PrescriberOrganization
from itou.users.factories import UserFactory
from itou.utils.mocks.api_entreprise import ETABLISSEMENT_API_RESULT_MOCK, INSEE_API_RESULT_MOCK
from itou.utils.test import TestCase


class PrescriberOrganizationManagerTest(TestCase):
    """
    Test PrescriberOrganizationManager.
    """

    def test_get_accredited_orgs_for(self):
        """
        Test `get_accredited_orgs_for`.
        """
        departmental_council_org = PrescriberOrganizationFactory(authorized=True, kind=PrescriberOrganizationKind.DEPT)

        # An org accredited by a departmental council:
        # - is in the same department
        # - is accredited BRSA
        accredited_org = PrescriberOrganizationFactory(
            authorized=True,
            department=departmental_council_org.department,
            kind=PrescriberOrganizationKind.OTHER,
            is_brsa=True,
        )

        other_org = PrescriberOrganizationFactory(
            authorized=True,
            department=departmental_council_org.department,
            kind=PrescriberOrganizationKind.CAP_EMPLOI,
        )

        # `expected_num` orgs should be accredited by the departmental council.
        accredited_orgs = PrescriberOrganization.objects.get_accredited_orgs_for(departmental_council_org)
        self.assertEqual(accredited_org, accredited_orgs.first())

        # No orgs should be accredited by the other org.
        accredited_orgs = PrescriberOrganization.objects.get_accredited_orgs_for(other_org)
        self.assertEqual(accredited_orgs.count(), 0)

    def test_create_organization(self):
        """
        Test `create_organization`.
        """
        PrescriberOrganization.objects.create_organization(
            {
                "siret": "11122233300000",
                "name": "Ma petite entreprise",
                "authorization_status": PrescriberAuthorizationStatus.NOT_REQUIRED,
            },
        )
        self.assertEqual(1, PrescriberOrganization.objects.count())
        self.assertEqual(len(mail.outbox), 0)

        org = PrescriberOrganization.objects.create_organization(
            {
                "siret": "11122233300001",
                "name": "Ma seconde entreprise",
                "authorization_status": PrescriberAuthorizationStatus.NOT_SET,
            },
        )
        self.assertEqual(2, PrescriberOrganization.objects.count())
        self.assertEqual(len(mail.outbox), 1)
        self.assertIn(str(org.pk), mail.outbox[0].body)


class PrescriberOrganizationModelTest(TestCase):
    def test_accept_survey_url(self):

        org = PrescriberOrganizationFactory(kind=PrescriberOrganizationKind.PE, department="57")
        url = org.accept_survey_url
        self.assertTrue(url.startswith(f"{settings.TALLY_URL}/r/"))
        self.assertIn(f"idorganisation={org.pk}", url)
        self.assertIn("region=Grand+Est", url)
        self.assertIn("departement=57", url)

        # Ensure that the URL does not break when there is no department.
        org = PrescriberOrganizationFactory(kind=PrescriberOrganizationKind.CAP_EMPLOI, department="")
        url = org.accept_survey_url
        self.assertTrue(url.startswith(f"{settings.TALLY_URL}/r/"))
        self.assertIn(f"idorganisation={org.pk}", url)
        self.assertIn("region=", url)
        self.assertIn("departement=", url)

    def test_clean_siret(self):
        """
        Test that a SIRET number is required only for non-PE organizations.
        """
        org = PrescriberOrganizationFactory.build(siret="", kind=PrescriberOrganizationKind.PE)
        org.clean_siret()
        with self.assertRaises(ValidationError):
            org = PrescriberOrganizationFactory.build(siret="", kind=PrescriberOrganizationKind.CAP_EMPLOI)
            org.clean_siret()

    def test_clean_code_safir_pole_emploi(self):
        """
        Test that a code SAFIR can only be set for PE agencies.
        """
        org = PrescriberOrganizationFactory.build(code_safir_pole_emploi="12345", kind=PrescriberOrganizationKind.PE)
        org.clean_code_safir_pole_emploi()
        with self.assertRaises(ValidationError):
            org = PrescriberOrganizationFactory.build(
                code_safir_pole_emploi="12345", kind=PrescriberOrganizationKind.CAP_EMPLOI
            )
            org.clean_code_safir_pole_emploi()

    def test_has_pending_authorization_proof(self):

        org = PrescriberOrganizationFactory(
            kind=PrescriberOrganizationKind.OTHER,
            authorization_status=PrescriberAuthorizationStatus.NOT_SET,
        )
        self.assertTrue(org.has_pending_authorization())
        self.assertTrue(org.has_pending_authorization_proof())

        org = PrescriberOrganizationFactory(
            kind=PrescriberOrganizationKind.CAP_EMPLOI,
            authorization_status=PrescriberAuthorizationStatus.NOT_SET,
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

    def test_add_member(self):
        org = PrescriberOrganizationFactory()
        self.assertEqual(0, org.members.count())
        admin_user = UserFactory()
        org.add_member(admin_user)
        self.assertEqual(1, org.memberships.count())
        self.assertTrue(org.memberships.get(user=admin_user).is_admin)

        other_user = UserFactory()
        org.add_member(other_user)
        self.assertEqual(2, org.memberships.count())
        self.assertFalse(org.memberships.get(user=other_user).is_admin)

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

    @respx.mock
    @override_settings(
        API_INSEE_BASE_URL="https://insee.fake",
        API_ENTREPRISE_BASE_URL="https://entreprise.fake",
        API_INSEE_CONSUMER_KEY="foo",
        API_INSEE_CONSUMER_SECRET="bar",
    )
    def test_update_prescriber_with_api_entreprise(self):
        respx.post(f"{settings.API_INSEE_BASE_URL}/token").mock(
            return_value=httpx.Response(200, json=INSEE_API_RESULT_MOCK)
        )

        siret = ETABLISSEMENT_API_RESULT_MOCK["etablissement"]["siret"]
        organization = PrescriberOrganizationFactory(siret=siret, is_head_office=False)

        respx.get(f"{settings.API_ENTREPRISE_BASE_URL}/siret/{siret}").mock(
            return_value=httpx.Response(200, json=ETABLISSEMENT_API_RESULT_MOCK)
        )

        # updated_at is empty, an update is required
        self.assertIsNone(organization.updated_at)
        call_command("update_prescriber_organizations_with_api_entreprise", verbosity=0, days=7)
        organization.refresh_from_db()
        self.assertIsNotNone(organization.updated_at)
        self.assertTrue(organization.is_head_office)

        old_updated_at = organization.updated_at

        # No update required
        call_command("update_prescriber_organizations_with_api_entreprise", verbosity=0, days=7)
        organization.refresh_from_db()
        self.assertEqual(old_updated_at, organization.updated_at)
        self.assertTrue(organization.is_head_office)

        # Force updated of latest records
        call_command("update_prescriber_organizations_with_api_entreprise", verbosity=0, days=0)
        organization.refresh_from_db()
        self.assertNotEqual(old_updated_at, organization.updated_at)
        self.assertTrue(organization.is_head_office)


class PrescriberOrganizationAdminTest(TestCase):
    def setUp(self):
        # super user
        self.superuser = UserFactory()
        self.superuser.is_staff = True
        self.superuser.is_superuser = True
        self.superuser.save()

        # staff user with permissions
        self.user = UserFactory()
        self.user.is_staff = True
        self.user.save()
        content_type = ContentType.objects.get_for_model(PrescriberOrganization)
        permission = Permission.objects.get(content_type=content_type, codename="change_prescriberorganization")
        self.user.user_permissions.add(permission)

        # authorization status x is_authorizedis_authorized combinations
        self.rights_list = [
            (authorization_status, authorization_status == PrescriberAuthorizationStatus.VALIDATED)
            for authorization_status in list(PrescriberAuthorizationStatus)
        ]

    def test_refuse_prescriber_habilitation_by_superuser(self):
        self.client.force_login(self.superuser)

        prescriberorganization = PrescriberOrganizationFactory(
            authorized=True,
            siret="83987278500010",
            department="14",
            post_code="14000",
            authorization_updated_at=datetime.now(tz=get_current_timezone()),
        )

        url = reverse("admin:prescribers_prescriberorganization_change", args=[prescriberorganization.pk])
        response = self.client.get(url)
        self.assertEqual(response.status_code, 200)

        for authorization_status, is_authorized in self.rights_list:
            with self.subTest(authorization_status=authorization_status, is_authorized=is_authorized):

                post_data = {
                    "id": prescriberorganization.pk,
                    "post_code": prescriberorganization.post_code,
                    "department": prescriberorganization.department,
                    "kind": prescriberorganization.kind,
                    "name": prescriberorganization.name,
                    "prescribermembership_set-TOTAL_FORMS": 1,
                    "prescribermembership_set-INITIAL_FORMS": 0,
                    "utils-pksupportremark-content_type-object_id-TOTAL_FORMS": 1,
                    "utils-pksupportremark-content_type-object_id-INITIAL_FORMS": 0,
                    "is_authorized": is_authorized,
                    "authorization_status": authorization_status,
                    "_authorization_action_refuse": "Refuser+l'habilitation",
                }

                response = self.client.post(url, data=post_data)
                self.assertEqual(response.status_code, 302)

                updated_prescriberorganization = PrescriberOrganization.objects.get(pk=prescriberorganization.pk)
                self.assertFalse(updated_prescriberorganization.is_authorized)
                self.assertEqual(updated_prescriberorganization.kind, PrescriberOrganizationKind.OTHER)
                self.assertEqual(updated_prescriberorganization.authorization_updated_by, self.superuser)
                self.assertEqual(
                    updated_prescriberorganization.authorization_status,
                    PrescriberAuthorizationStatus.REFUSED,
                )

    def test_refuse_prescriber_habilitation_pending_status(self):
        self.client.force_login(self.user)

        prescriberorganization = PrescriberOrganizationFactory(
            authorized=True,
            siret="83987278500010",
            department="14",
            post_code="14000",
            authorization_updated_at=datetime.now(tz=get_current_timezone()),
            authorization_status=PrescriberAuthorizationStatus.NOT_SET,
            is_authorized=False,
        )

        url = reverse("admin:prescribers_prescriberorganization_change", args=[prescriberorganization.pk])
        response = self.client.get(url)
        self.assertEqual(response.status_code, 200)

        post_data = {
            "id": prescriberorganization.pk,
            "post_code": prescriberorganization.post_code,
            "department": prescriberorganization.department,
            "kind": prescriberorganization.kind,
            "name": prescriberorganization.name,
            "prescribermembership_set-TOTAL_FORMS": 1,
            "prescribermembership_set-INITIAL_FORMS": 0,
            "utils-pksupportremark-content_type-object_id-TOTAL_FORMS": 1,
            "utils-pksupportremark-content_type-object_id-INITIAL_FORMS": 0,
            "is_authorized": prescriberorganization.is_authorized,
            "authorization_status": prescriberorganization.authorization_status,
            "_authorization_action_refuse": "Refuser+l'habilitation",
        }

        response = self.client.post(url, data=post_data)
        self.assertEqual(response.status_code, 302)

        updated_prescriberorganization = PrescriberOrganization.objects.get(pk=prescriberorganization.pk)
        self.assertFalse(updated_prescriberorganization.is_authorized)
        self.assertEqual(updated_prescriberorganization.kind, PrescriberOrganizationKind.OTHER)
        self.assertEqual(updated_prescriberorganization.authorization_updated_by, self.user)
        self.assertEqual(updated_prescriberorganization.authorization_status, PrescriberAuthorizationStatus.REFUSED)

    def test_refuse_prescriber_habilitation_not_pending_status(self):
        self.client.force_login(self.user)

        prescriberorganization = PrescriberOrganizationFactory(
            authorized=True,
            siret="83987278500010",
            department="14",
            post_code="14000",
            authorization_updated_at=datetime.now(tz=get_current_timezone()),
        )

        url = reverse("admin:prescribers_prescriberorganization_change", args=[prescriberorganization.pk])
        response = self.client.get(url)
        self.assertEqual(response.status_code, 200)

        for authorization_status, is_authorized in self.rights_list:
            with self.subTest(authorization_status=authorization_status, is_authorized=is_authorized):

                post_data = {
                    "id": prescriberorganization.pk,
                    "post_code": prescriberorganization.post_code,
                    "department": prescriberorganization.department,
                    "kind": prescriberorganization.kind,
                    "name": prescriberorganization.name,
                    "prescribermembership_set-TOTAL_FORMS": 1,
                    "prescribermembership_set-INITIAL_FORMS": 0,
                    "utils-pksupportremark-content_type-object_id-TOTAL_FORMS": 1,
                    "utils-pksupportremark-content_type-object_id-INITIAL_FORMS": 0,
                    "is_authorized": is_authorized,
                    "authorization_status": authorization_status,
                    "_authorization_action_refuse": "Refuser+l'habilitation",
                }

                response = self.client.post(url, data=post_data)
                self.assertEqual(response.status_code, 403)

                updated_prescriberorganization = PrescriberOrganization.objects.get(pk=prescriberorganization.pk)
                self.assertEqual(updated_prescriberorganization.is_authorized, prescriberorganization.is_authorized)
                self.assertEqual(updated_prescriberorganization.kind, prescriberorganization.kind)
                self.assertIsNone(updated_prescriberorganization.authorization_updated_by)
                self.assertEqual(
                    updated_prescriberorganization.authorization_status, prescriberorganization.authorization_status
                )

    def test_accept_prescriber_habilitation_by_superuser(self):
        self.client.force_login(self.superuser)

        prescriberorganization = PrescriberOrganizationFactory(
            authorized=True,
            siret="83987278500010",
            department="14",
            post_code="14000",
            authorization_updated_at=datetime.now(tz=get_current_timezone()),
        )

        url = reverse("admin:prescribers_prescriberorganization_change", args=[prescriberorganization.pk])
        response = self.client.get(url)
        self.assertEqual(response.status_code, 200)

        for authorization_status, is_authorized in self.rights_list:
            with self.subTest(authorization_status=authorization_status, is_authorized=is_authorized):

                post_data = {
                    "id": prescriberorganization.pk,
                    "post_code": prescriberorganization.post_code,
                    "department": prescriberorganization.department,
                    "kind": prescriberorganization.kind,
                    "name": prescriberorganization.name,
                    "prescribermembership_set-TOTAL_FORMS": 1,
                    "prescribermembership_set-INITIAL_FORMS": 0,
                    "utils-pksupportremark-content_type-object_id-TOTAL_FORMS": 1,
                    "utils-pksupportremark-content_type-object_id-INITIAL_FORMS": 0,
                    "is_authorized": is_authorized,
                    "authorization_status": authorization_status,
                    "_authorization_action_validate": "Valider+l'habilitation",
                }

                response = self.client.post(url, data=post_data)
                self.assertEqual(response.status_code, 302)

                updated_prescriberorganization = PrescriberOrganization.objects.get(pk=prescriberorganization.pk)
                self.assertTrue(updated_prescriberorganization.is_authorized)
                self.assertEqual(updated_prescriberorganization.kind, prescriberorganization.kind)
                self.assertEqual(updated_prescriberorganization.authorization_updated_by, self.superuser)
                self.assertEqual(
                    updated_prescriberorganization.authorization_status,
                    PrescriberAuthorizationStatus.VALIDATED,
                )

    def test_accept_prescriber_habilitation_pending_status(self):
        self.client.force_login(self.user)

        prescriberorganization = PrescriberOrganizationFactory(
            authorized=True,
            siret="83987278500010",
            department="14",
            post_code="14000",
            authorization_updated_at=datetime.now(tz=get_current_timezone()),
            authorization_status=PrescriberAuthorizationStatus.NOT_SET,
            is_authorized=False,
        )

        url = reverse("admin:prescribers_prescriberorganization_change", args=[prescriberorganization.pk])
        response = self.client.get(url)
        self.assertEqual(response.status_code, 200)

        post_data = {
            "id": prescriberorganization.pk,
            "post_code": prescriberorganization.post_code,
            "department": prescriberorganization.department,
            "kind": prescriberorganization.kind,
            "name": prescriberorganization.name,
            "prescribermembership_set-TOTAL_FORMS": 1,
            "prescribermembership_set-INITIAL_FORMS": 0,
            "utils-pksupportremark-content_type-object_id-TOTAL_FORMS": 1,
            "utils-pksupportremark-content_type-object_id-INITIAL_FORMS": 0,
            "is_authorized": prescriberorganization.is_authorized,
            "authorization_status": prescriberorganization.authorization_status,
            "_authorization_action_validate": "Valider+l'habilitation",
        }

        response = self.client.post(url, data=post_data)
        self.assertEqual(response.status_code, 302)

        updated_prescriberorganization = PrescriberOrganization.objects.get(pk=prescriberorganization.pk)
        self.assertTrue(updated_prescriberorganization.is_authorized)
        self.assertEqual(updated_prescriberorganization.kind, prescriberorganization.kind)
        self.assertEqual(updated_prescriberorganization.authorization_updated_by, self.user)
        self.assertEqual(updated_prescriberorganization.authorization_status, PrescriberAuthorizationStatus.VALIDATED)

    def test_accept_prescriber_habilitation_refused_status(self):
        self.client.force_login(self.user)

        prescriberorganization = PrescriberOrganizationFactory(
            authorized=True,
            siret="83987278500010",
            department="14",
            post_code="14000",
            authorization_updated_at=datetime.now(tz=get_current_timezone()),
            authorization_status=PrescriberAuthorizationStatus.REFUSED,
            is_authorized=False,
        )

        url = reverse("admin:prescribers_prescriberorganization_change", args=[prescriberorganization.pk])
        response = self.client.get(url)
        self.assertEqual(response.status_code, 200)

        post_data = {
            "id": prescriberorganization.pk,
            "post_code": prescriberorganization.post_code,
            "department": prescriberorganization.department,
            "kind": prescriberorganization.kind,
            "name": prescriberorganization.name,
            "prescribermembership_set-TOTAL_FORMS": 1,
            "prescribermembership_set-INITIAL_FORMS": 0,
            "utils-pksupportremark-content_type-object_id-TOTAL_FORMS": 1,
            "utils-pksupportremark-content_type-object_id-INITIAL_FORMS": 0,
            "is_authorized": prescriberorganization.is_authorized,
            "authorization_status": prescriberorganization.authorization_status,
            "_authorization_action_validate": "Valider+l'habilitation",
        }

        response = self.client.post(url, data=post_data)
        self.assertEqual(response.status_code, 302)

        updated_prescriberorganization = PrescriberOrganization.objects.get(pk=prescriberorganization.pk)
        self.assertTrue(updated_prescriberorganization.is_authorized)
        self.assertEqual(updated_prescriberorganization.kind, prescriberorganization.kind)
        self.assertEqual(updated_prescriberorganization.authorization_updated_by, self.user)
        self.assertEqual(updated_prescriberorganization.authorization_status, PrescriberAuthorizationStatus.VALIDATED)

    def test_accept_prescriber_habilitation_other_status(self):
        self.client.force_login(self.user)

        prescriberorganization = PrescriberOrganizationFactory(
            authorized=True,
            siret="83987278500010",
            department="14",
            post_code="14000",
            authorization_updated_at=datetime.now(tz=get_current_timezone()),
        )

        url = reverse("admin:prescribers_prescriberorganization_change", args=[prescriberorganization.pk])
        response = self.client.get(url)
        self.assertEqual(response.status_code, 200)

        rights_list = [
            (authorization_status, is_authorized)
            for authorization_status, is_authorized in self.rights_list
            if authorization_status
            not in [
                PrescriberAuthorizationStatus.NOT_SET,
                PrescriberAuthorizationStatus.REFUSED,
            ]
        ]

        for authorization_status, is_authorized in rights_list:
            with self.subTest(authorization_status=authorization_status, is_authorized=is_authorized):

                post_data = {
                    "id": prescriberorganization.pk,
                    "post_code": prescriberorganization.post_code,
                    "department": prescriberorganization.department,
                    "kind": prescriberorganization.kind,
                    "name": prescriberorganization.name,
                    "prescribermembership_set-TOTAL_FORMS": 1,
                    "prescribermembership_set-INITIAL_FORMS": 0,
                    "utils-pksupportremark-content_type-object_id-TOTAL_FORMS": 1,
                    "utils-pksupportremark-content_type-object_id-INITIAL_FORMS": 0,
                    "is_authorized": is_authorized,
                    "authorization_status": authorization_status,
                    "_authorization_action_refuse": "Refuser+l'habilitation",
                }

                response = self.client.post(url, data=post_data)
                self.assertEqual(response.status_code, 403)

                updated_prescriberorganization = PrescriberOrganization.objects.get(pk=prescriberorganization.pk)
                self.assertEqual(updated_prescriberorganization.is_authorized, prescriberorganization.is_authorized)
                self.assertEqual(updated_prescriberorganization.kind, prescriberorganization.kind)
                self.assertIsNone(updated_prescriberorganization.authorization_updated_by)
                self.assertEqual(
                    updated_prescriberorganization.authorization_status, prescriberorganization.authorization_status
                )


class UpdateRefusedPrescriberOrganizationKindManagementCommandsTest(TestCase):
    def test_update_kind(self):
        # Prescriber organization - one sample per authorization status
        # One refused prescriber organizations without duplicated siret which will be
        # updated in this subset
        for authorization_status in list(PrescriberAuthorizationStatus):
            PrescriberOrganizationFactory(authorization_status=authorization_status)

        # Prescriber organization - Authorization Status = Refused - with duplicated siret
        # These Prescriber organization kind won't be updated into Other, because
        # of unicity constraint on (siret,kind)
        PrescriberOrganizationFactory(
            authorization_status=PrescriberAuthorizationStatus.REFUSED,
            siret="83987278500010",
            kind=PrescriberOrganizationKind.CHRS,
        )
        PrescriberOrganizationFactory(
            authorization_status=PrescriberAuthorizationStatus.REFUSED,
            siret="83987278500010",
            kind=PrescriberOrganizationKind.CHU,
        )

        # Controls before execution
        self.assertEqual(len(PrescriberAuthorizationStatus) + 2, PrescriberOrganization.objects.all().count())
        self.assertEqual(
            3,
            PrescriberOrganization.objects.filter(authorization_status=PrescriberAuthorizationStatus.REFUSED).count(),
        )
        self.assertEqual(0, PrescriberOrganization.objects.filter(kind=PrescriberOrganizationKind.OTHER).count())

        # Update refused prescriber organizations without duplicated siret
        call_command("update_refused_prescriber_organizations_kind")

        # Controls after execution
        self.assertEqual(len(PrescriberAuthorizationStatus) + 2, PrescriberOrganization.objects.all().count())
        self.assertEqual(
            3,
            PrescriberOrganization.objects.filter(authorization_status=PrescriberAuthorizationStatus.REFUSED).count(),
        )
        self.assertEqual(1, PrescriberOrganization.objects.filter(kind=PrescriberOrganizationKind.OTHER).count())
