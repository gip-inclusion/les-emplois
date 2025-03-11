from datetime import date
from functools import partial

import freezegun
import pytest
from django.urls import reverse
from django.utils import timezone
from pytest_django.asserts import assertContains, assertNotContains, assertRedirects

from itou.gps.models import FollowUpGroup
from itou.prescribers.models import PrescriberOrganization
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
        "factory,status_code",
        [
            [partial(JobSeekerFactory, for_snapshot=True), 403],
            [partial(EmployerFactory, with_company=True), 200],
            [PrescriberFactory, 200],  # we don't need authorized organizations as of today
            [partial(LaborInspectorFactory, membership=True), 403],
        ],
        ids=[
            "job_seeker",
            "employer",
            "prescriber",
            "labor_inspector",
        ],
    )
    def test_permissions(self, client, factory, status_code):
        client.force_login(factory())
        for route in ["gps:group_list", "gps:old_group_list"]:
            response = client.get(reverse(route))
            assert response.status_code == status_code

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

    def test_mask_names(self, client):
        prescriber = PrescriberFactory(membership__organization__authorized=False)
        job_seeker = JobSeekerFactory(for_snapshot=True)
        FollowUpGroupFactory(memberships=1, memberships__member=prescriber, beneficiary=job_seeker)

        client.force_login(prescriber)
        my_groups_url = reverse("gps:group_list")
        response = client.get(my_groups_url)
        assertNotContains(response, "Jane DOE")
        assertContains(response, "J… D…")


