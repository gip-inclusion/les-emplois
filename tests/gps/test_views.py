import itertools
from datetime import date, timedelta
from functools import partial

import freezegun
import pytest
from django.contrib import messages
from django.test import override_settings
from django.urls import reverse
from django.utils import timezone
from json_log_formatter import BUILTIN_ATTRS
from pytest_django.asserts import assertContains, assertMessages, assertNotContains, assertRedirects

from itou.asp.models import Commune, Country, RSAAllocation
from itou.companies.models import Company
from itou.gps.models import FollowUpGroup, FollowUpGroupMembership
from itou.prescribers.enums import PrescriberAuthorizationStatus
from itou.prescribers.models import PrescriberOrganization
from itou.users.enums import LackOfPoleEmploiId, Title
from itou.users.models import User
from itou.utils.mocks.address_format import mock_get_geocoding_data_by_ban_api_resolved
from itou.utils.templatetags.str_filters import mask_unless
from itou.utils.urls import get_absolute_url
from itou.www.gps.enums import EndReason
from itou.www.job_seekers_views.enums import JobSeekerSessionKinds
from tests.cities.factories import create_city_geispolsheim
from tests.companies.factories import CompanyFactory, CompanyMembershipFactory
from tests.gps.factories import FollowUpGroupFactory, FollowUpGroupMembershipFactory
from tests.prescribers.factories import PrescriberMembershipFactory, PrescriberOrganizationFactory
from tests.users.factories import (
    EmployerFactory,
    JobSeekerFactory,
    LaborInspectorFactory,
    PrescriberFactory,
)
from tests.utils.htmx.testing import assertSoupEqual, update_page_with_htmx
from tests.utils.testing import (
    PAGINATION_PAGE_ONE_MARKUP,
    assertSnapshotQueries,
    get_session_name,
    parse_response_to_soup,
    pretty_indented,
)


def gps_logs(caplog):
    ignored_keys = BUILTIN_ATTRS - {"message"}
    records = []
    for record in caplog.records:
        if record.name == "itou.gps":
            records.append({k: v for k, v in record.__dict__.items() if k not in ignored_keys})
    caplog.clear()
    return records


def assert_new_beneficiary_toast(response, job_seeker, can_view_personal_info=True):
    name = mask_unless(job_seeker.get_full_name(), predicate=can_view_personal_info)
    assertMessages(
        response,
        [
            messages.Message(
                messages.SUCCESS,
                f"Bénéficiaire ajouté||{name} fait maintenant partie de la liste de vos bénéficiaires.",
                extra_tags="toast",
            ),
        ],
    )


def assert_already_followed_beneficiary_toast(response, job_seeker, can_view_personal_info=True):
    name = mask_unless(job_seeker.get_full_name(), predicate=can_view_personal_info)
    assertMessages(
        response,
        [
            messages.Message(
                messages.INFO,
                f"Bénéficiaire déjà dans la liste||{name} fait déjà partie de la liste de vos bénéficiaires.",
                extra_tags="toast",
            ),
        ],
    )


