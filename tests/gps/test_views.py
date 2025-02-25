from datetime import date
from functools import partial

import freezegun
import pytest
from django.urls import reverse
from django.utils import timezone
from pytest_django.asserts import assertContains, assertNotContains

from itou.gps.models import FollowUpGroup, FollowUpGroupMembership, FranceTravailContact
from tests.gps.factories import FollowUpGroupFactory, FollowUpGroupMembershipFactory
from tests.users.factories import (
    EmployerFactory,
    JobSeekerFactory,
    LaborInspectorFactory,
    PrescriberFactory,
)
from tests.utils.htmx.test import assertSoupEqual, update_page_with_htmx
from tests.utils.test import assertSnapshotQueries, parse_response_to_soup


class TestGroupLists:
    @pytest.mark.parametrize(
        "factory,access",
        [
            [partial(JobSeekerFactory, for_snapshot=True), False],
            [partial(EmployerFactory, with_company=True), True],
            [PrescriberFactory, True],  # we don't need authorized organizations as of today
            [partial(LaborInspectorFactory, membership=True), False],
        ],
        ids=[
            "job_seeker",
            "employer",
            "prescriber",
            "labor_inspector",
        ],
    )
    def test_permissions(self, client, factory, access):
        client.force_login(factory())
        for route in ["gps:group_list", "gps:old_group_list"]:
            response = client.get(reverse(route))
            if access:
                assert response.status_code == 200
            else:
                assert response.status_code == 403

    @freezegun.freeze_time("2024-06-21", tick=True)
    def test_group_list(self, snapshot, client):
        user = PrescriberFactory(
            membership__organization__authorized=True, membership__organization__for_snapshot=True
        )
        client.force_login(user)

        # Nominal case
        # Groups created latelly should come first.
        group_1 = FollowUpGroupFactory(for_snapshot=True)
        FollowUpGroupMembershipFactory(
            follow_up_group=group_1,
            is_referent=True,
            member__first_name="John",
            member__last_name="Doe",
        )
        FollowUpGroup.objects.follow_beneficiary(group_1.beneficiary, user)

        # We are referent
        group_2 = FollowUpGroupMembershipFactory(
            follow_up_group__beneficiary__first_name="François",
            follow_up_group__beneficiary__last_name="Le Français",
            is_referent=True,
            member=user,
        ).follow_up_group

        # No referent
        group_3 = FollowUpGroupMembershipFactory(
            follow_up_group__beneficiary__first_name="Jean",
            follow_up_group__beneficiary__last_name="Bon",
            is_referent=False,
            member=user,
        ).follow_up_group

        # old membership
        FollowUpGroupMembershipFactory(ended_at=timezone.localdate(), member=user)

        # inactive membership
        FollowUpGroupMembershipFactory(is_active=False, member=user)

        with assertSnapshotQueries(snapshot):
            response = client.get(reverse("gps:group_list"))
        groups = parse_response_to_soup(
            response,
            selector="#follow-up-groups-section",
            replace_in_attr=[
                ("href", f"/gps/groups/{group.pk}", "/gps/groups/[PK of FollowUpGroup]")
                for group in [group_1, group_2, group_3]
            ],
        )
        assert str(groups) == snapshot(name="test_my_groups__group_card")

        assertContains(response, f'<a class="nav-link active" href="{reverse("gps:group_list")}">')

        # Test `is_referent` display.
        group_1 = FollowUpGroupFactory(memberships=1, beneficiary__first_name="Janis", beneficiary__last_name="Joplin")
        FollowUpGroup.objects.follow_beneficiary(group_1.beneficiary, user, is_referent=True)
        response = client.get(reverse("gps:group_list"))
        assertContains(response, "vous êtes référent")

    @freezegun.freeze_time("2024-06-21", tick=True)
    def test_old_group_list(self, snapshot, client):
        user = PrescriberFactory(
            membership__organization__authorized=True, membership__organization__for_snapshot=True
        )
        client.force_login(user)

        # old membership
        membership = FollowUpGroupMembershipFactory(
            follow_up_group__beneficiary__first_name="Jean",
            follow_up_group__beneficiary__last_name="Bon",
            is_referent=False,
            ended_at=timezone.localdate(),
            member=user,
        )

        # ongoing membership
        FollowUpGroupMembershipFactory(member=user)

        # inactive membership
        FollowUpGroupMembershipFactory(is_active=False, member=user)

        with assertSnapshotQueries(snapshot):
            response = client.get(reverse("gps:old_group_list"))
        groups = parse_response_to_soup(
            response,
            selector="#follow-up-groups-section",
            replace_in_attr=[
                ("href", f"/gps/groups/{membership.follow_up_group.pk}", "/gps/groups/[PK of FollowUpGroup]")
            ],
        )
        assert str(groups) == snapshot(name="test_my_groups__group_card")

        assertContains(response, f'<a class="nav-link active" href="{reverse("gps:old_group_list")}">')

    def test_groups_pagination_and_name_filter(self, client):
        prescriber = PrescriberFactory(membership__organization__authorized=True)
        created_groups = FollowUpGroupFactory.create_batch(51, memberships=1, memberships__member=prescriber)

        client.force_login(prescriber)
        my_groups_url = reverse("gps:group_list")
        response = client.get(my_groups_url)
        assert len(response.context["memberships_page"].object_list) == 50
        assert f"{my_groups_url}?page=2" in response.content.decode()

        # Filter by beneficiary name.
        beneficiary = created_groups[0].beneficiary
        response = client.get(my_groups_url, {"beneficiary": beneficiary.pk})
        memberships_page = response.context["memberships_page"]
        assert len(memberships_page.object_list) == 1
        assert memberships_page[0].follow_up_group.beneficiary == beneficiary
        # Assert 11 names are displayed in the dropdown.
        form = response.context["filters_form"]
        assert len(form.fields["beneficiary"].choices) == 51

        # Inactive memberships should not be displayed in the dropdown.
        membership = created_groups[0].memberships.first()
        membership.is_active = False
        membership.save()
        response = client.get(my_groups_url)
        form = response.context["filters_form"]
        assert len(form.fields["beneficiary"].choices) == 50

        # Filtering by another beneficiary should not be allowed.
        beneficiary = FollowUpGroupFactory().beneficiary
        response = client.get(my_groups_url, {"beneficiary": beneficiary.pk})
        memberships_page = response.context["memberships_page"]
        assert len(memberships_page.object_list) == 50

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


