from datetime import date
from functools import partial

import freezegun
import pytest
from django.contrib import messages
from django.urls import reverse
from django.utils import timezone
from pytest_django.asserts import assertContains, assertMessages, assertNotContains, assertRedirects

from itou.asp.models import Commune, Country, RSAAllocation
from itou.gps.models import FollowUpGroup, FollowUpGroupMembership
from itou.prescribers.models import PrescriberOrganization
from itou.users.enums import LackOfPoleEmploiId
from itou.users.models import User
from itou.utils.mocks.address_format import mock_get_geocoding_data_by_ban_api_resolved
from itou.www.job_seekers_views.enums import JobSeekerSessionKinds
from tests.cities.factories import create_city_geispolsheim
from tests.companies.factories import CompanyFactory, CompanyMembershipFactory
from tests.gps.factories import FollowUpGroupFactory, FollowUpGroupMembershipFactory
from tests.prescribers.factories import PrescriberMembershipFactory
from tests.users.factories import (
    EmployerFactory,
    JobSeekerFactory,
    LaborInspectorFactory,
    PrescriberFactory,
)
from tests.utils.htmx.test import assertSoupEqual, update_page_with_htmx
from tests.utils.test import KNOWN_SESSION_KEYS, assertSnapshotQueries, parse_response_to_soup


def assert_new_beneficiary_toast(response, job_seeker):
    assertMessages(
        response,
        [
            messages.Message(
                messages.SUCCESS,
                "Bénéficiaire ajouté||"
                f"{job_seeker.get_full_name()} fait maintenant partie de la liste de vos bénéficiaires.",
                extra_tags="toast",
            ),
        ],
    )


def assert_already_followed_beneficiary_toast(response, job_seeker):
    assertMessages(
        response,
        [
            messages.Message(
                messages.INFO,
                "Bénéficiaire déjà dans la liste||"
                f"{job_seeker.get_full_name()} fait déjà partie de la liste de vos bénéficiaires.",
                extra_tags="toast",
            ),
        ],
    )


def assert_ask_to_follow_beneficiary_toast(response, job_seeker):
    assertMessages(
        response,
        [
            messages.Message(
                messages.INFO,
                "Demande d’ajout envoyée||"
                f"Votre demande d’ajout pour {job_seeker.get_full_name()} a bien été transmise pour validation.",
                extra_tags="toast",
            ),
        ],
    )


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
        assertRedirects(response, reverse("gps:join_group_from_coworker"), fetch_redirect_response=False)

        response = client.post(url, data={"channel": "from_nir"})
        assertRedirects(response, reverse("gps:join_group_from_nir"), fetch_redirect_response=False)

        response = client.post(url, data={"channel": "from_name_email"})
        assertRedirects(response, reverse("gps:join_group_from_name_and_email"), fetch_redirect_response=False)

    def test_view_without_org(self, client):
        url = reverse("gps:join_group")
        user = PrescriberFactory()
        client.force_login(user)
        response = client.get(url)
        assertRedirects(response, reverse("gps:join_group_from_name_and_email"), fetch_redirect_response=False)