def assert_ask_to_follow_beneficiary_toast(response, job_seeker):
    name = mask_unless(job_seeker.get_full_name(), False)
    assertMessages(
        response,
        [
            messages.Message(
                messages.INFO,
                f"Demande d’ajout envoyée||Votre demande d’ajout pour {name} a bien été transmise pour validation.",
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
    def test_group_list(self, snapshot, client, caplog):
        user = PrescriberFactory(
            membership__organization__authorized=True, membership__organization__for_snapshot=True
        )
        client.force_login(user)

        # Nominal case
        # Groups created latelly should come first.
        group_1 = FollowUpGroupFactory(for_snapshot=True)
        FollowUpGroupMembershipFactory(
            follow_up_group=group_1,
            member__first_name="John",
            member__last_name="Doe",
        )
        FollowUpGroup.objects.follow_beneficiary(group_1.beneficiary, user)

        # We are referent
        group_2 = FollowUpGroupMembershipFactory(
            follow_up_group__beneficiary__first_name="François",
            follow_up_group__beneficiary__last_name="Le Français",
            is_referent_certified=True,
            member=user,
        ).follow_up_group

        # old membership
        FollowUpGroupMembershipFactory(ended_at=timezone.localdate(), end_reason=EndReason.MANUAL, member=user)

        # inactive membership
        FollowUpGroupMembershipFactory(is_active=False, member=user)

        with assertSnapshotQueries(snapshot):
            response = client.get(reverse("gps:group_list"))
        groups = parse_response_to_soup(
            response,
            selector="#main",
            replace_in_attr=itertools.chain(
                *(
                    [
                        ("href", f"/gps/groups/{group.pk}", "/gps/groups/[PK of FollowUpGroup]"),
                        (
                            "value",
                            str(group.beneficiary_id),
                            "[PK of JobSeeker]",
                        ),
                    ]
                    for group in [group_1, group_2]
                ),
            ),
        )
        assert pretty_indented(groups) == snapshot(name="test_my_groups__group_card")

        assertContains(response, f'<a class="nav-link active" href="{reverse("gps:group_list")}">')

        assert gps_logs(caplog) == [{"message": "GPS visit_list_groups"}]

    @override_settings(PAGE_SIZE_LARGE=1)
    def test_pagination(self, client):
        user = PrescriberFactory(membership__organization__authorized=True)
        groups = FollowUpGroupFactory.create_batch(2)
        for group in groups:
            FollowUpGroupMembershipFactory(
                follow_up_group=group,
            )
            FollowUpGroup.objects.follow_beneficiary(group.beneficiary, user)
        client.force_login(user)
        url = reverse("gps:group_list")
        response = client.get(url)
        assertContains(response, PAGINATION_PAGE_ONE_MARKUP % (url + "?page=1"), html=True)

    @freezegun.freeze_time("2024-06-21", tick=True)
    def test_old_group_list(self, snapshot, client, caplog):
        user = PrescriberFactory(
            membership__organization__authorized=True, membership__organization__for_snapshot=True
        )
        client.force_login(user)

        # old membership
        membership = FollowUpGroupMembershipFactory(
            follow_up_group__beneficiary__first_name="Jean",
            follow_up_group__beneficiary__last_name="Bon",
            ended_at=timezone.localdate(),
            end_reason=EndReason.MANUAL,
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
        assert pretty_indented(groups) == snapshot(name="test_my_groups__group_card")

        assertContains(response, f'<a class="nav-link active" href="{reverse("gps:old_group_list")}">')
        assert gps_logs(caplog) == [{"message": "GPS visit_list_groups_old"}]

    def test_groups_pagination_and_name_filter(self, client):
        prescriber = PrescriberFactory(membership__organization__authorized=True)
        created_groups = FollowUpGroupFactory.create_batch(51, memberships=1, memberships__member=prescriber)

        client.force_login(prescriber)
        my_groups_url = reverse("gps:group_list")
        response = client.get(my_groups_url)
        assert len(response.context["memberships_page"].object_list) == 50
        assert f"{my_groups_url}?page=2" in response.text

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
        group = FollowUpGroupFactory(memberships=1, memberships__member=prescriber, beneficiary=job_seeker)
        masked_name = "J… D…"
        full_name = "Jane DOE"

        client.force_login(prescriber)
        my_groups_url = reverse("gps:group_list")
        response = client.get(my_groups_url)
        assertNotContains(response, full_name)
        assertContains(response, masked_name)

        # If the membership allows to view personal information
        group.memberships.update(can_view_personal_information=True)
        my_groups_url = reverse("gps:group_list")
        response = client.get(my_groups_url)
        assertContains(response, full_name)
        assertNotContains(response, masked_name)

        # If the organization is authorized
        group.memberships.update(can_view_personal_information=False)
        PrescriberOrganization.objects.all().update(
            authorization_status=PrescriberAuthorizationStatus.VALIDATED,
        )
        my_groups_url = reverse("gps:group_list")
        response = client.get(my_groups_url)
        assertContains(response, full_name)
        assertNotContains(response, masked_name)

        # If the organization is "gps authorized"
        PrescriberOrganization.objects.all().update(
            authorization_status=PrescriberAuthorizationStatus.REFUSED,
            is_gps_authorized=True,
        )
        my_groups_url = reverse("gps:group_list")
        response = client.get(my_groups_url)
        assertContains(response, full_name)
        assertNotContains(response, masked_name)


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
    def test_tab(self, client, snapshot, caplog):
        prescriber = PrescriberFactory(
            membership=True,
            for_snapshot=True,
            membership__organization__name="Les Olivades",
            membership__organization__authorized=True,
        )
        beneficiary = JobSeekerFactory(for_snapshot=True)
        membership = FollowUpGroupMembershipFactory(
            follow_up_group__beneficiary=beneficiary,
            member=prescriber,
            started_at=date(2024, 1, 1),
            ended_at=date(2024, 6, 20),
            end_reason=EndReason.MANUAL,
            reason="iae",  # With a reason
        )
        group = membership.follow_up_group
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
                ("href", f"followupgroup_id={group.pk}", "followupgroup_id=[PK of FollowUpGroup]"),
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
        assert pretty_indented(html_details) == snapshot
        assert gps_logs(caplog) == [{"message": "GPS visit_group_memberships", "group": group.pk}]

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
        certified_referent = FollowUpGroupMembershipFactory(
            follow_up_group=group, created_at=timezone.now(), is_referent_certified=True
        ).member

        client.force_login(prescriber)
        url = reverse("gps:group_memberships", kwargs={"group_id": group.pk})
        response = client.get(url)

        html_details = parse_response_to_soup(response, selector="#gps_intervenants")
        cards = html_details.find_all("div", attrs={"class": "c-box c-box--results has-links-inside mb-3 my-md-4"})
        participant_ids = [card.attrs["id"].split("card-")[1] for card in cards]
        assert participant_ids == [
            str(certified_referent.public_id),
            str(participant.public_id),
            str(prescriber.public_id),
        ]

    @freezegun.freeze_time("2025-01-20")
    def test_display_participant_contact_info_as_prescriber(self, client, snapshot, mocker, caplog):
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
        assert gps_logs(caplog) == [{"message": "GPS visit_group_memberships", "group": group.pk}]

        simulated_page = parse_response_to_soup(
            response,
            selector=f"#card-{target_participant.public_id}",
            replace_in_attr=[("id", f"card-{target_participant.public_id}", "card'[Public ID of target_participant]")],
        )

        response = client.post(display_phone_url)
        assertContains(response, target_participant.phone)
        update_page_with_htmx(simulated_page, f"#phone-{target_participant.pk}", response)
        assert gps_logs(caplog) == [
            {
                "message": "GPS display_contact_information",
                "group": group.pk,
                "target_participant": target_participant.pk,
                "target_participant_type": "orienteur",
                "beneficiary": beneficiary.pk,
                "current_user": prescriber.pk,
                "current_user_type": "prescripteur habilité",
                "mode": "phone",
                "are_colleagues": False,
            },
        ]

        # Add target_participant to the current user org
        organization = PrescriberOrganization.objects.get()
        PrescriberMembershipFactory(user=target_participant, organization=organization)

        response = client.post(display_email_url)
        assertContains(response, target_participant.email)
        update_page_with_htmx(simulated_page, f"#email-{target_participant.pk}", response)
        assert gps_logs(caplog) == [
            {
                "message": "GPS display_contact_information",
                "group": group.pk,
                "target_participant": target_participant.pk,
                "target_participant_type": "prescripteur habilité",
                "beneficiary": beneficiary.pk,
                "current_user": prescriber.pk,
                "current_user_type": "prescripteur habilité",
                "mode": "email",
                "are_colleagues": True,
            },
        ]

        assert pretty_indented(simulated_page) == snapshot

        assert grist_log_mock.call_args_list == [
            ((prescriber, group, target_participant, "phone"),),
            ((prescriber, group, target_participant, "email"),),
        ]

    @freezegun.freeze_time("2025-01-20")
    def test_display_participant_contact_info_as_employer(self, client, snapshot, caplog):
        employer = EmployerFactory(
            with_company=True,
            for_snapshot=True,
            with_company__company__name="Les Olivades",
        )
        beneficiary = JobSeekerFactory(for_snapshot=True)
        group = FollowUpGroupFactory(beneficiary=beneficiary, memberships=1, memberships__member=employer)
        target_participant = FollowUpGroupMembershipFactory(
            member=EmployerFactory(
                first_name="Jean",
                last_name="Dupont",
                email="jean@dupont.fr",
                phone="0123456789",
            ),
            follow_up_group=group,
        ).member

        client.force_login(employer)

        url = reverse("gps:group_memberships", kwargs={"group_id": group.pk})
        response = client.get(url)
        display_phone_url = reverse("gps:display_contact_info", args=(group.pk, target_participant.public_id, "phone"))
        assertContains(response, display_phone_url)
        display_email_url = reverse("gps:display_contact_info", args=(group.pk, target_participant.public_id, "email"))
        assertContains(response, display_email_url)
        assert gps_logs(caplog) == [{"message": "GPS visit_group_memberships", "group": group.pk}]

        simulated_page = parse_response_to_soup(
            response,
            selector=f"#card-{target_participant.public_id}",
            replace_in_attr=[("id", f"card-{target_participant.public_id}", "card'[Public ID of target_participant]")],
        )

        response = client.post(display_phone_url)
        assertContains(response, target_participant.phone)
        update_page_with_htmx(simulated_page, f"#phone-{target_participant.pk}", response)
        assert gps_logs(caplog) == [
            {
                "message": "GPS display_contact_information",
                "group": group.pk,
                "target_participant": target_participant.pk,
                "target_participant_type": "employeur",
                "beneficiary": beneficiary.pk,
                "current_user": employer.pk,
                "current_user_type": "employeur",
                "mode": "phone",
                "are_colleagues": False,
            },
        ]

        # Add target_participant to the current user company
        company = Company.objects.get()
        CompanyMembershipFactory(user=target_participant, company=company)

        response = client.post(display_email_url)
        assertContains(response, target_participant.email)
        update_page_with_htmx(simulated_page, f"#email-{target_participant.pk}", response)
        assert gps_logs(caplog) == [
            {
                "message": "GPS display_contact_information",
                "group": group.pk,
                "target_participant": target_participant.pk,
                "target_participant_type": "employeur",
                "beneficiary": beneficiary.pk,
                "current_user": employer.pk,
                "current_user_type": "employeur",
                "mode": "email",
                "are_colleagues": True,
            },
        ]

        assert pretty_indented(simulated_page) == snapshot

    def test_ask_access(self, client, mocker, snapshot, caplog):
        user = PrescriberFactory()
        job_seeker = JobSeekerFactory(for_snapshot=True)
        group = FollowUpGroupFactory(beneficiary=job_seeker, memberships=1, memberships__member=user)
        membership = group.memberships.get()
        slack_mock = mocker.patch("itou.www.gps.views.send_slack_message_for_gps")  # mock the imported link

        ask_access_str = "Demander l’accès complet à la fiche"

        client.force_login(user)
        url = reverse("gps:group_memberships", kwargs={"group_id": group.pk})
        response = client.get(url)
        assertContains(response, ask_access_str)

        ask_access_url = reverse("gps:ask_access", args=(group.pk,))
        ask_access_url_for_snapshot = ask_access_url.replace(str(group.pk), "[PK of FollowUpGroup]")
        page_soup = parse_response_to_soup(response, selector="#ask_access_modal")
        assert pretty_indented(page_soup).replace(ask_access_url, ask_access_url_for_snapshot) == snapshot(
            name="enabled_button"
        )

        htmx_response = client.post(ask_access_url)
        update_page_with_htmx(page_soup, f'button[hx-post="{ask_access_url}"]', htmx_response)
        assert pretty_indented(page_soup).replace(ask_access_url, ask_access_url_for_snapshot) == snapshot(
            name="disabled_button"
        )

        job_seeker_admin_url = get_absolute_url(reverse("admin:users_user_change", args=(job_seeker.pk,)))
        user_admin_url = get_absolute_url(reverse("admin:users_user_change", args=(user.pk,)))
        membership_url = get_absolute_url(reverse("admin:gps_followupgroupmembership_change", args=(membership.pk,)))

        expected_calls = [
            (
                (
                    f":mag: *Demande d’accès à la fiche*\n"
                    f"<{user_admin_url}|{user.get_full_name()}> veut avoir accès aux informations de "
                    f"<{job_seeker_admin_url}|{mask_unless(group.beneficiary.get_full_name(), False)}> "
                    f"(<{membership_url}|relation>).",
                ),
            )
        ]
        assert slack_mock.mock_calls == expected_calls
        assert gps_logs(caplog) == [
            {"message": "GPS visit_group_memberships", "group": group.pk},
            {"message": "GPS group_requested_full_access", "group": group.pk},
        ]

        slack_mock.reset_mock()
        membership.can_view_personal_information = True
        membership.save()
        client.post(ask_access_url)
        assert slack_mock.mock_calls == []


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

    def test_tab(self, client, snapshot, caplog):
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
        assert pretty_indented(html_details) == snapshot(name="masked_info")
        assert gps_logs(caplog) == [{"message": "GPS visit_group_beneficiary", "group": group.pk}]

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
        assert pretty_indented(html_details) == snapshot(name="no_diagnostic_can_edit")

        # Same if the membership allow it
        beneficiary.created_by = None
        beneficiary.save()
        group.memberships.update(can_view_personal_information=True)
        response = client.get(url)
        html_details = parse_response_to_soup(
            response,
            selector="#main",
            replace_in_attr=[
                ("href", f"/gps/groups/{group.pk}", "/gps/groups/[PK of FollowUpGroup]"),
                ("href", f"%2Fgps%2Fgroups%2F{group.pk}", "%2Fgps%2Fgroups%2F[PK of FollowUpGroup]"),
            ],
        )
        assert pretty_indented(html_details) == snapshot(name="no_diagnostic")

        # When he is in an authorized organization
        PrescriberOrganization.objects.update(
            authorization_status=PrescriberAuthorizationStatus.VALIDATED,
        )
        response = client.get(url)
        html_details = parse_response_to_soup(
            response,
            selector="#main",
            replace_in_attr=[
                ("href", f"/gps/groups/{group.pk}", "/gps/groups/[PK of FollowUpGroup]"),
                ("href", f"%2Fgps%2Fgroups%2F{group.pk}", "%2Fgps%2Fgroups%2F[PK of FollowUpGroup]"),
            ],
        )
        assert pretty_indented(html_details) == snapshot(name="with_diagnostic")

        # When the organization is gps autorized instead
        PrescriberOrganization.objects.update(
            authorization_status=PrescriberAuthorizationStatus.REFUSED,
            is_gps_authorized=True,
        )
        response = client.get(url)
        html_details = parse_response_to_soup(
            response,
            selector="#main",
            replace_in_attr=[
                ("href", f"/gps/groups/{group.pk}", "/gps/groups/[PK of FollowUpGroup]"),
                ("href", f"%2Fgps%2Fgroups%2F{group.pk}", "%2Fgps%2Fgroups%2F[PK of FollowUpGroup]"),
            ],
        )
        assert pretty_indented(html_details) == snapshot(name="with_diagnostic")

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
        assert pretty_indented(html_details) == snapshot(name="with_diagnostic_can_edit")


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
    def test_tab(self, client, snapshot, caplog):
        prescriber = PrescriberFactory(membership=True)
        beneficiary = JobSeekerFactory(for_snapshot=True)
        group = FollowUpGroupFactory(beneficiary=beneficiary, memberships=1, memberships__member=prescriber)
        membership = group.memberships.get()

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
        assert pretty_indented(html_details) == snapshot(name="ongoing_membership_no_reason")
        assert gps_logs(caplog) == [{"message": "GPS visit_group_contribution", "group": group.pk}]

        membership = group.memberships.get()
        membership.ended_at = timezone.localdate()
        membership.end_reason = EndReason.MANUAL
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
        assert pretty_indented(html_details) == snapshot(name="ended_membership_with_reason")


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
    def test_tab(self, client, snapshot, caplog):
        prescriber = PrescriberFactory(membership=True)
        beneficiary = JobSeekerFactory(for_snapshot=True)
        group = FollowUpGroupFactory(beneficiary=beneficiary)
        membership = FollowUpGroupMembershipFactory(
            member=prescriber,
            follow_up_group=group,
            started_at="2024-01-03",
        )

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
        assert pretty_indented(html_details) == snapshot()
        assert gps_logs(caplog) == [{"message": "GPS visit_group_edition", "group": group.pk}]

        # The user just clics on "Accompagnement terminé" without setting the ended_at field
        post_data = {
            "started_at": "2024-01-03",
            "is_ongoing": "False",
            "ended_at": "",
            "reason": "",
        }
        response = client.post(url, data=post_data)
        assertRedirects(response, reverse("gps:group_contribution", kwargs={"group_id": group.pk}))
        assert gps_logs(caplog) == [
            {"message": "GPS changed_end_date", "group": group.pk, "membership": membership.pk, "is_ongoing": False},
            {"message": "GPS visit_group_contribution", "group": group.pk},
        ]

        membership.refresh_from_db()
        assert membership.started_at == date(2024, 1, 3)
        assert membership.ended_at == date(2024, 6, 21)  # today
        assert membership.end_reason == EndReason.MANUAL

        # The user just clics on "Accompagnement en cours"
        post_data = {
            "started_at": "2024-01-03",
            "is_ongoing": "True",
            "ended_at": "2024-06-21",  # The field is set but will be ignored because of is_ongoing
            "reason": "",
        }
        response = client.post(url, data=post_data)
        assertRedirects(response, reverse("gps:group_contribution", kwargs={"group_id": group.pk}))
        assert gps_logs(caplog) == [
            {"message": "GPS changed_end_date", "group": group.pk, "membership": membership.pk, "is_ongoing": True},
            {"message": "GPS visit_group_contribution", "group": group.pk},
        ]

        membership.refresh_from_db()
        assert membership.started_at == date(2024, 1, 3)
        assert membership.ended_at is None
        assert membership.end_reason is None

        # The user ends again the membership and sets a date
        post_data = {
            "started_at": "2024-01-03",
            "is_ongoing": "False",
            "ended_at": "2024-06-20",
            "reason": "",
        }
        response = client.post(url, data=post_data)
        assertRedirects(response, reverse("gps:group_contribution", kwargs={"group_id": group.pk}))
        assert gps_logs(caplog) == [
            {"message": "GPS changed_end_date", "group": group.pk, "membership": membership.pk, "is_ongoing": False},
            {"message": "GPS visit_group_contribution", "group": group.pk},
        ]

        membership.refresh_from_db()
        assert membership.started_at == date(2024, 1, 3)
        assert membership.ended_at == date(2024, 6, 20)
        assert membership.end_reason == EndReason.MANUAL

        # If the membership was archived, saving the contribution without changing anything won't change the end reason
        membership.end_reason = EndReason.AUTOMATIC
        membership.save()
        post_data = {
            "started_at": "2024-01-03",
            "is_ongoing": "False",
            "ended_at": "2024-06-20",
            "reason": "",
        }
        response = client.post(url, data=post_data)
        assertRedirects(response, reverse("gps:group_contribution", kwargs={"group_id": group.pk}))
        assert gps_logs(caplog) == [
            {"message": "GPS visit_group_contribution", "group": group.pk},
        ]

        membership.refresh_from_db()
        assert membership.started_at == date(2024, 1, 3)
        assert membership.ended_at == date(2024, 6, 20)
        assert membership.end_reason == EndReason.AUTOMATIC

        # The user follows again the beneficiary
        post_data = {
            "started_at": "2024-01-03",
            "is_ongoing": "True",
            "ended_at": "2024-06-20",  # The field is set but will be ignored because of is_ongoing
            "reason": "",
        }
        response = client.post(url, data=post_data)
        assertRedirects(response, reverse("gps:group_contribution", kwargs={"group_id": group.pk}))
        assert gps_logs(caplog) == [
            {"message": "GPS changed_end_date", "group": group.pk, "membership": membership.pk, "is_ongoing": True},
            {"message": "GPS visit_group_contribution", "group": group.pk},
        ]

        membership.refresh_from_db()
        assert membership.started_at == date(2024, 1, 3)
        assert membership.ended_at is None
        assert membership.end_reason is None

        # The user sets a reason and changes the start_date
        post_data = {
            "started_at": "2024-01-02",
            "is_ongoing": "True",
            "ended_at": "2024-06-20",  # The field is set but will be ignored because of is_ongoing
            "reason": "iae",
        }
        response = client.post(url, data=post_data)
        assertRedirects(response, reverse("gps:group_contribution", kwargs={"group_id": group.pk}))
        assert gps_logs(caplog) == [
            {"message": "GPS changed_reason", "group": group.pk, "length": 3, "membership": membership.pk},
            {"message": "GPS changed_start_date", "group": group.pk, "membership": membership.pk},
            {"message": "GPS visit_group_contribution", "group": group.pk},
        ]

        membership.refresh_from_db()
        assert membership.reason == "iae"

    @freezegun.freeze_time("2024-06-21")
    def test_form_validation(self, client):
        prescriber = PrescriberFactory(membership=True)
        beneficiary = JobSeekerFactory(for_snapshot=True)
        group = FollowUpGroupFactory(beneficiary=beneficiary)
        FollowUpGroupMembershipFactory(member=prescriber, follow_up_group=group)

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
            partial(EmployerFactory, with_company=True),
            partial(PrescriberFactory, membership__organization__authorized=True),
            partial(PrescriberFactory, membership__organization__is_gps_authorized=True),
            partial(PrescriberFactory, membership=True),
        ],
        ids=[
            "employer",
            "authorized_prescriber",
            "gps_authorized_prescriber",
            "prescriber_with_org",
        ],
    )
    def test_view_with_org(self, client, snapshot, user_factory, caplog):
        url = reverse("gps:join_group")
        user = user_factory()
        client.force_login(user)
        response = client.get(url)
        assert pretty_indented(parse_response_to_soup(response, selector="#main")) == snapshot
        assert gps_logs(caplog) == [{"message": "GPS visit_join_group_index"}]

        # All redirection work : the join_group_from_* view will check if the user is allowed
        response = client.post(url, data={"channel": "from_coworker"})
        assertRedirects(response, reverse("gps:join_group_from_coworker"), fetch_redirect_response=False)
        assert gps_logs(caplog) == []

        response = client.post(url, data={"channel": "from_nir"})
        assertRedirects(response, reverse("gps:join_group_from_nir"), fetch_redirect_response=False)
        assert gps_logs(caplog) == []

        response = client.post(url, data={"channel": "from_name_email"})
        assertRedirects(response, reverse("gps:join_group_from_name_and_email"), fetch_redirect_response=False)
        assert gps_logs(caplog) == []

    def test_view_without_org(self, client, caplog):
        url = reverse("gps:join_group")
        user = PrescriberFactory()
        client.force_login(user)
        response = client.get(url)
        assertRedirects(response, reverse("gps:join_group_from_name_and_email"), fetch_redirect_response=False)
        assert gps_logs(caplog) == []


class TestBeneficiariesAutocomplete:
    @pytest.mark.parametrize(
        "factory,access",
        [
            [partial(JobSeekerFactory, for_snapshot=True), False],
            (partial(PrescriberFactory, membership__organization__authorized=True), True),
            (partial(PrescriberFactory, membership__organization__is_gps_authorized=True), True),
            (partial(PrescriberFactory, membership=True), True),
            (PrescriberFactory, False),
            (partial(EmployerFactory, with_company=True), True),
            [partial(LaborInspectorFactory, membership=True), False],
        ],
        ids=[
            "job_seeker",
            "authorized_prescriber",
            "gps_authorized_prescriber",
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

    @pytest.mark.parametrize("can_view_personal_info", ["authorized", "gps_authorized", "membership", False])
    def test_autocomplete(self, client, can_view_personal_info):
        prescriber = PrescriberFactory(first_name="gps member Vince")
        organization_1 = PrescriberMembershipFactory(
            user=prescriber,
            organization__authorized=can_view_personal_info == "authorized",
            organization__is_gps_authorized=can_view_personal_info == "gps_authorized",
        ).organization
        coworker_1 = PrescriberMembershipFactory(organization=organization_1).user
        organization_2 = PrescriberMembershipFactory(
            user=prescriber,
            organization__authorized=can_view_personal_info == "authorized",
            organization__is_gps_authorized=can_view_personal_info == "gps_authorized",
        ).organization
        coworker_2 = PrescriberMembershipFactory(organization=organization_2).user

        # created and followed by prescriber : he will always see the personal informations
        first_beneficiary = JobSeekerFactory(
            first_name="gps beneficiary Bob",
            last_name="Le Brico",
            created_by=prescriber,
            jobseeker_profile__birthdate=date(1980, 1, 1),
            title=Title.M,
        )
        FollowUpGroupFactory(beneficiary=first_beneficiary, memberships=1, memberships__member=prescriber)

        # followed by prescriber : he will only see personal info if he's authorized or if the memberships allows it
        second_beneficiary = JobSeekerFactory(
            first_name="gps second beneficiary Martin",
            last_name="Pêcheur",
            jobseeker_profile__birthdate=date(1990, 1, 1),
            title=Title.MME,
        )
        FollowUpGroupFactory(beneficiary=second_beneficiary, memberships=1, memberships__member=prescriber)

        # follow by coworker_1: the prescriber will only see personal info if he's authorized
        third_beneficiary = JobSeekerFactory(
            first_name="gps third beneficiary Jeanne",
            last_name="Bonneau",
            jobseeker_profile__birthdate=date(2000, 1, 1),
            title=Title.MME,
        )
        FollowUpGroupFactory(beneficiary=third_beneficiary, memberships=1, memberships__member=coworker_1)

        # Followed by coworker_2: not the active organization, but the prescriber will still see it
        fourth_beneficiary = JobSeekerFactory(first_name="gps fourth beneficiary Foo", last_name="Bar")
        FollowUpGroupFactory(beneficiary=fourth_beneficiary, memberships=1, memberships__member=coworker_2)

        # No link to the prescriber : don't display him
        JobSeekerFactory(first_name="gps other beneficiary Joe", last_name="Dalton")

        if can_view_personal_info == "membership":
            FollowUpGroupMembership.objects.filter(member=prescriber).update(can_view_personal_information=True)

        def get_autocomplete_results(user, term="gps"):
            client.force_login(user)
            response = client.get(reverse("gps:beneficiaries_autocomplete") + f"?term={term}")
            return [r["id"] for r in response.json()["results"]]

        # check we mask personal info when required
        client.force_login(prescriber)
        response = client.get(reverse("gps:beneficiaries_autocomplete") + "?term=gps")
        data = {d["id"]: d for d in response.json()["results"]}
        assert data[first_beneficiary.pk] == {
            "birthdate": "01/01/1980",
            "id": first_beneficiary.pk,
            "title": "M.",
            "name": first_beneficiary.get_full_name(),
        }
        if can_view_personal_info:
            second_beneficiary_data = {
                "birthdate": "01/01/1990",
                "id": second_beneficiary.pk,
                "title": "Mme",
                "name": second_beneficiary.get_full_name(),
            }
        else:
            second_beneficiary_data = {
                "birthdate": "",
                "id": second_beneficiary.pk,
                "title": "",
                "name": mask_unless(second_beneficiary.get_full_name(), False),
            }
        assert data[second_beneficiary.pk] == second_beneficiary_data
        if can_view_personal_info in ["authorized", "gps_authorized"]:
            third_beneficiary_data = {
                "birthdate": "01/01/2000",
                "id": third_beneficiary.pk,
                "title": "Mme",
                "name": third_beneficiary.get_full_name(),
            }
        else:
            third_beneficiary_data = {
                "birthdate": "",
                "id": third_beneficiary.pk,
                "title": "",
                "name": mask_unless(third_beneficiary.get_full_name(), False),
            }
        assert data[third_beneficiary.pk] == third_beneficiary_data

        # The prescriber should see the 4 job seekers followed by members of his organizations, but no the other one
        results = get_autocomplete_results(prescriber)
        assert set(results) == {
            first_beneficiary.pk,
            second_beneficiary.pk,
            third_beneficiary.pk,
            fourth_beneficiary.pk,
        }

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
            (partial(PrescriberFactory, membership__organization__is_gps_authorized=True), True),
            (partial(PrescriberFactory, membership=True), True),
            (PrescriberFactory, False),
            (partial(EmployerFactory, with_company=True), True),
            [partial(LaborInspectorFactory, membership=True), False],
        ],
        ids=[
            "job_seeker",
            "authorized_prescriber",
            "gps_authorized_prescriber",
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

    def test_view(self, client, snapshot, caplog):
        company = CompanyFactory(with_membership=True)
        user = company.members.get()
        coworker = CompanyMembershipFactory(company=company).user

        client.force_login(user)
        response = client.get(self.URL)
        assert pretty_indented(parse_response_to_soup(response, selector="#main")) == snapshot
        assert gps_logs(caplog) == [{"message": "GPS visit_join_group_from_coworker"}]

        followed_job_seeker = JobSeekerFactory()
        FollowUpGroupFactory(beneficiary=followed_job_seeker, memberships=1, memberships__member=user)
        response = client.post(self.URL, data={"user": followed_job_seeker.pk})
        assertRedirects(response, reverse("gps:group_list"))
        assert_already_followed_beneficiary_toast(response, followed_job_seeker)
        assert gps_logs(caplog) == [{"message": "GPS visit_list_groups"}]

        coworker_job_seeker = JobSeekerFactory()
        group = FollowUpGroupFactory(beneficiary=coworker_job_seeker, memberships=1, memberships__member=coworker)
        response = client.post(self.URL, data={"user": coworker_job_seeker.pk})
        assertRedirects(response, reverse("gps:group_list"))
        assert_new_beneficiary_toast(response, coworker_job_seeker)
        assert FollowUpGroupMembership.objects.filter(follow_up_group=group, member=user).exists()
        assert gps_logs(caplog) == [
            {"message": "GPS group_joined", "group": group.pk, "channel": "coworker"},
            {"message": "GPS visit_list_groups"},
        ]

        another_job_seeker = JobSeekerFactory()
        response = client.post(self.URL, data={"user": another_job_seeker.pk})
        assert response.status_code == 200
        assert response.context["form"].errors == {"user": ["Ce candidat ne peut être suivi."]}

    @pytest.mark.parametrize("can_view_personal_info", [True, False])
    def test_toasts(self, client, can_view_personal_info):
        organization = PrescriberOrganizationFactory(authorized=can_view_personal_info)
        user = PrescriberMembershipFactory(organization=organization).user
        coworker = PrescriberMembershipFactory(organization=organization).user
        client.force_login(user)

        coworker_job_seeker = JobSeekerFactory()
        FollowUpGroupFactory(beneficiary=coworker_job_seeker, memberships=1, memberships__member=coworker)
        response = client.post(self.URL, data={"user": coworker_job_seeker.pk}, follow=True)
        assert_new_beneficiary_toast(response, coworker_job_seeker, can_view_personal_info)

        response = client.post(self.URL, data={"user": coworker_job_seeker.pk}, follow=True)
        assert_already_followed_beneficiary_toast(response, coworker_job_seeker, can_view_personal_info)


class TestJoinGroupFromNir:
    URL = reverse("gps:join_group_from_nir")

    @pytest.mark.parametrize(
        "factory,access",
        [
            [partial(JobSeekerFactory, for_snapshot=True), False],
            (partial(PrescriberFactory, membership__organization__authorized=True), True),
            (partial(PrescriberFactory, membership__organization__is_gps_authorized=True), True),
            (partial(PrescriberFactory, membership=True), False),
            (PrescriberFactory, False),
            (partial(EmployerFactory, with_company=True), True),
            [partial(LaborInspectorFactory, membership=True), False],
        ],
        ids=[
            "job_seeker",
            "authorized_prescriber",
            "gps_authorized_prescriber",
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

    def test_view(self, client, snapshot, caplog):
        user = EmployerFactory(with_company=True)

        client.force_login(user)
        response = client.get(self.URL)
        assert pretty_indented(parse_response_to_soup(response, selector="#main")) == snapshot(name="get")
        assert gps_logs(caplog) == [{"message": "GPS visit_join_group_from_nir"}]

        # unknown NIR :
        dummy_job_seeker = JobSeekerFactory.build(for_snapshot=True)
        response = client.post(self.URL, data={"nir": dummy_job_seeker.jobseeker_profile.nir, "preview": "1"})
        job_seeker_session_name = get_session_name(client.session, JobSeekerSessionKinds.GET_OR_CREATE)
        next_url = reverse(
            "job_seekers_views:search_by_email_for_sender",
            kwargs={"session_uuid": job_seeker_session_name},
        )
        expected_job_seeker_session = {
            "config": {
                "tunnel": "gps",
                "from_url": reverse("gps:join_group_from_nir"),
            },
            "profile": {
                "nir": dummy_job_seeker.jobseeker_profile.nir,
            },
        }
        assertRedirects(response, next_url)
        assert client.session[job_seeker_session_name] == expected_job_seeker_session
        assert gps_logs(caplog) == []

        # existing nir
        job_seeker = JobSeekerFactory(for_snapshot=True)
        response = client.post(self.URL, data={"nir": job_seeker.jobseeker_profile.nir, "preview": "1"})
        assert pretty_indented(parse_response_to_soup(response, selector="#nir-confirmation-modal")) == snapshot(
            name="modal"
        )
        assert gps_logs(caplog) == [{"message": "GPS visit_join_group_from_nir"}]

        # Cancelling dismissed the modal, nothing to test

        # If we accept:
        response = client.post(self.URL, data={"nir": job_seeker.jobseeker_profile.nir, "confirm": "1"})
        assertRedirects(response, reverse("gps:group_list"))
        assert_new_beneficiary_toast(response, job_seeker)
        group = FollowUpGroup.objects.get(beneficiary=job_seeker)
        assert gps_logs(caplog) == [
            {"message": "GPS group_joined", "channel": "nir", "group": group.pk},
            {"message": "GPS visit_list_groups"},
        ]

        # If we were already following the user
        response = client.post(self.URL, data={"nir": job_seeker.jobseeker_profile.nir, "confirm": "1"})
        assertRedirects(response, reverse("gps:group_list"))
        assert_already_followed_beneficiary_toast(response, job_seeker)
        assert gps_logs(caplog) == [{"message": "GPS visit_list_groups"}]

    def test_unknown_nir_known_email_with_no_nir(self, client, snapshot, caplog):
        user = EmployerFactory(with_company=True)
        existing_job_seeker_without_nir = JobSeekerFactory(for_snapshot=True, jobseeker_profile__nir="")
        nir = "276024719711371"

        client.force_login(user)

        # Step search for NIR in GPS view
        # ----------------------------------------------------------------------
        response = client.post(self.URL, data={"nir": nir, "preview": "1"})

        job_seeker_session_name = get_session_name(client.session, JobSeekerSessionKinds.GET_OR_CREATE)
        next_url = reverse(
            "job_seekers_views:search_by_email_for_sender",
            kwargs={"session_uuid": job_seeker_session_name},
        )
        expected_job_seeker_session = {
            "config": {
                "tunnel": "gps",
                "from_url": reverse("gps:join_group_from_nir"),
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
        assert pretty_indented(parse_response_to_soup(response, "#email-confirmation-modal")) == snapshot

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

        group = FollowUpGroup.objects.get(beneficiary=existing_job_seeker_without_nir)
        assert group.memberships.filter(member=user).exists()
        assert gps_logs(caplog) == [
            {"message": "GPS group_created", "group": group.pk},
            {"message": "GPS visit_list_groups"},
        ]

    def test_unknown_nir_known_email_with_another_nir(self, client, snapshot, caplog):
        user = EmployerFactory(with_company=True)
        existing_job_seeker_with_nir = JobSeekerFactory(for_snapshot=True)
        job_seeker_nir = existing_job_seeker_with_nir.jobseeker_profile.nir
        nir = "276024719711371"

        client.force_login(user)

        # Step search for NIR in GPS view
        # ----------------------------------------------------------------------
        response = client.post(self.URL, data={"nir": nir, "preview": "1"})

        job_seeker_session_name = get_session_name(client.session, JobSeekerSessionKinds.GET_OR_CREATE)
        next_url = reverse(
            "job_seekers_views:search_by_email_for_sender",
            kwargs={"session_uuid": job_seeker_session_name},
        )
        expected_job_seeker_session = {
            "config": {
                "tunnel": "gps",
                "from_url": reverse("gps:join_group_from_nir"),
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
        assert pretty_indented(parse_response_to_soup(response, "#email-confirmation-modal")) == snapshot

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

        group = FollowUpGroup.objects.get(beneficiary=existing_job_seeker_with_nir)
        assert group.memberships.filter(member=user).exists()
        assert gps_logs(caplog) == [
            {"message": "GPS group_created", "group": group.pk},
            {"message": "GPS visit_list_groups"},
        ]

    def test_unknown_nir_and_unknown_email(self, client, settings, mocker, caplog, mailoutbox):
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

        job_seeker_session_name = get_session_name(client.session, JobSeekerSessionKinds.GET_OR_CREATE)
        next_url = reverse(
            "job_seekers_views:search_by_email_for_sender",
            kwargs={"session_uuid": job_seeker_session_name},
        )
        expected_job_seeker_session = {
            "config": {
                "tunnel": "gps",
                "from_url": reverse("gps:join_group_from_nir"),
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
            "birth_country": Country.FRANCE_ID,
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
        group = FollowUpGroup.objects.get(beneficiary=new_job_seeker)
        assert group.memberships.filter(member=user).exists()
        assert gps_logs(caplog) == [{"message": "GPS group_created", "group": group.pk}]

        [mail] = mailoutbox
        assert mail.to == [new_job_seeker.email]
        assert mail.from_email == settings.GPS_CONTACT_EMAIL
        assert mail.subject == "[TEST] Création de votre compte sur la Plateforme de l’inclusion"
        assert "Un compte à votre nom vient d’être créé par" in mail.body


class TestJoinGroupFromNameAndEmail:
    URL = reverse("gps:join_group_from_name_and_email")

    @pytest.mark.parametrize(
        "factory,access",
        [
            [partial(JobSeekerFactory, for_snapshot=True), False],
            (partial(PrescriberFactory, membership__organization__authorized=True), True),
            (partial(PrescriberFactory, membership__organization__is_gps_authorized=True), True),
            (partial(PrescriberFactory, membership=True), True),
            (PrescriberFactory, True),
            (partial(EmployerFactory, with_company=True), True),
            [partial(LaborInspectorFactory, membership=True), False],
        ],
        ids=[
            "job_seeker",
            "authorized_prescriber",
            "gps_authorized_prescriber",
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
    def test_unknown_email(self, client, settings, mocker, known_name, caplog, mailoutbox):
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
        job_seeker_session_name = get_session_name(client.session, JobSeekerSessionKinds.GET_OR_CREATE)
        next_url = reverse(
            "job_seekers_views:create_job_seeker_step_1_for_sender",
            kwargs={"session_uuid": job_seeker_session_name},
        )
        expected_job_seeker_session = {
            "config": {
                "tunnel": "gps",
                "from_url": reverse("gps:join_group_from_name_and_email"),
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

        def other_day_in_month(birthdate):
            a_day = timedelta(days=1)
            next_day = birthdate + a_day
            if next_day.month == birthdate.month:
                return next_day
            return birthdate - a_day

        birthdate = other_day_in_month(dummy_job_seeker.jobseeker_profile.birthdate)

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
            "birth_country": Country.FRANCE_ID,
        }
        response = client.post(next_url, data=post_data)
        assertContains(response, "Ce numéro de sécurité sociale est déjà associé à un autre utilisateur.")

        step2_url = reverse(
            "job_seekers_views:create_job_seeker_step_2_for_sender",
            kwargs={"session_uuid": job_seeker_session_name},
        )
        # With a other NIR
        post_data["nir"] = dummy_job_seeker.jobseeker_profile.nir
        response = client.post(next_url, data=post_data)
        assertRedirects(response, step2_url)
        expected_job_seeker_session["profile"] = {}
        for key in ["nir", "birthdate", "lack_of_nir_reason", "birth_place", "birth_country"]:
            expected_job_seeker_session["profile"][key] = post_data.pop(key)
        expected_job_seeker_session["user"] |= post_data
        assert client.session[job_seeker_session_name] == expected_job_seeker_session

        assertRedirects(response, step2_url)

        response = client.get(step2_url)
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

        response = client.post(step2_url, data=post_data)

        expected_job_seeker_session["user"] |= post_data | {"address_line_2": "", "address_for_autocomplete": None}
        assert client.session[job_seeker_session_name] == expected_job_seeker_session

        step3_url = reverse(
            "job_seekers_views:create_job_seeker_step_3_for_sender",
            kwargs={"session_uuid": job_seeker_session_name},
        )
        assertRedirects(response, step3_url)

        response = client.get(step3_url)
        assert response.status_code == 200

        post_data = {"education_level": dummy_job_seeker.jobseeker_profile.education_level}
        response = client.post(step3_url, data=post_data)
        step_end_url = reverse(
            "job_seekers_views:create_job_seeker_step_end_for_sender",
            kwargs={"session_uuid": job_seeker_session_name},
        )
        assertRedirects(response, step_end_url)

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

        response = client.get(step_end_url)
        assertContains(response, "Créer et suivre le bénéficiaire")

        response = client.post(step_end_url)
        assert job_seeker_session_name not in client.session
        new_job_seeker = User.objects.get(email=dummy_job_seeker.email)
        assert_new_beneficiary_toast(response, new_job_seeker)
        group = FollowUpGroup.objects.get(beneficiary=new_job_seeker)
        assert group.memberships.filter(member=user).exists()

        expected_mock_calls = []
        if known_name:
            new_job_seeker_admin_url = get_absolute_url(reverse("admin:users_user_change", args=(new_job_seeker.pk,)))
            expected_mock_calls = [
                (
                    (
                        ":black_square_for_stop: Création d’un nouveau bénéficiaire : "
                        f"<{new_job_seeker_admin_url}|{mask_unless(new_job_seeker.get_full_name(), False)}>.",
                    ),
                )
            ]
        assert slack_mock.mock_calls == expected_mock_calls
        assert gps_logs(caplog) == [{"group": group.pk, "message": "GPS group_created"}]

        [mail] = mailoutbox
        assert mail.to == [new_job_seeker.email]
        assert mail.from_email == settings.GPS_CONTACT_EMAIL
        assert mail.subject == "[TEST] Création de votre compte sur la Plateforme de l’inclusion"
        assert "Un compte à votre nom vient d’être créé par" in mail.body

    def test_full_match_with_advanced_features(self, client, snapshot, caplog):
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
        assert pretty_indented(parse_response_to_soup(response, selector="#main")) == snapshot
        assert gps_logs(caplog) == [{"message": "GPS visit_join_group_from_name_and_email"}]

        post_data = {
            "email": job_seeker.email,
            "first_name": job_seeker.first_name,
            "last_name": job_seeker.last_name,
            "confirm": "1",
        }
        response = client.post(self.URL, data=post_data)
        assertRedirects(response, reverse("gps:group_list"))
        assert_new_beneficiary_toast(response, job_seeker)
        group = FollowUpGroup.objects.get(beneficiary=job_seeker)
        assert group.memberships.filter(member=user).exists()
        assert gps_logs(caplog) == [
            {"message": "GPS group_joined", "group": group.pk, "channel": "name_and_email"},
            {"message": "GPS visit_list_groups"},
        ]

    def test_full_match_without_advanced_features(self, client, snapshot, mocker, caplog):
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
        assert pretty_indented(parse_response_to_soup(response, selector="#main")) == snapshot
        assert gps_logs(caplog) == [{"message": "GPS visit_join_group_from_name_and_email"}]

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
        assert gps_logs(caplog) == [{"message": "GPS visit_join_group_from_name_and_email"}]

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
        group = FollowUpGroup.objects.get(beneficiary=job_seeker)
        relation = group.memberships.get(member=user)
        assert relation.is_active is False

        job_seeker_admin_url = get_absolute_url(reverse("admin:users_user_change", args=(job_seeker.pk,)))
        user_admin_url = get_absolute_url(reverse("admin:users_user_change", args=(user.pk,)))
        membership_url = get_absolute_url(reverse("admin:gps_followupgroupmembership_change", args=(relation.pk,)))
        assert slack_mock.mock_calls == [
            (
                (
                    f":gemini: Demande d’ajout <{user_admin_url}|{user.get_full_name()}> "
                    f"veut suivre <{job_seeker_admin_url}|{mask_unless(job_seeker.get_full_name(), False)}> "
                    f"(<{membership_url}|relation>).",
                ),
            )
        ]
        assert gps_logs(caplog) == [
            {"message": "GPS group_requested_access", "group": group.pk},
            {"message": "GPS visit_list_groups"},
        ]

    def test_partial_match_with_advanced_features(self, client, snapshot, caplog):
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
        assert pretty_indented(parse_response_to_soup(response, selector="#main")) == snapshot
        assert gps_logs(caplog) == [{"message": "GPS visit_join_group_from_name_and_email"}]

        post_data = {
            "email": job_seeker.email,
            "first_name": "John",
            "last_name": "Snow",
            "confirm": "1",
        }
        response = client.post(self.URL, data=post_data)
        assertRedirects(response, reverse("gps:group_list"))
        assert_new_beneficiary_toast(response, job_seeker)
        group = FollowUpGroup.objects.get(beneficiary=job_seeker)
        assert group.memberships.filter(member=user).exists()
        assert gps_logs(caplog) == [
            {"message": "GPS group_joined", "group": group.pk, "channel": "name_and_email"},
            {"message": "GPS visit_list_groups"},
        ]

    def test_partial_match_without_advanced_features(self, client, snapshot, caplog):
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
        assert pretty_indented(parse_response_to_soup(response, selector="#main")) == snapshot
        assert gps_logs(caplog) == [{"message": "GPS visit_join_group_from_name_and_email"}]

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
        assert gps_logs(caplog) == [{"message": "GPS visit_join_group_from_name_and_email"}]
