import random
from unittest.mock import PropertyMock

from django.utils import timezone
from pytest_django.asserts import assertQuerySetEqual

from itou.companies.models import CompanyMembership
from itou.nexus.enums import Service
from itou.nexus.models import NexusMembership, NexusStructure, NexusUser
from itou.nexus.utils import service_id
from itou.prescribers.models import PrescriberMembership
from itou.users.models import User
from tests.companies.factories import CompanyFactory, CompanyMembershipFactory, SiaeConventionFactory
from tests.prescribers.factories import PrescriberMembershipFactory, PrescriberOrganizationFactory
from tests.users.factories import (
    EmployerFactory,
    ItouStaffFactory,
    JobSeekerFactory,
    LaborInspectorFactory,
    PrescriberFactory,
)


def assert_user_synced(user):
    assertQuerySetEqual(
        NexusUser.objects.all(),
        [(service_id(Service.EMPLOIS, user.pk))],
        transform=lambda o: o.pk,
    )


def assert_structure_synced(structure):
    assertQuerySetEqual(
        NexusStructure.objects.all(),
        [(service_id(Service.EMPLOIS, structure.uid))],
        transform=lambda o: o.pk,
    )


def assert_membership_synced(membership):
    assertQuerySetEqual(
        NexusMembership.objects.all(),
        [(service_id(Service.EMPLOIS, membership.nexus_id))],
        transform=lambda o: o.pk,
    )


class TestUser:
    def test_user_model_save(self):
        factory = random.choice([PrescriberFactory, EmployerFactory])
        user = factory.build()
        user.save()
        assert_user_synced(user)

        # if inactive, we clean the user
        user.is_active = False
        user.save()
        assert NexusUser.objects.count() == 0

        # if no email
        user.is_active = True
        user.email = None
        user.save()
        assert NexusUser.objects.count() == 0

        # if not an employer or prescriber
        for factory in [JobSeekerFactory, LaborInspectorFactory, ItouStaffFactory]:
            user = factory.build()
            user.save()
        assert NexusUser.objects.count() == 0

    def test_user_model_delete(self):
        factory = random.choice([PrescriberFactory, EmployerFactory])
        user = factory()
        assert_user_synced(user)

        user.delete()
        assert NexusUser.objects.count() == 0

    def test_user_manager_update(self):
        factory = random.choice([PrescriberFactory, EmployerFactory])
        user = factory()
        assert_user_synced(user)

        # Updating is_active
        User.objects.update(is_active=False)
        assert NexusUser.objects.count() == 0

        User.objects.update(is_active=True)
        assert_user_synced(user)

        # Updating an untracked field does nont sync data again
        NexusUser.objects.all().delete()
        User.objects.update(address_filled_at=timezone.now())
        assert NexusUser.objects.count() == 0

        # Update a tracked field
        User.objects.update(first_name="Jeanmiche")
        assert_user_synced(user)


class TestPrescriberOrganisation:
    def test_organization_model_save(self):
        org = PrescriberOrganizationFactory.build()
        org.save()
        assert_structure_synced(org)

    def test_organization_model_delete(self):
        org = PrescriberOrganizationFactory()
        assert_structure_synced(org)

        org.delete()
        assert NexusStructure.objects.count() == 0


class TestCompanyOrganisation:
    def test_company_model_save(self, mocker):
        convention = SiaeConventionFactory()
        company = CompanyFactory.build(kind="EI", convention=convention)
        company.save()
        assert_structure_synced(company)

        mocker.patch("itou.companies.models.Company.is_active", new_callable=PropertyMock(return_value=False))
        company.brand = "Toto"
        company.save()
        assert NexusStructure.objects.count() == 0

    def test_company_model_delete(self):
        company = CompanyFactory()
        assert_structure_synced(company)

        company.delete()
        assert NexusStructure.objects.count() == 0


class TestPrescriberMembership:
    def test_prescriber_membership_model_save(self):
        prescriber = PrescriberFactory()
        org = PrescriberOrganizationFactory()
        membership = PrescriberMembershipFactory.build(user=prescriber, organization=org)
        membership.save()
        assert_membership_synced(membership)

        # Inactive memberships are removed from nexus data
        membership.is_active = False
        membership.save()
        assert NexusMembership.objects.count() == 0

        membership.is_active = True
        membership.save()
        assert_membership_synced(membership)

        # inactive users have all their memberships removed (thanks to cascading)
        prescriber.is_active = False
        prescriber.save()
        assert NexusMembership.objects.count() == 0

    def test_prescriber_membership_model_delete(self):
        membership = PrescriberMembershipFactory()
        assert_membership_synced(membership)

        membership.delete()
        assert NexusMembership.objects.count() == 0

    def test_prescriber_membership_manager_update(self):
        membership = PrescriberMembershipFactory()
        assert_membership_synced(membership)

        # Updating is_active
        PrescriberMembership.objects.update(is_active=False)
        assert NexusMembership.objects.count() == 0

        PrescriberMembership.include_inactive.update(is_active=True)
        assert_membership_synced(membership)


class TestCompanyMembership:
    def test_company_membership_model_save(self, mocker):
        employer = EmployerFactory()
        company = CompanyFactory()
        membership = CompanyMembershipFactory.build(user=employer, company=company)
        membership.save()
        assert_membership_synced(membership)

        # Inactive memberships are removed from nexus data
        membership.is_active = False
        membership.save()
        assert NexusMembership.objects.count() == 0

        membership.is_active = True
        membership.save()
        assert_membership_synced(membership)

        # inactive users have all their memberships removed (thanks to cascading)
        employer.is_active = False
        employer.save()
        assert NexusMembership.objects.count() == 0

        # inactive company also have their memberships removed
        employer.is_active = True
        employer.save()
        membership.is_active = True
        membership.save()
        assert_membership_synced(membership)

        mocker.patch("itou.companies.models.Company.is_active", new_callable=PropertyMock(return_value=False))
        membership.save()
        assert NexusMembership.objects.count() == 0

    def test_company_membership_model_delete(self):
        membership = CompanyMembershipFactory()
        assert_membership_synced(membership)

        membership.delete()
        assert NexusMembership.objects.count() == 0

    def test_company_membership_manager_update(self, mocker):
        membership = CompanyMembershipFactory()
        assert_membership_synced(membership)

        # Updating is_active
        CompanyMembership.objects.update(is_active=False)
        assert NexusMembership.objects.count() == 0

        CompanyMembership.include_inactive.update(is_active=True)
        assert_membership_synced(membership)

        # inactive company also have their memberships removed
        mocker.patch("itou.companies.models.Company.is_active", new_callable=PropertyMock(return_value=False))
        CompanyMembership.objects.update(is_active=True)
        assert NexusMembership.objects.count() == 0
