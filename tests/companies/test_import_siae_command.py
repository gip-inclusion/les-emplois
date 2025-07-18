import collections
import datetime
import shutil
import uuid
from pathlib import Path

import pandas as pd
import pytest
from django.core.management import call_command
from django.test import override_settings
from django.urls import reverse
from freezegun import freeze_time
from pytest_django.asserts import assertNumQueries

from itou.companies.enums import CompanyKind
from itou.companies.management.commands._import_siae.convention import get_creatable_conventions
from itou.companies.management.commands._import_siae.financial_annex import get_creatable_and_deletable_afs
from itou.companies.management.commands._import_siae.siae import (
    check_whether_signup_is_possible_for_all_siaes,
    create_new_siaes,
)
from itou.companies.management.commands._import_siae.utils import anonymize_fluxiae_df, could_siae_be_deleted
from itou.companies.management.commands._import_siae.vue_af import (
    Convention,
    get_conventions_by_siae_key,
    get_vue_af_df,
)
from itou.companies.management.commands._import_siae.vue_structure import (
    get_siret_to_siae_row,
    get_vue_structure_df,
)
from itou.companies.models import Company
from tests.approvals.factories import ApprovalFactory, ProlongationRequestFactory
from tests.companies.factories import CompanyFactory, CompanyWith2MembershipsFactory, SiaeConventionFactory
from tests.eligibility.factories import IAEEligibilityDiagnosisFactory
from tests.job_applications.factories import JobApplicationFactory
from tests.utils.test import normalize_fields_history


