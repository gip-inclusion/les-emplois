import collections
import datetime
import importlib
import os
import shutil
import tempfile
import unittest
from pathlib import Path
from unittest import mock

import pandas as pd
import pytest
from django.conf import settings
from django.core import mail
from django.test import TransactionTestCase, override_settings
from django.urls import reverse
from freezegun import freeze_time

from itou.companies.enums import CompanyKind
from itou.companies.management.commands import import_siae
from itou.companies.management.commands._import_siae.utils import anonymize_fluxiae_df, could_siae_be_deleted
from itou.companies.management.commands._import_siae.vue_af import (
    get_active_siae_keys,
    get_af_number_to_row,
    get_vue_af_df,
)
from itou.companies.management.commands._import_siae.vue_structure import (
    get_siret_to_asp_id,
    get_siret_to_siae_row,
    get_vue_structure_df,
)
from itou.companies.models import Company
from tests.approvals.factories import ApprovalFactory
from tests.companies.factories import CompanyFactory, CompanyWith2MembershipsFactory, SiaeConventionFactory
from tests.eligibility.factories import EligibilityDiagnosisMadeBySiaeFactory


@unittest.skipUnless(
    os.getenv("CI", "False"), "Slow and scarcely updated management command, no need for constant testing!"
)
@freeze_time("2022-10-10")
class ImportSiaeManagementCommandsTest(TransactionTestCase):
    path_source = "./companies/fixtures"
    app_dir_path = Path(settings.APPS_DIR)
    mod = None

    @classmethod
    def setUpClass(cls):
        """We need to setup fake files before loading any `import_siae` related script,
        since it does rely on dynamic file loading upon startup (!)
        """
        super().setUpClass()
        path_dest = tempfile.mkdtemp()
        cls.addClassCleanup(shutil.rmtree, path_dest)
        data_dir = Path(path_dest) / "data"
        data_dir.mkdir()
        data_dir_mock = mock.patch("itou.companies.management.commands._import_siae.utils.CURRENT_DIR", data_dir)
        data_dir_mock.start()
        cls.addClassCleanup(data_dir_mock.stop)

        # Beware : fluxIAE_Structure_22022022_112211.csv.gz ends with .gz but is compressed with pkzip.
        # Since it happened once, and the code now allows it, we also want to test it.
        files = [x for x in cls.app_dir_path.joinpath(cls.path_source).glob("fluxIAE_*.csv.gz") if x.is_file()]
        for file in files:
            shutil.copy(file, data_dir)

        cls.mod = importlib.import_module("itou.companies.management.commands._import_siae.convention")

    @classmethod
    def tearDownClass(cls):
        super().tearDownClass()
        cls.mod = None

    def test_uncreatable_conventions_for_active_siae_with_active_convention(self):
        vue_structure_df = get_vue_structure_df()
        siret_to_siae_row = get_siret_to_siae_row(vue_structure_df)
        siret_to_asp_id = get_siret_to_asp_id(vue_structure_df)
        vue_af_df = get_vue_af_df()
        active_siae_keys = get_active_siae_keys(vue_af_df)

        company = CompanyFactory(source=Company.SOURCE_ASP)
        assert company.is_active
        assert not self.mod.get_creatable_conventions(vue_af_df, siret_to_asp_id, siret_to_siae_row, active_siae_keys)

    def test_uncreatable_conventions_when_convention_exists_for_asp_id_and_kind(self):
        # siae without convention, but a convention already exists for this
        # asp_id and this kind. ACHTUNG: asp_id is collected from vue_structure_df :D
        SIRET = "26290411300061"
        ASP_ID = 190

        vue_structure_df = get_vue_structure_df()
        siret_to_siae_row = get_siret_to_siae_row(vue_structure_df)
        siret_to_asp_id = get_siret_to_asp_id(vue_structure_df)
        vue_af_df = get_vue_af_df()
        active_siae_keys = get_active_siae_keys(vue_af_df)

        company = CompanyFactory(source=Company.SOURCE_ASP, siret=SIRET, convention=None)
        SiaeConventionFactory(kind=company.kind, asp_id=ASP_ID)

        with pytest.raises(AssertionError):
            self.mod.get_creatable_conventions(vue_af_df, siret_to_asp_id, siret_to_siae_row, active_siae_keys)

    def test_creatable_conventions_for_active_siae_where_siret_equals_siret_signature(self):
        SIRET = SIRET_SIGNATURE = "21540323900019"
        ASP_ID = 112

        vue_structure_df = get_vue_structure_df()
        siret_to_siae_row = get_siret_to_siae_row(vue_structure_df)
        siret_to_asp_id = get_siret_to_asp_id(vue_structure_df)
        vue_af_df = get_vue_af_df()
        active_siae_keys = get_active_siae_keys(vue_af_df)

        company = CompanyFactory(source=Company.SOURCE_ASP, siret=SIRET, kind=CompanyKind.ACI, convention=None)
        results = self.mod.get_creatable_conventions(vue_af_df, siret_to_asp_id, siret_to_siae_row, active_siae_keys)

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

        vue_structure_df = get_vue_structure_df()
        siret_to_siae_row = get_siret_to_siae_row(vue_structure_df)
        siret_to_asp_id = get_siret_to_asp_id(vue_structure_df)
        vue_af_df = get_vue_af_df()
        active_siae_keys = get_active_siae_keys(vue_af_df)

        company = CompanyFactory(source=Company.SOURCE_ASP, siret=SIRET, kind=CompanyKind.AI, convention=None)
        results = self.mod.get_creatable_conventions(vue_af_df, siret_to_asp_id, siret_to_siae_row, active_siae_keys)

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

        vue_structure_df = get_vue_structure_df()
        siret_to_siae_row = get_siret_to_siae_row(vue_structure_df)
        siret_to_asp_id = get_siret_to_asp_id(vue_structure_df)
        vue_af_df = get_vue_af_df()
        active_siae_keys = get_active_siae_keys(vue_af_df)

        company = CompanyFactory(source=Company.SOURCE_ASP, siret=SIRET, kind=CompanyKind.ACI, convention=None)
        company = self.mod.get_creatable_conventions(vue_af_df, siret_to_asp_id, siret_to_siae_row, active_siae_keys)

        assert len(company) == 1

        convention, company = company[0]
        assert (
            convention.asp_id,
            convention.kind,
            convention.siret_signature,
            convention.is_active,
            convention.deactivated_at.to_pydatetime(),
        ) == (ASP_ID, company.kind, SIRET_SIGNATURE, False, datetime.datetime(2020, 2, 29, 0, 0))
        assert (company.source, company.siret, company.kind) == (Company.SOURCE_ASP, SIRET, CompanyKind.ACI)

    def test_get_creatable_and_deletable_afs(self):
        af_number_to_row = get_af_number_to_row(get_vue_af_df())

        existing_convention = SiaeConventionFactory(kind=CompanyKind.ACI, asp_id=2855)
        # Get AF created by SiaeConventionFactory
        deletable_af = existing_convention.financial_annexes.first()
        financial_annex = importlib.import_module("itou.companies.management.commands._import_siae.financial_annex")
        to_create, to_delete = financial_annex.get_creatable_and_deletable_afs(af_number_to_row)
        assert to_delete == [deletable_af]
        # This list comes from the fixture file
        assert sorted((af.number, af.start_at.isoformat(), af.end_at.isoformat()) for af in to_create) == [
            ("ACI972180023A0M0", "2018-07-01T00:00:00+02:00", "2018-12-31T00:00:00+01:00"),
            ("ACI972180023A0M1", "2018-07-01T00:00:00+02:00", "2018-12-31T00:00:00+01:00"),
            ("ACI972180024A0M0", "2018-07-01T00:00:00+02:00", "2018-12-31T00:00:00+01:00"),
            ("ACI972180024A0M1", "2018-07-01T00:00:00+02:00", "2018-12-31T00:00:00+01:00"),
            ("ACI972190114A0M0", "2019-01-01T00:00:00+01:00", "2019-12-31T00:00:00+01:00"),
            ("ACI972190114A0M1", "2019-01-01T00:00:00+01:00", "2019-12-31T00:00:00+01:00"),
            ("ACI972190114A1M0", "2020-01-01T00:00:00+01:00", "2020-12-31T00:00:00+01:00"),
            ("ACI972190114A1M1", "2020-01-01T00:00:00+01:00", "2020-12-31T00:00:00+01:00"),
            ("ACI972190115A0M0", "2019-05-01T00:00:00+02:00", "2019-12-31T00:00:00+01:00"),
            ("ACI972190115A0M1", "2019-05-01T00:00:00+02:00", "2019-12-31T00:00:00+01:00"),
            ("ACI972190115A1M0", "2020-01-01T00:00:00+01:00", "2020-12-31T00:00:00+01:00"),
            ("ACI972190115A1M1", "2020-01-01T00:00:00+01:00", "2020-12-31T00:00:00+01:00"),
            ("ACI972190115A2M0", "2022-01-01T00:00:00+01:00", "2022-12-31T00:00:00+01:00"),
            ("ACI972190115A2M1", "2022-01-01T00:00:00+01:00", "2022-12-31T00:00:00+01:00"),
            ("ACI972190115A2M2", "2021-01-01T00:00:00+01:00", "2021-12-31T00:00:00+01:00"),
            ("ACI972190115A2M3", "2021-01-01T00:00:00+01:00", "2021-12-31T00:00:00+01:00"),
            ("ACI972200037A0M0", "2020-01-01T00:00:00+01:00", "2020-12-31T00:00:00+01:00"),
            ("ACI972200038A0M0", "2020-01-01T00:00:00+01:00", "2020-12-31T00:00:00+01:00"),
        ]

    def test_check_signup_possible_for_a_siae_without_members_but_with_auth_email(self):
        instance = import_siae.Command()
        CompanyFactory(auth_email="tadaaa")
        with self.assertNumQueries(1):
            instance.check_whether_signup_is_possible_for_all_siaes()
        assert instance.fatal_errors == 0

    def test_check_signup_possible_for_a_siae_without_members_nor_auth_email(self):
        instance = import_siae.Command()
        CompanyFactory(auth_email="")
        with self.assertNumQueries(1):
            instance.check_whether_signup_is_possible_for_all_siaes()
        assert instance.fatal_errors == 1

    def test_check_signup_possible_for_a_siae_with_members_but_no_auth_email_case_one(self):
        instance = import_siae.Command()
        CompanyWith2MembershipsFactory(
            auth_email="",
            membership1__is_active=False,
            membership1__user__is_active=False,
        )
        with self.assertNumQueries(1):
            instance.check_whether_signup_is_possible_for_all_siaes()
        assert instance.fatal_errors == 0

    def test_check_signup_possible_for_a_siae_with_members_but_no_auth_email_case_two(self):
        instance = import_siae.Command()
        CompanyWith2MembershipsFactory(
            auth_email="",
            membership1__is_active=False,
            membership1__user__is_active=False,
            membership2__is_active=False,
            membership2__user__is_active=False,
        )
        with self.assertNumQueries(1):
            instance.check_whether_signup_is_possible_for_all_siaes()
        assert instance.fatal_errors == 1

    def test_check_signup_possible_for_a_siae_with_members_but_no_auth_email_case_three(self):
        instance = import_siae.Command()
        CompanyWith2MembershipsFactory(auth_email="")
        with self.assertNumQueries(1):
            instance.check_whether_signup_is_possible_for_all_siaes()
        assert instance.fatal_errors == 0

    def test_activate_your_account_email_for_a_siae_without_members_but_with_auth_email(self):
        vue_structure_df = get_vue_structure_df()
        vue_af_df = get_vue_af_df()

        instance = import_siae.Command()
        instance.create_new_siaes(
            get_siret_to_siae_row(vue_structure_df),
            get_siret_to_asp_id(vue_structure_df),
            get_active_siae_keys(vue_af_df),
        )
        assert reverse("signup:company_select") in mail.outbox[0].body
        assert collections.Counter(mail.subject for mail in mail.outbox) == collections.Counter(
            f"Activez le compte de votre {kind} {name} sur les emplois de l'inclusion"
            for (kind, name) in Company.objects.values_list("kind", "name")
        )


