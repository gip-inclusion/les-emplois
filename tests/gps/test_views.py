import freezegun
import pytest
from django.test.utils import override_settings
from django.urls import reverse
from pytest_django.asserts import assertContains, assertQuerySetEqual, assertRedirects

from itou.gps.models import FollowUpGroup, FollowUpGroupMembership, FranceTravailContact
from itou.users.models import User
from tests.gps.factories import FollowUpGroupFactory
from tests.prescribers.factories import PrescriberOrganizationWithMembershipFactory
from tests.users.factories import (
    EmployerFactory,
    JobSeekerFactory,
    JobSeekerWithAddressFactory,
    PrescriberFactory,
)
from tests.utils.htmx.test import assertSoupEqual, update_page_with_htmx
from tests.utils.test import parse_response_to_soup


def test_job_seeker_cannot_use_gps(client):
    job_seeker = JobSeekerFactory()
    client.force_login(job_seeker)
    group = FollowUpGroupFactory(beneficiary=job_seeker)

    for route, kwargs in [
        ("gps:my_groups", {}),
        ("gps:join_group", {}),
        ("gps:leave_group", {"group_id": group.pk}),
        ("gps:toggle_referent", {"group_id": group.pk}),
    ]:
        response = client.get(reverse(route, kwargs=kwargs))
        assertRedirects(response, reverse("dashboard:index"), fetch_redirect_response=False)
    response = client.get(reverse("users:details", kwargs={"public_id": job_seeker.public_id}))
    assert response.status_code == 403


def test_orienter_cannot_use_gps(client):
    prescriber = PrescriberFactory()
    job_seeker = JobSeekerFactory()
    client.force_login(prescriber)
    group = FollowUpGroupFactory(beneficiary=job_seeker, memberships__member=prescriber)

    for route, kwargs in [
        ("gps:my_groups", {}),
        ("gps:join_group", {}),
        ("gps:leave_group", {"group_id": group.pk}),
        ("gps:toggle_referent", {"group_id": group.pk}),
    ]:
        response = client.get(reverse(route, kwargs=kwargs))
        assertRedirects(response, reverse("dashboard:index"), fetch_redirect_response=False)
    response = client.get(reverse("users:details", kwargs={"public_id": job_seeker.public_id}))
    assert response.status_code == 403


def test_user_autocomplete():
    prescriber = PrescriberFactory(first_name="gps member Vince")
    first_beneficiary = JobSeekerFactory(first_name="gps beneficiary Bob", last_name="Le Brico")
    second_beneficiary = JobSeekerFactory(first_name="gps second beneficiary Martin", last_name="Pêcheur")
    third_beneficiary = JobSeekerFactory(first_name="gps third beneficiary Foo", last_name="Bar")

    my_group = FollowUpGroupFactory(beneficiary=first_beneficiary, memberships=4, memberships__member=prescriber)
    FollowUpGroupFactory(beneficiary=third_beneficiary, memberships=3, memberships__member=prescriber)
    FollowUpGroupFactory(beneficiary=second_beneficiary, memberships=2)

    # Employers should get the 3 job seekers.
    users = User.objects.autocomplete("gps", EmployerFactory())
    assertQuerySetEqual(users, [first_beneficiary, second_beneficiary, third_beneficiary], ordered=False)

    # Authorized prescribers should get the 3 job seekers.
    org = PrescriberOrganizationWithMembershipFactory(authorized=True)
    users = User.objects.autocomplete("gps", org.members.get())
    assertQuerySetEqual(users, [first_beneficiary, second_beneficiary, third_beneficiary], ordered=False)

    # We should not get ourself nor the first and third user user because we are a member of their group
    users = User.objects.autocomplete("gps", prescriber).all()
    assertQuerySetEqual(users, [second_beneficiary])

    # Now, if we remove the first user from our group by setting the membership to is_active False
    # The autocomplete should return it again
    membership = FollowUpGroupMembership.objects.filter(member=prescriber).filter(follow_up_group=my_group).first()
    membership.is_active = False
    membership.save()

    # We should not get ourself but we should get the first beneficiary (we are is_active=False)
    # and the second one (we are not part of his group)
    users = User.objects.autocomplete("gps", prescriber)

    assertQuerySetEqual(users, [first_beneficiary, second_beneficiary], ordered=False)


