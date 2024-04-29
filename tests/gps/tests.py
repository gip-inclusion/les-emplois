from django.urls import reverse
from pytest_django.asserts import assertContains

from itou.users.models import User
from tests.gps.factories import FollowUpGroupFactory
from tests.users.factories import JobSeekerFactory, PrescriberFactory
from tests.utils.test import parse_response_to_soup


def test_user_autocomplete():

    member = PrescriberFactory(first_name="gps member first_name")
    beneficiary = JobSeekerFactory(first_name="gps beneficiary first_name")
    another_beneficiary = JobSeekerFactory(first_name="gps another beneficiary first_name")

    FollowUpGroupFactory(beneficiary=beneficiary, memberships=4, memberships__member=member)
    FollowUpGroupFactory(beneficiary=another_beneficiary, memberships=2)

    assert User.objects.autocomplete("gps").count() == 3
    assert User.objects.autocomplete("gps member").count() == 1

    # We should not get ourself nor the other user because we are a member of his group
    users = User.objects.autocomplete("gps", current_user=member)
    assert users.count() == 1
    assert users[0].id == another_beneficiary.id


def test_navigation(snapshot, client):

    member = PrescriberFactory(first_name="gps member first_name")
    member_first_beneficiary = JobSeekerFactory(first_name="gps first beneficiary first_name")
    member_second_beneficiary = JobSeekerFactory(first_name="gps second beneficiary first_name")

    FollowUpGroupFactory(beneficiary=member_first_beneficiary, memberships=4, memberships__member=member)
    FollowUpGroupFactory(beneficiary=member_second_beneficiary, memberships=2, memberships__member=member)

    client.force_login(member)

    response = client.get(reverse("dashboard:index"))

    assert str(parse_response_to_soup(response, ".c-box__header--gps")) == snapshot

    response = client.get(reverse("gps:my_groups"))

    assertContains(response, member_first_beneficiary.get_full_name())
    assertContains(response, member_second_beneficiary.get_full_name())

    assertContains(response, member_first_beneficiary.email)
    assertContains(response, member_second_beneficiary.email)

    assertContains(response, "référent")

    assertContains(response, "2 bénéficiaires suivis")