class TestBeneficiariesAutocomplete:
    @pytest.mark.parametrize(
        "factory,access",
        [
            [partial(JobSeekerFactory, for_snapshot=True), False],
            (partial(PrescriberFactory, membership__organization__authorized=True), True),
            (partial(PrescriberFactory, membership__organization__authorized=False), True),
            (PrescriberFactory, False),
            (partial(EmployerFactory, with_company=True), True),
            [partial(LaborInspectorFactory, membership=True), False],
        ],
        ids=[
            "job_seeker",
            "authorized_prescriber",
            "prescriber_with_org",
            "prescriber_no_org",
            "employer",
            "labor_inspector",
        ],
    )
    def test_permissions(self, client, factory, access):
        user = factory()
        client.force_login(user)
        url = reverse("gps:beneficiaries_autocomplete")
        response = client.get(url)
        if access:
            assert response.status_code == 200
        else:
            assert response.status_code == 403

    def test_autocomplete(self, client):
        prescriber = PrescriberFactory(first_name="gps member Vince")
        organization_1 = PrescriberMembershipFactory(user=prescriber).organization
        coworker_1 = PrescriberMembershipFactory(organization=organization_1).user
        organization_2 = PrescriberMembershipFactory(user=prescriber).organization
        coworker_2 = PrescriberMembershipFactory(organization=organization_2).user

        first_beneficiary = JobSeekerFactory(first_name="gps beneficiary Bob", last_name="Le Brico")
        second_beneficiary = JobSeekerFactory(first_name="gps second beneficiary Martin", last_name="Pêcheur")
        third_beneficiary = JobSeekerFactory(first_name="gps third beneficiary Foo", last_name="Bar")
        JobSeekerFactory(first_name="gps other beneficiary Joe", last_name="Dalton")

        FollowUpGroupFactory(beneficiary=first_beneficiary, memberships=4, memberships__member=prescriber)
        FollowUpGroupFactory(beneficiary=second_beneficiary, memberships=2, memberships__member=coworker_1)
        FollowUpGroupFactory(beneficiary=third_beneficiary, memberships=3, memberships__member=coworker_2)

        def get_autocomplete_results(user, term="gps"):
            client.force_login(user)
            response = client.get(reverse("gps:beneficiaries_autocomplete") + f"?term={term}")
            return [r["id"] for r in response.json()["results"]]

        # The prescriber should see the 3 job seekers followed by members of his organizations, but no the other one
        results = get_autocomplete_results(prescriber)
        assert set(results) == {first_beneficiary.pk, second_beneficiary.pk, third_beneficiary.pk}

        # a random other user won't see anyone
        results = get_autocomplete_results(EmployerFactory(with_company=True))
        assert results == []

        # with "martin gps" Martin is the only match
        results = get_autocomplete_results(prescriber, term="martin gps")
        assert results == [second_beneficiary.pk]

    def test_XSS(self):
        # The javascript code return a jquery object that will not be escaped, we need to escape the user name
        # to prevent xss
        with open("itou/static/js/gps.js") as f:
            script_content = f.read()
            assert "${select2Utils.escapeMarkup(data.name)}" in script_content
            assert "${select2Utils.escapeMarkup(data.title)}" in script_content


class TestJoinGroupFromCoworker:
    URL = reverse("gps:join_group_from_coworker")

    @pytest.mark.parametrize(
        "factory,access",
        [
            [partial(JobSeekerFactory, for_snapshot=True), False],
            (partial(PrescriberFactory, membership__organization__authorized=True), True),
            (partial(PrescriberFactory, membership__organization__authorized=False), True),
            (PrescriberFactory, False),
            (partial(EmployerFactory, with_company=True), True),
            [partial(LaborInspectorFactory, membership=True), False],
        ],
        ids=[
            "job_seeker",
            "authorized_prescriber",
            "prescriber_with_org",
            "prescriber_no_org",
            "employer",
            "labor_inspector",
        ],
    )
    def test_permissions(self, client, factory, access):
        user = factory()
        client.force_login(user)
        response = client.get(self.URL)
        if access:
            assert response.status_code == 200
        else:
            assert response.status_code == 403

    def test_view(self, client, snapshot):
        company = CompanyFactory(with_membership=True)
        user = company.members.get()
        coworker = CompanyMembershipFactory(company=company).user

        client.force_login(user)
        response = client.get(self.URL)
        assert str(parse_response_to_soup(response, selector="#main")) == snapshot

        followed_job_seeker = JobSeekerFactory()
        FollowUpGroupFactory(beneficiary=followed_job_seeker, memberships=1, memberships__member=user)
        response = client.post(self.URL, data={"user": followed_job_seeker.pk})
        assertRedirects(response, reverse("gps:group_list"))
        assert_already_followed_beneficiary_toast(response, followed_job_seeker)

        coworker_job_seeker = JobSeekerFactory()
        group = FollowUpGroupFactory(beneficiary=coworker_job_seeker, memberships=1, memberships__member=coworker)
        response = client.post(self.URL, data={"user": coworker_job_seeker.pk})
        assertRedirects(response, reverse("gps:group_list"))
        assert_new_beneficiary_toast(response, coworker_job_seeker)
        assert FollowUpGroupMembership.objects.filter(follow_up_group=group, member=user).exists()

        another_job_seeker = JobSeekerFactory()
        response = client.post(self.URL, data={"user": another_job_seeker.pk})
        assert response.status_code == 200
        assert response.context["form"].errors == {"user": ["Ce candidat ne peut être suivi."]}


