from itou.cities.models import DirectoryActiveCity
from itou.directory.services import get_directory_people
from itou.prescribers.enums import PrescriberOrganizationKind
from tests.cities.factories import create_city_vannes
from tests.companies.factories import CompanyFactory, CompanyMembershipFactory
from tests.prescribers.factories import PrescriberMembershipFactory, PrescriberOrganizationFactory
from tests.users.factories import EmployerFactory, PrescriberFactory


def setup_directory(client, *, target_phone="0601020304"):
    city = create_city_vannes()
    DirectoryActiveCity.objects.create(city=city)
    current_user = EmployerFactory(membership=False)
    current_company = CompanyFactory(coords=city.coords, insee_city=city)
    CompanyMembershipFactory(user=current_user, company=current_company)
    target = PrescriberFactory(
        membership=False,
        first_name="Alice",
        last_name="Martin",
        email="alice@example.com",
        phone=target_phone,
    )
    target_organization = PrescriberOrganizationFactory(
        authorized=True,
        kind=PrescriberOrganizationKind.ML,
        name="Mission locale de Vannes",
        coords=city.coords,
        insee_city=city,
        phone="0299000000",
        email="structure@example.com",
        website="https://mission-locale.example",
        address_line_1="1 rue de Vannes",
        post_code="56000",
        city="Vannes",
    )
    PrescriberMembershipFactory(user=target, organization=target_organization)
    client.force_login(current_user)
    return current_user, target, target_organization, city


def get_target_person(client, *, target_phone="0601020304"):
    current_user, target, target_organization, city = setup_directory(client, target_phone=target_phone)
    person = next(person for person in get_directory_people(city.coords) if person.email == target.email)
    return current_user, target, target_organization, person
