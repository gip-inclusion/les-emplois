from django.core.management import call_command
from django.utils import timezone
from freezegun import freeze_time
from itoutils.django.testing import assertSnapshotQueries
from pytest_django.asserts import assertQuerySetEqual

from itou.nexus.enums import Role, Service
from itou.nexus.management.commands.populate_metabase_nexus import create_table, get_connection
from itou.nexus.models import NexusMembership, NexusRessourceSyncStatus, NexusStructure, NexusUser
from itou.nexus.utils import build_user, serialize_user, service_id, sync_users
from tests.cities.factories import create_city_saint_andre
from tests.companies.factories import CompanyMembershipFactory
from tests.prescribers.factories import PrescriberMembershipFactory
from tests.users.factories import EmployerFactory, PrescriberFactory


@freeze_time()
def test_populate_metabase_nexus(snapshot):
    authorized_prescriber = PrescriberFactory(email="1@mailinator.com")
    employer = EmployerFactory(email="2@mailinator.com")
    prescriber_1 = PrescriberFactory(email="3@mailinator.com")
    prescriber_2 = PrescriberFactory(email="4@mailinator.com")

    company_1 = CompanyMembershipFactory(
        user=employer,
        company__uid="11111111-1111-1111-1111-111111111111",
        company__insee_city=create_city_saint_andre(),
    ).company
    company_2 = CompanyMembershipFactory(
        user=employer,
        is_admin=False,
        company__uid="22222222-2222-2222-2222-222222222222",
    ).company
    organization_1 = PrescriberMembershipFactory(
        user=authorized_prescriber,
        organization__uid="33333333-3333-3333-3333-333333333333",
        organization__authorized=True,
    ).organization
    organization_2 = PrescriberMembershipFactory(
        user=prescriber_1,
        organization__uid="44444444-4444-4444-4444-444444444444",
    ).organization

    create_table(reset=True)
    with assertSnapshotQueries(snapshot(name="SQL queries")):
        call_command("populate_metabase_nexus")

    with get_connection() as conn, conn.cursor() as cursor:
        cursor.execute("SELECT * FROM users ORDER BY email")
        rows = cursor.fetchall()
        assert rows == [
            (
                "emplois-de-linclusion",
                str(authorized_prescriber.pk),
                f"emplois-de-linclusion--{authorized_prescriber.pk}",
                authorized_prescriber.last_name,
                authorized_prescriber.first_name,
                authorized_prescriber.email,
                authorized_prescriber.phone,
                authorized_prescriber.last_login,
                authorized_prescriber.get_identity_provider_display(),
                "prescripteur habilité",
                timezone.now(),
            ),
            (
                "emplois-de-linclusion",
                str(employer.pk),
                f"emplois-de-linclusion--{employer.pk}",
                employer.last_name,
                employer.first_name,
                employer.email,
                employer.phone,
                employer.last_login,
                employer.get_identity_provider_display(),
                "employeur",
                timezone.now(),
            ),
            (
                "emplois-de-linclusion",
                str(prescriber_1.pk),
                f"emplois-de-linclusion--{prescriber_1.pk}",
                prescriber_1.last_name,
                prescriber_1.first_name,
                prescriber_1.email,
                prescriber_1.phone,
                prescriber_1.last_login,
                prescriber_1.get_identity_provider_display(),
                "orienteur",
                timezone.now(),
            ),
            (
                "emplois-de-linclusion",
                str(prescriber_2.pk),
                f"emplois-de-linclusion--{prescriber_2.pk}",
                prescriber_2.last_name,
                prescriber_2.first_name,
                prescriber_2.email,
                prescriber_2.phone,
                prescriber_2.last_login,
                prescriber_2.get_identity_provider_display(),
                "orienteur",
                timezone.now(),
            ),
        ]

        cursor.execute("SELECT * FROM memberships ORDER BY structure_id_unique")
        rows = cursor.fetchall()
        assert rows == [
            (
                "emplois-de-linclusion",
                f"emplois-de-linclusion--{employer.pk}",
                "emplois-de-linclusion--11111111-1111-1111-1111-111111111111",
                "administrateur",
                timezone.now(),
            ),
            (
                "emplois-de-linclusion",
                f"emplois-de-linclusion--{employer.pk}",
                "emplois-de-linclusion--22222222-2222-2222-2222-222222222222",
                "collaborateur",
                timezone.now(),
            ),
            (
                "emplois-de-linclusion",
                f"emplois-de-linclusion--{authorized_prescriber.pk}",
                "emplois-de-linclusion--33333333-3333-3333-3333-333333333333",
                "administrateur",
                timezone.now(),
            ),
            (
                "emplois-de-linclusion",
                f"emplois-de-linclusion--{prescriber_1.pk}",
                "emplois-de-linclusion--44444444-4444-4444-4444-444444444444",
                "administrateur",
                timezone.now(),
            ),
        ]

        cursor.execute("SELECT * FROM structures ORDER BY id_unique")
        rows = cursor.fetchall()
        assert rows == [
            (
                "emplois-de-linclusion",
                str(company_1.pk),
                "emplois-de-linclusion--11111111-1111-1111-1111-111111111111",
                company_1.siret,
                company_1.display_name,
                f"company--{company_1.kind}",
                company_1.insee_city.code_insee,
                company_1.address_on_one_line,
                company_1.post_code,
                company_1.latitude,
                company_1.longitude,
                company_1.email,
                company_1.phone,
                timezone.now(),
            ),
            (
                "emplois-de-linclusion",
                str(company_2.pk),
                "emplois-de-linclusion--22222222-2222-2222-2222-222222222222",
                company_2.siret,
                company_2.display_name,
                f"company--{company_2.kind}",
                None,
                company_2.address_on_one_line,
                company_2.post_code,
                company_2.latitude,
                company_2.longitude,
                company_2.email,
                company_2.phone,
                timezone.now(),
            ),
            (
                "emplois-de-linclusion",
                str(organization_1.pk),
                "emplois-de-linclusion--33333333-3333-3333-3333-333333333333",
                organization_1.siret,
                organization_1.name,
                f"prescriber--{organization_1.kind}",
                None,
                organization_1.address_on_one_line,
                organization_1.post_code,
                organization_1.latitude,
                organization_1.longitude,
                organization_1.email,
                organization_1.phone,
                timezone.now(),
            ),
            (
                "emplois-de-linclusion",
                str(organization_2.pk),
                "emplois-de-linclusion--44444444-4444-4444-4444-444444444444",
                organization_2.siret,
                organization_2.name,
                f"prescriber--{organization_2.kind}",
                None,
                organization_2.address_on_one_line,
                organization_2.post_code,
                organization_2.latitude,
                organization_2.longitude,
                organization_2.email,
                organization_2.phone,
                timezone.now(),
            ),
        ]