def test_backward_compat_urls(client):
    prescriber = PrescriberFactory()
    client.force_login(prescriber)

    response = client.get("/gps", follow=True)  # there is a first redirection to /gps/
    assertRedirects(response, reverse("gps:group_list"), status_code=301)

    response = client.get("/gps/")
    assertRedirects(response, reverse("gps:group_list"), status_code=301)

    response = client.get("/gps/groups")
    assertRedirects(response, reverse("gps:group_list"), status_code=301)


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
            reason="iae",  # With a reason
        ).follow_up_group
        participant = FollowUpGroupMembershipFactory(
            member__first_name="François",
            member__last_name="Le Français",
            follow_up_group=group,
            created_at=timezone.now(),
            reason="",  # No reason
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


class TestGroupDetailsBeneficiaryTab:
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
        url = reverse("gps:group_beneficiary", kwargs={"group_id": group.pk})
        response = client.get(url)
        if access:
            assert response.status_code == 404
            FollowUpGroupMembershipFactory(follow_up_group=group, member=user)
            response = client.get(url)
            assert response.status_code == 200
        else:
            assert response.status_code == 403

    def test_tab(self, client, snapshot):
        prescriber = PrescriberFactory(membership=True, for_snapshot=True)
        beneficiary = JobSeekerFactory(for_snapshot=True)
        group = FollowUpGroupFactory(beneficiary=beneficiary, memberships=1, memberships__member=prescriber)

        client.force_login(prescriber)

        # When the prescriber can't view personal info
        url = reverse("gps:group_beneficiary", kwargs={"group_id": group.pk})
        response = client.get(url)
        html_details = parse_response_to_soup(
            response,
            selector="#main",
            replace_in_attr=[
                ("href", f"/gps/groups/{group.pk}", "/gps/groups/[PK of FollowUpGroup]"),
                ("href", f"%2Fgps%2Fgroups%2F{group.pk}", "%2Fgps%2Fgroups%2F[PK of FollowUpGroup]"),
            ],
        )
        assert str(html_details) == snapshot(name="masked_info")

        # When he can but is not from an authorized organization
        beneficiary.created_by = prescriber
        beneficiary.save()
        response = client.get(url)
        html_details = parse_response_to_soup(
            response,
            selector="#main",
            replace_in_attr=[
                ("href", f"/gps/groups/{group.pk}", "/gps/groups/[PK of FollowUpGroup]"),
                ("href", f"%2Fgps%2Fgroups%2F{group.pk}", "%2Fgps%2Fgroups%2F[PK of FollowUpGroup]"),
            ],
        )
        assert str(html_details) == snapshot(name="no_diagnostic")

        # When he is
        PrescriberOrganization.objects.update(is_authorized=True)
        response = client.get(url)
        html_details = parse_response_to_soup(
            response,
            selector="#main",
            replace_in_attr=[
                ("href", f"/gps/groups/{group.pk}", "/gps/groups/[PK of FollowUpGroup]"),
                ("href", f"%2Fgps%2Fgroups%2F{group.pk}", "%2Fgps%2Fgroups%2F[PK of FollowUpGroup]"),
            ],
        )
        assert str(html_details) == snapshot(name="with_diagnostic")

        # When the user can edit the beneficiary details
        beneficiary.created_by = prescriber
        beneficiary.save()
        response = client.get(url)
        html_details = parse_response_to_soup(
            response,
            selector="#main",
            replace_in_attr=[
                ("href", f"/gps/groups/{group.pk}", "/gps/groups/[PK of FollowUpGroup]"),
                ("href", beneficiary.public_id, "[PublicID of Beneficiary]"),
                ("href", f"%2Fgps%2Fgroups%2F{group.pk}", "%2Fgps%2Fgroups%2F[PK of FollowUpGroup]"),
            ],
        )
        assert str(html_details) == snapshot(name="with_beneficiary_edition")


class TestGroupDetailsContributionTab:
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
        url = reverse("gps:group_contribution", kwargs={"group_id": group.pk})
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
        prescriber = PrescriberFactory(membership=True)
        beneficiary = JobSeekerFactory(for_snapshot=True)
        group = FollowUpGroupFactory(beneficiary=beneficiary, memberships=1, memberships__member=prescriber)

        client.force_login(prescriber)

        url = reverse("gps:group_contribution", kwargs={"group_id": group.pk})
        response = client.get(url)
        html_details = parse_response_to_soup(
            response,
            selector="#main",
            replace_in_attr=[
                ("href", f"/gps/groups/{group.pk}", "/gps/groups/[PK of FollowUpGroup]"),
            ],
        )
        assert str(html_details) == snapshot(name="ongoing_membership_no_reason")

        membership = group.memberships.get()
        membership.ended_at = timezone.localdate()
        membership.reason = "parce que"
        membership.save()
        response = client.get(url)
        html_details = parse_response_to_soup(
            response,
            selector="#main",
            replace_in_attr=[
                ("href", f"/gps/groups/{group.pk}", "/gps/groups/[PK of FollowUpGroup]"),
            ],
        )
        assert str(html_details) == snapshot(name="ended_membership_with_reason")


class TestGroupDetailsEditionTab:
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
        url = reverse("gps:group_edition", kwargs={"group_id": group.pk})
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
        prescriber = PrescriberFactory(membership=True)
        beneficiary = JobSeekerFactory(for_snapshot=True)
        group = FollowUpGroupFactory(beneficiary=beneficiary)
        membership = FollowUpGroupMembershipFactory(member=prescriber, is_referent=True, follow_up_group=group)

        client.force_login(prescriber)
        url = reverse("gps:group_edition", kwargs={"group_id": group.pk})
        response = client.get(url)
        html_details = parse_response_to_soup(
            response,
            selector="#main",
            replace_in_attr=[
                ("href", f"/gps/groups/{group.pk}", "/gps/groups/[PK of FollowUpGroup]"),
            ],
        )
        assert str(html_details) == snapshot()

        # The user just clics on "Accompagnement terminé" without setting the ended_at field
        post_data = {
            "started_at": "2024-01-03",
            "is_ongoing": "False",
            "ended_at": "",
            "is_referent": "on",
            "reason": "",
        }
        response = client.post(url, data=post_data)
        assertRedirects(response, reverse("gps:group_contribution", kwargs={"group_id": group.pk}))

        membership.refresh_from_db()
        assert membership.started_at == date(2024, 1, 3)
        assert membership.ended_at == date(2024, 6, 21)  # today
        assert membership.is_referent is False

        # The user just clics on "Accompagnement en cours"
        post_data = {
            "started_at": "2024-01-03",
            "is_ongoing": "True",
            "ended_at": "2024-06-21",  # The field is set but will be ignored because of is_ongoing
            "reason": "",
        }
        response = client.post(url, data=post_data)
        assertRedirects(response, reverse("gps:group_contribution", kwargs={"group_id": group.pk}))

        membership.refresh_from_db()
        assert membership.started_at == date(2024, 1, 3)
        assert membership.ended_at is None
        assert membership.is_referent is False

        # The user ends again the membership and sets a date
        post_data = {
            "started_at": "2024-01-03",
            "is_ongoing": "False",
            "ended_at": "2024-06-20",
            "reason": "",
        }
        response = client.post(url, data=post_data)
        assertRedirects(response, reverse("gps:group_contribution", kwargs={"group_id": group.pk}))

        membership.refresh_from_db()
        assert membership.started_at == date(2024, 1, 3)
        assert membership.ended_at == date(2024, 6, 20)
        assert membership.is_referent is False

        # The user follows again the beneficiary as referent
        post_data = {
            "started_at": "2024-01-03",
            "is_ongoing": "True",
            "ended_at": "2024-06-20",  # The field is set but will be ignored because of is_ongoing
            "is_referent": "on",
            "reason": "",
        }
        response = client.post(url, data=post_data)
        assertRedirects(response, reverse("gps:group_contribution", kwargs={"group_id": group.pk}))

        membership.refresh_from_db()
        assert membership.started_at == date(2024, 1, 3)
        assert membership.ended_at is None
        assert membership.is_referent is True

        # The user sets a reason
        post_data = {
            "started_at": "2024-01-03",
            "is_ongoing": "True",
            "ended_at": "2024-06-20",  # The field is set but will be ignored because of is_ongoing
            "is_referent": "on",
            "reason": "iae",
        }
        response = client.post(url, data=post_data)
        assertRedirects(response, reverse("gps:group_contribution", kwargs={"group_id": group.pk}))

        membership.refresh_from_db()
        assert membership.reason == "iae"

    @freezegun.freeze_time("2024-06-21")
    def test_form_validation(self, client):
        prescriber = PrescriberFactory(membership=True)
        beneficiary = JobSeekerFactory(for_snapshot=True)
        group = FollowUpGroupFactory(beneficiary=beneficiary)
        FollowUpGroupMembershipFactory(member=prescriber, is_referent=True, follow_up_group=group)

        client.force_login(prescriber)
        url = reverse("gps:group_edition", kwargs={"group_id": group.pk})

        # started_at and ended_at must be in the past
        post_data = {
            "started_at": "2025-01-03",
            "is_ongoing": "False",
            "ended_at": "2025-01-01",
        }
        response = client.post(url, data=post_data)
        assert response.status_code == 200
        assert response.context["form"].errors == {
            "started_at": ["Ce champ ne peut pas être dans le futur."],
            "ended_at": ["Ce champ ne peut pas être dans le futur."],
        }

        # ended_at must be after started_at
        post_data = {
            "started_at": "2024-01-03",
            "is_ongoing": "False",
            "ended_at": "2024-01-01",
        }
        response = client.post(url, data=post_data)
        assert response.status_code == 200
        assert response.context["form"].errors == {
            "ended_at": ["Cette date ne peut pas être avant la date de début."],
        }


class TestJoinGroup:
    @pytest.mark.parametrize(
        "user_factory",
        [
            partial(PrescriberFactory, membership__organization__authorized=True),
            partial(EmployerFactory, with_company=True),
            partial(PrescriberFactory, membership__organization__authorized=False),
        ],
        ids=[
            "authorized_prescriber",
            "employer",
            "prescriber_with_org",
        ],
    )
    def test_view_with_org(self, client, snapshot, user_factory):
        url = reverse("gps:join_group")
        user = user_factory()
        client.force_login(user)
        response = client.get(url)
        assert str(parse_response_to_soup(response, selector="#main")) == snapshot

        # All redirection work : the join_group_from_* view will check if the user is allowed
        response = client.post(url, data={"channel": "from_coworker"})
        assertRedirects(response, url)  # FIXME

        response = client.post(url, data={"channel": "from_nir"})
        assertRedirects(response, url)  # FIXME

        response = client.post(url, data={"channel": "from_name_email"})
        assertRedirects(response, url)  # FIXME

    def test_view_without_org(self, client):
        url = reverse("gps:join_group")
        user = PrescriberFactory()
        client.force_login(user)
        response = client.get(url)
        assertRedirects(response, url, fetch_redirect_response=False)  # FIXME
