import random

import pytest
from allauth.account.models import EmailAddress
from django.contrib import messages
from django.contrib.admin import helpers
from django.contrib.auth import get_user
from django.contrib.auth.models import Permission
from django.contrib.contenttypes.models import ContentType
from django.urls import reverse
from django.utils import timezone
from freezegun import freeze_time
from pytest_django.asserts import assertContains, assertHTMLEqual, assertMessages, assertNotContains, assertRedirects

from itou.job_applications.enums import SenderKind
from itou.users.enums import UserKind
from itou.users.models import IdentityProvider, User
from itou.utils.models import PkSupportRemark
from tests.companies.factories import CompanyMembershipFactory
from tests.institutions.factories import InstitutionMembershipFactory
from tests.job_applications.factories import (
    JobApplicationFactory,
    JobApplicationSentByCompanyFactory,
    JobApplicationSentByJobSeekerFactory,
    JobApplicationSentByPrescriberFactory,
)
from tests.prescribers.factories import PrescriberMembershipFactory, PrescriberOrganizationFactory
from tests.users.factories import (
    EmployerFactory,
    ItouStaffFactory,
    JobSeekerFactory,
    JobSeekerProfileFactory,
    LaborInspectorFactory,
    PrescriberFactory,
)
from tests.utils.testing import assertSnapshotQueries, parse_response_to_soup


def test_add_user(client):
    admin_user = ItouStaffFactory(is_superuser=True)
    client.force_login(admin_user)
    response = client.post(
        reverse("admin:users_user_add"),
        {
            "username": "foo",
            "email": "foo@mailinator.com",
            "kind": UserKind.JOB_SEEKER,
            "utils-pksupportremark-content_type-object_id-INITIAL_FORMS": "0",
            "utils-pksupportremark-content_type-object_id-TOTAL_FORMS": "0",
        },
    )
    user = User.objects.get(username="foo")
    assertRedirects(response, reverse("admin:users_user_change", kwargs={"object_id": user.pk}))
    assert user.kind == UserKind.JOB_SEEKER


def test_no_email_sent(client):
    user = JobSeekerFactory(identity_provider=IdentityProvider.FRANCE_CONNECT)

    # Typical admin user.
    admin_user = ItouStaffFactory(is_superuser=True)
    client.force_login(admin_user)
    now = timezone.now()
    naive_now = timezone.make_naive(now)
    response = client.post(
        reverse("admin:users_user_change", kwargs={"object_id": user.pk}),
        {
            "date_joined_0": naive_now.date(),
            "date_joined_1": naive_now.time(),
            "last_checked_at_0": naive_now.date(),
            "last_checked_at_1": naive_now.time(),
            # email was set by SSO.
            # kind can not be submitted in a change
            "emailaddress_set-INITIAL_FORMS": "0",
            "emailaddress_set-TOTAL_FORMS": "0",
            "eligibility_diagnoses-INITIAL_FORMS": "0",
            "eligibility_diagnoses-TOTAL_FORMS": "0",
            "geiq_eligibility_diagnoses-INITIAL_FORMS": "0",
            "geiq_eligibility_diagnoses-TOTAL_FORMS": "0",
            "approvals-INITIAL_FORMS": "0",
            "approvals-TOTAL_FORMS": "0",
            "job_applications-INITIAL_FORMS": "0",
            "job_applications-TOTAL_FORMS": "0",
            "utils-pksupportremark-content_type-object_id-INITIAL_FORMS": "0",
            "utils-pksupportremark-content_type-object_id-TOTAL_FORMS": "0",
            "_save": "Save",
        },
    )
    assertRedirects(response, reverse("admin:users_user_changelist"))
    user.refresh_from_db()
    assert user.kind == UserKind.JOB_SEEKER
    assert user.first_name == user.first_name
    assert user.last_name == user.last_name
    assert user.date_joined == now
    assert user.last_checked_at == now
    assert user.identity_provider == IdentityProvider.FRANCE_CONNECT


def test_hijack_button(client):
    user = JobSeekerFactory()
    hijack_url = reverse("hijack:acquire")

    # Basic staff users don't have access to the button
    admin_user = ItouStaffFactory()
    perms = Permission.objects.filter(codename__in=("change_user", "view_user"))
    admin_user.user_permissions.add(*perms)
    client.force_login(admin_user)
    response = client.get(reverse("admin:users_user_change", kwargs={"object_id": user.pk}))
    assertNotContains(response, hijack_url)

    # Superusers (and those matching has_hijack_perm) can
    admin_user.is_superuser = True
    admin_user.save(update_fields=("is_superuser",))
    response = client.get(reverse("admin:users_user_change", kwargs={"object_id": user.pk}))
    assertContains(response, hijack_url)