@pytest.mark.parametrize(
    "is_referent",
    [
        True,
        False,
    ],
)
def test_join_group_of_a_job_seeker(is_referent, client):
    prescriber = PrescriberFactory(membership__organization__authorized=True)
    job_seeker = JobSeekerFactory()

    client.force_login(prescriber)

    url = reverse("gps:join_group")

    response = client.get(url)

    post_data = {
        "user": job_seeker.id,
        "is_referent": is_referent,
    }

    response = client.post(url, data=post_data)
    assert response.status_code == 302

    # A follow up group and a membership to this group should have been created
    assert FollowUpGroup.objects.count() == 1
    follow_up_group = FollowUpGroup.objects.get(beneficiary=job_seeker)
    assert FollowUpGroupMembership.objects.count() == 1
    membership = (
        FollowUpGroupMembership.objects.filter(member=prescriber).filter(follow_up_group=follow_up_group).first()
    )

    assert membership.is_referent == is_referent

    # Login with another prescriber and join the same follow_up_group
    other_prescriber = PrescriberFactory(membership__organization__authorized=True)

    client.force_login(other_prescriber)

    post_data = {
        "user": job_seeker.id,
        "is_referent": not is_referent,
    }

    response = client.post(url, data=post_data)
    assert response.status_code == 302

    # We should not have created another FollowUpGroup
    assert FollowUpGroup.objects.count() == 1
    follow_up_group = FollowUpGroup.objects.get(beneficiary=job_seeker)

    # Just a new membership should have been created
    assert FollowUpGroupMembership.objects.count() == 2


def test_join_group_of_a_prescriber(client):
    prescriber = PrescriberFactory(membership__organization__authorized=True)
    another_prescriber = PrescriberFactory(membership=True)

    client.force_login(prescriber)

    url = reverse("gps:join_group")

    response = client.get(url)

    post_data = {
        "user": another_prescriber.id,
        "is_referent": True,
    }

    response = client.post(url, data=post_data)

    # We should not be redirected to "my_groups" because the form is not valid
    # regarding queryset=User.objects.filter(kind=UserKind.JOB_SEEKER)
    assert response.status_code == 200
    assertContains(
        response,
        "Sélectionnez un choix valide. Ce choix ne fait pas partie de ceux disponibles.",
    )


@override_settings(TALLY_URL="https://hello-tally.so")
def test_dashboard_card(snapshot, client):
    member = PrescriberFactory(
        for_snapshot=True,
        membership=True,
        membership__organization__authorized=True,
        membership__organization__for_snapshot=True,
    )
    client.force_login(member)
    response = client.get(reverse("dashboard:index"))
    assert str(parse_response_to_soup(response, "#gps-card")) == snapshot


@freezegun.freeze_time("2024-06-21", tick=True)
def test_my_groups(snapshot, client):
    user = PrescriberFactory(membership__organization__authorized=True, membership__organization__for_snapshot=True)
    client.force_login(user)

    # Nominal case
    # Groups created latelly should come first.
    group = FollowUpGroupFactory(memberships=1, for_snapshot=True)
    FollowUpGroup.objects.follow_beneficiary(beneficiary=group.beneficiary, user=user)

    response = client.get(reverse("gps:my_groups"))
    groups = parse_response_to_soup(
        response,
        selector="#follow-up-groups-section",
        replace_in_attr=[
            ("data-bs-confirm-url", f"/gps/groups/{group.pk}", "/gps/groups/[PK of Group]"),
        ],
    ).select(".membership-card")
    assert len(groups) == 1
    assert str(groups[0]) == snapshot(name="test_my_groups__group_card")

    # Test `is_referent` display.
    group = FollowUpGroupFactory(memberships=1, beneficiary__first_name="Janis", beneficiary__last_name="Joplin")
    FollowUpGroup.objects.follow_beneficiary(beneficiary=group.beneficiary, user=user, is_referent=True)
    response = client.get(reverse("gps:my_groups"))
    groups = parse_response_to_soup(response, selector="#follow-up-groups-section").select(".membership-card")
    assert len(groups) == 2
    assert "Janis" in str(groups[0])
    assert "et êtes <strong>référent</strong>" in str(groups[0])


def test_access_as_jobseeker(client):
    user = JobSeekerWithAddressFactory()
    client.force_login(user)

    response = client.get(reverse("gps:my_groups"))
    assert response.status_code == 302

    response = client.get(reverse("gps:join_group"))
    assert response.status_code == 302