class TestJoinGroupFromNir:
    URL = reverse("gps:join_group_from_nir")

    @pytest.mark.parametrize(
        "factory,access",
        [
            [partial(JobSeekerFactory, for_snapshot=True), False],
            (partial(PrescriberFactory, membership__organization__authorized=True), True),
            (partial(PrescriberFactory, membership__organization__authorized=False), False),
            (PrescriberFactory, False),
            (partial(EmployerFactory, with_company=True), True),
            [partial(LaborInspectorFactory, membership=True), False],
        ],
        ids=[
            "job_seeker",
            "authorized_prescriber",
            "prescriber_with_org",
            "prescriber_no_org",
            "employer",
            "labor_inspector",
        ],
    )
    def test_permissions(self, client, factory, access):
        user = factory()
        client.force_login(user)
        response = client.get(self.URL)
        if access:
            assert response.status_code == 200
        else:
            assert response.status_code == 403

    def test_view(self, client, snapshot):
        user = EmployerFactory(with_company=True)

        client.force_login(user)
        response = client.get(self.URL)
        assert str(parse_response_to_soup(response, selector="#main")) == snapshot(name="get")

        # unknown NIR :
        dummy_job_seeker = JobSeekerFactory.build(for_snapshot=True)
        response = client.post(self.URL, data={"nir": dummy_job_seeker.jobseeker_profile.nir, "preview": "1"})
        [job_seeker_session_name] = [k for k in client.session.keys() if k not in KNOWN_SESSION_KEYS]
        next_url = reverse(
            "job_seekers_views:search_by_email_for_sender",
            kwargs={"session_uuid": job_seeker_session_name},
        )
        expected_job_seeker_session = {
            "config": {
                "tunnel": "gps",
                "from_url": reverse("gps:join_group_from_nir"),
                "session_kind": JobSeekerSessionKinds.GET_OR_CREATE,
            },
            "profile": {
                "nir": dummy_job_seeker.jobseeker_profile.nir,
            },
        }
        assertRedirects(response, next_url)
        assert client.session[job_seeker_session_name] == expected_job_seeker_session

        # existing nit
        job_seeker = JobSeekerFactory(for_snapshot=True)
        response = client.post(self.URL, data={"nir": job_seeker.jobseeker_profile.nir, "preview": "1"})
        assert str(parse_response_to_soup(response, selector="#nir-confirmation-modal")) == snapshot(name="modal")

        # if we cancel: back to start with the nir we didn't find in the input
        response = client.post(self.URL, data={"nir": job_seeker.jobseeker_profile.nir, "cancel": "1"})
        html_detail = parse_response_to_soup(response, selector="#main")
        del html_detail.find(id="id_nir").attrs["value"]
        assert str(html_detail) == snapshot(name="get")

        # But if we accept:
        response = client.post(self.URL, data={"nir": job_seeker.jobseeker_profile.nir, "confirm": "1"})
        assertRedirects(response, reverse("gps:group_list"))
        assert_new_beneficiary_toast(response, job_seeker)

        # If we were already following the user
        response = client.post(self.URL, data={"nir": job_seeker.jobseeker_profile.nir, "confirm": "1"})
        assertRedirects(response, reverse("gps:group_list"))
        assert_already_followed_beneficiary_toast(response, job_seeker)

    def test_unknown_nir_known_email_with_no_nir(self, client, snapshot):
        user = EmployerFactory(with_company=True)
        existing_job_seeker_without_nir = JobSeekerFactory(for_snapshot=True, jobseeker_profile__nir="")
        nir = "276024719711371"

        client.force_login(user)

        # Step search for NIR in GPS view
        # ----------------------------------------------------------------------
        response = client.post(self.URL, data={"nir": nir, "preview": "1"})

        [job_seeker_session_name] = [k for k in client.session.keys() if k not in KNOWN_SESSION_KEYS]
        next_url = reverse(
            "job_seekers_views:search_by_email_for_sender",
            kwargs={"session_uuid": job_seeker_session_name},
        )
        expected_job_seeker_session = {
            "config": {
                "tunnel": "gps",
                "from_url": reverse("gps:join_group_from_nir"),
                "session_kind": JobSeekerSessionKinds.GET_OR_CREATE,
            },
            "profile": {
                "nir": nir,
            },
        }
        assertRedirects(response, next_url)
        assert client.session[job_seeker_session_name] == expected_job_seeker_session

        # Step get job seeker e-mail : the user is found
        # ----------------------------------------------------------------------
        response = client.get(next_url)
        assertContains(response, "<h1>Enregistrer un nouveau bénéficiaire</h1>", html=True)

        response = client.post(
            next_url,
            data={"email": existing_job_seeker_without_nir.email, "preview": 1},
        )
        assert str(parse_response_to_soup(response, "#email-confirmation-modal")) == snapshot

        # The job seeker isn't followed yet
        assert not FollowUpGroupMembership.objects.filter(
            follow_up_group__beneficiary=existing_job_seeker_without_nir, member=user
        ).exists()

        response = client.post(
            next_url,
            data={"email": existing_job_seeker_without_nir.email, "confirm": 1},
        )
        assertRedirects(response, reverse("gps:group_list"))
        assert_new_beneficiary_toast(response, existing_job_seeker_without_nir)

        existing_job_seeker_without_nir.refresh_from_db()
        assert existing_job_seeker_without_nir.jobseeker_profile.nir == nir

        assert FollowUpGroupMembership.objects.filter(
            follow_up_group__beneficiary=existing_job_seeker_without_nir, member=user
        ).exists()

    def test_unknown_nir_known_email_with_another_nir(self, client, snapshot):
        user = EmployerFactory(with_company=True)
        existing_job_seeker_with_nir = JobSeekerFactory(for_snapshot=True)
        job_seeker_nir = existing_job_seeker_with_nir.jobseeker_profile.nir
        nir = "276024719711371"

        client.force_login(user)

        # Step search for NIR in GPS view
        # ----------------------------------------------------------------------
        response = client.post(self.URL, data={"nir": nir, "preview": "1"})

        [job_seeker_session_name] = [k for k in client.session.keys() if k not in KNOWN_SESSION_KEYS]
        next_url = reverse(
            "job_seekers_views:search_by_email_for_sender",
            kwargs={"session_uuid": job_seeker_session_name},
        )
        expected_job_seeker_session = {
            "config": {
                "tunnel": "gps",
                "from_url": reverse("gps:join_group_from_nir"),
                "session_kind": JobSeekerSessionKinds.GET_OR_CREATE,
            },
            "profile": {
                "nir": nir,
            },
        }
        assertRedirects(response, next_url)
        assert client.session[job_seeker_session_name] == expected_job_seeker_session

        # Step get job seeker e-mail : the user is found
        # ----------------------------------------------------------------------
        response = client.post(
            next_url,
            data={"email": existing_job_seeker_with_nir.email, "preview": 1},
        )
        assert str(parse_response_to_soup(response, "#email-confirmation-modal")) == snapshot

        # The job seeker isn't followed yet
        assert not FollowUpGroupMembership.objects.filter(
            follow_up_group__beneficiary=existing_job_seeker_with_nir, member=user
        ).exists()

        response = client.post(
            next_url,
            data={"email": existing_job_seeker_with_nir.email, "confirm": 1},
        )
        assertRedirects(response, reverse("gps:group_list"))
        assert_new_beneficiary_toast(response, existing_job_seeker_with_nir)

        existing_job_seeker_with_nir.refresh_from_db()
        assert existing_job_seeker_with_nir.jobseeker_profile.nir == job_seeker_nir

        assert FollowUpGroupMembership.objects.filter(
            follow_up_group__beneficiary=existing_job_seeker_with_nir, member=user
        ).exists()

    def test_unknown_nir_and_unknown_email(self, client, settings, mocker):
        user = EmployerFactory(with_company=True)
        dummy_job_seeker = JobSeekerFactory.build(
            jobseeker_profile__with_hexa_address=True,
            jobseeker_profile__with_education_level=True,
            with_ban_geoloc_address=True,
        )

        client.force_login(user)

        # Step search for NIR in GPS view
        # ----------------------------------------------------------------------
        response = client.post(self.URL, data={"nir": dummy_job_seeker.jobseeker_profile.nir, "preview": "1"})

        [job_seeker_session_name] = [k for k in client.session.keys() if k not in KNOWN_SESSION_KEYS]
        next_url = reverse(
            "job_seekers_views:search_by_email_for_sender",
            kwargs={"session_uuid": job_seeker_session_name},
        )
        expected_job_seeker_session = {
            "config": {
                "tunnel": "gps",
                "from_url": reverse("gps:join_group_from_nir"),
                "session_kind": JobSeekerSessionKinds.GET_OR_CREATE,
            },
            "profile": {
                "nir": dummy_job_seeker.jobseeker_profile.nir,
            },
        }
        assertRedirects(response, next_url)
        assert client.session[job_seeker_session_name] == expected_job_seeker_session

        # Step get job seeker e-mail : no user is found
        # ----------------------------------------------------------------------
        response = client.post(next_url, data={"email": dummy_job_seeker.email, "preview": 1})

        expected_job_seeker_session |= {
            "user": {
                "email": dummy_job_seeker.email,
            },
        }
        assert client.session[job_seeker_session_name] == expected_job_seeker_session

        next_url = reverse(
            "job_seekers_views:create_job_seeker_step_1_for_sender",
            kwargs={"session_uuid": job_seeker_session_name},
        )
        assertRedirects(response, next_url)

        # Step create a job seeker.
        # ----------------------------------------------------------------------
        response = client.get(next_url)
        # The NIR is prefilled
        assertContains(response, dummy_job_seeker.jobseeker_profile.nir)

        geispolsheim = create_city_geispolsheim()
        birthdate = dummy_job_seeker.jobseeker_profile.birthdate

        post_data = {
            "title": dummy_job_seeker.title,
            "first_name": dummy_job_seeker.first_name,
            "last_name": dummy_job_seeker.last_name,
            "birthdate": birthdate,
            "lack_of_nir": False,
            "lack_of_nir_reason": "",
            "birth_place": Commune.objects.by_insee_code_and_period(geispolsheim.code_insee, birthdate).id,
            "birth_country": Country.france_id,
        }
        response = client.post(next_url, data=post_data)
        expected_job_seeker_session["profile"]["birthdate"] = post_data.pop("birthdate")
        expected_job_seeker_session["profile"]["lack_of_nir_reason"] = post_data.pop("lack_of_nir_reason")
        expected_job_seeker_session["profile"]["birth_place"] = post_data.pop("birth_place")
        expected_job_seeker_session["profile"]["birth_country"] = post_data.pop("birth_country")
        expected_job_seeker_session["user"] |= post_data
        assert client.session[job_seeker_session_name] == expected_job_seeker_session

        next_url = reverse(
            "job_seekers_views:create_job_seeker_step_2_for_sender",
            kwargs={"session_uuid": job_seeker_session_name},
        )
        assertRedirects(response, next_url)

        response = client.get(next_url)
        assert response.status_code == 200

        post_data = {
            "ban_api_resolved_address": dummy_job_seeker.geocoding_address,
            "address_line_1": dummy_job_seeker.address_line_1,
            "post_code": geispolsheim.post_codes[0],
            "insee_code": geispolsheim.code_insee,
            "city": geispolsheim.name,
            "phone": dummy_job_seeker.phone,
            "fill_mode": "ban_api",
        }

        settings.API_BAN_BASE_URL = "http://ban-api"
        mocker.patch(
            "itou.utils.apis.geocoding.get_geocoding_data",
            side_effect=mock_get_geocoding_data_by_ban_api_resolved,
        )

        response = client.post(next_url, data=post_data)

        expected_job_seeker_session["user"] |= post_data | {"address_line_2": "", "address_for_autocomplete": None}
        assert client.session[job_seeker_session_name] == expected_job_seeker_session

        next_url = reverse(
            "job_seekers_views:create_job_seeker_step_3_for_sender",
            kwargs={"session_uuid": job_seeker_session_name},
        )
        assertRedirects(response, next_url)

        response = client.get(next_url)
        assert response.status_code == 200

        post_data = {
            "education_level": dummy_job_seeker.jobseeker_profile.education_level,
        }
        response = client.post(next_url, data=post_data)
        expected_job_seeker_session["profile"] |= post_data | {
            "pole_emploi_id": "",
            "lack_of_pole_emploi_id_reason": LackOfPoleEmploiId.REASON_NOT_REGISTERED.value,
            "resourceless": False,
            "rqth_employee": False,
            "oeth_employee": False,
            "pole_emploi": False,
            "pole_emploi_id_forgotten": "",
            "pole_emploi_since": "",
            "unemployed": False,
            "unemployed_since": "",
            "rsa_allocation": False,
            "has_rsa_allocation": RSAAllocation.NO.value,
            "rsa_allocation_since": "",
            "ass_allocation": False,
            "ass_allocation_since": "",
            "aah_allocation": False,
            "aah_allocation_since": "",
        }
        assert client.session[job_seeker_session_name] == expected_job_seeker_session

        next_url = reverse(
            "job_seekers_views:create_job_seeker_step_end_for_sender",
            kwargs={"session_uuid": job_seeker_session_name},
        )
        assertRedirects(response, next_url)

        response = client.get(next_url)
        assertContains(response, "Créer et suivre le bénéficiaire")

        response = client.post(next_url)
        assert job_seeker_session_name not in client.session
        new_job_seeker = User.objects.get(email=dummy_job_seeker.email)
        assert_new_beneficiary_toast(response, new_job_seeker)
        assert FollowUpGroupMembership.objects.filter(
            follow_up_group__beneficiary=new_job_seeker, member=user
        ).exists()


