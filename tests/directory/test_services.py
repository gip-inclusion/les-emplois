from django.contrib.gis.geos import Point
from django.core import signing

from itou.directory.services import PERSON_KEY_SALT, get_directory_people, get_directory_person
from itou.nexus.enums import NexusStructureKind, NexusUserKind, Service
from tests.companies.factories import CompanyFactory, CompanyMembershipFactory
from tests.insertion.factories import StructureFactory
from tests.nexus.factories import NexusMembershipFactory
from tests.users.factories import ProfessionalFactory


ORIGIN = Point(-0.58, 44.84, srid=4326)


def test_directory_people_merge_memberships_by_email():
    user = ProfessionalFactory(first_name="Alice", last_name="Martin", email="alice@example.com")
    company = CompanyFactory(coords=ORIGIN, kind="EI")
    CompanyMembershipFactory(user=user, company=company)
    nexus_membership = NexusMembershipFactory(
        source=Service.DORA,
        user__source=Service.DORA,
        user__email=user.email,
        user__first_name=user.first_name,
        user__last_name=user.last_name,
        user__kind=NexusUserKind.GUIDE,
        structure__source=Service.DORA,
        structure__coords=Point(-0.57, 44.84, srid=4326),
        structure__kind=NexusStructureKind.ML,
        structure__siret="12345678901234",
    )

    [person] = get_directory_people(ORIGIN)

    assert person.full_name == "Alice Martin"
    assert person.kind == NexusUserKind.GUIDE
    assert person.recipient_id == nexus_membership.user_id
    assert signing.loads(person.key, salt=PERSON_KEY_SALT) == person.recipient_id
    assert user.email not in person.key
    assert len(person.organizations) == 2
    assert person.main_organization.siret == company.siret
    assert get_directory_person(ORIGIN, person.key).email == user.email


def test_directory_people_exclude_opted_out_email_and_distant_structure():
    opted_out = ProfessionalFactory(email="hidden@example.com", is_directory_opted_out=True)
    NexusMembershipFactory(
        source=Service.DORA,
        user__source=Service.DORA,
        user__email=opted_out.email,
        structure__source=Service.DORA,
        structure__coords=ORIGIN,
    )
    visible = ProfessionalFactory()
    CompanyMembershipFactory(
        user=visible,
        company=CompanyFactory(coords=Point(2.35, 48.85, srid=4326)),
    )

    assert get_directory_people(ORIGIN) == []


def test_directory_people_keeps_structures_within_radius():
    nearby = ProfessionalFactory(first_name="Near", last_name="By")
    CompanyMembershipFactory(user=nearby, company=CompanyFactory(coords=Point(-0.58, 44.93, srid=4326)))
    far = ProfessionalFactory(first_name="Far", last_name="Away")
    CompanyMembershipFactory(user=far, company=CompanyFactory(coords=Point(-0.58, 45.20, srid=4326)))

    people = get_directory_people(ORIGIN)

    assert [person.full_name for person in people] == ["Near By"]


def test_directory_people_dedupes_organizations_by_siret():
    user = ProfessionalFactory(email="alice@example.com")
    company = CompanyFactory(coords=ORIGIN, kind="EI", siret="12345678901234")
    CompanyMembershipFactory(user=user, company=company)
    NexusMembershipFactory(
        source=Service.DORA,
        user__source=Service.DORA,
        user__email=user.email,
        structure__source=Service.DORA,
        structure__coords=ORIGIN,
        structure__siret=company.siret,
        structure__kind=NexusStructureKind.EI,
    )

    [person] = get_directory_people(ORIGIN)

    assert len(person.organizations) == 1
    assert person.organizations[0].siret == company.siret


def test_directory_people_resolves_dora_structure_by_siret():
    siret = "12345678901234"
    dora_structure = StructureFactory(
        siret=siret,
        name="Mission locale DORA",
        coordinates=ORIGIN,
        phone="0297010203",
        email="dora@example.com",
        website="https://dora.example.com",
    )
    NexusMembershipFactory(
        source=Service.DORA,
        user__source=Service.DORA,
        user__email="guide@example.com",
        user__kind=NexusUserKind.GUIDE,
        structure__source=Service.DORA,
        structure__source_id=dora_structure.uid,
        structure__coords=ORIGIN,
        structure__siret=siret,
        structure__kind=NexusStructureKind.ML,
    )
    StructureFactory(
        siret=siret,
        name="Autre structure avec le même SIRET",
        coordinates=ORIGIN,
    )

    [person] = get_directory_people(ORIGIN)

    assert person.main_organization.name == "Mission locale DORA"
    assert person.main_organization.phone == "0297010203"
    assert dora_structure.uid in person.main_organization.card_url


def test_directory_people_uses_closest_organization_as_main():
    user = ProfessionalFactory()
    close_company = CompanyFactory(name="Proche", coords=ORIGIN, kind="EI")
    farther_company = CompanyFactory(name="Loin", coords=Point(-0.58, 44.93, srid=4326), kind="ACI")
    CompanyMembershipFactory(user=user, company=farther_company)
    CompanyMembershipFactory(user=user, company=close_company)

    [person] = get_directory_people(ORIGIN)

    assert person.main_organization.name == close_company.display_name
    assert person.other_organizations_count == 1