class TestGroupDetailsMembershipTab:
    @pytest.mark.parametrize(
        "factory,access",
        [
            [partial(JobSeekerFactory, for_snapshot=True), False],
            [partial(EmployerFactory, with_company=True), True],
            [PrescriberFactory, True],  # we don't need authorized organizations as of today
            [partial(LaborInspectorFactory, membership=True), False],
        ],
        ids=[
            "job_seeker",
            "employer",
            "prescriber",
            "labor_inspector",
        ],
    )
    def test_permission(self, client, factory, access):
        user = factory()
        client.force_login(user)
        group = FollowUpGroupFactory()
        url = reverse("gps:group_memberships", kwargs={"group_id": group.pk})
        response = client.get(url)
        if access:
            assert response.status_code == 404
            FollowUpGroupMembershipFactory(follow_up_group=group, member=user)
            response = client.get(url)
            assert response.status_code == 200
        else:
            assert response.status_code == 403

    @freezegun.freeze_time("2024-06-21")
    def test_tab(self, client, snapshot):
        prescriber = PrescriberFactory(
            membership=True,
            for_snapshot=True,
            membership__organization__name="Les Olivades",
            membership__organization__authorized=True,
        )
        beneficiary = JobSeekerFactory(for_snapshot=True)
        group = FollowUpGroupMembershipFactory(
            follow_up_group__beneficiary=beneficiary,
            member=prescriber,
            started_at=date(2024, 1, 1),
            ended_at=date(2024, 6, 20),
        ).follow_up_group
        participant = FollowUpGroupMembershipFactory(
            member__first_name="François",
            member__last_name="Le Français",
            follow_up_group=group,
            created_at=timezone.now(),
        ).member

        client.force_login(prescriber)

        url = reverse("gps:group_memberships", kwargs={"group_id": group.pk})
        response = client.get(url)
        html_details = parse_response_to_soup(
            response,
            selector="#main",
            replace_in_attr=[
                ("href", f"/gps/groups/{group.pk}", "/gps/groups/[PK of FollowUpGroup]"),
                ("href", f"%2Fgps%2Fgroups%2F{group.pk}", "%2Fgps%2Fgroups%2F[PK of FollowUpGroup]"),
                ("href", f"user_id={prescriber.pk}", "user_id=[PK of user]"),
                (
                    "href",
                    f"user_organization_id={prescriber.prescribermembership_set.get().organization_id}",
                    "user_organization_id=[PK of organization]",
                ),
                ("href", f"beneficiary_id={beneficiary.pk}", "beneficiary_id=[PK of beneficiary]"),
                ("id", f"card-{prescriber.public_id}", "card-[Public ID of prescriber]"),
                ("id", f"card-{participant.public_id}", "card-[Public ID of participant]"),
                (
                    "hx-post",
                    f"/gps/display/{group.pk}/{participant.public_id}/phone",
                    "/gps/display/[PK of group]/[Public ID of participant]/phone",
                ),
                (
                    "hx-post",
                    f"/gps/display/{group.pk}/{participant.public_id}/email",
                    "/gps/display/[PK of group]/[Public ID of participant]/email",
                ),
                ("id", f"phone-{participant.pk}", "phone-[PK of participant]"),
                ("id", f"email-{participant.pk}", "email-[PK of participant]"),
            ],
        )
        assert str(html_details) == snapshot

        display_phone_txt = "<span>Afficher le téléphone</span>"
        display_email_txt = "<span>Afficher l'email</span>"

        assertContains(response, display_email_txt, count=1)
        assertContains(response, display_phone_txt, count=1)

        # Membership card: missing member information.
        participant.phone = ""
        participant.save()
        response = client.get(url)
        assertContains(response, display_email_txt, count=1)
        assertNotContains(response, display_phone_txt)

        assertContains(response, "Ajouter un intervenant")
        assertContains(response, "https://formulaires.gps.inclusion.gouv.fr/ajouter-intervenant")

    def test_group_memberships_order(self, client):
        prescriber = PrescriberFactory(membership=True)
        beneficiary = JobSeekerFactory(for_snapshot=True)
        group = FollowUpGroupFactory(beneficiary=beneficiary, memberships=1, memberships__member=prescriber)
        participant = FollowUpGroupMembershipFactory(follow_up_group=group, created_at=timezone.now()).member

        client.force_login(prescriber)
        url = reverse("gps:group_memberships", kwargs={"group_id": group.pk})
        response = client.get(url)

        html_details = parse_response_to_soup(response, selector="#gps_intervenants")
        cards = html_details.find_all("div", attrs={"class": "c-box c-box--results has-links-inside mb-3 my-md-4"})
        participant_ids = [card.attrs["id"].split("card-")[1] for card in cards]
        assert participant_ids == [str(participant.public_id), str(prescriber.public_id)]

    @freezegun.freeze_time("2025-01-20")
    def test_display_participant_contact_info(self, client, mocker, snapshot):
        prescriber = PrescriberFactory(
            membership=True,
            for_snapshot=True,
            membership__organization__name="Les Olivades",
            membership__organization__authorized=True,
        )
        beneficiary = JobSeekerFactory(for_snapshot=True)
        group = FollowUpGroupFactory(beneficiary=beneficiary, memberships=1, memberships__member=prescriber)
        target_participant = FollowUpGroupMembershipFactory(
            follow_up_group=group,
            member__first_name="Jean",
            member__last_name="Dupont",
            member__email="jean@dupont.fr",
            member__phone="0123456789",
        ).member

        client.force_login(prescriber)
        grist_log_mock = mocker.patch(
            "itou.www.gps.views.log_contact_info_display"
        )  # Mock the import in the views file

        url = reverse("gps:group_memberships", kwargs={"group_id": group.pk})
        response = client.get(url)
        display_phone_url = reverse("gps:display_contact_info", args=(group.pk, target_participant.public_id, "phone"))
        assertContains(response, display_phone_url)
        display_email_url = reverse("gps:display_contact_info", args=(group.pk, target_participant.public_id, "email"))
        assertContains(response, display_email_url)

        simulated_page = parse_response_to_soup(
            response,
            selector=f"#card-{target_participant.public_id}",
            replace_in_attr=[("id", f"card-{target_participant.public_id}", "card'[Public ID of target_participant]")],
        )

        response = client.post(display_phone_url)
        assertContains(response, target_participant.phone)
        update_page_with_htmx(simulated_page, f"#phone-{target_participant.pk}", response)
        response = client.post(display_email_url)
        assertContains(response, target_participant.email)
        update_page_with_htmx(simulated_page, f"#email-{target_participant.pk}", response)

        assert str(simulated_page) == snapshot

        assert grist_log_mock.call_args_list == [
            ((prescriber, group, target_participant, "phone"),),
            ((prescriber, group, target_participant, "email"),),
        ]