class TestJoinGroupFromNameAndEmail:
    URL = reverse("gps:join_group_from_name_and_email")

    @pytest.mark.parametrize(
        "factory,access",
        [
            [partial(JobSeekerFactory, for_snapshot=True), False],
            (partial(PrescriberFactory, membership__organization__authorized=True), True),
            (partial(PrescriberFactory, membership__organization__authorized=False), True),
            (PrescriberFactory, True),
            (partial(EmployerFactory, with_company=True), True),
            [partial(LaborInspectorFactory, membership=True), False],
        ],
        ids=[
            "job_seeker",
            "authorized_prescriber",
            "prescriber_with_org",
            "prescriber_no_org",
            "employer",
            "labor_inspector",
        ],
    )
    def test_permissions(self, client, factory, access):
        user = factory()
        client.force_login(user)
        response = client.get(self.URL)
        if access:
            assert response.status_code == 200
        else:
            assert response.status_code == 403

    @pytest.mark.parametrize("known_name", [True, False])
    def test_unknown_email(self, client, settings, mocker, known_name):
        # This process is the same with or without gps advanced features
        user = PrescriberFactory()
        slack_mock = mocker.patch("itou.www.gps.utils.send_slack_message_for_gps")  # mock the imported link

        client.force_login(user)

        dummy_job_seeker = JobSeekerFactory.build(
            jobseeker_profile__with_hexa_address=True,
            jobseeker_profile__with_education_level=True,
            with_ban_geoloc_address=True,
        )

        response = client.get(self.URL)

        # Unknown email -> redirect to job seeker creation flow
        # ----------------------------------------------------------------------
        job_seeker = JobSeekerFactory()
        first_name = job_seeker.first_name if known_name else "John"
        last_name = job_seeker.last_name if known_name else "Snow"
        post_data = {
            "email": dummy_job_seeker.email,
            "first_name": first_name,
            "last_name": last_name,
            "preview": "1",
        }
        response = client.post(self.URL, data=post_data)
        [job_seeker_session_name] = [k for k in client.session.keys() if k not in KNOWN_SESSION_KEYS]
        next_url = reverse(
            "job_seekers_views:create_job_seeker_step_1_for_sender",
            kwargs={"session_uuid": job_seeker_session_name},
        )
        expected_job_seeker_session = {
            "config": {
                "tunnel": "gps",
                "from_url": reverse("gps:join_group_from_name_and_email"),
                "session_kind": JobSeekerSessionKinds.GET_OR_CREATE,
            },
            "user": {
                "email": dummy_job_seeker.email,
                "first_name": first_name,
                "last_name": last_name,
            },
        }
        assertRedirects(response, next_url)
        assert client.session[job_seeker_session_name] == expected_job_seeker_session

        # Step create a job seeker.
        # ----------------------------------------------------------------------
        response = client.get(next_url)
        # The name is prefilled
        assertContains(response, first_name)
        assertContains(response, last_name)

        geispolsheim = create_city_geispolsheim()
        birthdate = dummy_job_seeker.jobseeker_profile.birthdate

        # If we use an existing NIR
        existing_nir = JobSeekerFactory().jobseeker_profile.nir
        post_data = {
            "title": dummy_job_seeker.title,
            "first_name": first_name,
            "last_name": last_name,
            "birthdate": birthdate,
            "nir": existing_nir,
            "lack_of_nir": False,
            "lack_of_nir_reason": "",
            "birth_place": Commune.objects.by_insee_code_and_period(geispolsheim.code_insee, birthdate).id,
            "birth_country": Country.france_id,
        }
        response = client.post(next_url, data=post_data)
        assert response.status_code == 200
        assertContains(response, "Ce numéro de sécurité sociale est déjà associé à un autre utilisateur.")

        # With a other NIR
        post_data["nir"] = dummy_job_seeker.jobseeker_profile.nir
        response = client.post(next_url, data=post_data)
        expected_job_seeker_session["profile"] = {}
        for key in ["nir", "birthdate", "lack_of_nir_reason", "birth_place", "birth_country"]:
            expected_job_seeker_session["profile"][key] = post_data.pop(key)
        expected_job_seeker_session["user"] |= post_data
        assert client.session[job_seeker_session_name] == expected_job_seeker_session

        next_url = reverse(
            "job_seekers_views:create_job_seeker_step_2_for_sender",
            kwargs={"session_uuid": job_seeker_session_name},
        )
        assertRedirects(response, next_url)

        response = client.get(next_url)
        assert response.status_code == 200

        post_data = {
            "ban_api_resolved_address": dummy_job_seeker.geocoding_address,
            "address_line_1": dummy_job_seeker.address_line_1,
            "post_code": geispolsheim.post_codes[0],
            "insee_code": geispolsheim.code_insee,
            "city": geispolsheim.name,
            "phone": dummy_job_seeker.phone,
            "fill_mode": "ban_api",
        }

        settings.API_BAN_BASE_URL = "http://ban-api"
        mocker.patch(
            "itou.utils.apis.geocoding.get_geocoding_data",
            side_effect=mock_get_geocoding_data_by_ban_api_resolved,
        )

        response = client.post(next_url, data=post_data)

        expected_job_seeker_session["user"] |= post_data | {"address_line_2": "", "address_for_autocomplete": None}
        assert client.session[job_seeker_session_name] == expected_job_seeker_session

        next_url = reverse(
            "job_seekers_views:create_job_seeker_step_3_for_sender",
            kwargs={"session_uuid": job_seeker_session_name},
        )
        assertRedirects(response, next_url)

        response = client.get(next_url)
        assert response.status_code == 200

        post_data = {"education_level": dummy_job_seeker.jobseeker_profile.education_level}
        response = client.post(next_url, data=post_data)
        next_url = reverse(
            "job_seekers_views:create_job_seeker_step_end_for_sender",
            kwargs={"session_uuid": job_seeker_session_name},
        )
        assertRedirects(response, next_url)

        expected_job_seeker_session["profile"] |= post_data | {
            "pole_emploi_id": "",
            "lack_of_pole_emploi_id_reason": LackOfPoleEmploiId.REASON_NOT_REGISTERED.value,
            "resourceless": False,
            "rqth_employee": False,
            "oeth_employee": False,
            "pole_emploi": False,
            "pole_emploi_id_forgotten": "",
            "pole_emploi_since": "",
            "unemployed": False,
            "unemployed_since": "",
            "rsa_allocation": False,
            "has_rsa_allocation": RSAAllocation.NO.value,
            "rsa_allocation_since": "",
            "ass_allocation": False,
            "ass_allocation_since": "",
            "aah_allocation": False,
            "aah_allocation_since": "",
        }
        assert client.session[job_seeker_session_name] == expected_job_seeker_session

        response = client.get(next_url)
        assertContains(response, "Créer et suivre le bénéficiaire")

        response = client.post(next_url)
        assert job_seeker_session_name not in client.session
        new_job_seeker = User.objects.get(email=dummy_job_seeker.email)
        assert_new_beneficiary_toast(response, new_job_seeker)
        assert FollowUpGroupMembership.objects.filter(
            follow_up_group__beneficiary=new_job_seeker, member=user
        ).exists()

        expected_mock_calls = []
        if known_name:
            new_job_seeker_admin_url = reverse("admin:users_user_change", args=(new_job_seeker.pk,))
            expected_mock_calls = [
                (
                    (
                        ":black_square_for_stop: Création d’un nouveau bénéficiaire : "
                        f'<a href="{new_job_seeker_admin_url}">{new_job_seeker.get_full_name()}</a>.',
                    ),
                )
            ]
        assert slack_mock.mock_calls == expected_mock_calls

    def test_full_match_with_advanced_features(self, client, snapshot):
        user = PrescriberFactory(membership__organization__authorized=True)
        client.force_login(user)

        job_seeker = JobSeekerFactory(for_snapshot=True)
        post_data = {
            "email": job_seeker.email,
            "first_name": job_seeker.first_name,
            "last_name": job_seeker.last_name,
            "preview": "1",
        }
        response = client.post(self.URL, data=post_data)
        assert str(parse_response_to_soup(response, selector="#main")) == snapshot

        post_data = {
            "email": job_seeker.email,
            "first_name": job_seeker.first_name,
            "last_name": job_seeker.last_name,
            "confirm": "1",
        }
        response = client.post(self.URL, data=post_data)
        assertRedirects(response, reverse("gps:group_list"))
        assert_new_beneficiary_toast(response, job_seeker)
        assert FollowUpGroupMembership.objects.filter(follow_up_group__beneficiary=job_seeker, member=user).exists()

    def test_full_match_without_advanced_features(self, client, snapshot, mocker):
        user = PrescriberFactory(membership__organization__authorized=False)
        slack_mock = mocker.patch("itou.www.gps.views.send_slack_message_for_gps")  # mock the imported link
        client.force_login(user)

        job_seeker = JobSeekerFactory(for_snapshot=True)
        post_data = {
            "email": job_seeker.email,
            "first_name": job_seeker.first_name,
            "last_name": job_seeker.last_name,
            "preview": "1",
        }
        response = client.post(self.URL, data=post_data)
        assert str(parse_response_to_soup(response, selector="#main")) == snapshot

        # Cannot confirm
        post_data = {
            "email": job_seeker.email,
            "first_name": job_seeker.first_name,
            "last_name": job_seeker.last_name,
            "confirm": "1",
        }
        response = client.post(self.URL, data=post_data)
        assert response.status_code == 200
        assert not FollowUpGroupMembership.objects.filter(
            follow_up_group__beneficiary=job_seeker, member=user
        ).exists()

        # When asking
        post_data = {
            "email": job_seeker.email,
            "first_name": job_seeker.first_name,
            "last_name": job_seeker.last_name,
            "ask": "1",
        }
        response = client.post(self.URL, data=post_data)
        assertRedirects(response, reverse("gps:group_list"))

        assert_ask_to_follow_beneficiary_toast(response, job_seeker)
        assert not FollowUpGroupMembership.objects.filter(
            follow_up_group__beneficiary=job_seeker, member=user
        ).exists()

        job_seeker_admin_url = reverse("admin:users_user_change", args=(job_seeker.pk,))
        user_admin_url = reverse("admin:users_user_change", args=(user.pk,))
        assert slack_mock.mock_calls == [
            (
                (
                    f':gemini: Demande d’ajout <a href="{user_admin_url}">{user.get_full_name()}</a> '
                    f'veut suivre <a href="{job_seeker_admin_url}">{job_seeker.get_full_name()}</a>.',
                ),
            )
        ]

    def test_partial_match_with_advanced_features(self, client, snapshot):
        user = PrescriberFactory(membership__organization__authorized=True)
        client.force_login(user)

        response = client.get(self.URL)

        job_seeker = JobSeekerFactory(for_snapshot=True)
        post_data = {
            "email": job_seeker.email,
            "first_name": "John",
            "last_name": "Snow",
            "preview": "1",
        }
        response = client.post(self.URL, data=post_data)
        assert str(parse_response_to_soup(response, selector="#main")) == snapshot

        post_data = {
            "email": job_seeker.email,
            "first_name": "John",
            "last_name": "Snow",
            "confirm": "1",
        }
        response = client.post(self.URL, data=post_data)
        assertRedirects(response, reverse("gps:group_list"))
        assert_new_beneficiary_toast(response, job_seeker)
        assert FollowUpGroupMembership.objects.filter(follow_up_group__beneficiary=job_seeker, member=user).exists()

    def test_partial_match_without_advanced_features(self, client, snapshot):
        user = PrescriberFactory(membership__organization__authorized=False)
        client.force_login(user)

        response = client.get(self.URL)

        job_seeker = JobSeekerFactory(for_snapshot=True)
        post_data = {
            "email": job_seeker.email,
            "first_name": "John",
            "last_name": "Snow",
            "preview": "1",
        }
        response = client.post(self.URL, data=post_data)
        assert str(parse_response_to_soup(response, selector="#main")) == snapshot

        # Cannot confirm
        post_data = {
            "email": job_seeker.email,
            "first_name": "John",
            "last_name": "Snow",
            "confirm": "1",
        }
        response = client.post(self.URL, data=post_data)
        assert response.status_code == 200
        assert not FollowUpGroupMembership.objects.filter(
            follow_up_group__beneficiary=job_seeker, member=user
        ).exists()
