import pytest
from django.contrib import messages
from django.contrib.admin import helpers
from django.contrib.auth.models import Permission
from django.contrib.contenttypes.models import ContentType
from django.urls import reverse
from freezegun import freeze_time
from pytest_django.asserts import assertContains, assertMessages, assertNotContains, assertNumQueries, assertRedirects

from itou.companies.enums import CompanyKind
from itou.companies.models import Company
from itou.utils.models import PkSupportRemark
from tests.common_apps.organizations.tests import assert_set_admin_role__creation, assert_set_admin_role__removal
from tests.companies.factories import CompanyFactory
from tests.job_applications.factories import JobApplicationFactory
from tests.users.factories import EmployerFactory, ItouStaffFactory
from tests.utils.test import (
    BASE_NUM_QUERIES,
    assertSnapshotQueries,
    get_rows_from_streaming_response,
    parse_response_to_soup,
)


class TestCompanyAdmin:
    # Variable is not defined for the add view, comes from django-import-export.
    @pytest.mark.ignore_unknown_variable_template_error("show_change_form_export")
    def test_display_for_new_company(self, admin_client, snapshot):
        """Does not search approvals with company IS NULL"""
        with assertSnapshotQueries(snapshot(name="SQL queries")):
            response = admin_client.get(reverse("admin:companies_company_add"))
        response = parse_response_to_soup(response, selector=".field-approvals_list")
        assert str(response) == snapshot(name="approvals list")

    def test_deactivate_last_admin(self, admin_client, mailoutbox):
        company = CompanyFactory(with_membership=True)
        membership = company.memberships.first()
        assert membership.is_admin

        change_url = reverse("admin:companies_company_change", args=[company.pk])
        response = admin_client.get(change_url)
        assert response.status_code == 200

        response = admin_client.post(
            change_url,
            data={
                "id": company.id,
                "siret": company.siret,
                "kind": company.kind.value,
                "name": company.name,
                "phone": company.phone,
                "email": company.email,
                "companymembership_set-TOTAL_FORMS": "2",
                "companymembership_set-INITIAL_FORMS": "1",
                "companymembership_set-MIN_NUM_FORMS": "0",
                "companymembership_set-MAX_NUM_FORMS": "1000",
                "companymembership_set-0-id": membership.pk,
                "companymembership_set-0-company": company.pk,
                "companymembership_set-0-user": membership.user.pk,
                # companymembership_pet-0-is_admin is absent
                "job_description_through-TOTAL_FORMS": "0",
                "job_description_through-INITIAL_FORMS": "0",
                "utils-pksupportremark-content_type-object_id-TOTAL_FORMS": 1,
                "utils-pksupportremark-content_type-object_id-INITIAL_FORMS": 0,
                "_continue": "Enregistrer+et+continuer+les+modifications",
            },
        )
        assertRedirects(response, change_url, fetch_redirect_response=False)
        response = admin_client.get(change_url)
        assertContains(
            response,
            (
                "Vous venez de supprimer le dernier administrateur de la structure. "
                "Les membres restants risquent de solliciter le support."
            ),
        )

        assert_set_admin_role__removal(membership.user, company, mailoutbox)

    def test_delete_admin(self, admin_client, mailoutbox):
        company = CompanyFactory(with_membership=True)
        membership = company.memberships.first()
        assert membership.is_admin

        change_url = reverse("admin:companies_company_change", args=[company.pk])
        response = admin_client.get(change_url)
        assert response.status_code == 200

        response = admin_client.post(
            change_url,
            data={
                "id": company.id,
                "siret": company.siret,
                "kind": company.kind.value,
                "name": company.name,
                "phone": company.phone,
                "email": company.email,
                "companymembership_set-TOTAL_FORMS": "2",
                "companymembership_set-INITIAL_FORMS": "1",
                "companymembership_set-MIN_NUM_FORMS": "0",
                "companymembership_set-MAX_NUM_FORMS": "1000",
                "companymembership_set-0-id": membership.pk,
                "companymembership_set-0-company": company.pk,
                "companymembership_set-0-user": membership.user.pk,
                "companymembership_set-0-is_admin": "on",
                "companymembership_set-0-DELETE": "on",
                "job_description_through-TOTAL_FORMS": "0",
                "job_description_through-INITIAL_FORMS": "0",
                "utils-pksupportremark-content_type-object_id-TOTAL_FORMS": 1,
                "utils-pksupportremark-content_type-object_id-INITIAL_FORMS": 0,
                "_continue": "Enregistrer+et+continuer+les+modifications",
            },
        )
        assertRedirects(response, change_url, fetch_redirect_response=False)
        response = admin_client.get(change_url)

        assert_set_admin_role__removal(membership.user, company, mailoutbox)

    def test_add_admin(self, admin_client, mailoutbox):
        company = CompanyFactory(with_membership=True)
        membership = company.memberships.first()
        employer = EmployerFactory()
        assert membership.is_admin

        change_url = reverse("admin:companies_company_change", args=[company.pk])
        response = admin_client.get(change_url)
        assert response.status_code == 200

        response = admin_client.post(
            change_url,
            data={
                "id": company.id,
                "siret": company.siret,
                "kind": company.kind.value,
                "name": company.name,
                "phone": company.phone,
                "email": company.email,
                "companymembership_set-TOTAL_FORMS": "2",
                "companymembership_set-INITIAL_FORMS": "1",
                "companymembership_set-MIN_NUM_FORMS": "0",
                "companymembership_set-MAX_NUM_FORMS": "1000",
                "companymembership_set-0-id": membership.pk,
                "companymembership_set-0-company": company.pk,
                "companymembership_set-0-user": membership.user.pk,
                "companymembership_set-0-is_admin": "on",
                "companymembership_set-1-company": company.pk,
                "companymembership_set-1-user": employer.pk,
                "companymembership_set-1-is_admin": "on",
                "job_description_through-TOTAL_FORMS": "0",
                "job_description_through-INITIAL_FORMS": "0",
                "utils-pksupportremark-content_type-object_id-TOTAL_FORMS": 1,
                "utils-pksupportremark-content_type-object_id-INITIAL_FORMS": 0,
                "_continue": "Enregistrer+et+continuer+les+modifications",
            },
        )
        assertRedirects(response, change_url, fetch_redirect_response=False)
        response = admin_client.get(change_url)

        assert_set_admin_role__creation(employer, company, mailoutbox)