# tests that will soon be removed or re-written
# -------------------------------------------------------------------------------------------


def test_job_seeker_cannot_use_gps(client):
    job_seeker = JobSeekerFactory()
    client.force_login(job_seeker)
    group = FollowUpGroupFactory(beneficiary=job_seeker)

    for route, kwargs in [
        ("gps:leave_group", {"group_id": group.pk}),
        ("gps:toggle_referent", {"group_id": group.pk}),
    ]:
        response = client.get(reverse(route, kwargs=kwargs))
        assert response.status_code == 403
    response = client.get(reverse("gps:user_details", kwargs={"public_id": job_seeker.public_id}))
    assert response.status_code == 403


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

    # And the 4 are ongoing
    assert FollowUpGroupMembership.objects.filter(ended_at=None).filter(follow_up_group=my_group).count() == 4

    client.force_login(member)
    response = client.get(reverse("gps:leave_group", kwargs={"group_id": my_group.id}))
    assert response.status_code == 302

    # We still have 4 group members
    assert my_group.members.count() == 4
    # But only 3 are ongoing
    assert FollowUpGroupMembership.objects.filter(ended_at=None).filter(follow_up_group=my_group).count() == 3

    # We can't leave a group we're not part of
    assert another_group.members.count() == 2
    response = client.get(reverse("gps:leave_group", kwargs={"group_id": another_group.id}))
    assert response.status_code == 302
    assert FollowUpGroupMembership.objects.filter(ended_at=None).filter(follow_up_group=another_group).count() == 2


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
        membership__organization__department="24",
    )
    beneficiary = JobSeekerFactory(for_snapshot=True)
    group = FollowUpGroupFactory(beneficiary=beneficiary, memberships=1, memberships__member=prescriber)
    participant = FollowUpGroupMembershipFactory(
        member__first_name="François",
        member__last_name="Le Français",
        follow_up_group=group,
        created_at=timezone.now(),
    ).member

    client.force_login(prescriber)

    user_details_url = reverse("gps:user_details", kwargs={"public_id": beneficiary.public_id})
    response = client.get(user_details_url)
    html_details = parse_response_to_soup(
        response,
        selector="#main",
        replace_in_attr=[
            ("href", f"user_id={prescriber.pk}", "user_id=[PK of user]"),
            ("data-bs-confirm-url", f"/gps/groups/{group.pk}/", "/gps/groups/[PK of group]/"),
            (
                "href",
                f"user_organization_id={prescriber.prescribermembership_set.get().organization_id}",
                "user_organization_id=[PK of organization]",
            ),
            ("href", f"beneficiary_id={beneficiary.pk}", "beneficiary_id=[PK of beneficiary]"),
            ("id", f"card-{prescriber.public_id}", "card-[PK of prescriber]"),
            ("id", f"card-{participant.public_id}", "card-[PK of participant]"),
            (
                "hx-post",
                f"/gps/display/{group.pk}/{participant.public_id}/phone",
                "/gps/display/[PK of group]/[Public ID of participant]/phone",
            ),
            (
                "hx-post",
                f"/gps/display/{group.pk}/{participant.public_id}/email",
                "/gps/display/[PK of group]/[Public ID of participant]/email",
            ),
            ("id", f"phone-{participant.pk}", "phone-[PK of participant]"),
            ("id", f"email-{participant.pk}", "email-[PK of participant]"),
        ],
    )
    assert str(html_details) == snapshot
    user_dropdown_menu = parse_response_to_soup(response, selector="div#dashboardUserDropdown")

    assert prescriber.email in str(user_dropdown_menu)
    assert beneficiary.email not in str(user_dropdown_menu)

    display_phone_txt = "<span>Afficher le téléphone</span>"
    display_email_txt = "<span>Afficher l'email</span>"

    assertContains(response, display_email_txt)
    assertContains(response, display_phone_txt)

    # Membership card: missing member information.
    participant.phone = ""
    participant.save()
    response = client.get(user_details_url)
    assertContains(response, display_email_txt)
    assertNotContains(response, display_phone_txt)

    assertContains(response, "Ajouter un intervenant")
    assertContains(response, "https://formulaires.gps.inclusion.gouv.fr/ajouter-intervenant")


