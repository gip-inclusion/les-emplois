import datetime

import pytest
from django.urls import reverse
from freezegun import freeze_time
from pytest_django.asserts import assertRedirects

from itou.companies.enums import CompanyKind
from itou.companies.models import Company
from itou.eligibility.models.geiq import GEIQEligibilityDiagnosis
from itou.eligibility.models.iae import AdministrativeCriteria, EligibilityDiagnosis
from itou.users.enums import UserKind
from tests.companies.factories import CompanyFactory
from tests.eligibility.admin_utils import build_geiq_diag_post_data, build_iae_diag_post_data
from tests.eligibility.factories import IAEEligibilityDiagnosisFactory
from tests.prescribers.factories import PrescriberOrganizationFactory
from tests.users.factories import EmployerFactory, ItouStaffFactory, JobSeekerFactory, PrescriberFactory


def test_selected_criteria_inline(admin_client):
    diagnosis = IAEEligibilityDiagnosisFactory(from_employer=True)
    diagnosis.administrative_criteria.add(AdministrativeCriteria.objects.certifiable().first())
    certifiable = diagnosis.selected_administrative_criteria.get()
    certifiable.certified = True
    certifiable.save()
    diagnosis.administrative_criteria.add(AdministrativeCriteria.objects.not_certifiable().first())
    not_certifiable = diagnosis.selected_administrative_criteria.exclude(pk=certifiable.pk).get()

    url = reverse("admin:eligibility_eligibilitydiagnosis_change", args=(diagnosis.pk,))
    post_data = {
        "author": diagnosis.author_id,
        "author_kind": diagnosis.author_kind,
        "job_seeker": diagnosis.job_seeker_id,
        "author_siae": diagnosis.author_siae_id,
        "selected_administrative_criteria-TOTAL_FORMS": "2",
        "selected_administrative_criteria-INITIAL_FORMS": "2",
        "selected_administrative_criteria-MIN_NUM_FORMS": "0",
        "selected_administrative_criteria-MAX_NUM_FORMS": "1000",
        "selected_administrative_criteria-0-id": certifiable.pk,
        "selected_administrative_criteria-0-eligibility_diagnosis": diagnosis.pk,
        "selected_administrative_criteria-1-id": not_certifiable.pk,
        "selected_administrative_criteria-1-eligibility_diagnosis": diagnosis.pk,
        "selected_administrative_criteria-__prefix__-id": "",
        "selected_administrative_criteria-__prefix__-eligibility_diagnosis": "1100350",
        "jobapplication_set-TOTAL_FORMS": "0",
        "jobapplication_set-INITIAL_FORMS": "0",
        "jobapplication_set-MIN_NUM_FORMS": "0",
        "jobapplication_set-MAX_NUM_FORMS": "0",
        "approval_set-TOTAL_FORMS": "0",
        "approval_set-INITIAL_FORMS": "0",
        "approval_set-MIN_NUM_FORMS": "0",
        "approval_set-MAX_NUM_FORMS": "0",
        "utils-pksupportremark-content_type-object_id-TOTAL_FORMS": "1",
        "utils-pksupportremark-content_type-object_id-INITIAL_FORMS": "0",
        "utils-pksupportremark-content_type-object_id-MIN_NUM_FORMS": "0",
        "utils-pksupportremark-content_type-object_id-MAX_NUM_FORMS": "1",
        "utils-pksupportremark-content_type-object_id-0-remark": "",
        "utils-pksupportremark-content_type-object_id-0-id": "",
        "utils-pksupportremark-content_type-object_id-__prefix__-remark": "",
        "utils-pksupportremark-content_type-object_id-__prefix__-id": "",
        "_save": "Enregistrer",
    }

    response = admin_client.post(url, data=post_data | {"selected_administrative_criteria-0-DELETE": "on"})
    assert response.status_code == 200
    assert response.context["errors"] == ["Impossible de supprimer un critère certifié"]
    diagnosis.refresh_from_db()
    assert diagnosis.administrative_criteria.count() == 2

    response = admin_client.post(url, data=post_data | {"selected_administrative_criteria-1-DELETE": "on"})
    assert response.status_code == 302  # it worked and we were redirected to the changelist
    diagnosis.refresh_from_db()
    assert diagnosis.administrative_criteria.count() == 1


