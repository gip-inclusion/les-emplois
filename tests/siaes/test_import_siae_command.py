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

from itou.siaes.enums import SiaeKind
from itou.siaes.management.commands._import_siae.utils import anonymize_fluxiae_df, could_siae_be_deleted
from itou.siaes.models import Siae
from tests.approvals.factories import ApprovalFactory
from tests.eligibility.factories import EligibilityDiagnosisMadeBySiaeFactory
from tests.siaes.factories import SiaeConventionFactory, SiaeFactory, SiaeWith2MembershipsFactory


def lazy_import_siae_command():
    # Has to be lazy-loaded to benefit from the file mock, this management command does crazy stuff at import.
    from itou.siaes.management.commands import import_siae

    instance = import_siae.Command()
    # Required otherwise the variable is undefined and throws an exception when incrementend the first time.
    instance.fatal_errors = 0
    return instance


@unittest.skipUnless(
    os.getenv("CI", "False"), "Slow and scarcely updated management command, no need for constant testing!"
)
@freeze_time("2022-10-10")
class ImportSiaeManagementCommandsTest(TransactionTestCase):
    path_source = "./siaes/fixtures"
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
        data_dir_mock = mock.patch("itou.siaes.management.commands._import_siae.utils.CURRENT_DIR", data_dir)
        data_dir_mock.start()
        cls.addClassCleanup(data_dir_mock.stop)

        # Beware : fluxIAE_Structure_22022022_112211.csv.gz ends with .gz but is compressed with pkzip.
        # Since it happened once, and the code now allows it, we also want to test it.
        files = [x for x in cls.app_dir_path.joinpath(cls.path_source).glob("fluxIAE_*.csv.gz") if x.is_file()]
        for file in files:
            shutil.copy(file, data_dir)

        cls.mod = importlib.import_module("itou.siaes.management.commands._import_siae.convention")

    @classmethod
    def tearDownClass(cls):
        super().tearDownClass()
        cls.mod = None

    def test_uncreatable_conventions_for_active_siae_with_active_convention(self):
        siae = SiaeFactory(source=Siae.SOURCE_ASP)
        assert siae.is_active
        assert not self.mod.get_creatable_conventions()

    def test_uncreatable_conventions_when_convention_exists_for_asp_id_and_kind(self):
        # siae without convention, but a convention already exists for this
        # asp_id and this kind. ACHTUNG: asp_id is collected from vue_structure_df :D
        SIRET = "26290411300061"
        ASP_ID = 190

        siae = SiaeFactory(source=Siae.SOURCE_ASP, siret=SIRET, convention=None)
        SiaeConventionFactory(kind=siae.kind, asp_id=ASP_ID)

        with pytest.raises(AssertionError):
            self.mod.get_creatable_conventions()

    def test_creatable_conventions_for_active_siae_where_siret_equals_siret_signature(self):
        SIRET = SIRET_SIGNATURE = "21540323900019"
        ASP_ID = 112

        siae = SiaeFactory(source=Siae.SOURCE_ASP, siret=SIRET, kind=SiaeKind.ACI, convention=None)
        results = self.mod.get_creatable_conventions()

        assert len(results) == 1

        convention, siae = results[0]
        assert (
            convention.asp_id,
            convention.kind,
            convention.siret_signature,
            convention.is_active,
            convention.deactivated_at,
        ) == (ASP_ID, siae.kind, SIRET_SIGNATURE, True, None)
        assert (siae.source, siae.siret, siae.kind) == (Siae.SOURCE_ASP, SIRET, SiaeKind.ACI)

    def test_creatable_conventions_for_active_siae_where_siret_not_equals_siret_signature(self):
        SIRET = "34950857200055"
        SIRET_SIGNATURE = "34950857200048"
        ASP_ID = 768

        siae = SiaeFactory(source=Siae.SOURCE_ASP, siret=SIRET, kind=SiaeKind.AI, convention=None)
        results = self.mod.get_creatable_conventions()

        assert len(results) == 1

        convention, siae = results[0]
        assert (
            convention.asp_id,
            convention.kind,
            convention.siret_signature,
            convention.is_active,
            convention.deactivated_at,
        ) == (ASP_ID, siae.kind, SIRET_SIGNATURE, True, None)
        assert (siae.source, siae.siret, siae.kind) == (Siae.SOURCE_ASP, SIRET, SiaeKind.AI)

    def test_creatable_conventions_inactive_siae(self):
        SIRET = SIRET_SIGNATURE = "41294123900011"
        ASP_ID = 1780
        siae = SiaeFactory(source=Siae.SOURCE_ASP, siret=SIRET, kind=SiaeKind.ACI, convention=None)
        results = self.mod.get_creatable_conventions()

        assert len(results) == 1

        convention, siae = results[0]
        assert (
            convention.asp_id,
            convention.kind,
            convention.siret_signature,
            convention.is_active,
            convention.deactivated_at.to_pydatetime(),
        ) == (ASP_ID, siae.kind, SIRET_SIGNATURE, False, datetime.datetime(2020, 2, 29, 0, 0))
        assert (siae.source, siae.siret, siae.kind) == (Siae.SOURCE_ASP, SIRET, SiaeKind.ACI)

    def test_check_signup_possible_for_a_siae_without_members_but_with_auth_email(self):
        instance = lazy_import_siae_command()
        SiaeFactory(auth_email="tadaaa")
        with self.assertNumQueries(1):
            instance.check_whether_signup_is_possible_for_all_siaes()
        assert instance.fatal_errors == 0

    def test_check_signup_possible_for_a_siae_without_members_nor_auth_email(self):
        instance = lazy_import_siae_command()
        SiaeFactory(auth_email="")
        with self.assertNumQueries(1):
            instance.check_whether_signup_is_possible_for_all_siaes()
        assert instance.fatal_errors == 1

    def test_check_signup_possible_for_a_siae_with_members_but_no_auth_email_case_one(self):
        instance = lazy_import_siae_command()
        SiaeWith2MembershipsFactory(
            auth_email="",
            membership1__is_active=False,
            membership1__user__is_active=False,
        )
        with self.assertNumQueries(1):
            instance.check_whether_signup_is_possible_for_all_siaes()
        assert instance.fatal_errors == 0

    def test_check_signup_possible_for_a_siae_with_members_but_no_auth_email_case_two(self):
        instance = lazy_import_siae_command()
        SiaeWith2MembershipsFactory(
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
        instance = lazy_import_siae_command()
        SiaeWith2MembershipsFactory(auth_email="")
        with self.assertNumQueries(1):
            instance.check_whether_signup_is_possible_for_all_siaes()
        assert instance.fatal_errors == 0

    def test_activate_your_account_email_for_a_siae_without_members_but_with_auth_email(self):
        instance = lazy_import_siae_command()
        instance.create_new_siaes()
        assert reverse("signup:siae_select") in mail.outbox[0].body
        assert [mail.subject for mail in mail.outbox] == [
            f"Activez le compte de votre {kind} {name} sur les emplois de l'inclusion"
            for (kind, name) in Siae.objects.values_list("kind", "name")
        ]


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
    siae = SiaeWith2MembershipsFactory()
    assert could_siae_be_deleted(siae)

    # An eligibility diagnosis without related approval
    EligibilityDiagnosisMadeBySiaeFactory(author_siae=siae, author=siae.members.first())
    assert could_siae_be_deleted(siae)

    # Approval with eligibility diagnosis authored by SIAE
    ApprovalFactory(eligibility_diagnosis__author_siae=siae)
    assert not could_siae_be_deleted(siae)