class TestTransferUserData:
    IMPOSSIBLE_TRANSFER_TEXT = "Transfert impossible: aucune donnée à transférer"
    CHOOSE_TARGET_TEXT = "Choisissez l'utilisateur cible :"

    def test_transfer_button(self, client):
        user = JobSeekerFactory()
        transfer_url = reverse("admin:transfer_user_data", kwargs={"from_user_pk": user.pk})

        # Basic staff users without write access don't see the button
        admin_user = ItouStaffFactory()
        perms = Permission.objects.filter(codename="view_user")
        admin_user.user_permissions.add(*perms)
        client.force_login(admin_user)
        response = client.get(reverse("admin:users_user_change", kwargs={"object_id": user.pk}))
        assertNotContains(response, transfer_url)

        # With the change permission, the button appears
        perms = Permission.objects.filter(codename="change_user")
        admin_user.user_permissions.add(*perms)
        response = client.get(reverse("admin:users_user_change", kwargs={"object_id": user.pk}))
        assertContains(response, transfer_url)

    def test_transfer_without_change_permission(self, client):
        from_user = JobSeekerFactory()
        to_user = JobSeekerFactory()
        transfer_url_1 = reverse("admin:transfer_user_data", kwargs={"from_user_pk": from_user.pk})
        transfer_url_2 = reverse(
            "admin:transfer_user_data", kwargs={"from_user_pk": from_user.pk, "to_user_pk": to_user.pk}
        )

        admin_user = ItouStaffFactory()
        perms = Permission.objects.filter(codename="view_user")
        admin_user.user_permissions.add(*perms)
        client.force_login(admin_user)
        response = client.get(transfer_url_1)
        assert response.status_code == 403
        response = client.get(transfer_url_2)
        assert response.status_code == 403

    def test_transfer_no_data_to_transfer(self, admin_client):
        user = JobSeekerFactory()
        transfer_url = reverse("admin:transfer_user_data", kwargs={"from_user_pk": user.pk})
        response = admin_client.get(transfer_url)
        assertContains(response, self.IMPOSSIBLE_TRANSFER_TEXT)
        assertNotContains(response, self.CHOOSE_TARGET_TEXT, html=True)

    @freeze_time("2023-08-31 12:34:56")
    def test_transfer_data(self, admin_client, snapshot):
        job_application = JobApplicationFactory(with_approval=True)
        approval = job_application.approval

        from_user = job_application.job_seeker
        to_user = JobSeekerFactory()

        transfer_url_1 = reverse("admin:transfer_user_data", kwargs={"from_user_pk": from_user.pk})
        transfer_url_2 = reverse(
            "admin:transfer_user_data", kwargs={"from_user_pk": from_user.pk, "to_user_pk": to_user.pk}
        )
        response = admin_client.get(transfer_url_1)
        assertNotContains(response, self.IMPOSSIBLE_TRANSFER_TEXT)
        assertContains(response, self.CHOOSE_TARGET_TEXT, html=True)
        # Select same user
        response = admin_client.post(transfer_url_1, data={"to_user": from_user.pk})
        assertContains(response, "L'utilisateur cible doit être différent de celui d'origine", html=True)
        # Select valid target
        response = admin_client.post(transfer_url_1, data={"to_user": to_user.pk})
        assertRedirects(response, transfer_url_2, fetch_redirect_response=False)

        response = admin_client.get(transfer_url_2)
        assertContains(response, "Choisissez les objets à transférer")
        assertContains(response, str(job_application))
        assertContains(response, str(approval))

        response = admin_client.post(transfer_url_2, data={"fields_to_transfer": ["job_applications", "approvals"]})
        assertRedirects(response, reverse("admin:users_user_change", kwargs={"object_id": from_user.pk}))

        job_application.refresh_from_db()
        approval.refresh_from_db()
        assert job_application.job_seeker == to_user
        assert approval.user == to_user
        assertMessages(
            response,
            [
                messages.Message(
                    messages.INFO, f"Transfert effectué avec succès de l'utilisateur {from_user} vers {to_user}."
                ),
                messages.Message(
                    messages.WARNING,
                    (
                        "2 objets incohérents: <ul>"
                        '<li class="warning">'
                        f'<a href="/admin/job_applications/jobapplication/{job_application.pk}/change/">'
                        f"candidature - {job_application.pk}"
                        "</a>: Candidature liée au diagnostic d&#x27;un autre candidat</li>"
                        '<li class="warning">'
                        f'<a href="/admin/approvals/approval/{job_application.approval.pk}/change/">'
                        f"PASS IAE - {job_application.approval.pk}"
                        "</a>: PASS IAE lié au diagnostic d&#x27;un autre candidat</li>"
                        "</ul>"
                    ),
                ),
            ],
        )
        user_content_type = ContentType.objects.get_for_model(User)
        to_user_remark = PkSupportRemark.objects.filter(content_type=user_content_type, object_id=to_user.pk).first()
        from_user_remark = PkSupportRemark.objects.filter(
            content_type=user_content_type, object_id=from_user.pk
        ).first()
        assert to_user_remark.remark == from_user_remark.remark
        remark = to_user_remark.remark
        assert "Transfert du 2023-08-31 12:34:56 effectué par" in remark
        assert "- CANDIDATURES" in remark
        assert "- PASS IAE" in remark

    @pytest.mark.parametrize(
        "factory",
        [
            JobApplicationSentByJobSeekerFactory,
            JobApplicationSentByCompanyFactory,
            JobApplicationSentByPrescriberFactory,
        ],
    )
    def test_transfer_sender(self, admin_client, factory):
        job_application = factory()
        from_user = job_application.job_seeker
        to_user = JobSeekerFactory()
        sender = to_user if job_application.sender_kind == SenderKind.JOB_SEEKER else job_application.sender
        transfer_url = reverse(
            "admin:transfer_user_data", kwargs={"from_user_pk": from_user.pk, "to_user_pk": to_user.pk}
        )
        admin_client.post(transfer_url, data={"fields_to_transfer": ["job_applications"]})

        job_application.refresh_from_db()
        assert job_application.job_seeker == to_user
        assert job_application.sender == sender