@pytest.mark.parametrize("kind", ["iae", "geiq"])
class TestAdminForm:
    def build_post_data(self, kind, author, job_seeker, with_administrative_criteria=True):
        if kind == "iae":
            return build_iae_diag_post_data(author, job_seeker, with_administrative_criteria)
        return build_geiq_diag_post_data(author, job_seeker, with_administrative_criteria)

    def get_add_url(self, kind):
        if kind == "iae":
            return reverse("admin:eligibility_eligibilitydiagnosis_add")
        return reverse("admin:eligibility_geiqeligibilitydiagnosis_add")

    def get_list_url(self, kind):
        if kind == "iae":
            return reverse("admin:eligibility_eligibilitydiagnosis_changelist")
        return reverse("admin:eligibility_geiqeligibilitydiagnosis_changelist")

    def user_factory(self, kind, user_kind):
        if user_kind == UserKind.PRESCRIBER:
            return PrescriberFactory(membership=True, membership__organization__is_authorized=True)
        if kind == "iae":
            return EmployerFactory(with_company=True)
        return EmployerFactory(with_company=True, with_company__company__kind=CompanyKind.GEIQ)

    def get_diag_model(self, kind):
        if kind == "iae":
            return EligibilityDiagnosis
        return GEIQEligibilityDiagnosis

    def company_field_name(self, kind):
        if kind == "iae":
            return "author_siae"
        return "author_geiq"

    @freeze_time("2025-01-21")
    @pytest.mark.parametrize("user_kind", [UserKind.EMPLOYER, UserKind.PRESCRIBER])
    def test_add_eligibility_diagnostic(self, admin_client, kind, user_kind):
        author = self.user_factory(kind, user_kind)
        post_data = self.build_post_data(kind, author=author, job_seeker=JobSeekerFactory())
        response = admin_client.post(self.get_add_url(kind), data=post_data)
        assertRedirects(response, self.get_list_url(kind))

        diagnostic = self.get_diag_model(kind).objects.get()
        if author.kind == UserKind.PRESCRIBER or kind == "geiq":
            assert diagnostic.expires_at == datetime.date(2025, 7, 21)  # 6 months
        else:
            assert diagnostic.expires_at == datetime.date(2025, 4, 23)  # 92 days
        assert diagnostic.administrative_criteria.count() == 1

    def test_add_eligibility_diagnostic_no_criteria(self, admin_client, kind):
        author = PrescriberFactory(membership=True, membership__organization__is_authorized=True)
        post_data = self.build_post_data(kind, author, JobSeekerFactory(), with_administrative_criteria=False)

        response = admin_client.post(self.get_add_url(kind), data=post_data)
        assertRedirects(response, self.get_list_url(kind))

        diagnostic = self.get_diag_model(kind).objects.get()
        assert diagnostic.administrative_criteria.count() == 0

    def test_add_eligibility_diagnostic_bad_job_seeker(self, admin_client, kind):
        author = PrescriberFactory(membership=True, membership__organization__is_authorized=True)
        post_data = self.build_post_data(kind, author, PrescriberFactory(), with_administrative_criteria=False)

        response = admin_client.post(self.get_add_url(kind), data=post_data)

        assert response.status_code == 200
        assert response.context["errors"] == [["L'utilisateur doit être un candidat"]]
        assert not self.get_diag_model(kind).objects.exists()

    def test_add_eligibility_diagnostic_bad_author(self, admin_client, kind):
        author = ItouStaffFactory()
        post_data = self.build_post_data(kind, author, JobSeekerFactory(), with_administrative_criteria=False)
        post_data["author_kind"] = "prescriber"
        post_data["author_prescriber_organization"] = PrescriberOrganizationFactory().pk

        response = admin_client.post(self.get_add_url(kind), data=post_data)

        assert response.status_code == 200
        assert response.context["errors"] == [["Seul un prescripteur ou employeur peut être auteur d'un diagnostic."]]
        assert not self.get_diag_model(kind).objects.exists()

    def test_add_eligibility_diagnostic_bad_author_kind(self, admin_client, kind):
        author = PrescriberFactory(membership=True, membership__organization__is_authorized=True)
        post_data = self.build_post_data(kind, author, JobSeekerFactory(), with_administrative_criteria=False)
        post_data["author_kind"] = "geiq" if kind == "iae" else "employer"

        response = admin_client.post(self.get_add_url(kind), data=post_data)

        assert response.status_code == 200
        assert response.context["errors"] == [
            [f"Un diagnostic d'éligibilité {kind.upper()} ne peut pas avoir ce type d'auteur."]
        ]
        assert not self.get_diag_model(kind).objects.exists()

    def test_add_eligibility_diagnostic_bad_prescriber(self, admin_client, kind):
        author = PrescriberFactory(membership=True)
        post_data = self.build_post_data(kind, author, JobSeekerFactory(), with_administrative_criteria=False)
        author.prescribermembership_set.all().delete()
        post_data["author_kind"] = "employer" if kind == "iae" else "geiq"

        response = admin_client.post(self.get_add_url(kind), data=post_data)
        assert response.status_code == 200
        assert response.context["errors"] == [
            ["Le type ne correspond pas à l'auteur."],
            [
                "Une organisation prescriptrice habilitée est obligatoire pour cet auteur.",
                "L'auteur n'appartient pas à cette organisation.",
            ],
        ]
        assert not self.get_diag_model(kind).objects.exists()

    def test_add_eligibility_diagnostic_employer_bad_author_kind(self, admin_client, kind):
        author = self.user_factory(kind, UserKind.EMPLOYER)
        post_data = self.build_post_data(kind, author, JobSeekerFactory(), with_administrative_criteria=False)
        post_data["author_kind"] = "prescriber"

        response = admin_client.post(self.get_add_url(kind), data=post_data)
        assert response.status_code == 200
        assert response.context["errors"] == [["Le type ne correspond pas à l'auteur."]]
        assert not self.get_diag_model(kind).objects.exists()

    def test_add_eligibility_diagnostic_employer_bad_company_kind(self, admin_client, kind):
        author = EmployerFactory(with_company=True)
        post_data = self.build_post_data(kind, author, JobSeekerFactory(), with_administrative_criteria=False)
        Company.objects.filter(pk=post_data[self.company_field_name(kind)]).update(kind=CompanyKind.EA)  # Not a siae
        response = admin_client.post(self.get_add_url(kind), data=post_data)
        assert response.status_code == 200
        company_name = "SIAE" if kind == "iae" else "entreprise GEIQ"
        assert response.context["errors"] == [
            [
                "Sélectionnez un choix valide. Ce choix ne fait pas partie de ceux disponibles.",
                f"Une {company_name} est obligatoire pour cet auteur.",
            ],
        ]
        assert not self.get_diag_model(kind).objects.exists()

    def test_add_eligibility_diagnostic_employer_not_a_member(self, admin_client, kind):
        author = self.user_factory(kind, UserKind.EMPLOYER)
        post_data = self.build_post_data(kind, author, JobSeekerFactory(), with_administrative_criteria=False)
        author.companymembership_set.all().delete()

        response = admin_client.post(self.get_add_url(kind), data=post_data)
        assert response.status_code == 200
        assert response.context["errors"] == [["L'auteur n'appartient pas à cette structure."]]

    @pytest.mark.parametrize("user_kind", [UserKind.EMPLOYER, UserKind.PRESCRIBER])
    def test_add_eligibility_not_both_org_and_company(self, admin_client, kind, user_kind):
        author = self.user_factory(kind, user_kind)
        post_data = self.build_post_data(kind, author=author, job_seeker=JobSeekerFactory())
        if user_kind == UserKind.EMPLOYER:
            post_data["author_prescriber_organization"] = PrescriberOrganizationFactory().pk
        else:
            post_data[self.company_field_name(kind)] = CompanyFactory(
                kind=CompanyKind.GEIQ if kind == "geiq" else CompanyKind.EI
            ).pk

        response = admin_client.post(self.get_add_url(kind), data=post_data)
        assert response.status_code == 200
        expected_errors = [["Vous ne pouvez pas saisir une entreprise et une organisation prescriptrice."]]
        if kind == "geiq":
            # Additional error thanks to the db constraint
            expected_errors[0].append("Le diagnostic d'éligibilité GEIQ ne peut avoir 2 structures pour auteur")
        assert response.context["errors"] == expected_errors
        assert not self.get_diag_model(kind).objects.exists()
