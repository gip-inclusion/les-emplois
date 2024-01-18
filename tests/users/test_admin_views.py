from django.contrib.admin import helpers
from django.contrib.auth.models import Permission
from django.contrib.contenttypes.models import ContentType
from django.urls import reverse
from django.utils import timezone
from freezegun import freeze_time
from pytest_django.asserts import assertContains, assertNotContains, assertNumQueries, assertRedirects

from itou.job_applications.enums import SenderKind
from itou.users.enums import UserKind
from itou.users.models import IdentityProvider, User
from itou.utils.models import PkSupportRemark
from tests.job_applications.factories import JobApplicationFactory
from tests.users.factories import (
    EmployerFactory,
    ItouStaffFactory,
    JobSeekerFactory,
    PrescriberFactory,
)
from tests.utils.test import BASE_NUM_QUERIES, assertMessages


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
            response, [("INFO", f"Transfert effectué avec succès de l'utilisateur {from_user} vers {to_user}.")]
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
        assert "- PASS IAE" in remark


def test_app_model_change_url(admin_client):
    user = JobSeekerFactory()
    # Check that the page does not crash
    response = admin_client.get(reverse("admin:users_user_change", kwargs={"object_id": user.pk}))
    assert response.status_code == 200
    response = admin_client.get(
        reverse("admin:users_jobseekerprofile_change", kwargs={"object_id": user.jobseeker_profile.pk})
    )
    assert response.status_code == 200


def test_free_ic_email(admin_client):
    employer = EmployerFactory(with_company=True, username="ic_uuid_username", email="ic_user@email.com")
    prescriber = PrescriberFactory(identity_provider=IdentityProvider.DJANGO)

    # only:one user at a time
    response = admin_client.post(
        reverse("admin:users_user_changelist"),
        {
            "action": "free_ic_email",
            helpers.ACTION_CHECKBOX_NAME: [prescriber.pk, employer.pk],
        },
        follow=True,
    )
    assertContains(response, "Vous ne pouvez selectionner qu'un seul utilisateur à la fois", html=True)
    prescriber.refresh_from_db()
    assert prescriber.is_active is True
    employer.refresh_from_db()
    assert employer.is_active is True

    # only IC accounts
    response = admin_client.post(
        reverse("admin:users_user_changelist"),
        {
            "action": "free_ic_email",
            helpers.ACTION_CHECKBOX_NAME: [prescriber.pk],
        },
        follow=True,
    )
    assertContains(response, "Vous devez sélectionner un compte Inclusion Connect")
    prescriber.refresh_from_db()
    assert prescriber.is_active is True

    # When it works
    response = admin_client.post(
        reverse("admin:users_user_changelist"),
        {
            "action": "free_ic_email",
            helpers.ACTION_CHECKBOX_NAME: [employer.pk],
        },
        follow=True,
    )
    assertContains(response, "L'utilisateur peut à présent se créer un nouveau compte", html=True)
    employer.refresh_from_db()
    assert employer.is_active is False
    assert employer.companymembership_set.get().is_active is False
    assert employer.username == "old_ic_uuid_username"
    assert employer.email == "ic_user@email.com_old"

    # It won't work twice on the same user
    response = admin_client.post(
        reverse("admin:users_user_changelist"),
        {
            "action": "free_ic_email",
            helpers.ACTION_CHECKBOX_NAME: [employer.pk],
        },
        follow=True,
    )
    assertContains(response, "Ce compte a déjà été libré de l'emprise d'Inclusion Connect", html=True)
    employer.refresh_from_db()
    assert employer.is_active is False
    assert employer.username == "old_ic_uuid_username"
    assert employer.email == "ic_user@email.com_old"


def test_num_queries(admin_client):
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
    # prewarm ContentType cache if needed to avoid extra query
    ContentType.objects.get_for_model(prescriber)
    with assertNumQueries(
        BASE_NUM_QUERIES
        + 1  # Load Django session
        + 1  # Load admin user
        + 2  # savepoint & release
        + 1  # load user
        + 1  # users_user_groups
        + 1  # auth_permission
        + 1  # companies_companymembership
        + 1  # institutions_institutionmembership
        + 1  # eligibility_eligibilitydiagnosis
        + 1  # eligibility_geiqeligibilitydiagnosis
        + 1  # approvals_approval
        + 1  # account_emailaddress
        + 1  # job_applications_jobapplication
        + 1  # prescribers_prescribermembership
        + 1  # utils_pksupportremark
        + 2  # auth_group & auth_permission
        + 3  # savepoint, session update & release
    ):
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
            (
                "WARNING",
                (
                    '1 objet incohérent: <ul><li class="warning">'
                    f'<a href="/admin/job_applications/jobapplication/{inconsistent_job_app.pk}/change/">'
                    f"candidature - {inconsistent_job_app.pk}"
                    "</a>: Candidature liée au PASS IAE d&#x27;un autre candidat"
                    "</li></ul>"
                ),
            )
        ],
    )