def test_app_model_change_url(admin_client):
    user = JobSeekerFactory()
    # Check that the page does not crash
    response = admin_client.get(reverse("admin:users_user_change", kwargs={"object_id": user.pk}))
    assert response.status_code == 200
    response = admin_client.get(
        reverse("admin:users_jobseekerprofile_change", kwargs={"object_id": user.jobseeker_profile.pk})
    )
    assert response.status_code == 200


def test_num_queries(admin_client, snapshot):
    prescriber = PrescriberFactory()
    sent_job_application1 = JobApplicationFactory(
        sender=prescriber,
        sender_kind=SenderKind.PRESCRIBER,
    )
    JobApplicationFactory(
        job_seeker=sent_job_application1.job_seeker,
        sender=prescriber,
        sender_kind=SenderKind.PRESCRIBER,
    )
    with assertSnapshotQueries(snapshot):
        response = admin_client.get(reverse("admin:users_user_change", kwargs={"object_id": prescriber.pk}))
    assert response.status_code == 200


def test_check_inconsistency_check(admin_client):
    job_seeker = JobSeekerFactory()

    response = admin_client.post(
        reverse("admin:users_user_changelist"),
        {
            "action": "check_inconsistencies",
            helpers.ACTION_CHECKBOX_NAME: [job_seeker.pk],
        },
        follow=True,
    )
    assertContains(response, "Aucune incohérence trouvée")

    inconsistent_job_app = JobApplicationFactory(
        with_approval=True,
        approval__user=job_seeker,
    )
    response = admin_client.post(
        reverse("admin:users_user_changelist"),
        {
            "action": "check_inconsistencies",
            helpers.ACTION_CHECKBOX_NAME: [inconsistent_job_app.job_seeker.pk],
        },
        follow=True,
    )
    assertMessages(
        response,
        [
            messages.Message(
                messages.WARNING,
                (
                    '1 objet incohérent: <ul><li class="warning">'
                    f'<a href="/admin/job_applications/jobapplication/{inconsistent_job_app.pk}/change/">'
                    f"candidature - {inconsistent_job_app.pk}"
                    "</a>: Candidature liée au PASS IAE d&#x27;un autre candidat"
                    "</li></ul>"
                ),
            )
        ],
    )