def test_beneficiary_details_members_order(client):
    prescriber = PrescriberFactory(membership=True, membership__organization__authorized=True)
    beneficiary = JobSeekerFactory(for_snapshot=True)
    group = FollowUpGroupFactory(beneficiary=beneficiary, memberships=1, memberships__member=prescriber)
    participant = FollowUpGroupMembershipFactory(follow_up_group=group, created_at=timezone.now()).member

    client.force_login(prescriber)
    user_details_url = reverse("gps:user_details", kwargs={"public_id": beneficiary.public_id})
    response = client.get(user_details_url)

    html_details = parse_response_to_soup(response, selector="#gps_intervenants")
    cards = html_details.find_all("div", attrs={"class": "c-box c-box--results has-links-inside mb-3 my-md-4"})
    participant_ids = [card.attrs["id"].split("card-")[1] for card in cards]
    assert participant_ids == [str(participant.public_id), str(prescriber.public_id)]


@freezegun.freeze_time("2025-01-20")
def test_display_participant_contact_info(client, mocker, snapshot):
    prescriber = PrescriberFactory(
        membership=True,
        for_snapshot=True,
        membership__organization__name="Les Olivades",
        membership__organization__authorized=True,
        membership__organization__department="24",
    )
    beneficiary = JobSeekerFactory(for_snapshot=True)
    group = FollowUpGroupFactory(beneficiary=beneficiary, memberships=1, memberships__member=prescriber)
    target_participant = FollowUpGroupMembershipFactory(
        follow_up_group=group,
        member__first_name="Jean",
        member__last_name="Dupont",
        member__email="jean@dupont.fr",
        member__phone="0123456789",
    ).member

    client.force_login(prescriber)
    grist_log_mock = mocker.patch("itou.www.gps.views.log_contact_info_display")  # Mock the import in the views file

    user_details_url = reverse("gps:user_details", kwargs={"public_id": beneficiary.public_id})
    response = client.get(user_details_url)
    display_phone_url = reverse("gps:display_contact_info", args=(group.pk, target_participant.public_id, "phone"))
    assertContains(response, display_phone_url)
    display_email_url = reverse("gps:display_contact_info", args=(group.pk, target_participant.public_id, "email"))
    assertContains(response, display_email_url)

    simulated_page = parse_response_to_soup(
        response,
        selector=f"#card-{target_participant.public_id}",
        replace_in_attr=[("id", f"card-{target_participant.public_id}", "card'[Public ID of target_participant]")],
    )

    response = client.post(display_phone_url)
    assertContains(response, target_participant.phone)
    update_page_with_htmx(simulated_page, f"#phone-{target_participant.pk}", response)
    response = client.post(display_email_url)
    assertContains(response, target_participant.email)
    update_page_with_htmx(simulated_page, f"#email-{target_participant.pk}", response)

    assert str(simulated_page) == snapshot

    assert grist_log_mock.call_args_list == [
        ((prescriber, group, target_participant, "phone"),),
        ((prescriber, group, target_participant, "email"),),
    ]