def test_leave_group(client):
    member = PrescriberFactory(membership__organization__authorized=True)
    another_member = PrescriberFactory(membership=True)

    beneficiary = JobSeekerFactory()
    another_beneficiary = JobSeekerFactory()

    my_group = FollowUpGroupFactory(beneficiary=beneficiary, memberships=4, memberships__member=member)
    another_group = FollowUpGroupFactory(
        beneficiary=another_beneficiary,
        memberships=2,
        memberships__member=another_member,
    )

    # We have 4 group members
    assert my_group.members.count() == 4

    # And the 4 are active
    assert FollowUpGroupMembership.objects.filter(is_active=True).filter(follow_up_group=my_group).count() == 4

    client.force_login(member)
    response = client.get(reverse("gps:leave_group", kwargs={"group_id": my_group.id}))
    assert response.status_code == 302

    # We still have 4 group members
    assert my_group.members.count() == 4
    # But only 3 are active
    assert FollowUpGroupMembership.objects.filter(is_active=True).filter(follow_up_group=my_group).count() == 3

    # We can't leave a group we're not part of
    assert another_group.members.count() == 2
    response = client.get(reverse("gps:leave_group", kwargs={"group_id": another_group.id}))
    assert response.status_code == 302
    assert FollowUpGroupMembership.objects.filter(is_active=True).filter(follow_up_group=another_group).count() == 2


def test_referent_group(client):
    prescriber = PrescriberFactory(membership__organization__authorized=True)

    beneficiary = JobSeekerFactory()

    my_group = FollowUpGroupFactory(beneficiary=beneficiary, memberships=4, memberships__member=prescriber)

    membership = FollowUpGroupMembership.objects.filter(member=prescriber).filter(follow_up_group=my_group).first()

    assert membership.is_referent

    client.force_login(prescriber)
    response = client.get(reverse("gps:toggle_referent", kwargs={"group_id": my_group.id}))
    assert response.status_code == 302

    membership.refresh_from_db()

    assert not membership.is_referent


@freezegun.freeze_time("2024-06-21")
def test_beneficiary_details(client, snapshot):
    prescriber = PrescriberFactory(
        membership=True,
        for_snapshot=True,
        membership__organization__name="Les Olivades",
        membership__organization__authorized=True,
    )
    beneficiary = JobSeekerFactory(for_snapshot=True, department="24")
    FollowUpGroupFactory(beneficiary=beneficiary, memberships=1, memberships__member=prescriber)

    client.force_login(prescriber)

    user_details_url = reverse("users:details", kwargs={"public_id": beneficiary.public_id})
    response = client.get(user_details_url)
    html_details = parse_response_to_soup(response, selector="#beneficiary_details_container")
    assert str(html_details) == snapshot
    user_dropdown_menu = parse_response_to_soup(response, selector="div#dashboardUserDropdown")

    assert prescriber.email in str(user_dropdown_menu)
    assert beneficiary.email not in str(user_dropdown_menu)

    # Membership card: missing member information.
    prescriber.phone = ""
    prescriber.save()
    response = client.get(user_details_url)
    assert "Téléphone non renseigné" in str(response.content.decode())


def test_remove_members_from_group(client):
    prescriber = PrescriberFactory(membership__organization__authorized=True)
    beneficiary = JobSeekerFactory()
    my_group = FollowUpGroupFactory(beneficiary=beneficiary, memberships=4, memberships__member=prescriber)
    my_groups_url = reverse("gps:my_groups")
    user_details_url = reverse("users:details", kwargs={"public_id": beneficiary.public_id})

    client.force_login(prescriber)

    # Prescriber has only one group.
    response = client.get(my_groups_url)
    groups = response.context["memberships_page"]
    assert len(groups.object_list) == 1

    # The group of this beneficiary contains 4 members.
    response = client.get(user_details_url)
    members = response.context["gps_memberships"]
    assert members.count() == 4

    # Setting is_active False to the prescriber membership should remove it from the group.
    membership = FollowUpGroupMembership.objects.filter(member=prescriber).filter(follow_up_group=my_group).first()
    membership.is_active = False
    membership.save()

    # Prescriber doesn't belong to a group anymore.
    response = client.get(my_groups_url)
    groups = response.context["memberships_page"]
    assert len(groups.object_list) == 0

    response = client.get(user_details_url)
    members = response.context["gps_memberships"]
    assert members.count() == 3


