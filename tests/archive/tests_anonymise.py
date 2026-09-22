from itou.archive.anonymize import deactivate_professionals_without_deletion
from itou.companies.models import CompanyMembership
from itou.users.models import User
from itou.utils import triggers
from tests.cities.factories import create_city_saint_andre
from tests.companies.factories import CompanyMembershipFactory
from tests.users.factories import ItouStaffFactory


def test_deactivate_professional_without_deletion():
    city = create_city_saint_andre()
    membership = CompanyMembershipFactory(
        user__is_active=True,
        user__first_name="Alice",
        user__last_name="Cooper",
        user__phone=f"06060{city.post_codes[0]}",
        user__address_line_1="8 rue du moulin",
        user__address_line_2="Apt 4B",
        user__post_code=city.post_codes[0],
        user__city="Test City",
        user__coords=city.coords,
        user__insee_city=city,
        user__email=f"test{city.post_codes[0]}@mail.com",
        user__with_verified_email=True,
        is_active=True,
        is_admin=True,
        updated_by=ItouStaffFactory(),
    )
    employer = membership.user
    username_before_anonymization = employer.username
    updated_at_before_anonymization = membership.updated_at

    with triggers.fake_context():
        deactivate_professionals_without_deletion([employer])

    employer = User.objects.get(pk=employer.pk)
    assert not employer.is_active
    assert employer.email is None
    assert employer.phone == ""
    assert employer.address_line_1 == ""
    assert employer.address_line_2 == ""
    assert employer.post_code == ""
    assert employer.city == ""
    assert employer.coords is None
    assert employer.insee_city is None
    assert employer.first_name == "Alice"
    assert employer.last_name == "Cooper"
    assert employer.username == f"old_{employer.pk}_{username_before_anonymization}"

    membership = CompanyMembership.include_inactive.get(user=employer)
    assert not membership.is_active
    assert not membership.is_admin
    assert membership.updated_by is None
    assert membership.updated_at > updated_at_before_anonymization