def test_search_fields(admin_client):
    list_url = reverse("admin:users_jobseekerprofile_changelist")
    job_seeker1 = JobSeekerFactory(
        first_name="Jean Michel",
        last_name="Dupont",
        email="jean.michel@example.com",
        jobseeker_profile__nir="190031398700953",
    )
    url_1 = reverse("admin:users_jobseekerprofile_change", kwargs={"object_id": job_seeker1.jobseeker_profile.pk})
    job_seeker2 = JobSeekerFactory(
        first_name="Pierre François",
        last_name="Martin",
        email="pierre.francois@example.com",
        jobseeker_profile__nir="",
    )
    url_2 = reverse("admin:users_jobseekerprofile_change", kwargs={"object_id": job_seeker2.jobseeker_profile.pk})

    # Nothing to hide
    response = admin_client.get(list_url)
    assertContains(response, url_1)
    assertContains(response, url_2)

    # Search by ASP uid
    response = admin_client.get(list_url, {"q": job_seeker1.jobseeker_profile.asp_uid})
    assertContains(response, url_1)
    assertNotContains(response, url_2)

    # Search by pk
    response = admin_client.get(list_url, {"q": job_seeker2.jobseeker_profile.pk})
    assertNotContains(response, url_1)
    assertContains(response, url_2)

    # Search by NIR
    response = admin_client.get(list_url, {"q": job_seeker1.jobseeker_profile.nir})
    assertContains(response, url_1)
    assertNotContains(response, url_2)

    # Search on email
    response = admin_client.get(list_url, {"q": "michel@example"})
    assertContains(response, url_1)
    assertNotContains(response, url_2)

    # Search on first_name
    response = admin_client.get(list_url, {"q": "françois"})
    assertNotContains(response, url_1)
    assertContains(response, url_2)

    # Search on last_name
    response = admin_client.get(list_url, {"q": "martin"})
    assertNotContains(response, url_1)
    assertContains(response, url_2)


def test_profile_check_inconsistency_check(admin_client):
    profile = JobSeekerProfileFactory()

    response = admin_client.post(
        reverse("admin:users_jobseekerprofile_changelist"),
        {
            "action": "check_inconsistencies",
            helpers.ACTION_CHECKBOX_NAME: [profile.pk],
        },
        follow=True,
    )
    assertContains(response, "Aucune incohérence trouvée")

    prescriber = PrescriberFactory()
    inconsistent_profile = JobSeekerProfileFactory(user=prescriber)

    response = admin_client.post(
        reverse("admin:users_jobseekerprofile_changelist"),
        {
            "action": "check_inconsistencies",
            helpers.ACTION_CHECKBOX_NAME: [inconsistent_profile.pk],
        },
        follow=True,
    )
    assertMessages(
        response,
        [
            messages.Message(
                messages.WARNING,
                (
                    '1 objet incohérent: <ul><li class="warning">'
                    f'<a href="/admin/users/jobseekerprofile/{inconsistent_profile.pk}/change/">'
                    f"profil demandeur d&#x27;emploi - {inconsistent_profile.pk}"
                    "</a>: Profil lié à un utilisateur non-candidat"
                    "</li></ul>"
                ),
            )
        ],
    )


group_permissions_markup = (
    '<select name="groups" data-context="available-source" aria-describedby="id_groups_helptext" id="id_groups" '
    'multiple class="selectfilter" data-field-name="groupes" data-is-stacked="0">'
)

user_permissions_markup = (
    '<select name="user_permissions" data-context="available-source" aria-describedby="id_user_permissions_helptext" '
    'id="id_user_permissions" multiple class="selectfilter" data-field-name="permissions de l’utilisateur" '
    'data-is-stacked="0">'
)


@pytest.mark.parametrize(
    "superuser,assertion",
    [
        (False, assertNotContains),
        (True, assertContains),
    ],
)
def test_change_hides_permission_section_on_regular_users(client, superuser, assertion):
    viewed = JobSeekerFactory()
    user = ItouStaffFactory(is_superuser=superuser, is_staff=True)
    if not superuser:
        perms = Permission.objects.filter(codename__in=("change_user", "view_user"))
        user.user_permissions.add(*perms)
    client.force_login(user)
    response = client.get(reverse("admin:users_user_change", kwargs={"object_id": viewed.pk}))
    assertion(
        response,
        '<input type="checkbox" name="is_superuser" aria-describedby="id_is_superuser_helptext" id="id_is_superuser">',
    )
    assertNotContains(response, group_permissions_markup)
    assertNotContains(response, user_permissions_markup)


def test_change_shows_permission_section_on_staff_users(client):
    viewed = ItouStaffFactory(is_staff=True)
    user = ItouStaffFactory(is_superuser=True, is_staff=True)
    client.force_login(user)
    response = client.get(reverse("admin:users_user_change", kwargs={"object_id": viewed.pk}))
    assertContains(response, "Permissions")
    assertContains(response, group_permissions_markup)
    assertContains(response, user_permissions_markup)