@override_settings(METABASE_HASH_SALT="foobar2000")
def test_hashed_approval_number():
    df = pd.DataFrame(data={"salarie_agrement": ["999992012369", None, ""]})
    anonymize_fluxiae_df(df)
    assert df.hash_numéro_pass_iae[0] == "314b2d285803a46c89e09ba9ad4e23a52f2e823ad28343cdff15be0cb03fee4a"
    assert df.hash_numéro_pass_iae[1] == "8e728c4578281ea0b6a7817e50a0f6d50c995c27f02dd359d67427ac3d86e019"
    assert df.hash_numéro_pass_iae[2] == "6cc868860cee823f0ffe0b3498bb4ebda51baa1b7858e2022f6590b0bd86c31c"
    assert "salarie_agrement" not in df


def test_could_siae_be_deleted_with_eligibility_diagnosis():
    # Check that eligibility diagnoses made by SIAE are blocking its deletion

    # No eligibility diagnosis linked
    company = CompanyWith2MembershipsFactory()
    assert could_siae_be_deleted(company)

    # An eligibility diagnosis without related approval
    EligibilityDiagnosisMadeBySiaeFactory(author_siae=company, author=company.members.first())
    assert could_siae_be_deleted(company)

    # Approval with eligibility diagnosis authored by SIAE
    ApprovalFactory(eligibility_diagnosis__author_siae=company)
    assert not could_siae_be_deleted(company)