class TestImportSiaeManagementCommands:
    @pytest.fixture(autouse=True)
    def setup(self, tmp_path, settings):
        settings.ASP_FLUX_IAE_DIR = tmp_path

        # Beware : fluxIAE_Structure_22022022_112211.csv.gz ends with .gz but is compressed with pkzip.
        # Since it happened once, and the code now allows it, we also want to test it.
        files = [
            x for x in Path(settings.APPS_DIR).joinpath("./companies/fixtures").glob("fluxIAE_*.csv.gz") if x.is_file()
        ]
        for file in files:
            shutil.copy(file, tmp_path)

    @freeze_time("2024-07-09")
    def test_get_conventions_by_siae_key(self):
        data = [
            (1, "ACI", False, datetime.date(2024, 12, 31)),
            (1, "ACI", True, datetime.date(2024, 9, 30)),
            (2, "AI", False, datetime.date(2024, 8, 31)),
            (2, "AI", False, datetime.date(2024, 7, 31)),
            (3, "AI", False, datetime.date(2024, 7, 31)),
        ]
        # This is missing a bunch of columns, but only those are relevant for get_conventions_by_siae_key
        vue_af_df_simplified = pd.DataFrame(data, columns=["asp_id", "kind", "has_active_state", "end_at"])
        assert get_conventions_by_siae_key(vue_af_df_simplified) == {
            (1, "ACI"): Convention(True, datetime.date(2024, 9, 30)),
            (2, "AI"): Convention(False, datetime.date(2024, 8, 31)),
            (3, "AI"): Convention(False, datetime.date(2024, 7, 31)),
        }

    def test_uncreatable_conventions_for_active_siae_with_active_convention(self):
        siret_to_siae_row = get_siret_to_siae_row(get_vue_structure_df())
        conventions_by_siae_key = get_conventions_by_siae_key(get_vue_af_df())

        company = CompanyFactory(source=Company.SOURCE_ASP)
        assert company.is_active
        assert not get_creatable_conventions(siret_to_siae_row, conventions_by_siae_key)

    def test_uncreatable_conventions_when_convention_exists_for_asp_id_and_kind(self):
        # siae without convention, but a convention already exists for this
        # asp_id and this kind. ACHTUNG: asp_id is collected from vue_structure_df :D
        SIRET = "26290411300061"
        ASP_ID = 190

        siret_to_siae_row = get_siret_to_siae_row(get_vue_structure_df())
        conventions_by_siae_key = get_conventions_by_siae_key(get_vue_af_df())

        company = CompanyFactory(source=Company.SOURCE_ASP, siret=SIRET, convention=None)
        SiaeConventionFactory(kind=company.kind, asp_id=ASP_ID)

        with pytest.raises(AssertionError):
            get_creatable_conventions(siret_to_siae_row, conventions_by_siae_key)

    def test_creatable_conventions_for_active_siae_where_siret_equals_siret_signature(self):
        SIRET = SIRET_SIGNATURE = "21540323900019"
        ASP_ID = 112
        CompanyFactory(source=Company.SOURCE_ASP, siret=SIRET, kind=CompanyKind.ACI, convention=None)

        with freeze_time("2022-10-10"):
            results = get_creatable_conventions(
                get_siret_to_siae_row(get_vue_structure_df()),
                get_conventions_by_siae_key(get_vue_af_df()),
            )
        assert len(results) == 1

        convention, company = results[0]
        assert (
            convention.asp_id,
            convention.kind,
            convention.siret_signature,
            convention.is_active,
            convention.deactivated_at,
        ) == (ASP_ID, company.kind, SIRET_SIGNATURE, True, None)
        assert (company.source, company.siret, company.kind) == (Company.SOURCE_ASP, SIRET, CompanyKind.ACI)

    def test_creatable_conventions_for_active_siae_where_siret_not_equals_siret_signature(self):
        SIRET = "34950857200055"
        SIRET_SIGNATURE = "34950857200048"
        ASP_ID = 768
        CompanyFactory(source=Company.SOURCE_ASP, siret=SIRET, kind=CompanyKind.AI, convention=None)

        with freeze_time("2022-10-10"):
            results = get_creatable_conventions(
                get_siret_to_siae_row(get_vue_structure_df()),
                get_conventions_by_siae_key(get_vue_af_df()),
            )
        assert len(results) == 1

        convention, company = results[0]
        assert (
            convention.asp_id,
            convention.kind,
            convention.siret_signature,
            convention.is_active,
            convention.deactivated_at,
        ) == (ASP_ID, company.kind, SIRET_SIGNATURE, True, None)
        assert (company.source, company.siret, company.kind) == (Company.SOURCE_ASP, SIRET, CompanyKind.AI)

    def test_creatable_conventions_inactive_siae(self):
        SIRET = SIRET_SIGNATURE = "41294123900011"
        ASP_ID = 1780
        CompanyFactory(source=Company.SOURCE_ASP, siret=SIRET, kind=CompanyKind.ACI, convention=None)

        conventions = get_creatable_conventions(
            get_siret_to_siae_row(get_vue_structure_df()),
            get_conventions_by_siae_key(get_vue_af_df()),
        )
        assert len(conventions) == 1

        convention, company = conventions[0]
        assert (
            convention.asp_id,
            convention.kind,
            convention.siret_signature,
            convention.is_active,
            convention.deactivated_at,
        ) == (ASP_ID, company.kind, SIRET_SIGNATURE, False, datetime.datetime(2020, 12, 31, tzinfo=datetime.UTC))
        assert (company.source, company.siret, company.kind) == (Company.SOURCE_ASP, SIRET, CompanyKind.ACI)

    def test_get_creatable_and_deletable_afs(self):
        af_number_to_row = {row.number: row for _, row in get_vue_af_df().iterrows()}

        existing_convention = SiaeConventionFactory(kind=CompanyKind.ACI, asp_id=2855)
        # Get AF created by SiaeConventionFactory
        deletable_af = existing_convention.financial_annexes.first()
        to_create, to_delete = get_creatable_and_deletable_afs(af_number_to_row)
        assert to_delete == [deletable_af]
        # This list comes from the fixture file
        assert sorted((af.number, af.start_at.isoformat(), af.end_at.isoformat()) for af in to_create) == [
            ("ACI972180023A0M0", "2018-07-01", "2018-12-31"),
            ("ACI972180023A0M1", "2018-07-01", "2018-12-31"),
            ("ACI972180024A0M0", "2018-07-01", "2018-12-31"),
            ("ACI972180024A0M1", "2018-07-01", "2018-12-31"),
            ("ACI972190114A0M0", "2019-01-01", "2019-12-31"),
            ("ACI972190114A0M1", "2019-01-01", "2019-12-31"),
            ("ACI972190114A1M0", "2020-01-01", "2020-12-31"),
            ("ACI972190114A1M1", "2020-01-01", "2020-12-31"),
            ("ACI972190115A0M0", "2019-05-01", "2019-12-31"),
            ("ACI972190115A0M1", "2019-05-01", "2019-12-31"),
            ("ACI972190115A1M0", "2020-01-01", "2020-12-31"),
            ("ACI972190115A1M1", "2020-01-01", "2020-12-31"),
            ("ACI972190115A2M0", "2022-01-01", "2022-12-31"),
            ("ACI972190115A2M1", "2022-01-01", "2022-12-31"),
            ("ACI972190115A2M2", "2021-01-01", "2021-12-31"),
            ("ACI972190115A2M3", "2021-01-01", "2021-12-31"),
            ("ACI972200037A0M0", "2020-01-01", "2020-12-31"),
            ("ACI972200038A0M0", "2020-01-01", "2020-12-31"),
        ]

    def test_check_signup_possible_for_a_siae_without_members_but_with_auth_email(self):
        CompanyFactory(auth_email="tadaaa")
        with assertNumQueries(1):
            assert check_whether_signup_is_possible_for_all_siaes() == 0

    def test_check_signup_possible_for_a_siae_without_members_nor_auth_email(self):
        CompanyFactory(auth_email="")
        with assertNumQueries(1):
            assert check_whether_signup_is_possible_for_all_siaes() == 1

    def test_check_signup_possible_for_a_siae_with_members_but_no_auth_email_case_one(self):
        CompanyWith2MembershipsFactory(
            auth_email="",
            membership1__is_active=False,
            membership1__user__is_active=False,
        )
        with assertNumQueries(1):
            assert check_whether_signup_is_possible_for_all_siaes() == 0

    def test_check_signup_possible_for_a_siae_with_members_but_no_auth_email_case_two(self):
        CompanyWith2MembershipsFactory(
            auth_email="",
            membership1__is_active=False,
            membership1__user__is_active=False,
            membership2__is_active=False,
            membership2__user__is_active=False,
        )
        with assertNumQueries(1):
            assert check_whether_signup_is_possible_for_all_siaes() == 1

    def test_check_signup_possible_for_a_siae_with_members_but_no_auth_email_case_three(self):
        CompanyWith2MembershipsFactory(auth_email="")
        with assertNumQueries(1):
            assert check_whether_signup_is_possible_for_all_siaes() == 0

    def test_activate_your_account_email_for_a_siae_without_members_but_with_auth_email(
        self, django_capture_on_commit_callbacks, mailoutbox
    ):
        with freeze_time("2022-10-10"), django_capture_on_commit_callbacks(execute=True) as commit_callbacks:
            create_new_siaes(
                get_siret_to_siae_row(get_vue_structure_df()),
                get_conventions_by_siae_key(get_vue_af_df()),
            )
        assert len(commit_callbacks) == 6
        assert len(mailoutbox) == 6
        assert reverse("signup:company_select") in mailoutbox[0].body
        assert collections.Counter(mail.subject for mail in mailoutbox) == collections.Counter(
            f"[DEV] Activez le compte de votre {kind} {name} sur les emplois de l'inclusion"
            for (kind, name) in Company.objects.values_list("kind", "name")
        )

    def test_create_siae_raise_if_siret_mismatch(self, django_capture_on_commit_callbacks):
        siret_to_siae = get_siret_to_siae_row(get_vue_structure_df())

        with freeze_time("2022-10-10"), django_capture_on_commit_callbacks(execute=True):
            call_command("import_siae", wet_run=True)
        assert Company.objects.count() == len(siret_to_siae)

        # Now let's change a company SIRET on the ASP side.
        company = Company.objects.first()
        new_siret = f"{company.siren}11111"
        siret_to_siae[new_siret] = siret_to_siae[company.siret]
        siret_to_siae[new_siret]["siret"] = new_siret
        siret_to_siae[new_siret]["siret_signature"] = new_siret
        del siret_to_siae[company.siret]

        # It should raise an error message and break.
        with freeze_time("2022-10-10"), django_capture_on_commit_callbacks(execute=True):
            error_message = f"SIRET mismatch: existing_siae.siret='{company.siret}', row.siret='{new_siret}'"
            with pytest.raises(AssertionError, match=error_message):
                create_new_siaes(siret_to_siae, conventions_by_siae_key=get_conventions_by_siae_key(get_vue_af_df()))
        assert not Company.objects.filter(siret=new_siret).exists()

    def test_update_siret_and_auth_email_of_existing_siaes_when_siret_changes(self, monkeypatch):
        clever_user_id = f"user_{uuid.uuid4()}"
        company = CompanyFactory(
            source=Company.SOURCE_ASP,
            siret="21540323900000",
            kind=CompanyKind.ACI,
            convention=SiaeConventionFactory(kind=CompanyKind.ACI, asp_id=112, siret_signature="21540323900000"),
        )

        monkeypatch.setenv("CC_USER_ID", clever_user_id)
        with freeze_time("2022-10-10"):
            call_command("import_siae", wet_run=True)
        company.refresh_from_db()
        assert company.siret == "21540323900019"
        assert normalize_fields_history(company.fields_history) == [
            {
                "_context": {"user": clever_user_id, "run_uid": "[RUN UID]"},
                "_timestamp": "[TIMESTAMP]",
                "before": {"siret": "21540323900000"},
                "after": {"siret": "21540323900019"},
            }
        ]