def test_groups_pagination_and_name_filter(client):
    prescriber = PrescriberFactory(membership__organization__authorized=True)
    created_groups = FollowUpGroupFactory.create_batch(11, memberships=1, memberships__member=prescriber)

    client.force_login(prescriber)
    my_groups_url = reverse("gps:my_groups")
    response = client.get(my_groups_url)
    assert len(response.context["memberships_page"].object_list) == 10
    assert f"{my_groups_url}?page=2" in response.content.decode()

    # Filter by beneficiary name.
    beneficiary = created_groups[0].beneficiary
    response = client.get(my_groups_url, {"beneficiary": beneficiary.pk})
    memberships_page = response.context["memberships_page"]
    assert len(memberships_page.object_list) == 1
    assert memberships_page[0].follow_up_group.beneficiary == beneficiary
    # Assert 11 names are displayed in the dropdown.
    form = response.context["filters_form"]
    assert len(form.fields["beneficiary"].choices) == 11

    # Inactive memberships should not be displayed in the dropdown.
    membership = created_groups[0].memberships.first()
    membership.is_active = False
    membership.save()
    response = client.get(my_groups_url)
    form = response.context["filters_form"]
    assert len(form.fields["beneficiary"].choices) == 10

    # Filtering by another beneficiary should not be allowed.
    beneficiary = FollowUpGroupFactory().beneficiary
    response = client.get(my_groups_url, {"beneficiary": beneficiary.pk})
    memberships_page = response.context["memberships_page"]
    assert len(memberships_page.object_list) == 10

    # HTMX
    beneficiary = created_groups[-1].beneficiary
    response = client.get(my_groups_url, {"beneficiary": beneficiary.pk})
    page = parse_response_to_soup(response, selector="#main")
    [results] = page.select("#follow-up-groups-section")

    response = client.get(
        my_groups_url,
        {"beneficiary": beneficiary.pk},
        headers={"HX-Request": "true"},
    )
    update_page_with_htmx(page, f"form[hx-get='{my_groups_url}']", response)

    response = client.get(
        my_groups_url,
        {"beneficiary": beneficiary.pk},
    )
    fresh_results = parse_response_to_soup(response, selector="#follow-up-groups-section")
    assertSoupEqual(results, fresh_results)


def test_contact_information_display(client, snapshot):
    prescriber = PrescriberFactory(
        membership=True,
        for_snapshot=True,
        membership__organization__address_line_1="14 Rue Saint-Agricol",
        membership__organization__post_code="30000",
        membership__organization__city="Nîmes",
        membership__organization__name="Les Olivades",
        membership__organization__authorized=True,
    )

    beneficiary = JobSeekerFactory(for_snapshot=True)
    FollowUpGroupFactory(beneficiary=beneficiary, memberships=1, memberships__member=prescriber)
    user_details_url = reverse("users:details", kwargs={"public_id": beneficiary.public_id})
    client.force_login(prescriber)

    # no contact information to display
    response = client.get(user_details_url)
    assert response.status_code == 200
    assert response.context["render_advisor_matomo_option"] == "30"
    assert str(parse_response_to_soup(response, selector="#advisor-info-details-collapsable")) == snapshot(
        name="info_not_available"
    )

    # contact information to display
    FranceTravailContact.objects.create(
        name="Test MacTest", email="test.mactest@francetravail.fr", jobseeker_profile=beneficiary.jobseeker_profile
    )

    response = client.get(user_details_url)

    assert str(parse_response_to_soup(response, selector="#advisor-info-details-collapsable")) == snapshot(
        name="info_displayed"
    )


def test_contact_information_display_not_live(client, snapshot):
    # NOTE: this can be removed when the service goes live for everyone
    prescriber = PrescriberFactory(
        membership=True,
        for_snapshot=True,
        membership__organization__address_line_1="12 Rue de Rivoli",
        membership__organization__post_code="75004",
        membership__organization__city="Paris",
        membership__organization__name="Enterprise Test",
        membership__organization__authorized=True,
    )

    beneficiary = JobSeekerFactory(for_snapshot=True)
    FollowUpGroupFactory(beneficiary=beneficiary, memberships=1, memberships__member=prescriber)
    FranceTravailContact.objects.create(
        name="Test MacTest", email="test.mactest@francetravail.fr", jobseeker_profile=beneficiary.jobseeker_profile
    )

    client.force_login(prescriber)
    response = client.get(reverse("users:details", kwargs={"public_id": beneficiary.public_id}))
    assert response.status_code == 200
    assert not response.context["render_advisor_matomo_option"]
    assert str(parse_response_to_soup(response, selector="#advisor-info-details-collapsable")) == snapshot(
        name="preview_displayed"
    )