def test_membership_inline_includes_inactive(admin_client):
    organization = PrescriberOrganizationFactory()
    membership = PrescriberMembershipFactory(organization=organization, is_active=False, is_admin=False)

    response = admin_client.get(reverse("admin:users_user_change", kwargs={"object_id": membership.user_id}))
    assert response.status_code == 200
    soup = parse_response_to_soup(response, "#prescribermembership_set-0")
    [is_active_cell] = soup.select("td.field-is_active")
    assertHTMLEqual(
        """
        <td class="field-is_active">
        <p><img src="/static/admin/img/icon-no.svg" alt="False"></p>
        </td>
        """,
        str(is_active_cell),
    )


class TestDeactivateView:
    def test_deactivate_button(self, client):
        user = random.choice([EmployerFactory, PrescriberFactory, LaborInspectorFactory, JobSeekerFactory])()
        deactivate_url = reverse("admin:deactivate_user", kwargs={"user_pk": user.pk})

        # Basic staff users without write access don't see the button
        admin_user = ItouStaffFactory()
        perms = Permission.objects.filter(codename="view_user")
        admin_user.user_permissions.add(*perms)
        client.force_login(admin_user)
        response = client.get(reverse("admin:users_user_change", kwargs={"object_id": user.pk}))
        assertNotContains(response, deactivate_url)

        # With the change permission, the button appears
        perms = Permission.objects.filter(codename="change_user")
        admin_user.user_permissions.add(*perms)
        response = client.get(reverse("admin:users_user_change", kwargs={"object_id": user.pk}))
        assertContains(response, deactivate_url)

        # But if the user is already inactive, it doesn't appear
        user.is_active = False
        user.save(update_fields=("is_active",))
        response = client.get(reverse("admin:users_user_change", kwargs={"object_id": user.pk}))
        assertNotContains(response, deactivate_url)

    def test_deactivate_without_change_permission(self, client):
        user = random.choice([EmployerFactory, PrescriberFactory, LaborInspectorFactory, JobSeekerFactory])()
        deactivate_url = reverse("admin:deactivate_user", kwargs={"user_pk": user.pk})
        admin_user = ItouStaffFactory()
        perms = Permission.objects.filter(codename="view_user")
        admin_user.user_permissions.add(*perms)
        client.force_login(admin_user)
        response = client.post(deactivate_url)
        assert response.status_code == 403

    def test_deactivate_inactive_user(self, admin_client):
        user = random.choice([EmployerFactory, PrescriberFactory, LaborInspectorFactory, JobSeekerFactory])(
            is_active=False
        )
        deactivate_url = reverse("admin:deactivate_user", kwargs={"user_pk": user.pk})
        response = admin_client.post(deactivate_url)
        assert response.status_code == 404

    @freeze_time("2023-08-31 12:34:56")
    def test_deactivate_user(self, admin_client, caplog):
        user = random.choice([EmployerFactory, PrescriberFactory, LaborInspectorFactory, JobSeekerFactory])(
            username="0e8bee68-6c4b-48bb-850c-0dea09915d94",
            email="user@example.com",
        )
        EmailAddress.objects.create(user=user, email=user.email, primary=True, verified=True)
        membership_factory = {
            UserKind.EMPLOYER: CompanyMembershipFactory,
            UserKind.PRESCRIBER: PrescriberMembershipFactory,
            UserKind.LABOR_INSPECTOR: InstitutionMembershipFactory,
            UserKind.JOB_SEEKER: None,
        }[user.kind]
        if membership_factory:
            membership = membership_factory(user=user)
        else:
            membership = None

        response = admin_client.post(reverse("admin:deactivate_user", kwargs={"user_pk": user.pk}))
        assertRedirects(response, reverse("admin:users_user_change", kwargs={"object_id": user.pk}))

        admin_user = get_user(admin_client)
        user.refresh_from_db()
        assert user.is_active is False
        assert user.username == "old_0e8bee68-6c4b-48bb-850c-0dea09915d94"
        assert user.email == "user@example.com_old"
        assert not EmailAddress.objects.filter(user=user).exists()
        if membership is not None:
            membership.refresh_from_db()
            assert membership.is_active is False
            assert membership.updated_by == admin_user

        assert f"user={user.pk} deactivated" in caplog.text
        assertMessages(
            response,
            [
                messages.Message(messages.SUCCESS, f"Désactivation de l'utilisateur {user} effectuée."),
            ],
        )
        user_content_type = ContentType.objects.get_for_model(User)
        user_remark = PkSupportRemark.objects.filter(content_type=user_content_type, object_id=user.pk).first()
        assert f"2023-08-31 ({admin_user.get_full_name()}): Désactivation de l’utilisateur" in user_remark.remark