@override_settings(METABASE_HASH_SALT="foobar2000")
def test_hashed_approval_number():
    df = pd.DataFrame(data={"salarie_agrement": ["999992012369", None, ""]})
    anonymize_fluxiae_df(df)
    assert df.hash_numéro_pass_iae[0] == "314b2d285803a46c89e09ba9ad4e23a52f2e823ad28343cdff15be0cb03fee4a"
    assert df.hash_numéro_pass_iae[1] == "8e728c4578281ea0b6a7817e50a0f6d50c995c27f02dd359d67427ac3d86e019"
    assert df.hash_numéro_pass_iae[2] == "6cc868860cee823f0ffe0b3498bb4ebda51baa1b7858e2022f6590b0bd86c31c"
    assert "salarie_agrement" not in df


class TestCouldSiaeBeDeleted:
    def test_with_eligibility_diagnosis(self):
        # Check that eligibility diagnoses made by SIAE are blocking its deletion

        # No eligibility diagnosis linked
        company = CompanyWith2MembershipsFactory()
        assert could_siae_be_deleted(company)

        # An eligibility diagnosis without related approval
        IAEEligibilityDiagnosisFactory(from_employer=True, author_siae=company, author=company.members.first())
        assert could_siae_be_deleted(company)

        # Approval with eligibility diagnosis authored by SIAE
        ApprovalFactory(with_diagnosis_from_employer=True, eligibility_diagnosis__author_siae=company)
        assert not could_siae_be_deleted(company)

    def test_with_job_app(self):
        company = JobApplicationFactory().to_company
        assert not could_siae_be_deleted(company)

    def test_transferred_job_apps(self):
        company = CompanyFactory()
        JobApplicationFactory(transferred_from=company)
        assert could_siae_be_deleted(company) is False

    def test_sent_job_apps(self):
        job_app = JobApplicationFactory(sent_by_another_employer=True)
        assert could_siae_be_deleted(job_app.sender_company) is False

    def test_prolongation_request(self):
        prolongation_request = ProlongationRequestFactory()
        assert could_siae_be_deleted(prolongation_request.declared_by_siae) is False