@freeze_time("2024-05-17T11:11:11+02:00")
def test_companies_export(admin_client, snapshot):
    company_1 = CompanyFactory(for_snapshot=True, created_by=ItouStaffFactory(for_snapshot=True))
    company_2 = CompanyFactory(for_snapshot=True, kind=CompanyKind.AI)

    with assertNumQueries(
        BASE_NUM_QUERIES
        + 1  # Load Django session
        + 1  # Load user
        + 2  # count companies in admin list
        + 1  # select companies and created_by relation
    ):
        response = admin_client.post(
            reverse("admin:companies_company_changelist"),
            {
                "action": "export",
                helpers.ACTION_CHECKBOX_NAME: [company_1.pk, company_2.pk],
            },
        )
        assert response.status_code == 200
        assert response["Content-Disposition"] == ("attachment; " 'filename="entreprises_2024-05-17_11-11-11.xlsx"')
        assert get_rows_from_streaming_response(response) == snapshot


class TestTransferCompanyData:
    CHOOSE_TARGET_TEXT = "Choisissez l’entreprise cible :"

    def test_transfer_button(self, client):
        company = CompanyFactory()
        transfer_url = reverse("admin:transfer_company_data", kwargs={"from_company_pk": company.pk})

        # Basic staff users without write access don't see the button
        admin_user = ItouStaffFactory()
        perms = Permission.objects.filter(codename="view_company")
        admin_user.user_permissions.add(*perms)
        client.force_login(admin_user)
        response = client.get(reverse("admin:companies_company_change", kwargs={"object_id": company.pk}))
        assertNotContains(response, transfer_url)

        # A superuser, the button appears
        # TODO(xfernandez): in a few weeks, show the buttons to user with change permission
        # perms = Permission.objects.filter(codename="change_company")
        # admin_user.user_permissions.add(*perms)
        admin_user.is_superuser = True
        admin_user.save(update_fields=("is_superuser",))
        response = client.get(reverse("admin:companies_company_change", kwargs={"object_id": company.pk}))
        assertContains(response, transfer_url)

    def test_transfer_without_change_permission(self, client):
        from_company = CompanyFactory()
        to_company = CompanyFactory()
        transfer_url_1 = reverse("admin:transfer_company_data", kwargs={"from_company_pk": from_company.pk})
        transfer_url_2 = reverse(
            "admin:transfer_company_data", kwargs={"from_company_pk": from_company.pk, "to_company_pk": to_company.pk}
        )

        admin_user = ItouStaffFactory()
        perms = Permission.objects.filter(codename="view_company")
        admin_user.user_permissions.add(*perms)
        client.force_login(admin_user)
        response = client.get(transfer_url_1)
        assert response.status_code == 403
        response = client.get(transfer_url_2)
        assert response.status_code == 403

    @pytest.mark.ignore_unknown_variable_template_error("has_view_permission", "subtitle")
    @freeze_time("2023-08-31 12:34:56")
    def test_transfer_data(self, admin_client, snapshot):
        job_application = JobApplicationFactory(with_approval=True)

        from_company = job_application.to_company
        to_company = CompanyFactory()

        transfer_url_1 = reverse("admin:transfer_company_data", kwargs={"from_company_pk": from_company.pk})
        transfer_url_2 = reverse(
            "admin:transfer_company_data", kwargs={"from_company_pk": from_company.pk, "to_company_pk": to_company.pk}
        )
        response = admin_client.get(transfer_url_1)
        assertContains(response, self.CHOOSE_TARGET_TEXT, html=True)
        # Select same company
        response = admin_client.post(transfer_url_1, data={"to_company": from_company.pk})
        assertContains(response, "L’entreprise cible doit être différente de celle d’origine", html=True)
        # Select valid target
        response = admin_client.post(transfer_url_1, data={"to_company": to_company.pk})
        assertRedirects(response, transfer_url_2, fetch_redirect_response=False)

        response = admin_client.get(transfer_url_2)
        assertContains(response, "Choisissez les objets à transférer")
        assertContains(response, str(job_application))

        response = admin_client.post(transfer_url_2, data={"fields_to_transfer": ["job_applications_received"]})
        assertRedirects(response, reverse("admin:companies_company_change", kwargs={"object_id": from_company.pk}))

        job_application.refresh_from_db()
        assert job_application.to_company == to_company
        assertMessages(
            response,
            [
                messages.Message(
                    messages.INFO, f"Transfert effectué avec succès de l’entreprise {from_company} vers {to_company}."
                ),
            ],
        )
        company_content_type = ContentType.objects.get_for_model(Company)
        to_user_remark = PkSupportRemark.objects.filter(
            content_type=company_content_type, object_id=to_company.pk
        ).first()
        from_user_remark = PkSupportRemark.objects.filter(
            content_type=company_content_type, object_id=from_company.pk
        ).first()
        assert to_user_remark.remark == from_user_remark.remark
        remark = to_user_remark.remark
        assert "Transfert du 2023-08-31 12:34:56 effectué par" in remark
        assert "Candidatures reçues" in remark

    @pytest.mark.ignore_unknown_variable_template_error("has_view_permission", "subtitle")
    @freeze_time("2023-08-31 12:34:56")
    def test_transfer_data_is_searchable_and_disable_from_company(self, admin_client, snapshot):
        job_application = JobApplicationFactory(with_approval=True)

        from_company = job_application.to_company
        assert from_company.is_searchable
        assert not from_company.block_job_applications
        assert not from_company.job_applications_blocked_at

        to_company = CompanyFactory(is_searchable=False)

        transfer_url = reverse(
            "admin:transfer_company_data", kwargs={"from_company_pk": from_company.pk, "to_company_pk": to_company.pk}
        )

        response = admin_client.get(transfer_url)
        assertContains(response, "Choisissez les objets à transférer")
        assertContains(response, str(job_application))

        response = admin_client.post(
            transfer_url,
            data={"fields_to_transfer": ["job_applications_received", "is_searchable"], "disable_from_company": True},
        )
        assertRedirects(response, reverse("admin:companies_company_change", kwargs={"object_id": from_company.pk}))

        job_application.refresh_from_db()
        assert job_application.to_company == to_company
        assertMessages(
            response,
            [
                messages.Message(
                    messages.INFO, f"Transfert effectué avec succès de l’entreprise {from_company} vers {to_company}."
                ),
            ],
        )

        # Check that from_company has been properly disable
        from_company.refresh_from_db()
        assert not from_company.is_searchable
        assert from_company.block_job_applications
        assert from_company.job_applications_blocked_at

        # and to_company should now be searchable
        to_company.refresh_from_db()
        assert to_company.is_searchable

        # Check support remark
        company_content_type = ContentType.objects.get_for_model(Company)
        to_user_remark = PkSupportRemark.objects.filter(
            content_type=company_content_type, object_id=to_company.pk
        ).first()
        from_user_remark = PkSupportRemark.objects.filter(
            content_type=company_content_type, object_id=from_company.pk
        ).first()
        assert to_user_remark.remark == from_user_remark.remark
        remark = to_user_remark.remark
        assert "Transfert du 2023-08-31 12:34:56 effectué par" in remark
        assert "Candidatures reçues" in remark
        assert f"Désactivation entreprise:\n  * companies.Company[{from_company.pk}]" in remark
        assert "Peut apparaître dans la recherche:\n  * is_searchable: False remplacé par True" in remark
