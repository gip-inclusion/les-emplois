from allauth.account.models import EmailAddress
from django.contrib.auth.models import Permission
from django.contrib.contenttypes.models import ContentType
from django.urls import reverse
from django.utils import timezone
from freezegun import freeze_time
from pytest_django.asserts import assertContains, assertNotContains, assertRedirects

from itou.users.enums import UserKind
from itou.users.models import IdentityProvider, User
from itou.utils.models import PkSupportRemark
from tests.job_applications.factories import JobApplicationFactory
from tests.users.factories import ItouStaffFactory, JobSeekerFactory
from tests.utils.test import assertMessages


def test_add_user(client):
    admin_user = ItouStaffFactory(is_superuser=True)
    client.force_login(admin_user)
    response = client.post(
        reverse("admin:users_user_add"),
        {
            "username": "foo",
            "password1": "Véry_$S3C®3T!",
            "password2": "Véry_$S3C®3T!",
            "kind": UserKind.JOB_SEEKER,
            "utils-pksupportremark-content_type-object_id-INITIAL_FORMS": "0",
            "utils-pksupportremark-content_type-object_id-TOTAL_FORMS": "0",
        },
    )
    user = User.objects.get(username="foo")
    assertRedirects(response, reverse("admin:users_user_change", kwargs={"object_id": user.pk}))
    assert user.kind == UserKind.JOB_SEEKER
    email_address = EmailAddress.objects.get()
    assert email_address.email == user.email
    assert email_address.user_id == user.pk
    assert email_address.primary is True
    assert email_address.verified is False


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
        assertRedirects(response, reverse("admin:users_user_change", kwargs={"object_id": to_user.pk}))

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