def test_display_participant_contact_info_not_allowed(client):
    prescriber = PrescriberFactory(
        membership=True,
        membership__organization__authorized=True,
    )
    group = FollowUpGroupFactory(memberships=1)
    target_participant = FollowUpGroupMembershipFactory(
        follow_up_group=group,
        member__first_name="Jean",
        member__last_name="Dupont",
        member__email="jean@dupont.fr",
        member__phone="0123456789",
    ).member

    client.force_login(prescriber)

    display_phone_url = reverse("gps:display_contact_info", args=(group.pk, target_participant.public_id, "phone"))
    display_email_url = reverse("gps:display_contact_info", args=(group.pk, target_participant.public_id, "email"))

    response = client.post(display_phone_url)
    assert response.status_code == 404
    response = client.post(display_email_url)
    assert response.status_code == 404


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
    user_details_url = reverse("gps:user_details", kwargs={"public_id": beneficiary.public_id})
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
    response = client.get(reverse("gps:user_details", kwargs={"public_id": beneficiary.public_id}))
    assert response.status_code == 200
    assert not response.context["render_advisor_matomo_option"]
    assert str(parse_response_to_soup(response, selector="#advisor-info-details-collapsable")) == snapshot(
        name="preview_displayed"
    )


@pytest.mark.parametrize(
    "UserFactory, factory_args",
    [
        (PrescriberFactory, {"membership": False}),
        (PrescriberFactory, {"membership": True}),
        (PrescriberFactory, {"membership__organization__authorized": True}),
        (EmployerFactory, {"with_company": True}),
    ],
)
def test_contact_information_access(client, UserFactory, factory_args):
    user = UserFactory(**factory_args)
    client.force_login(user)

    beneficiary = JobSeekerFactory()

    response = client.get(reverse("gps:user_details", kwargs={"public_id": beneficiary.public_id}))
    assert response.status_code == 403

    FollowUpGroupFactory(beneficiary=beneficiary, memberships=1, memberships__member=user)
    response = client.get(reverse("gps:user_details", kwargs={"public_id": beneficiary.public_id}))
    assert response.status_code == 200
