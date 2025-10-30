from django.core.management import call_command
from django.utils import timezone
from freezegun import freeze_time

from itou.nexus.management.commands.populate_metabase_nexus import create_table, get_connection
from tests.cities.factories import create_city_saint_andre
from tests.companies.factories import CompanyMembershipFactory
from tests.prescribers.factories import PrescriberMembershipFactory
from tests.users.factories import EmployerFactory, PrescriberFactory


@freeze_time()
def test_populate_metabase_nexus(db):
    prescriber = PrescriberFactory(email="1@mailinator.com")
    employer = EmployerFactory(email="2@mailinator.com")

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
    organization = PrescriberMembershipFactory(
        user=prescriber,
        organization__uid="33333333-3333-3333-3333-333333333333",
    ).organization

    create_table(reset=True)
    call_command("populate_metabase_nexus")

    with get_connection() as conn, conn.cursor() as cursor:
        cursor.execute("SELECT * FROM users ORDER BY email")
        rows = cursor.fetchall()
        assert rows == [
            (
                "emplois-de-linclusion",
                str(prescriber.pk),
                f"emplois-de-linclusion--{prescriber.pk}",
                prescriber.last_name,
                prescriber.first_name,
                prescriber.email,
                prescriber.phone,
                prescriber.last_login,
                prescriber.get_identity_provider_display(),
                "prescripteur",
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
                f"emplois-de-linclusion--{prescriber.pk}",
                "emplois-de-linclusion--33333333-3333-3333-3333-333333333333",
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
                str(organization.pk),
                "emplois-de-linclusion--33333333-3333-3333-3333-333333333333",
                organization.siret,
                organization.name,
                f"prescriber--{organization.kind}",
                None,
                organization.address_on_one_line,
                organization.post_code,
                organization.latitude,
                organization.longitude,
                organization.email,
                organization.phone,
                timezone.now(),
            ),
        ]
