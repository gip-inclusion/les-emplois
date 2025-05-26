from zoneinfo import ZoneInfo

import pytest
from django.conf import settings
from django.contrib import messages
from django.contrib.admin import helpers
from django.contrib.auth.models import Permission
from django.contrib.contenttypes.models import ContentType
from django.urls import reverse
from freezegun import freeze_time
from pytest_django.asserts import assertContains, assertMessages, assertNotContains, assertNumQueries, assertRedirects

from itou.companies.enums import CompanyKind
from itou.companies.models import Company, CompanyMembership
from itou.utils.models import PkSupportRemark
from tests.common_apps.organizations.tests import (
    assert_set_admin_role_creation,
    assert_set_admin_role_removal,
)
from tests.companies.factories import CompanyFactory, JobDescriptionFactory
from tests.invitations.factories import EmployerInvitationFactory
from tests.job_applications.factories import JobApplicationFactory
from tests.jobs.factories import create_test_romes_and_appellations
from tests.users.factories import EmployerFactory, ItouStaffFactory
from tests.utils.test import (
    BASE_NUM_QUERIES,
    assertSnapshotQueries,
    get_rows_from_streaming_response,
    parse_response_to_soup,
    pretty_indented,
)


class TestCompanyAdmin:
    def test_display_for_new_company(self, admin_client, snapshot):
        """Does not search approvals with company IS NULL"""
        with assertSnapshotQueries(snapshot(name="SQL queries")):
            response = admin_client.get(reverse("admin:companies_company_add"))
        response = parse_response_to_soup(response, selector=".field-approvals_list")
        assert pretty_indented(response) == snapshot(name="approvals list")

    def test_remove_last_admin_status(self, admin_client, mailoutbox):
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
                "companymembership_set-TOTAL_FORMS": "1",
                "companymembership_set-INITIAL_FORMS": "1",
                "companymembership_set-MIN_NUM_FORMS": "0",
                "companymembership_set-MAX_NUM_FORMS": "1000",
                "companymembership_set-0-id": membership.pk,
                "companymembership_set-0-company": company.pk,
                "companymembership_set-0-user": membership.user.pk,
                "companymembership_set-0-is_active": "on",
                # companymembership_set-0-is_admin is absent
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

        assert_set_admin_role_removal(membership.user, company, mailoutbox)

    def test_deactivate_admin(self, admin_client, caplog, mailoutbox):
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
                "companymembership_set-TOTAL_FORMS": "1",
                "companymembership_set-INITIAL_FORMS": "1",
                "companymembership_set-MIN_NUM_FORMS": "0",
                "companymembership_set-MAX_NUM_FORMS": "1000",
                "companymembership_set-0-id": membership.pk,
                "companymembership_set-0-company": company.pk,
                "companymembership_set-0-user": membership.user.pk,
                "companymembership_set-0-is_admin": "on",
                # companymembership_set-0-is_active is absent
                "job_description_through-TOTAL_FORMS": "0",
                "job_description_through-INITIAL_FORMS": "0",
                "utils-pksupportremark-content_type-object_id-TOTAL_FORMS": 1,
                "utils-pksupportremark-content_type-object_id-INITIAL_FORMS": 0,
                "_continue": "Enregistrer+et+continuer+les+modifications",
            },
        )
        assertRedirects(response, change_url, fetch_redirect_response=False)
        response = admin_client.get(change_url)

        assert membership.user not in company.active_admin_members
        [email] = mailoutbox
        assert f"[DEV] [Désactivation] Vous n'êtes plus membre de {company.display_name}" == email.subject
        assert "Un administrateur vous a retiré d'une structure" in email.body
        assert email.to == [membership.user.email]
        assert (
            f"User {admin_client.session['_auth_user_id']} deactivated companies.CompanyMembership "
            f"of organization_id={company.pk} for user_id={membership.user_id} is_admin=True."
        ) in caplog.messages

    def test_add_admin(self, admin_client, caplog, mailoutbox):
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
                "companymembership_set-0-is_active": "on",
                "companymembership_set-1-company": company.pk,
                "companymembership_set-1-user": employer.pk,
                "companymembership_set-1-is_admin": "on",
                "companymembership_set-1-is_active": "on",
                "job_description_through-TOTAL_FORMS": "0",
                "job_description_through-INITIAL_FORMS": "0",
                "utils-pksupportremark-content_type-object_id-TOTAL_FORMS": 1,
                "utils-pksupportremark-content_type-object_id-INITIAL_FORMS": 0,
                "_continue": "Enregistrer+et+continuer+les+modifications",
            },
        )
        assertRedirects(response, change_url, fetch_redirect_response=False)
        response = admin_client.get(change_url)

        assert_set_admin_role_creation(employer, company, mailoutbox)
        assert (
            f"Creating companies.CompanyMembership of organization_id={company.pk} "
            f"for user_id={employer.pk} is_admin=True."
        ) in caplog.messages


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
        assert response["Content-Disposition"] == ('attachment; filename="entreprises_2024-05-17_11-11-11.xlsx"')
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

        # With change permission, the button appears
        perms = Permission.objects.filter(codename="change_company")
        admin_user.user_permissions.add(*perms)
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

    @freeze_time("2023-08-31 12:34:56")
    def test_transfer_data_is_searchable_and_disable_from_company(self, admin_client, snapshot):
        job_application = JobApplicationFactory(with_approval=True)

        from_company = job_application.to_company
        assert from_company.is_searchable
        assert not from_company.block_job_applications
        assert not from_company.job_applications_blocked_at
        assert from_company.memberships.filter(is_active=True).count() == 1
        EmployerInvitationFactory(company=from_company)

        to_company = CompanyFactory(is_searchable=False)

        transfer_url = reverse(
            "admin:transfer_company_data", kwargs={"from_company_pk": from_company.pk, "to_company_pk": to_company.pk}
        )

        response = admin_client.get(transfer_url)
        assertContains(response, "Choisissez les objets à transférer")
        assertContains(response, str(job_application))

        response = admin_client.post(
            transfer_url,
            data={
                "fields_to_transfer": ["job_applications_received", "invitations", "is_searchable"],
                "disable_from_company": True,
            },
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

        # Check that from_company has been properly disabled and that the memberships have been disabled
        from_company.refresh_from_db()
        assert not from_company.is_searchable
        assert from_company.block_job_applications
        assert from_company.job_applications_blocked_at
        assert from_company.memberships.filter(is_active=True).count() == 0

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
        assert (
            f"Désactivation entreprise avec désactivation des membres:\n  * companies.Company[{from_company.pk}]"
            in remark
        )
        assert "Peut apparaître dans la recherche:\n  * is_searchable: False remplacé par True" in remark

    @pytest.mark.parametrize("field", {"is_admin", "is_active"})
    @pytest.mark.parametrize(
        "value_in_from_company,value_in_to_company,expected",
        [
            (None, False, False),
            (False, None, False),
            (None, True, True),
            (True, None, True),
            (False, False, False),
            (True, False, True),
            (False, True, True),
            (True, True, True),
        ],
    )
    def test_transfer_data_memberships(
        self, admin_client, field, value_in_from_company, value_in_to_company, expected
    ):
        user = EmployerFactory()
        default_args = {"user": user, "is_active": False, "is_admin": False}
        from_company = CompanyFactory(with_membership=False)
        if value_in_from_company is not None:
            CompanyMembership(company=from_company, **{**default_args, field: value_in_from_company}).save()

        to_company = CompanyFactory(with_membership=False)
        if value_in_to_company is not None:
            CompanyMembership(company=to_company, **{**default_args, field: value_in_to_company}).save()

        transfer_url = reverse(
            "admin:transfer_company_data", kwargs={"from_company_pk": from_company.pk, "to_company_pk": to_company.pk}
        )

        response = admin_client.get(transfer_url)
        assertContains(response, "Choisissez les objets à transférer")

        if value_in_from_company is not None:
            assertContains(response, str(from_company.memberships.get(user=user)))

            response = admin_client.post(
                transfer_url,
                data={"fields_to_transfer": ["memberships"], "disable_from_company": False},
            )
            assertRedirects(response, reverse("admin:companies_company_change", kwargs={"object_id": from_company.pk}))
            assertMessages(
                response,
                [
                    messages.Message(
                        messages.INFO,
                        f"Transfert effectué avec succès de l’entreprise {from_company} vers {to_company}.",
                    ),
                ],
            )

        from_company.refresh_from_db()
        to_company.refresh_from_db()

        if value_in_to_company is None or value_in_from_company is None:
            # Real transfer, membership in from_company is moved
            assert from_company.memberships.count() == 0
        else:
            assert from_company.memberships.count() == 1
        assert to_company.memberships.count() == 1
        assert getattr(to_company.memberships.first(), field) is expected


class TestJobDescriptionAdmin:
    TZ = ZoneInfo(settings.TIME_ZONE)

    def _format_date(self, dt):
        return dt.astimezone(self.TZ).date() if dt else ""

    def _format_time(self, dt):
        return dt.astimezone(self.TZ).time() if dt else ""

    def _get_job_description_post_data(self, job_description):
        post_data = {
            "appellation": job_description.appellation.pk,
            "company": job_description.company.pk,
            "created_at_0": self._format_date(job_description.created_at),
            "created_at_1": self._format_time(job_description.created_at),
            "initial-created_at_0": self._format_date(job_description.created_at),
            "initial-created_at_1": self._format_time(job_description.created_at),
            "last_employer_update_at_0": self._format_date(job_description.last_employer_update_at),
            "last_employer_update_at_1": self._format_time(job_description.last_employer_update_at),
            "custom_name": job_description.custom_name or "",
            "description": job_description.description or "",
            "ui_rank": job_description.ui_rank,
            "contract_type": job_description.contract_type,
            "other_contract_type": job_description.other_contract_type or "",
            "contract_nature": job_description.contract_nature or "",
            "location": job_description.location.pk if job_description.location else "",
            "hours_per_week": job_description.hours_per_week or "",
            "open_positions": job_description.open_positions or "",
            "profile_description": job_description.profile_description or "",
            "market_context_description": job_description.market_context_description or "",
            "creation_source": job_description.creation_source,
            "_continue": "Enregistrer et continuer les modifications",
        }

        if job_description.is_resume_mandatory:
            post_data["is_resume_mandatory"] = "on"

        if job_description.is_qpv_mandatory:
            post_data["is_qpv_mandatory"] = "on"

        return post_data

    @pytest.mark.parametrize("is_active", [True, False])
    def test_edition_does_not_postpone_last_employer_update_at(self, is_active, admin_client):
        create_test_romes_and_appellations(("N1101", "N1105", "N1103", "N4105"))
        job_description = JobDescriptionFactory(is_active=is_active)
        last_employer_update_at = job_description.last_employer_update_at

        change_url = reverse("admin:companies_jobdescription_change", args=[job_description.pk])
        admin_client.post(change_url, data=self._get_job_description_post_data(job_description))

        job_description.refresh_from_db()
        assert job_description.last_employer_update_at == last_employer_update_at