def test_sync_data(caplog):
    authorized_prescriber = PrescriberFactory(email="1@mailinator.com")
    employer = EmployerFactory(email="2@mailinator.com")
    prescriber_1 = PrescriberFactory(email="3@mailinator.com")
    prescriber_2 = PrescriberFactory(email="4@mailinator.com")

    company_membership_1 = CompanyMembershipFactory(
        user=employer,
        company__uid="11111111-1111-1111-1111-111111111111",
        company__insee_city=create_city_saint_andre(),
    )
    company_membership_2 = CompanyMembershipFactory(
        user=employer,
        is_admin=False,
        company__uid="22222222-2222-2222-2222-222222222222",
    )
    prescriber_membership_1 = PrescriberMembershipFactory(
        user=authorized_prescriber,
        organization__uid="33333333-3333-3333-3333-333333333333",
        organization__authorized=True,
    )
    prescriber_membership_2 = PrescriberMembershipFactory(
        user=prescriber_1,
        organization__uid="44444444-4444-4444-4444-444444444444",
    )

    NexusUser.objects.all().delete()
    NexusStructure.objects.all().delete()
    # no need to delete NexusMembership, they were all removed when removing the users

    call_command("nexus_sync_data")
    assert set(caplog.messages[:-1]) == {
        f"NexusSync: Missing instance=NexusUser object (emplois-de-linclusion--{authorized_prescriber.pk})",
        f"NexusSync: Missing instance=NexusUser object (emplois-de-linclusion--{employer.pk})",
        f"NexusSync: Missing instance=NexusUser object (emplois-de-linclusion--{prescriber_1.pk})",
        f"NexusSync: Missing instance=NexusUser object (emplois-de-linclusion--{prescriber_2.pk})",
        "NexusSync: Missing instance=NexusStructure object "
        "(emplois-de-linclusion--22222222-2222-2222-2222-222222222222)",
        "NexusSync: Missing instance=NexusStructure object "
        "(emplois-de-linclusion--11111111-1111-1111-1111-111111111111)",
        "NexusSync: Missing instance=NexusStructure object "
        "(emplois-de-linclusion--44444444-4444-4444-4444-444444444444)",
        "NexusSync: Missing instance=NexusStructure object "
        "(emplois-de-linclusion--33333333-3333-3333-3333-333333333333)",
        f"NexusSync: Missing instance=NexusMembership object (emplois-de-linclusion--{company_membership_1.nexus_id})",
        f"NexusSync: Missing instance=NexusMembership object (emplois-de-linclusion--{company_membership_2.nexus_id})",
        "NexusSync: Missing instance=NexusMembership object "
        f"(emplois-de-linclusion--{prescriber_membership_1.nexus_id})",
        "NexusSync: Missing instance=NexusMembership object "
        f"(emplois-de-linclusion--{prescriber_membership_2.nexus_id})",
    }

    assertQuerySetEqual(
        NexusUser.objects.values_list("pk", flat=True),
        [
            service_id(Service.EMPLOIS, authorized_prescriber.pk),
            service_id(Service.EMPLOIS, prescriber_1.pk),
            service_id(Service.EMPLOIS, prescriber_2.pk),
            service_id(Service.EMPLOIS, employer.pk),
        ],
        ordered=False,
    )
    assertQuerySetEqual(
        NexusMembership.objects.values_list("user_id", "structure_id"),
        [
            (
                service_id(Service.EMPLOIS, authorized_prescriber.pk),
                service_id(Service.EMPLOIS, prescriber_membership_1.organization.uid),
            ),
            (
                service_id(Service.EMPLOIS, prescriber_1.pk),
                service_id(Service.EMPLOIS, prescriber_membership_2.organization.uid),
            ),
            (service_id(Service.EMPLOIS, employer.pk), service_id(Service.EMPLOIS, company_membership_1.company.uid)),
            (service_id(Service.EMPLOIS, employer.pk), service_id(Service.EMPLOIS, company_membership_2.company.uid)),
        ],
        ordered=False,
    )
    assertQuerySetEqual(
        NexusStructure.objects.values_list("pk", flat=True),
        [
            service_id(Service.EMPLOIS, prescriber_membership_1.organization.uid),
            service_id(Service.EMPLOIS, prescriber_membership_2.organization.uid),
            service_id(Service.EMPLOIS, company_membership_1.company.uid),
            service_id(Service.EMPLOIS, company_membership_2.company.uid),
        ],
        ordered=False,
    )

    # Sync again to check there no warning logs
    caplog.clear()
    call_command("nexus_sync_data")
    assert caplog.messages[:-1] == []

    # Using no-checks option
    NexusUser.objects.all().delete()
    NexusStructure.objects.all().delete()
    caplog.clear()
    call_command("nexus_sync_data", no_checks=True)
    assert caplog.messages[:-1] == []

    # Check Pilotage and Mon-Récap data sync
    # mock old users for pilotage and mon_recap
    sync_users([build_user(serialize_user(employer), service) for service in [Service.PILOTAGE, Service.MON_RECAP]])
    NexusRessourceSyncStatus.objects.update(valid_since=timezone.now())
    assert NexusUser.objects.filter().count() == 0

    call_command("nexus_sync_data")
    assertQuerySetEqual(
        NexusUser.objects.values_list("pk", flat=True),
        [
            service_id(Service.EMPLOIS, authorized_prescriber.pk),
            service_id(Service.EMPLOIS, prescriber_1.pk),
            service_id(Service.EMPLOIS, prescriber_2.pk),
            service_id(Service.EMPLOIS, employer.pk),
            service_id(Service.MON_RECAP, employer.pk),
            service_id(Service.PILOTAGE, employer.pk),
        ],
        ordered=False,
    )

    # With a diff detected
    NexusUser.objects.filter(source_id=prescriber_1.pk).update(first_name="Fifi")
    NexusStructure.objects.filter(source_id=company_membership_1.company.uid).update(name="Carrouf")
    NexusMembership.objects.filter(source_id=f"c-{company_membership_1.pk}").update(role=Role.COLLABORATOR)
    caplog.clear()
    call_command("nexus_sync_data")
    assert caplog.messages[:-1] == [
        f"NexusSync: diff detected on instance=NexusUser object (emplois-de-linclusion--{prescriber_1.pk}) "
        "fields=[first_name]",
        "NexusSync: diff detected on instance=NexusStructure object "
        "(emplois-de-linclusion--11111111-1111-1111-1111-111111111111) "
        "fields=[name]",
        "NexusSync: diff detected on instance=NexusMembership object "
        f"(emplois-de-linclusion--{company_membership_1.nexus_id}) fields=[role]",
    ]
